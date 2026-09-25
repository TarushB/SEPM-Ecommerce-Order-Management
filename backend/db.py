"""
Database access layer: Front End -> **SQL** -> Database -> Result.

* The app logs in to PostgreSQL as the low-privilege role  olist_app.
* Every request runs inside one transaction that first does
      SET LOCAL ROLE olist_<user's role>
  so PostgreSQL itself enforces GRANTs and row-level security.
* psycopg's ClientCursor binds parameters client-side, so the SQL text we
  show in the UI is exactly the text the server executed.
* Every statement is recorded (SQL, rows, time, error) and returned to the
  browser, which displays it in the "SQL executed" panel.
"""
import os
import time
from contextlib import contextmanager

import psycopg

DB_CONFIG = {
    "host": os.environ.get("OLIST_DB_HOST", "localhost"),
    "port": int(os.environ.get("OLIST_DB_PORT", "5432")),
    "dbname": os.environ.get("OLIST_DB_NAME", "olist"),
    "user": os.environ.get("OLIST_DB_USER", "olist_app"),
    "password": os.environ.get("OLIST_DB_PASSWORD", "olist_app_pw"),
}

ROLE_MAP = {   # application role -> PostgreSQL group role
    "admin": "olist_admin", "manager": "olist_manager", "analyst": "olist_analyst",
    "seller": "olist_seller", "support": "olist_support",
}

MAX_ROWS = 500


class DBError(Exception):
    def __init__(self, message, sqlstate=None, log=None):
        super().__init__(message)
        self.message = message
        self.sqlstate = sqlstate
        self.log = log or []


def connect():
    return psycopg.connect(**DB_CONFIG, cursor_factory=psycopg.ClientCursor, connect_timeout=5)


def _error_text(e):
    diag = getattr(e, "diag", None)
    primary = getattr(diag, "message_primary", None) if diag else None
    return (primary or str(e)).strip().splitlines()[0]


class Session:
    """One transaction for one request, running as one database role."""

    def __init__(self, conn, user=None):
        self.conn = conn
        self.user = user
        self.log = []

    def run(self, sql, params=None, *, label=None, fetch=True, max_rows=MAX_ROWS, show=True):
        """Execute one statement; returns {'columns', 'rows', 'row_count'}; raises DBError."""
        entry = {"label": label, "sql": None, "row_count": None, "ms": None, "error": None}
        with self.conn.cursor() as cur:
            try:
                entry["sql"] = cur.mogrify(sql.strip(), params) if params else sql.strip()
            except Exception:
                entry["sql"] = sql.strip()
            start = time.perf_counter()
            try:
                cur.execute(sql, params)
                columns = [d.name for d in cur.description] if cur.description else []
                rows = cur.fetchmany(max_rows) if (fetch and cur.description) else []
                entry["row_count"] = cur.rowcount if cur.rowcount is not None and cur.rowcount >= 0 else len(rows)
                entry["ms"] = round((time.perf_counter() - start) * 1000, 1)
                entry["columns"] = columns
                entry["preview"] = [list(r) for r in rows[:5]] if show else None
                if show:
                    self.log.append(entry)
                return {"columns": columns, "rows": [dict(zip(columns, r)) for r in rows],
                        "row_count": entry["row_count"]}
            except psycopg.Error as e:
                entry["ms"] = round((time.perf_counter() - start) * 1000, 1)
                entry["error"] = _error_text(e)
                entry["sqlstate"] = getattr(e, "sqlstate", None)
                self.log.append(entry)
                raise DBError(entry["error"], entry["sqlstate"], self.log) from e

    def one(self, sql, params=None, **kw):
        res = self.run(sql, params, **kw)
        return res["rows"][0] if res["rows"] else None

    def all(self, sql, params=None, **kw):
        return self.run(sql, params, **kw)["rows"]

    def savepoint(self, name):
        self.run(f"SAVEPOINT {name}", label="savepoint")

    def rollback_to(self, name):
        with self.conn.cursor() as cur:
            cur.execute(f"ROLLBACK TO SAVEPOINT {name}")
        self.log.append({"label": "rollback to savepoint", "sql": f"ROLLBACK TO SAVEPOINT {name}",
                         "row_count": 0, "ms": 0, "error": None})


@contextmanager
def session(user=None, *, read_only=False, commit=True, isolation=None):
    """
    with session(user) as s:
        rows = s.all("SELECT ... WHERE x = %(x)s", {"x": 1})
    Commits on success, rolls back on any exception (atomic per request).
    """
    conn = connect()
    s = Session(conn, user)
    try:
        with conn.cursor() as cur:
            if isolation:
                cur.execute(f"SET TRANSACTION ISOLATION LEVEL {isolation}")
            if read_only:
                cur.execute("SET TRANSACTION READ ONLY")
            cur.execute("SET LOCAL statement_timeout = '15s'")
            if user:
                cur.execute(f"SET LOCAL ROLE {ROLE_MAP[user['app_role']]}")
                if user.get("seller_id"):
                    cur.execute("SELECT set_config('app.seller_id', %s, true)", (user["seller_id"],))
        if user:
            s.log.append({"label": "session setup", "sql": f"SET LOCAL ROLE {ROLE_MAP[user['app_role']]};"
                          + (f"\nSELECT set_config('app.seller_id', '{user['seller_id']}', true);"
                             if user.get("seller_id") else ""),
                          "row_count": 0, "ms": 0, "error": None})
        yield s
        if commit and not read_only:
            conn.commit()
            s.log.append({"label": "end", "sql": "COMMIT;", "row_count": 0, "ms": 0, "error": None})
        else:
            conn.rollback()
            s.log.append({"label": "end", "sql": "ROLLBACK;", "row_count": 0, "ms": 0, "error": None})
    except Exception:
        conn.rollback()
        s.log.append({"label": "end", "sql": "ROLLBACK;  -- the whole request is undone (atomicity)",
                      "row_count": 0, "ms": 0, "error": None})
        raise
    finally:
        conn.close()
