"""Loads the trained model file and scores orders using features read with SQL."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "ml"))

from common import FEATURES, MODEL_PATH, prepare  # noqa: E402

_bundle = None
_mtime = None


def load():
    """Load (or reload after retraining) the saved model bundle."""
    global _bundle, _mtime
    if not os.path.exists(MODEL_PATH):
        return None
    m = os.path.getmtime(MODEL_PATH)
    if _bundle is None or m != _mtime:
        import joblib
        _bundle = joblib.load(MODEL_PATH)
        _mtime = m
    return _bundle


def available():
    return load() is not None


def score(feature_rows):
    """feature_rows: list of dicts from v_order_features -> list of predictions."""
    import pandas as pd
    b = load()
    if b is None:
        raise RuntimeError("No trained model yet. Run train_model.bat (python ml/train.py) first.")
    df = prepare(pd.DataFrame(feature_rows))
    probs = b["classifier"].predict_proba(df[FEATURES])[:, 1]
    days = b["regressor"].predict(df[FEATURES])
    out = []
    for row, p, d in zip(feature_rows, probs, days):
        p = float(p)
        out.append({
            "order_id": row["order_id"],
            "late_probability": round(p, 4),
            "predicted_days": round(float(d), 1),
            "promised_days": float(row["promised_days"]) if row.get("promised_days") is not None else None,
            "risk": "high" if p >= b["threshold"] else ("medium" if p >= b["threshold"] * 0.6 else "low"),
            "threshold": round(float(b["threshold"]), 4),
            "model_version": b["version"],
            "algorithm": b["algorithm"],
        })
    return out
