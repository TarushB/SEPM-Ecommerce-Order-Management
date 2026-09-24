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


# ---------------------------------------------------------------------------
# 3. Train / select / evaluate
# ---------------------------------------------------------------------------
def main():
    t0 = time.time()
    df = load_data()
    dev, test = split(df)
    X_te, y_te = test[FEATURES], test["is_late"].astype(int)

    # --- model selection with rolling time-series CV -----------------------
    names = list(candidates().keys())
    scores = {n: {"roc": [], "pr": [], "lift": []} for n in names + ["Baseline (distance rule)"]}
    oof = {n: ([], []) for n in names}                       # out-of-fold (y, p) for threshold tuning
    for lo, hi in CV_FOLDS:
        tr = dev[dev["purchase_ts"] < lo]
        va = dev[(dev["purchase_ts"] >= lo) & (dev["purchase_ts"] < hi)]
        y_va = va["is_late"].astype(int)
        log(f"Fold validate {lo}..{hi}: train {len(tr):,}, valid {len(va):,}, late rate {y_va.mean():.1%}")
        base_p = va["distance_km"].fillna(va["distance_km"].median()).rank(pct=True)
        for n, p in [("Baseline (distance rule)", base_p)]:
            scores[n]["roc"].append(roc_auc_score(y_va, p)); scores[n]["pr"].append(average_precision_score(y_va, p))
            scores[n]["lift"].append(average_precision_score(y_va, p) / y_va.mean())
        for n, pipe in candidates().items():
            pipe.fit(tr[FEATURES], tr["is_late"].astype(int))
            p = pipe.predict_proba(va[FEATURES])[:, 1]
            scores[n]["roc"].append(roc_auc_score(y_va, p)); scores[n]["pr"].append(average_precision_score(y_va, p))
            scores[n]["lift"].append(average_precision_score(y_va, p) / y_va.mean())
            oof[n][0].append(y_va.values); oof[n][1].append(p)

    comparison = []
    for n, sc in scores.items():
        comparison.append({"model": n, "cv_roc_auc": float(np.mean(sc["roc"])), "cv_pr_auc": float(np.mean(sc["pr"])),
                           "cv_pr_lift": float(np.mean(sc["lift"]))})
        log(f"  {n:28s} CV ROC-AUC {comparison[-1]['cv_roc_auc']:.3f}  PR-AUC {comparison[-1]['cv_pr_auc']:.3f}  "
            f"(PR-AUC / base rate = {comparison[-1]['cv_pr_lift']:.2f}x)")

    best_name = max((c for c in comparison if c["model"] in names), key=lambda c: c["cv_roc_auc"])["model"]
    threshold = best_threshold(np.concatenate(oof[best_name][0]), np.concatenate(oof[best_name][1]))
    log(f"Selected: {best_name} (best mean CV ROC-AUC); threshold {threshold:.3f} tuned on out-of-fold predictions")

    # --- final fit on all development data, one evaluation on the test months ---
    fitted = {}
    for n, pipe in candidates().items():
        fitted[n] = pipe.fit(dev[FEATURES], dev["is_late"].astype(int))
    final = fitted[best_name]
    p_te = final.predict_proba(X_te)[:, 1]
    test_m = metrics(y_te, p_te, threshold)
    cm = confusion_matrix(y_te, (p_te >= threshold).astype(int)).tolist()
    for row in comparison:
        p = (fitted[row["model"]].predict_proba(X_te)[:, 1] if row["model"] in fitted
             else X_te["distance_km"].fillna(X_te["distance_km"].median()).rank(pct=True))
        row["test_roc_auc"] = float(roc_auc_score(y_te, p)); row["test_pr_auc"] = float(average_precision_score(y_te, p))
    log("TEST (Jun-Aug 2018): " + ", ".join(f"{k} {v:.3f}" for k, v in test_m.items())
        + f"  | base rate {y_te.mean():.3f}")
    log(f"Confusion matrix [[TN, FP], [FN, TP]] = {cm}")

    # Delivery-days regression
    lab_tv = dev
    reg = Pipeline([("prep", preprocessor(scale_numeric=False)),
                    ("model", HistGradientBoostingRegressor(learning_rate=0.05, max_iter=400,
                                                            loss="absolute_error", random_state=RANDOM_STATE))])
    reg.fit(lab_tv[FEATURES], lab_tv["delivery_days"])
    lin = Pipeline([("prep", preprocessor(scale_numeric=True)), ("model", LinearRegression())])
    lin.fit(lab_tv[FEATURES], lab_tv["delivery_days"])
    mae = mean_absolute_error(test["delivery_days"], reg.predict(test[FEATURES]))
    mae_lin = mean_absolute_error(test["delivery_days"], lin.predict(test[FEATURES]))
    mae_promise = mean_absolute_error(test["delivery_days"], test["promised_days"])
    log(f"Delivery days MAE: GB {mae:.2f}  | linear {mae_lin:.2f}  | Olist's promised date {mae_promise:.2f}")

    # Explainability: permutation importance on a test sample (original features)
    sample = test.sample(min(4000, len(test)), random_state=RANDOM_STATE)
    imp = permutation_importance(final, sample[FEATURES], sample["is_late"].astype(int),
                                 scoring="average_precision", n_repeats=3, random_state=RANDOM_STATE, n_jobs=-1)
    importance = sorted(({"feature": f, "importance": round(float(m), 4)}
                         for f, m in zip(FEATURES, imp.importances_mean)), key=lambda d: -d["importance"])
    log("Top features: " + ", ".join(f"{d['feature']} ({d['importance']})" for d in importance[:6]))

    # ---------------------------------------------------------------------
    # 4. Save model file + write results INTO THE DATABASE
    # ---------------------------------------------------------------------
    version = f"late_v{datetime.now():%Y%m%d_%H%M}"
    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    joblib.dump({"version": version, "algorithm": best_name, "classifier": final, "regressor": reg,
                 "threshold": threshold, "features": FEATURES}, MODEL_PATH)
    log(f"Model saved to {MODEL_PATH}")

    details = {"comparison": [{k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()}
                              for r in comparison],
               "confusion_matrix": cm, "feature_importance": importance,
               "split": {"cv_folds": CV_FOLDS, "final_train": f"< {TEST_START}",
                         "test": f"{TEST_START} .. {TEST_END}"},
               "rows": {"train": len(dev), "test": len(test)},
               "late_rate_test": round(float(y_te.mean()), 4),
               "mae_linear_days": round(mae_lin, 3)}
    execute("UPDATE ml_model SET is_active = false")
    execute(
        "INSERT INTO ml_model(model_version, algorithm, train_rows, test_rows, roc_auc, pr_auc, precision_at_t, "
        "recall_at_t, f1_at_t, threshold, mae_days, baseline_mae_days, is_active, details) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, true, %s::jsonb)",
        (version, best_name, len(dev), len(test), round(test_m["roc_auc"], 4), round(test_m["pr_auc"], 4),
         round(test_m["precision"], 4), round(test_m["recall"], 4), round(test_m["f1"], 4),
         round(threshold, 4), round(mae, 3), round(mae_promise, 3), json.dumps(details)))

    # Score every order (open orders get a live risk badge; delivered ones allow predicted-vs-actual SQL)
    probs = final.predict_proba(df[FEATURES])[:, 1]
    days = reg.predict(df[FEATURES])
    rows = [(oid, version, round(float(p), 4), round(float(d), 2))
            for oid, p, d in zip(df["order_id"], probs, days)]
    execute("TRUNCATE ml_prediction")
    copy_rows("ml_prediction", ["order_id", "model_version", "late_probability", "predicted_days"], rows)
    log(f"Wrote {len(rows):,} predictions to ml_prediction. Done in {time.time() - t0:.0f}s.")


if __name__ == "__main__":
    main()
