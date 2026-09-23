"""Shared ML helpers: feature lists and database I/O (psycopg 3).
Connection settings come from the standard libpq environment variables
(PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE)."""
import os

import pandas as pd
import psycopg

DB = {
    "host": os.environ.get("PGHOST", "localhost"),
    "port": os.environ.get("PGPORT", "5432"),
    "dbname": os.environ.get("PGDATABASE", "olist"),
    "user": os.environ.get("PGUSER", "postgres"),
}

MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "late_delivery_model.joblib")

NUMERIC_FEATURES = [
    "distance_km", "same_state", "n_items", "n_sellers", "total_price", "total_freight",
    "freight_ratio", "installments", "total_weight_g", "total_volume_cm3",
    "purchase_month", "purchase_dow", "purchase_hour", "promised_days",
    "ship_limit_days", "seller_prior_orders", "seller_prior_late_rate",
]
CATEGORICAL_FEATURES = ["customer_state", "seller_state", "customer_region", "payment_type", "main_category"]
FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES


def read_sql(sql: str) -> pd.DataFrame:
    """Run a SELECT and return a DataFrame."""
    with psycopg.connect(**DB) as conn, conn.cursor() as cur:
        cur.execute(sql)
        return pd.DataFrame(cur.fetchall(), columns=[d.name for d in cur.description])


def execute(sql: str, params=None):
    """Run a statement that returns nothing (INSERT / UPDATE / CALL)."""
    with psycopg.connect(**DB) as conn:
        conn.execute(sql, params)


def copy_rows(table: str, columns: list, rows: list):
    """Bulk-insert rows with COPY (fast path for ~100k predictions)."""
    with psycopg.connect(**DB) as conn, conn.cursor() as cur:
        with cur.copy(f"COPY {table} ({', '.join(columns)}) FROM STDIN") as cp:
            for r in rows:
                cp.write_row(r)


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    """Type-cast the feature columns the same way for training and scoring."""
    df = df.copy()
    for c in NUMERIC_FEATURES:
        df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
    for c in CATEGORICAL_FEATURES:
        df[c] = df[c].astype("string").fillna("unknown").astype(str)
    return df
