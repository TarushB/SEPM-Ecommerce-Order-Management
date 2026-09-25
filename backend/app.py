"""
Olist E-Commerce DBMS - web application (Flask).

Every endpoint:
  1. runs its SQL as the logged-in user's PostgreSQL role (see db.py),
  2. returns the rows AND the exact SQL statements executed,
so the browser can show  Front End -> SQL -> Database -> Result.

Run:  python backend/app.py      then open http://localhost:5000
"""
import datetime as dt
import decimal
import json
import os
import re
import secrets
import threading
import time
from functools import wraps

from flask import Flask, jsonify, request, send_from_directory, session as web_session
from flask.json.provider import DefaultJSONProvider

import ml_service
from db import DBError, connect, session
from queries import QUERIES, QUERY_BY_ID

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND = os.path.join(ROOT, "frontend")


class JSONProvider(DefaultJSONProvider):
    @staticmethod
    def default(o):
        if isinstance(o, decimal.Decimal):
            return float(o)
        if isinstance(o, dt.datetime):
            return o.strftime("%Y-%m-%d %H:%M:%S")
        if isinstance(o, dt.date):
            return o.isoformat()
        return DefaultJSONProvider.default(o)


app = Flask(__name__, static_folder=None)
app.json = JSONProvider(app)
app.json.sort_keys = False      # keep SQL column order
app.secret_key = os.environ.get("OLIST_SECRET_KEY") or secrets.token_hex(16)

ID_RE = re.compile(r"^[0-9a-zA-Z_]{1,32}$")
ORDER_STATUSES = ["created", "approved", "invoiced", "processing", "shipped", "delivered", "canceled", "unavailable"]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def ok(data=None, s=None, **extra):
    return jsonify({"ok": True, "data": data, "queries": s.log if s else [], **extra})


def fail(message, status=400, log=None, sqlstate=None):
    return jsonify({"ok": False, "error": message, "sqlstate": sqlstate, "queries": log or []}), status


def current_user():
    return web_session.get("user")


def api(roles=None):
    """Decorator: login check, role check (UI level) and uniform error handling.
    The database performs the real authorization; the role list only hides
    actions the UI knows would be refused."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            user = current_user()
            if user is None:
                return fail("Please log in", 401)
            if roles and user["app_role"] not in roles:
                return fail(f"Your role ({user['app_role']}) cannot do this", 403)
            try:
                return fn(user, *a, **kw)
            except DBError as e:
                status = 403 if e.sqlstate == "42501" else 400
                return fail(e.message, status, e.log, e.sqlstate)
            except (ValueError, KeyError) as e:
                return fail(f"Invalid input: {e}", 400)
            except RuntimeError as e:
                return fail(str(e), 400)
        return wrapper
    return deco


def body():
    return request.get_json(silent=True) or {}


def arg(name, default=None, cast=str):
    v = request.args.get(name, "")
    if v == "":
        return default
    return cast(v)


def check_id(v, what="id"):
    if not v or not ID_RE.match(str(v)):
        raise ValueError(f"bad {what}")
    return v


def new_id():
    return secrets.token_hex(16)


def try_run(s, sql, params=None, label=None):
    """Run an optional query inside a savepoint: on permission errors the
    rest of the request still works (e.g. a seller cannot read payments)."""
    s.savepoint("opt")
    try:
        return s.all(sql, params, label=label)
    except DBError:
        s.rollback_to("opt")
        return None



def facet_counts(s, from_sql, filters, dims, params):
    """Counts for each dropdown option, given all the OTHER active filters.
    filters: list of (dim_key, sql_condition); dims: {dim_key: value_expression}.
    One GROUP BY query per dimension; the filter on that same dimension is left
    out so the user sees what each alternative choice would return."""
    out = {}
    for dim, expr in dims.items():
        join = ""
        if isinstance(expr, tuple):             # (expression, extra JOIN needed for it)
            expr, join = expr
        conds = [c for k, c in filters if k != dim]
        sql = (f"SELECT {expr} AS value, COUNT(*) AS n\nFROM {from_sql}\n" + (join + "\n" if join else "")
               + ("WHERE " + "\n  AND ".join(conds) + "\n" if conds else "")
               + "GROUP BY 1 ORDER BY n DESC")
        rows = s.all(sql, params, label=f"dropdown counts: {dim}", max_rows=200)
        out[dim] = {"total": sum(r["n"] for r in rows),
                    "values": [{"value": r["value"], "n": r["n"]} for r in rows if r["value"] is not None]}
    return out


def cumulative_le(facet):
    """Turn counts per exact value into counts for 'value <= x' (used for the rating filter)."""
    exact = {int(v["value"]): v["n"] for v in facet["values"]}
    facet["values"] = sorted(({"value": x, "n": sum(n for k, n in exact.items() if k <= x)} for x in range(1, 6)),
                             key=lambda v: -v["n"])
    return facet


@app.get("/<path:path>")
def static_files(path):
    if path.startswith("api/"):
        return fail("Not found", 404)
    return send_from_directory(FRONTEND, path)


# ---------------------------------------------------------------------------
# authentication (password checked inside PostgreSQL by fn_login)
# ---------------------------------------------------------------------------
@app.post("/api/login")
def login():
    b = body()
    try:
        with session(None) as s:
            row = s.one("SELECT * FROM fn_login(%(u)s, %(p)s)",
                        {"u": b.get("username", ""), "p": b.get("password", "")}, label="login")
            log = s.log
            for entry in log:                       # never echo the password back
                if entry.get("sql") and "fn_login" in entry["sql"]:
                    entry["sql"] = "SELECT * FROM fn_login(%(u)s, '********')" % {"u": repr(b.get("username", ""))}
    except DBError as e:
        return fail(e.message, 500, e.log)
    except Exception as e:
        return fail(f"Cannot connect to PostgreSQL: {e}", 500)
    if not row:
        return fail("Wrong username or password", 401, log)
    user = {k: row[k] for k in ("user_id", "username", "app_role", "seller_id")}
    web_session["user"] = user
    return jsonify({"ok": True, "data": user, "queries": log})


@app.post("/api/logout")
def logout():
    web_session.pop("user", None)
    return jsonify({"ok": True})


@app.get("/api/me")
def me():
    return jsonify({"ok": True, "data": current_user(), "model_ready": ml_service.available()})


# ---------------------------------------------------------------------------
# dashboard (base tables, so a seller automatically sees only their data via RLS)
# ---------------------------------------------------------------------------
@app.get("/api/dashboard")
@api()
def dashboard(user):
    with session(user, read_only=True) as s:
        kpi = s.one("""
SELECT (SELECT COUNT(*) FROM orders)                                    AS orders,
       (SELECT ROUND(SUM(price), 2) FROM order_item)                    AS revenue,
       (SELECT ROUND(AVG(review_score), 2) FROM review)                 AS avg_rating,
       (SELECT ROUND(100.0 * AVG((delivered_customer_date > estimated_delivery_date)::int), 1)
          FROM orders WHERE delivered_customer_date IS NOT NULL)        AS late_pct,
       (SELECT COUNT(*) FROM orders
         WHERE order_status NOT IN ('delivered','canceled','unavailable')) AS open_orders""", label="KPIs")
        monthly = s.all("""
SELECT to_char(date_trunc('month', o.purchase_ts), 'YYYY-MM') AS month,
       COUNT(DISTINCT o.order_id) AS orders, ROUND(SUM(oi.price), 0) AS revenue
FROM orders o JOIN order_item oi ON oi.order_id = o.order_id
WHERE o.purchase_ts >= '2017-01-01' AND o.purchase_ts < '2018-09-01'
GROUP BY 1 ORDER BY 1""", label="monthly revenue")
        categories = s.all("""
SELECT COALESCE(c.category_name_en, 'unknown') AS category, ROUND(SUM(oi.price), 0) AS revenue,
       COUNT(*) AS items
FROM order_item oi
JOIN product p       ON p.product_id = oi.product_id
LEFT JOIN category c ON c.category_name = p.category_name
GROUP BY 1 ORDER BY revenue DESC LIMIT 10""", label="top categories")
        states = s.all("""
SELECT c.state_code AS state, COUNT(*) AS orders
FROM orders o JOIN v_customer_public c ON c.customer_id = o.customer_id
GROUP BY 1 ORDER BY 2 DESC LIMIT 12""", label="orders by state")
        status = s.all("SELECT order_status, COUNT(*) AS orders FROM orders GROUP BY 1 ORDER BY 2 DESC",
                       label="status mix")
        ratings = s.all("SELECT review_score, COUNT(*) AS reviews FROM review GROUP BY 1 ORDER BY 1",
                        label="rating distribution")
        return ok({"kpi": kpi, "monthly": monthly, "categories": categories, "states": states,
                   "status": status, "ratings": ratings}, s)
