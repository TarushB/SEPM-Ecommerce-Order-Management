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
