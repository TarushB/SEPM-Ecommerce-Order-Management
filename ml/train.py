"""
Late-delivery risk model for the Olist database.

Pipeline:  SQL (mv_order_features) -> preprocessing -> 4-5 candidate models
           -> rolling time-series CV -> threshold tuning -> test evaluation
           -> save model file -> write metrics to ml_model and scores to ml_prediction

Run (from the project folder):   python ml/train.py
"""
import json
import os
import sys
import time
from datetime import datetime

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.metrics import (average_precision_score, confusion_matrix, f1_score, mean_absolute_error,
                             precision_recall_curve, precision_score, recall_score, roc_auc_score)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (CATEGORICAL_FEATURES, FEATURES, MODEL_PATH, NUMERIC_FEATURES,  # noqa: E402
                    copy_rows, execute, prepare, read_sql)

RANDOM_STATE = 42
# Rolling-origin (time-series) cross-validation: each fold trains on everything
# purchased BEFORE the window and validates on the 3-month window itself.
CV_FOLDS = [("2017-09-01", "2017-12-01"), ("2017-12-01", "2018-03-01"), ("2018-03-01", "2018-06-01")]
TEST_START = "2018-06-01"    # test: Jun-Aug 2018, never seen during selection
TEST_END = "2018-09-01"


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


# ---------------------------------------------------------------------------
# 1. Data
# ---------------------------------------------------------------------------
def load_data():
    log("Refreshing materialized views and reading features with SQL ...")
    execute("CALL sp_refresh_reports()")
    df = read_sql("SELECT * FROM mv_order_features")
    df["purchase_ts"] = pd.to_datetime(df["purchase_ts"])
    for c in ("is_late", "delivery_days"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = prepare(df)
    log(f"{len(df):,} orders with items; {df['is_late'].notna().sum():,} delivered (labelled)")
    return df


def split(df):
    lab = df[df["is_late"].notna()]
    dev = lab[lab["purchase_ts"] < TEST_START]
    test = lab[(lab["purchase_ts"] >= TEST_START) & (lab["purchase_ts"] < TEST_END)]
    log(f"  development (before {TEST_START}): {len(dev):,} rows, late rate {dev['is_late'].mean():.1%}")
    log(f"  test ({TEST_START} .. {TEST_END}):   {len(test):,} rows, late rate {test['is_late'].mean():.1%}")
    return dev, test


# ---------------------------------------------------------------------------
# 2. Preprocessing + candidate models
# ---------------------------------------------------------------------------
def preprocessor(scale_numeric: bool):
    num_steps = [("impute", SimpleImputer(strategy="median"))]
    if scale_numeric:
        num_steps.append(("scale", StandardScaler()))
    return ColumnTransformer([
        ("num", Pipeline(num_steps), NUMERIC_FEATURES),
        ("cat", OneHotEncoder(handle_unknown="infrequent_if_exist", min_frequency=30,
                              sparse_output=False), CATEGORICAL_FEATURES),
    ])


def candidates():
    models = {
        "Logistic Regression": Pipeline([
            ("prep", preprocessor(scale_numeric=True)),
            ("model", LogisticRegression(max_iter=2000, class_weight="balanced", C=0.5))]),
        "Random Forest": Pipeline([
            ("prep", preprocessor(scale_numeric=False)),
            ("model", RandomForestClassifier(n_estimators=250, min_samples_leaf=20, max_features="sqrt",
                                             class_weight="balanced_subsample", n_jobs=-1,
                                             random_state=RANDOM_STATE))]),
        "Gradient Boosting (HistGB)": Pipeline([
            ("prep", preprocessor(scale_numeric=False)),
            ("model", HistGradientBoostingClassifier(learning_rate=0.05, max_iter=400, max_leaf_nodes=31,
                                                     min_samples_leaf=40, l2_regularization=1.0,
                                                     class_weight="balanced", early_stopping=True,
                                                     validation_fraction=0.1, random_state=RANDOM_STATE))]),
    }
    try:
        from lightgbm import LGBMClassifier
        models["LightGBM"] = Pipeline([
            ("prep", preprocessor(scale_numeric=False)),
            ("model", LGBMClassifier(n_estimators=500, learning_rate=0.03, num_leaves=31,
                                     min_child_samples=40, subsample=0.8, subsample_freq=1,
                                     colsample_bytree=0.8, class_weight="balanced",
                                     random_state=RANDOM_STATE, verbose=-1))])
    except ImportError:
        log("LightGBM not installed - skipping it (pip install lightgbm to include it)")
    return models


def best_threshold(y, p):
    """Threshold that maximises F1 on the validation set."""
    prec, rec, thr = precision_recall_curve(y, p)
    f1 = 2 * prec * rec / np.maximum(prec + rec, 1e-9)
    i = int(np.nanargmax(f1[:-1]))
    return float(thr[i])


def metrics(y, p, t):
    pred = (p >= t).astype(int)
    return {
        "roc_auc": roc_auc_score(y, p),
        "pr_auc": average_precision_score(y, p),
        "precision": precision_score(y, pred, zero_division=0),
        "recall": recall_score(y, pred, zero_division=0),
        "f1": f1_score(y, pred, zero_division=0),
    }
