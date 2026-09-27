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


# ---------------------------------------------------------------------------
# PRODUCTS
# ---------------------------------------------------------------------------
@app.get("/api/products")
@api()
def products_search(user):
    f, p = [], {}
    if arg("category"):
        f.append(("category", "c.category_name_en = %(cat)s")); p["cat"] = arg("category")
    if arg("q"):
        f.append(("q", "p.product_id LIKE %(q)s")); p["q"] = check_id(arg("q")) + "%"
    if arg("min_weight"):
        f.append(("min_weight", "p.weight_g >= %(minw)s")); p["minw"] = arg("min_weight", cast=int)
    if arg("max_weight"):
        f.append(("max_weight", "p.weight_g <= %(maxw)s")); p["maxw"] = arg("max_weight", cast=int)
    if arg("low_stock") == "yes":
        f.append(("low_stock", "p.stock_qty < 30"))
    where = [c for _, c in f]
    q = dict(p, limit=50, offset=50 * arg("page", 0, int))
    sql = f"""
SELECT p.product_id, p.category_name, COALESCE(c.category_name_en, 'unknown') AS category,
       p.weight_g, p.length_cm, p.height_cm, p.width_cm, p.photos_qty, p.stock_qty,
       (SELECT COUNT(*) FROM order_item oi WHERE oi.product_id = p.product_id) AS units_sold
FROM product p
LEFT JOIN category c ON c.category_name = p.category_name
{"WHERE " + chr(10) + "  AND ".join(where) if where else ""}
ORDER BY units_sold DESC, p.product_id
LIMIT %(limit)s OFFSET %(offset)s"""
    with session(user, read_only=True) as s:
        rows = s.all(sql, q, label="search products")
        facets = None
        if arg("facets") == "1":
            facets = facet_counts(s, "product p\nLEFT JOIN category c ON c.category_name = p.category_name", f, {
                "category": "c.category_name_en",
                "low_stock": "CASE WHEN p.stock_qty < 30 THEN 'yes' END",
            }, p)
        return ok(rows, s, facets=facets)


PRODUCT_FIELDS = ["category_name", "name_length", "description_length", "photos_qty", "weight_g",
                  "length_cm", "height_cm", "width_cm", "stock_qty"]


def _product_values(b):
    vals = {}
    for f in PRODUCT_FIELDS:
        v = b.get(f)
        vals[f] = None if v in (None, "") else (v if f == "category_name" else int(v))
    return vals


@app.post("/api/products")
@api(roles=["admin", "manager"])
def product_create(user):
    vals = _product_values(body())
    vals["product_id"] = new_id()
    if vals["stock_qty"] is None:
        vals["stock_qty"] = 50
    cols = ["product_id"] + PRODUCT_FIELDS
    with session(user) as s:
        row = s.one(f"INSERT INTO product ({', '.join(cols)})\nVALUES ({', '.join('%(' + c + ')s' for c in cols)})\n"
                    "RETURNING *", vals, label="insert product")
        return ok(row, s)


@app.put("/api/products/<pid>")
@api(roles=["admin", "manager"])
def product_update(user, pid):
    b = body()
    vals = _product_values(b)
    sets = [f for f in PRODUCT_FIELDS if f in b]
    if not sets:
        raise ValueError("nothing to update")
    vals["id"] = check_id(pid)
    with session(user) as s:
        row = s.one(f"UPDATE product SET {', '.join(f + ' = %(' + f + ')s' for f in sets)}\n"
                    "WHERE product_id = %(id)s RETURNING *", vals, label="update product")
        return ok(row, s)


@app.delete("/api/products/<pid>")
@api(roles=["admin", "manager"])
def product_delete(user, pid):
    with session(user) as s:
        res = s.run("DELETE FROM product WHERE product_id = %(id)s", {"id": check_id(pid)}, label="delete product")
        return ok({"deleted": res["row_count"]}, s)


# ---------------------------------------------------------------------------
# CUSTOMERS
# ---------------------------------------------------------------------------
@app.get("/api/customers")
@api(roles=["admin", "manager", "analyst", "support"])
def customers_search(user):
    f, p = [], {}
    repeat_expr = "(SELECT COUNT(*) FROM v_customer_public c2 WHERE c2.customer_unique_id = c.customer_unique_id)"
    if arg("state"):
        f.append(("state", "c.state_code = %(state)s")); p["state"] = arg("state").upper()
    if arg("city"):
        f.append(("city", "c.city LIKE %(city)s")); p["city"] = arg("city").lower() + "%"
    if arg("q"):
        f.append(("q", "(c.customer_id LIKE %(q)s OR c.customer_unique_id LIKE %(q)s)")); p["q"] = check_id(arg("q")) + "%"
    if arg("repeat") == "yes":
        f.append(("repeat", repeat_expr + " > 1"))
    where = [c for _, c in f]
    q = dict(p, limit=50, offset=50 * arg("page", 0, int))
    sql = f"""
SELECT c.customer_id, c.customer_unique_id, c.city, c.state_code,
       (SELECT COUNT(*) FROM orders o WHERE o.customer_id = c.customer_id) AS orders
FROM v_customer_public c
{"WHERE " + chr(10) + "  AND ".join(where) if where else ""}
ORDER BY c.state_code, c.city
LIMIT %(limit)s OFFSET %(offset)s"""
    with session(user, read_only=True) as s:
        rows = s.all(sql, q, label="search customers")
        facets = None
        if arg("facets") == "1":
            facets = facet_counts(s, "v_customer_public c", f, {
                "state": "c.state_code",
                "repeat": f"CASE WHEN {repeat_expr} > 1 THEN 'yes' END",
            }, p)
        return ok(rows, s, facets=facets)


@app.get("/api/customers/<cid>")
@api(roles=["admin", "manager", "analyst", "support"])
def customer_detail(user, cid):
    with session(user, read_only=True) as s:
        acc = s.one("SELECT * FROM v_customer_public WHERE customer_id = %(id)s", {"id": check_id(cid)}, label="customer")
        if not acc:
            return fail("Customer not found", 404, s.log)
        history = s.all("""
SELECT o.order_id, o.order_status, o.purchase_ts, fn_order_total(o.order_id) AS total,
       (SELECT MIN(review_score) FROM review r WHERE r.order_id = o.order_id) AS rating
FROM orders o
JOIN v_customer_public c ON c.customer_id = o.customer_id
WHERE c.customer_unique_id = %(u)s
ORDER BY o.purchase_ts DESC""", {"u": acc["customer_unique_id"]}, label="order history of this person")
        zip_row = try_run(s, "SELECT zip_prefix FROM customer_account WHERE customer_id = %(id)s", {"id": cid},
                          label="zip (restricted column)")
        return ok({"customer": acc, "orders": history,
                   "zip_prefix": zip_row[0]["zip_prefix"] if zip_row else None}, s)


@app.post("/api/customers")
@api(roles=["admin", "manager"])
def customer_create(user):
    b = body()
    p = {"u": check_id(b.get("customer_unique_id")) if b.get("customer_unique_id") else new_id(),
         "id": new_id(), "zip": int(b["zip_prefix"])}
    with session(user) as s:
        s.run("INSERT INTO customer(customer_unique_id) VALUES (%(u)s) ON CONFLICT DO NOTHING", p, label="insert person")
        row = s.one("INSERT INTO customer_account(customer_id, customer_unique_id, zip_prefix)\n"
                    "VALUES (%(id)s, %(u)s, %(zip)s) RETURNING *", p, label="insert account")
        info = s.one("SELECT city, state_code FROM zip_code WHERE zip_prefix = %(zip)s", p,
                     label="city/state come from zip_code (3NF)")
        return ok({**row, **(info or {})}, s)


@app.put("/api/customers/<cid>")
@api(roles=["admin", "manager"])
def customer_update(user, cid):
    with session(user) as s:
        row = s.one("UPDATE customer_account SET zip_prefix = %(zip)s WHERE customer_id = %(id)s RETURNING *",
                    {"zip": int(body()["zip_prefix"]), "id": check_id(cid)}, label="update address")
        return ok(row, s)


@app.delete("/api/customers/<cid>")
@api(roles=["admin", "manager"])
def customer_delete(user, cid):
    with session(user) as s:
        row = s.one("DELETE FROM customer_account WHERE customer_id = %(id)s RETURNING customer_unique_id",
                    {"id": check_id(cid)}, label="delete account")
        if row:
            s.run("""DELETE FROM customer c WHERE c.customer_unique_id = %(u)s
AND NOT EXISTS (SELECT 1 FROM customer_account a WHERE a.customer_unique_id = c.customer_unique_id)""",
                  {"u": row["customer_unique_id"]}, label="delete person if no accounts left")
        return ok({"deleted": 1 if row else 0}, s)


# ---------------------------------------------------------------------------
# SELLERS
# ---------------------------------------------------------------------------
@app.get("/api/sellers")
@api(roles=["admin", "manager", "analyst"])
def sellers_search(user):
    f, p = [], {}
    if arg("state"):
        f.append(("state", "seller_state = %(state)s")); p["state"] = arg("state").upper()
    if arg("min_orders"):
        f.append(("min_orders", "orders >= %(mino)s")); p["mino"] = arg("min_orders", cast=int)
    if arg("max_rating"):
        f.append(("max_rating", "avg_rating <= %(maxr)s")); p["maxr"] = arg("max_rating", cast=float)
    if arg("q"):
        f.append(("q", "seller_id LIKE %(q)s")); p["q"] = check_id(arg("q")) + "%"
    where = [c for _, c in f]
    order = {"revenue": "revenue DESC NULLS LAST", "rating": "avg_rating ASC NULLS LAST",
             "late": "late_pct DESC NULLS LAST"}.get(arg("sort", "revenue"), "revenue DESC NULLS LAST")
    sql = f"""
SELECT seller_id, seller_city, seller_state, orders, ROUND(revenue, 2) AS revenue, avg_rating, late_pct
FROM v_seller_performance
{"WHERE " + chr(10) + "  AND ".join(where) if where else ""}
ORDER BY {order}
LIMIT %(limit)s"""
    with session(user, read_only=True) as s:
        rows = s.all(sql, dict(p, limit=50), label="seller scorecard (view)")
        facets = None
        if arg("facets") == "1":
            facets = facet_counts(s, "v_seller_performance", f, {"state": "seller_state"}, p)
        return ok(rows, s, facets=facets)


@app.post("/api/sellers")
@api(roles=["admin", "manager"])
def seller_create(user):
    with session(user) as s:
        row = s.one("INSERT INTO seller(seller_id, zip_prefix) VALUES (%(id)s, %(zip)s) RETURNING *",
                    {"id": new_id(), "zip": int(body()["zip_prefix"])}, label="insert seller")
        return ok(row, s)


@app.put("/api/sellers/<sid>")
@api(roles=["admin", "manager"])
def seller_update(user, sid):
    with session(user) as s:
        row = s.one("UPDATE seller SET zip_prefix = %(zip)s WHERE seller_id = %(id)s RETURNING *",
                    {"zip": int(body()["zip_prefix"]), "id": check_id(sid)}, label="update seller")
        return ok(row, s)


@app.delete("/api/sellers/<sid>")
@api(roles=["admin", "manager"])
def seller_delete(user, sid):
    with session(user) as s:
        res = s.run("DELETE FROM seller WHERE seller_id = %(id)s", {"id": check_id(sid)}, label="delete seller")
        return ok({"deleted": res["row_count"]}, s)


# ---------------------------------------------------------------------------
# REVIEWS
# ---------------------------------------------------------------------------
@app.get("/api/reviews")
@api()
def reviews_search(user):
    f, p = [], {}
    if arg("word"):
        f.append(("word", "to_tsvector('portuguese', coalesce(r.comment_title,'') || ' ' || coalesce(r.comment_message,''))"
                          " @@ plainto_tsquery('portuguese', %(word)s)"))
        p["word"] = arg("word")
    if arg("score"):
        f.append(("score", "r.review_score = %(score)s")); p["score"] = arg("score", cast=int)
    if arg("order_id"):
        f.append(("order_id", "r.order_id = %(oid)s")); p["oid"] = check_id(arg("order_id"))
    if arg("unanswered") == "yes":
        f.append(("unanswered", "r.answer_ts IS NULL"))
    if arg("has_comment") == "yes":
        f.append(("has_comment", "r.comment_message IS NOT NULL"))
    where = [c for _, c in f]
    q = dict(p, limit=50, offset=50 * arg("page", 0, int))
    sql = f"""
SELECT r.review_id, r.order_id, r.review_score, r.comment_title, r.comment_message,
       r.creation_date, r.answer_ts
FROM review r
{"WHERE " + chr(10) + "  AND ".join(where) if where else ""}
ORDER BY r.creation_date DESC
LIMIT %(limit)s OFFSET %(offset)s"""
    with session(user, read_only=True) as s:
        rows = s.all(sql, q, label="search reviews")
        facets = None
        if arg("facets") == "1":
            facets = facet_counts(s, "review r", f, {
                "score": "r.review_score",
                "has_comment": "CASE WHEN r.comment_message IS NOT NULL THEN 'yes' END",
                "unanswered": "CASE WHEN r.answer_ts IS NULL THEN 'yes' END",
            }, p)
        return ok(rows, s, facets=facets)


@app.post("/api/reviews")
@api(roles=["admin", "manager"])
def review_create(user):
    b = body()
    p = {"rid": new_id(), "oid": check_id(b.get("order_id")), "score": int(b["review_score"]),
         "title": b.get("comment_title") or None, "msg": b.get("comment_message") or None}
    with session(user) as s:
        row = s.one("""INSERT INTO review(review_id, order_id, review_score, comment_title, comment_message, creation_date)
VALUES (%(rid)s, %(oid)s, %(score)s, %(title)s, %(msg)s, now())
RETURNING *""", p, label="insert review (trigger checks the order was delivered)")
        return ok(row, s)


@app.put("/api/reviews/<rid>/<oid>")
@api(roles=["admin", "manager", "support"])
def review_update(user, rid, oid):
    b = body()
    p = {"rid": check_id(rid), "oid": check_id(oid)}
    with session(user) as s:
        if b.get("answer"):
            row = s.one("UPDATE review SET answer_ts = now() WHERE review_id = %(rid)s AND order_id = %(oid)s "
                        "RETURNING review_id, order_id, answer_ts", p, label="mark review answered")
        else:
            p["score"] = int(b["review_score"])
            row = s.one("UPDATE review SET review_score = %(score)s WHERE review_id = %(rid)s AND order_id = %(oid)s "
                        "RETURNING review_id, order_id, review_score", p, label="change score")
        return ok(row, s)


@app.delete("/api/reviews/<rid>/<oid>")
@api(roles=["admin", "manager"])
def review_delete(user, rid, oid):
    with session(user) as s:
        res = s.run("DELETE FROM review WHERE review_id = %(rid)s AND order_id = %(oid)s",
                    {"rid": check_id(rid), "oid": check_id(oid)}, label="delete review")
        return ok({"deleted": res["row_count"]}, s)


# ---------------------------------------------------------------------------
# CATEGORIES
# ---------------------------------------------------------------------------
@app.get("/api/categories")
@api()
def categories_list(user):
    with session(user, read_only=True) as s:
        rows = s.all("""
SELECT c.category_name, c.category_name_en, COUNT(p.product_id) AS products
FROM category c LEFT JOIN product p ON p.category_name = c.category_name
GROUP BY c.category_name, c.category_name_en
ORDER BY products DESC""", label="categories with product counts")
        return ok(rows, s)


@app.post("/api/categories")
@api(roles=["admin", "manager"])
def category_create(user):
    b = body()
    with session(user) as s:
        row = s.one("INSERT INTO category(category_name, category_name_en) VALUES (%(pt)s, %(en)s) RETURNING *",
                    {"pt": b["category_name"].strip().lower(), "en": b["category_name_en"].strip().lower()},
                    label="insert category")
        return ok(row, s)


@app.put("/api/categories/<name>")
@api(roles=["admin", "manager"])
def category_update(user, name):
    with session(user) as s:
        row = s.one("UPDATE category SET category_name_en = %(en)s WHERE category_name = %(pt)s RETURNING *",
                    {"en": body()["category_name_en"].strip().lower(), "pt": name}, label="rename category")
        return ok(row, s)


@app.delete("/api/categories/<name>")
@api(roles=["admin", "manager"])
def category_delete(user, name):
    with session(user) as s:
        res = s.run("DELETE FROM category WHERE category_name = %(pt)s", {"pt": name}, label="delete category")
        return ok({"deleted": res["row_count"]}, s)


# ---------------------------------------------------------------------------
# REPORTS (Q1-Q16), EXPLAIN, SQL console
# ---------------------------------------------------------------------------
@app.get("/api/reports")
@api()
def reports_list(user):
    return jsonify({"ok": True, "data": [{k: q[k] for k in ("id", "title", "concept", "params", "sql")} for q in QUERIES]})


def _report_params(q, given):
    params = {}
    for k, default in q["params"].items():
        v = given.get(k, default)
        params[k] = type(default)(v) if v not in (None, "") else default
    return params


@app.post("/api/reports/<qid>")
@api()
def report_run(user, qid):
    q = QUERY_BY_ID.get(qid)
    if not q:
        return fail("Unknown report", 404)
    with session(user, read_only=True) as s:
        res = s.run(q["sql"], _report_params(q, body()), label=f"{q['id']} - {q['concept']}")
        return ok(res, s)


@app.post("/api/reports/<qid>/explain")
@api()
def report_explain(user, qid):
    q = QUERY_BY_ID.get(qid)
    if not q:
        return fail("Unknown report", 404)
    with session(user, read_only=True) as s:
        res = s.run("EXPLAIN (ANALYZE, COSTS OFF, SUMMARY ON) " + q["sql"].strip(), _report_params(q, body()),
                    label="query plan")
        return ok({"plan": "\n".join(r["QUERY PLAN"] for r in res["rows"])}, s)


@app.get("/api/reports/<qid>/csv")
@api()
def report_csv(user, qid):
    import csv
    import io
    q = QUERY_BY_ID.get(qid)
    if not q:
        return fail("Unknown report", 404)
    with session(user, read_only=True) as s:
        res = s.run(q["sql"], _report_params(q, request.args), max_rows=100000)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(res["columns"])
    for r in res["rows"]:
        w.writerow([r[c] for c in res["columns"]])
    return app.response_class(buf.getvalue(), mimetype="text/csv",
                              headers={"Content-Disposition": f"attachment; filename={qid}.csv"})


@app.post("/api/sql")
@api(roles=["admin", "manager", "analyst"])
def sql_console(user):
    sql = (body().get("sql") or "").strip().rstrip(";")
    if not re.match(r"^(select|with|explain|show|table|values)\b", sql, re.I) or ";" in sql:
        return fail("The console accepts one read-only statement (SELECT / WITH / EXPLAIN / SHOW).", 400)
    with session(user, read_only=True) as s:
        return ok(s.run(sql, label="console"), s)


# ---------------------------------------------------------------------------
# SCHEMA / ER model (read from the live catalog)
# ---------------------------------------------------------------------------
@app.get("/api/schema")
@api()
def schema(user):
    with session(user, read_only=True) as s:
        cols = s.all("""
SELECT c.table_name, c.column_name, c.data_type, c.character_maximum_length AS max_len,
       c.is_nullable, c.column_default,
       EXISTS (SELECT 1 FROM information_schema.table_constraints tc
               JOIN information_schema.key_column_usage k
                 ON k.constraint_name = tc.constraint_name AND k.table_name = tc.table_name
               WHERE tc.constraint_type = 'PRIMARY KEY' AND tc.table_name = c.table_name
                 AND k.column_name = c.column_name) AS is_pk
FROM information_schema.columns c
JOIN information_schema.tables t ON t.table_name = c.table_name AND t.table_schema = c.table_schema
WHERE c.table_schema = 'public' AND t.table_type = 'BASE TABLE'
ORDER BY c.table_name, c.ordinal_position""", label="columns + primary keys", max_rows=1000)
        fks = s.all("""
SELECT conrelid::regclass::text AS table_name, conname AS constraint_name,
       pg_get_constraintdef(oid) AS definition
FROM pg_constraint
WHERE contype IN ('f','c','u') AND connamespace = 'public'::regnamespace
ORDER BY 1, contype, 2""", label="foreign keys, CHECK and UNIQUE constraints", max_rows=1000)
        counts = s.all("""
SELECT relname AS table_name, reltuples::bigint AS approx_rows
FROM pg_class WHERE relnamespace = 'public'::regnamespace AND relkind = 'r' ORDER BY 1""", label="row estimates")
        objects = s.all("""
SELECT 'view' AS kind, table_name AS name FROM information_schema.views WHERE table_schema = 'public'
UNION ALL SELECT 'materialized view', matviewname FROM pg_matviews WHERE schemaname = 'public'
UNION ALL SELECT 'trigger', trigger_name || ' ON ' || event_object_table || ' (' ||
                 string_agg(event_manipulation, '/') || ')' FROM information_schema.triggers
          WHERE trigger_schema = 'public' GROUP BY trigger_name, event_object_table
UNION ALL SELECT CASE p.prokind WHEN 'p' THEN 'procedure' ELSE 'function' END,
                 p.proname || '(' || pg_get_function_identity_arguments(p.oid) || ')'
          FROM pg_proc p WHERE p.pronamespace = 'public'::regnamespace
            AND p.proname NOT LIKE 'trg_%' AND p.proname NOT IN (SELECT extname FROM pg_extension)
            AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.objid = p.oid AND d.deptype = 'e')
UNION ALL SELECT 'index', indexname || ' ON ' || tablename FROM pg_indexes WHERE schemaname = 'public'
UNION ALL SELECT 'RLS policy', policyname || ' ON ' || tablename || ' TO ' || array_to_string(roles, ',')
          FROM pg_policies WHERE schemaname = 'public'
ORDER BY 1, 2""", label="views, triggers, routines, indexes, policies", max_rows=1000)
        grants = s.all("""
SELECT grantee, table_name, string_agg(privilege_type, ', ' ORDER BY privilege_type) AS privileges
FROM information_schema.role_table_grants
WHERE grantee LIKE 'olist_%' AND table_schema = 'public'
GROUP BY grantee, table_name ORDER BY grantee, table_name""", label="role privileges", max_rows=1000)
        return ok({"columns": cols, "constraints": fks, "counts": counts, "objects": objects, "grants": grants}, s)


# ---------------------------------------------------------------------------
# ML
# ---------------------------------------------------------------------------
@app.get("/api/ml/summary")
@api(roles=["admin", "manager", "analyst"])
def ml_summary(user):
    with session(user, read_only=True) as s:
        model = s.one("SELECT * FROM ml_model WHERE is_active ORDER BY trained_at DESC LIMIT 1", label="active model")
        if not model:
            return ok({"model": None}, s)
        confusion = s.all("""
SELECT CASE WHEN f.is_late = 1 THEN 'actually late' ELSE 'actually on time' END AS actual,
       COUNT(*) FILTER (WHERE mp.late_probability >= m.threshold) AS predicted_late,
       COUNT(*) FILTER (WHERE mp.late_probability <  m.threshold) AS predicted_on_time
FROM ml_prediction mp
JOIN mv_order_features f ON f.order_id = mp.order_id
JOIN ml_model m          ON m.model_version = mp.model_version
WHERE f.is_late IS NOT NULL AND f.purchase_ts >= '2018-06-01' AND f.purchase_ts < '2018-09-01'
GROUP BY 1 ORDER BY 1 DESC""", label="confusion matrix on the test months, computed in SQL")
        deciles = s.all("""
SELECT bucket AS risk_decile, COUNT(*) AS orders,
       ROUND(100.0 * AVG(is_late), 1) AS actual_late_pct,
       ROUND(100.0 * AVG(late_probability), 1) AS avg_predicted_pct
FROM (SELECT f.is_late, mp.late_probability,
             NTILE(10) OVER (ORDER BY mp.late_probability) AS bucket
      FROM ml_prediction mp JOIN mv_order_features f ON f.order_id = mp.order_id
      WHERE f.is_late IS NOT NULL AND f.purchase_ts >= '2018-06-01' AND f.purchase_ts < '2018-09-01') t
GROUP BY bucket ORDER BY bucket""", label="actual late rate by predicted-risk decile (window function NTILE)")
        days = s.one("""
SELECT ROUND(AVG(ABS(mp.predicted_days - f.delivery_days)), 2) AS model_mae_days,
       ROUND(AVG(ABS(f.promised_days - f.delivery_days)), 2)  AS promise_mae_days,
       COUNT(*) AS orders
FROM ml_prediction mp JOIN mv_order_features f ON f.order_id = mp.order_id
WHERE f.delivery_days IS NOT NULL AND f.purchase_ts >= '2018-06-01' AND f.purchase_ts < '2018-09-01'""",
                     label="delivery-days error: model vs Olist's promise")
        risky = s.all("""
SELECT order_id, order_status, purchase_ts, customer_state, seller_state, distance_km, main_category,
       late_probability, predicted_days
FROM v_high_risk_orders ORDER BY late_probability DESC LIMIT 15""", label="open orders with highest risk")
        return ok({"model": model, "confusion": confusion, "deciles": deciles, "days": days, "risky": risky}, s)


@app.post("/api/ml/predict")
@api(roles=["admin", "manager"])
def ml_predict(user):
    """What-if: place the order inside a transaction, read its live features,
    score it, then ROLLBACK - nothing is saved."""
    b = body()
    items = [{"product_id": check_id(b.get("product_id"), "product id"), "seller_id": check_id(b.get("seller_id"), "seller id")}]
    with session(user, commit=False) as s:
        row = s.one("CALL sp_place_order(%(c)s, %(items)s::jsonb, %(pt)s, %(n)s, NULL)",
                    {"c": check_id(b.get("customer_id"), "customer id"), "items": json.dumps(items),
                     "pt": b.get("payment_type", "credit_card"), "n": int(b.get("installments", 1))},
                    label="temporary order (will be rolled back)")
        feats = s.all("SELECT * FROM v_order_features WHERE order_id = %(id)s", {"id": row["p_order_id"]},
                      label="ML features (live view)")
        pred = ml_service.score(feats)[0]
        return ok({"prediction": pred, "features": feats[0]}, s)


# ---------------------------------------------------------------------------
# TRANSACTIONS & CONCURRENCY LAB
# ---------------------------------------------------------------------------
DEMO = {"customer": "9ef432eb6251297304e76186b10a928d", "product": "4244733e06e7ecb4970a6e2683c13e61",
        "seller": "48436dade18ac8b2bce089ec2a041202", "delivered_order": "e481f51cbdc54678b7cc49136f2d6af7"}


@app.post("/api/lab/<demo>")
@api(roles=["admin", "manager"])
def lab(user, demo):
    if demo == "atomicity":
        with session(user, commit=False) as s:
            before = s.one("SELECT COUNT(*) AS orders, (SELECT COUNT(*) FROM order_item) AS items FROM orders",
                           label="count before")
            s.savepoint("demo")
            error = None
            try:
                s.run("CALL sp_place_order(%(c)s, %(items)s::jsonb)", {"c": DEMO["customer"], "items": json.dumps([
                    {"product_id": DEMO["product"], "seller_id": DEMO["seller"], "price": 50, "freight": 10},
                    {"product_id": "no_such_product_000000000000000", "seller_id": DEMO["seller"], "price": 20, "freight": 5}])},
                    label="order: item 1 valid, item 2 unknown product")
            except DBError as e:
                error = e.message
                s.rollback_to("demo")
            after = s.one("SELECT COUNT(*) AS orders, (SELECT COUNT(*) FROM order_item) AS items FROM orders",
                          label="count after")
            return ok({"before": before, "after": after, "error": error,
                       "explanation": "The procedure failed on item 2, so item 1 and the order row were undone too."}, s)

    if demo == "consistency":
        tests = [
            ("CHECK review_score BETWEEN 1 AND 5",
             "INSERT INTO review(review_id, order_id, review_score, creation_date) VALUES ('demo_review_000000000000000000', %(o)s, 7, now())"),
            ("CHECK price > 0",
             "UPDATE order_item SET price = -5 WHERE order_id = %(o)s AND order_item_id = 1"),
            ("FOREIGN KEY orders.customer_id",
             "INSERT INTO orders(order_id, customer_id, order_status, purchase_ts, estimated_delivery_date) "
             "VALUES ('demo_order_0000000000000000000', 'no_such_customer_000000000000000', 'created', now(), now())"),
            ("TRIGGER: status can only move forward",
             "UPDATE orders SET order_status = 'processing' WHERE order_id = %(o)s"),
            ("TRIGGER: delivered orders cannot be deleted",
             "DELETE FROM orders WHERE order_id = %(o)s"),
            ("CHECK stock_qty >= 0",
             "UPDATE product SET stock_qty = -1 WHERE product_id = %(p)s"),
        ]
        results = []
        with session(user, commit=False) as s:
            for rule, sql in tests:
                s.savepoint("t")
                try:
                    s.run(sql, {"o": DEMO["delivered_order"], "p": DEMO["product"]}, label=rule)
                    results.append({"rule": rule, "result": "accepted (unexpected)"})
                except DBError as e:
                    s.rollback_to("t")
                    results.append({"rule": rule, "result": "rejected", "error": e.message})
            return ok(results, s)

    if demo == "isolation":
        level = body().get("level", "READ COMMITTED").upper()
        if level not in ("READ COMMITTED", "REPEATABLE READ", "SERIALIZABLE"):
            raise ValueError("level")
        steps, log = [], []
        a, b = connect(), connect()
        q = "SELECT stock_qty FROM product WHERE product_id = %s"
        try:
            ca, cb = a.cursor(), b.cursor()
            for c in (ca, cb):
                c.execute("SET ROLE olist_manager")
            a.commit(); b.commit()
            ca.execute(f"SET TRANSACTION ISOLATION LEVEL {level}")
            ca.execute(q, (DEMO["product"],)); first = ca.fetchone()[0]
            steps.append({"session": "A", "sql": f"BEGIN ISOLATION LEVEL {level};\n" + ca.mogrify(q, (DEMO["product"],)),
                          "result": f"stock_qty = {first}"})
            cb.execute("UPDATE product SET stock_qty = stock_qty + 5 WHERE product_id = %s", (DEMO["product"],)); b.commit()
            steps.append({"session": "B", "sql": cb.mogrify("UPDATE product SET stock_qty = stock_qty + 5 WHERE product_id = %s",
                                                           (DEMO["product"],)) + ";\nCOMMIT;", "result": "committed +5"})
            ca.execute(q, (DEMO["product"],)); second = ca.fetchone()[0]
            steps.append({"session": "A", "sql": ca.mogrify(q, (DEMO["product"],)), "result": f"stock_qty = {second}"})
            a.rollback()
            steps.append({"session": "A", "sql": "ROLLBACK;", "result": ""})
            cb.execute("UPDATE product SET stock_qty = stock_qty - 5 WHERE product_id = %s", (DEMO["product"],)); b.commit()
            steps.append({"session": "B", "sql": "-- undo the demo change\nUPDATE product SET stock_qty = stock_qty - 5 ...; COMMIT;",
                          "result": "restored"})
        finally:
            a.close(); b.close()
        same = first == second
        return jsonify({"ok": True, "data": {"level": level, "steps": steps, "first": first, "second": second,
                        "explanation": ("Session A saw the SAME value both times: its snapshot was taken at the first "
                                        "read (no non-repeatable read)." if same else
                                        "Session A saw B's committed change inside its own transaction: "
                                        "a non-repeatable read, allowed under READ COMMITTED.")},
                        "queries": log})

    if demo == "lost_update":
        locking = bool(body().get("locking"))
        pid = DEMO["product"]
        read_sql = "SELECT stock_qty FROM product WHERE product_id = %s" + (" FOR UPDATE" if locking else "")
        steps = []
        start_conn = connect(); c0 = start_conn.cursor()
        c0.execute("SET ROLE olist_manager")
        c0.execute("SELECT stock_qty FROM product WHERE product_id = %s", (pid,)); start = c0.fetchone()[0]
        start_conn.rollback()
        barrier = threading.Barrier(2, timeout=10)

        def worker(name, delay):
            conn = connect(); cur = conn.cursor()
            try:
                cur.execute("SET ROLE olist_manager")
                cur.execute("SET lock_timeout = '8s'")
                if not locking:
                    barrier.wait()          # both read before either writes
                else:
                    time.sleep(delay)
                t = time.perf_counter()
                cur.execute(read_sql, (pid,)); seen = cur.fetchone()[0]
                waited = round((time.perf_counter() - t) * 1000)
                steps.append({"session": name, "sql": cur.mogrify(read_sql, (pid,)),
                              "result": f"read {seen}" + (f" (waited {waited} ms for the lock)" if waited > 50 else "")})
                if not locking:
                    barrier.wait()
                time.sleep(0.5 if name == "A" else 0.8)
                cur.execute("UPDATE product SET stock_qty = %s WHERE product_id = %s", (seen - 1, pid))
                conn.commit()
                steps.append({"session": name, "sql": cur.mogrify("UPDATE product SET stock_qty = %s WHERE product_id = %s",
                                                                (seen - 1, pid)) + ";\nCOMMIT;",
                              "result": f"wrote {seen - 1}"})
            finally:
                conn.close()

        threads = [threading.Thread(target=worker, args=("A", 0)), threading.Thread(target=worker, args=("B", 0.2))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        c1 = connect(); cur = c1.cursor()
        cur.execute("SET ROLE olist_manager")
        cur.execute("SELECT stock_qty FROM product WHERE product_id = %s", (pid,)); end = cur.fetchone()[0]
        cur.execute("UPDATE product SET stock_qty = %s WHERE product_id = %s", (start, pid)); c1.commit(); c1.close()
        lost = (start - end) < 2
        return jsonify({"ok": True, "data": {
            "locking": locking, "start": start, "end": end, "steps": steps,
            "explanation": (f"Two sales but stock only fell from {start} to {end}: one update was LOST."
                            if lost else f"Stock fell from {start} to {end}: FOR UPDATE made B wait for A, "
                                         "so both sales were counted."),
            "note": "Stock was restored to its starting value afterwards."}, "queries": []})

    return fail("unknown demo", 404)


# ---------------------------------------------------------------------------
# ADMIN: application users
# ---------------------------------------------------------------------------
@app.get("/api/admin/users")
@api(roles=["admin"])
def users_list(user):
    with session(user, read_only=True) as s:
        rows = s.all("SELECT user_id, username, app_role, seller_id, is_active, "
                     "left(password_hash, 7) || '...' AS bcrypt_hash FROM app_user ORDER BY user_id", label="users")
        return ok(rows, s)


@app.post("/api/admin/users")
@api(roles=["admin"])
def users_create(user):
    b = body()
    if b.get("app_role") not in ("admin", "manager", "analyst", "seller", "support"):
        raise ValueError("role")
    with session(user) as s:
        s.run("CALL sp_create_user(%(u)s, %(p)s, %(r)s, %(sid)s)",
              {"u": b["username"], "p": b["password"], "r": b["app_role"], "sid": b.get("seller_id") or None},
              label="create user (bcrypt hash computed in PostgreSQL)")
        for entry in s.log:
            if entry.get("sql") and "sp_create_user" in entry["sql"]:
                entry["sql"] = entry["sql"].replace(f"'{b['password']}'", "'********'")
        return ok({"username": b["username"]}, s)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    print(f"\n  Olist DBMS app running:  http://localhost:{port}\n")
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
