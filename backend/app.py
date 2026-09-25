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


# ---------------------------------------------------------------------------
# ORDERS
# ---------------------------------------------------------------------------
@app.get("/api/orders")
@api()
def orders_search(user):
    f, p = [], {}                                     # (dimension, condition)
    if arg("status"):
        f.append(("status", "o.order_status = %(status)s")); p["status"] = arg("status")
    if arg("state"):
        f.append(("state", "c.state_code = %(state)s")); p["state"] = arg("state").upper()
    if arg("date_from"):
        f.append(("date_from", "o.purchase_ts >= %(date_from)s")); p["date_from"] = arg("date_from")
    if arg("date_to"):
        f.append(("date_to", "o.purchase_ts < %(date_to)s::date + 1")); p["date_to"] = arg("date_to")
    if arg("order_id"):
        f.append(("order_id", "o.order_id LIKE %(order_id)s")); p["order_id"] = check_id(arg("order_id")) + "%"
    if arg("customer_id"):
        f.append(("customer_id", "o.customer_id = %(customer_id)s")); p["customer_id"] = check_id(arg("customer_id"))
    if arg("max_rating"):
        f.append(("max_rating", "EXISTS (SELECT 1 FROM review r WHERE r.order_id = o.order_id AND r.review_score <= %(max_rating)s)"))
        p["max_rating"] = arg("max_rating", cast=int)
    if arg("late") in ("yes", "no"):
        f.append(("late", "o.delivered_customer_date " + (">" if arg("late") == "yes" else "<=") + " o.estimated_delivery_date"))
    where = [c for _, c in f]
    q = dict(p, limit=50, offset=50 * arg("page", 0, int))
    sql = f"""
SELECT o.order_id, o.order_status, o.purchase_ts, o.estimated_delivery_date, o.delivered_customer_date,
       c.city AS customer_city, c.state_code AS customer_state,
       (SELECT COUNT(*) FROM order_item oi WHERE oi.order_id = o.order_id)                 AS items,
       (SELECT SUM(oi.price + oi.freight_value) FROM order_item oi WHERE oi.order_id = o.order_id) AS total,
       (SELECT MIN(r.review_score) FROM review r WHERE r.order_id = o.order_id)            AS rating
FROM orders o
JOIN v_customer_public c ON c.customer_id = o.customer_id
{"WHERE " + chr(10) + "  AND ".join(where) if where else ""}
ORDER BY o.purchase_ts DESC
LIMIT %(limit)s OFFSET %(offset)s"""
    with session(user, read_only=True) as s:
        rows = s.all(sql, q, label="search orders")
        facets = None
        if arg("facets") == "1":
            facets = facet_counts(s, "orders o\nJOIN v_customer_public c ON c.customer_id = o.customer_id", f, {
                "status": "o.order_status",
                "state": "c.state_code",
                "max_rating": ("rv.min_score", "LEFT JOIN (SELECT order_id, MIN(review_score) AS min_score\n"
                               "           FROM review GROUP BY order_id) rv ON rv.order_id = o.order_id"),
                "late": "CASE WHEN o.delivered_customer_date > o.estimated_delivery_date THEN 'yes' "
                        "WHEN o.delivered_customer_date <= o.estimated_delivery_date THEN 'no' END",
            }, p)
            cumulative_le(facets["max_rating"])
        return ok(rows, s, facets=facets)


@app.get("/api/orders/<order_id>")
@api()
def order_detail(user, order_id):
    check_id(order_id, "order id")
    p = {"id": order_id}
    with session(user, read_only=True) as s:
        order = s.one("""
SELECT o.*, c.customer_unique_id, c.city AS customer_city, c.state_code AS customer_state,
       fn_order_total(o.order_id) AS order_total, fn_delivery_days(o.order_id) AS delivery_days
FROM orders o JOIN v_customer_public c ON c.customer_id = o.customer_id
WHERE o.order_id = %(id)s""", p, label="order")
        if not order:
            return fail("Order not found (or not visible to your role)", 404, s.log)
        items = s.all("""
SELECT oi.order_item_id, oi.product_id, COALESCE(c.category_name_en, 'unknown') AS category,
       oi.seller_id, z.city AS seller_city, z.state_code AS seller_state,
       oi.price, oi.freight_value, oi.shipping_limit_date
FROM order_item oi
JOIN product p       ON p.product_id = oi.product_id
LEFT JOIN category c ON c.category_name = p.category_name
JOIN seller s        ON s.seller_id = oi.seller_id
JOIN zip_code z      ON z.zip_prefix = s.zip_prefix
WHERE oi.order_id = %(id)s ORDER BY oi.order_item_id""", p, label="items")
        payments = try_run(s, "SELECT payment_sequential, payment_type, installments, payment_value "
                              "FROM payment WHERE order_id = %(id)s ORDER BY 1", p, label="payments")
        reviews = try_run(s, "SELECT review_id, review_score, comment_title, comment_message, creation_date, answer_ts "
                             "FROM review WHERE order_id = %(id)s", p, label="reviews")
        history = try_run(s, "SELECT old_status, new_status, changed_at, changed_by FROM order_status_log "
                             "WHERE order_id = %(id)s ORDER BY log_id", p, label="status history")
        prediction = try_run(s, "SELECT mp.late_probability, mp.predicted_days, mp.model_version, mp.scored_at, m.threshold "
                                "FROM ml_prediction mp JOIN ml_model m ON m.model_version = mp.model_version "
                                "WHERE mp.order_id = %(id)s", p, label="ML prediction")
        return ok({"order": order, "items": items, "payments": payments, "reviews": reviews,
                   "history": history, "prediction": (prediction or [None])[0] if prediction is not None else None,
                   "prediction_access": prediction is not None, "statuses": ORDER_STATUSES}, s)


def _score_and_store(s, order_id):
    """Read live features with SQL, score with the model, store the result in ml_prediction."""
    if not ml_service.available():
        return None
    feats = s.all("SELECT * FROM v_order_features WHERE order_id = %(id)s", {"id": order_id},
                  label="ML features (live view)")
    if not feats:
        return None
    pred = ml_service.score(feats)[0]
    s.run("""
INSERT INTO ml_prediction(order_id, model_version, late_probability, predicted_days)
VALUES (%(id)s, %(v)s, %(p)s, %(d)s)
ON CONFLICT (order_id) DO UPDATE
   SET late_probability = EXCLUDED.late_probability, predicted_days = EXCLUDED.predicted_days,
       model_version = EXCLUDED.model_version, scored_at = now()""",
          {"id": order_id, "v": pred["model_version"], "p": pred["late_probability"], "d": pred["predicted_days"]},
          label="store prediction")
    return pred


@app.post("/api/orders")
@api(roles=["admin", "manager"])
def order_create(user):
    b = body()
    items = [{"product_id": check_id(i["product_id"], "product id"), "seller_id": check_id(i["seller_id"], "seller id"),
              **({"price": float(i["price"])} if i.get("price") not in (None, "") else {}),
              **({"freight": float(i["freight"])} if i.get("freight") not in (None, "") else {})}
             for i in b.get("items", [])]
    with session(user) as s:
        row = s.one("CALL sp_place_order(%(c)s, %(items)s::jsonb, %(pt)s, %(n)s, NULL)",
                    {"c": check_id(b.get("customer_id"), "customer id"), "items": json.dumps(items),
                     "pt": b.get("payment_type", "credit_card"), "n": int(b.get("installments", 1))},
                    label="place order (stored procedure, one transaction)")
        order_id = row["p_order_id"]
        pred = _score_and_store(s, order_id)
        return ok({"order_id": order_id, "prediction": pred}, s)


@app.post("/api/orders/<order_id>/status")
@api(roles=["admin", "manager", "seller"])
def order_status(user, order_id):
    new = body().get("status")
    if new not in ORDER_STATUSES:
        raise ValueError("unknown status")
    with session(user) as s:
        s.run("CALL sp_update_status(%(id)s, %(st)s)", {"id": check_id(order_id), "st": new}, label="update status")
        row = s.one("SELECT order_id, order_status, approved_at, delivered_carrier_date, delivered_customer_date "
                    "FROM orders WHERE order_id = %(id)s", {"id": order_id}, label="read back")
        return ok(row, s)


@app.post("/api/orders/<order_id>/cancel")
@api(roles=["admin", "manager"])
def order_cancel(user, order_id):
    with session(user) as s:
        s.run("CALL sp_cancel_order(%(id)s)", {"id": check_id(order_id)}, label="cancel order")
        return ok({"order_id": order_id}, s)


@app.put("/api/orders/<order_id>")
@api(roles=["admin", "manager"])
def order_update(user, order_id):
    b = body()
    with session(user) as s:
        row = s.one("""UPDATE orders SET estimated_delivery_date = %(d)s
WHERE order_id = %(id)s RETURNING order_id, estimated_delivery_date""",
                    {"d": b["estimated_delivery_date"], "id": check_id(order_id)}, label="update order")
        return ok(row, s)


@app.delete("/api/orders/<order_id>")
@api(roles=["admin", "manager"])
def order_delete(user, order_id):
    with session(user) as s:
        res = s.run("DELETE FROM orders WHERE order_id = %(id)s", {"id": check_id(order_id)}, label="delete order")
        return ok({"deleted": res["row_count"]}, s)


# ---------------------------------------------------------------------------
# lookups for the order form
# ---------------------------------------------------------------------------
@app.get("/api/lookup/customers")
@api()
def lookup_customers(user):
    q = (arg("q") or "").lower()
    with session(user, read_only=True) as s:
        rows = s.all("""
SELECT customer_id, customer_unique_id, city, state_code
FROM v_customer_public
WHERE customer_id LIKE %(q)s OR city LIKE %(q)s
ORDER BY city LIMIT 15""", {"q": q + "%"}, label="find customers")
        return ok(rows, s)


@app.get("/api/lookup/products")
@api()
def lookup_products(user):
    p = {"q": (arg("q") or "") + "%", "cat": arg("category")}
    cat = "AND c.category_name_en = %(cat)s" if p["cat"] else ""
    with session(user, read_only=True) as s:
        rows = s.all(f"""
SELECT p.product_id, COALESCE(c.category_name_en, 'unknown') AS category, p.stock_qty, p.weight_g,
       last.seller_id, last.price, last.freight_value
FROM product p
LEFT JOIN category c ON c.category_name = p.category_name
LEFT JOIN LATERAL (SELECT oi.seller_id, oi.price, oi.freight_value FROM order_item oi
                   WHERE oi.product_id = p.product_id
                   ORDER BY oi.shipping_limit_date DESC NULLS LAST LIMIT 1) last ON true
WHERE p.product_id LIKE %(q)s {cat} AND last.seller_id IS NOT NULL AND p.stock_qty > 0
ORDER BY p.stock_qty DESC LIMIT 15""", p, label="find products")
        facets = None
        if arg("facets") == "1":
            f = [("q", "p.product_id LIKE %(q)s"), ("base", "p.stock_qty > 0"),
                 ("base2", "EXISTS (SELECT 1 FROM order_item oi WHERE oi.product_id = p.product_id)")]
            if p["cat"]:
                f.append(("category", "c.category_name_en = %(cat)s"))
            facets = facet_counts(s, "product p\nLEFT JOIN category c ON c.category_name = p.category_name", f,
                                  {"category": "c.category_name_en"}, p)
        return ok(rows, s, facets=facets)


@app.get("/api/lookup/meta")
@api()
def lookup_meta(user):
    with session(user, read_only=True) as s:
        states = s.all("SELECT state_code, state_name, region FROM state ORDER BY state_code", label="states")
        cats = s.all("SELECT category_name, category_name_en FROM category ORDER BY category_name_en", label="categories")
        pts = s.all("SELECT payment_type, description FROM payment_type ORDER BY 1", label="payment types")
        return ok({"states": states, "categories": cats, "payment_types": pts, "statuses": ORDER_STATUSES}, s)
