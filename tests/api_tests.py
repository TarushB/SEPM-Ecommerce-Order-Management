"""Functional tests through the Flask API (Front end -> API -> SQL -> DB -> result).

Start the app first (run_app.bat or `python backend/app.py`), then:
    python tests/api_tests.py [base_url]

Each test prints PASS/FAIL with the evidence it checked. Tests that change
data clean up after themselves (the product created in TC-22 is deleted; the
order placed in TC-30 stays, like any order placed in the UI).
"""
import sys
import time

import requests

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:5000"
results = []


def login(user):
    s = requests.Session()
    r = s.post(f"{BASE}/api/login", json={"username": user, "password": user + "123"})
    assert r.status_code == 200, r.text
    return s


def check(tc, name, cond, evidence):
    results.append((tc, cond))
    print(f"{'PASS' if cond else 'FAIL'}  {tc}  {name}\n      {evidence}")


def sqls(resp_json):
    return [q.get("sql", "").strip().split("\n")[0][:90] for q in resp_json.get("queries", [])]


# TC-15 wrong password -------------------------------------------------------
r = requests.post(f"{BASE}/api/login", json={"username": "admin", "password": "nope"})
check("TC-15", "login with a wrong password", r.status_code == 401 and "Wrong username" in r.json()["error"],
      f"HTTP {r.status_code}, error={r.json().get('error')!r}")

admin, manager, analyst, seller = login("admin"), login("manager"), login("analyst"), login("seller")

# TC-17 seller RLS through the app -------------------------------------------
r_all = manager.get(f"{BASE}/api/orders", params={"facets": "1"}).json()
r_sel = seller.get(f"{BASE}/api/orders", params={"facets": "1"}).json()
total_all = r_all["facets"]["status"]["total"]
total_sel = r_sel["facets"]["status"]["total"]
check("TC-17", "seller sees only its own orders (UI/API)",
      total_all is not None and total_sel is not None and 0 < total_sel < total_all,
      f"manager sees {total_all} orders, seller sees {total_sel}")

# TC-19 analyst delete -------------------------------------------------------
pid = analyst.get(f"{BASE}/api/products").json()["data"][0]["product_id"]
r = analyst.delete(f"{BASE}/api/products/{pid}")
check("TC-19", "analyst tries to delete a product", r.status_code == 403,
      f"HTTP {r.status_code}, error={r.json().get('error')!r}, sqlstate={r.json().get('sqlstate')}")

# TC-20 SQL injection -------------------------------------------------------
r1 = manager.get(f"{BASE}/api/orders", params={"order_id": "' OR 1=1 --"})
r2 = manager.get(f"{BASE}/api/orders", params={"state": "SP' OR '1'='1"})
check("TC-20", "SQL injection in search filters",
      r1.status_code == 400 and r2.status_code == 200 and len(r2.json()["data"]) == 0,
      f"order_id filter -> HTTP {r1.status_code} ({r1.json().get('error')!r}); "
      f"state filter -> HTTP {r2.status_code}, {len(r2.json().get('data') or [])} rows (treated as a literal)")

# TC-21 SQL console write ------------------------------------------------------
r = admin.post(f"{BASE}/api/sql", json={"sql": "DELETE FROM orders"})
r2 = admin.post(f"{BASE}/api/sql", json={"sql": "WITH d AS (DELETE FROM orders RETURNING 1) SELECT COUNT(*) FROM d"})
check("TC-21", "SQL console rejects DELETE",
      r.status_code == 400 and r2.status_code >= 400,
      f"plain DELETE -> HTTP {r.status_code}; DELETE hidden in a CTE -> HTTP {r2.status_code} "
      f"({(r2.json().get('error') or '')[:70]!r})")

# TC-22 product CRUD ------------------------------------------------------------
c = manager.post(f"{BASE}/api/products", json={"category_name": "beleza_saude", "weight_g": 500, "length_cm": 20,
                                              "height_cm": 10, "width_cm": 15, "photos_qty": 1, "stock_qty": 10}).json()
new_pid = c["data"]["product_id"]
u = manager.put(f"{BASE}/api/products/{new_pid}", json={"stock_qty": 25}).json()
d = manager.delete(f"{BASE}/api/products/{new_pid}").json()
check("TC-22", "create, edit and delete a product",
      c["ok"] and u["ok"] and u["data"]["stock_qty"] == 25 and d["data"]["deleted"] == 1,
      f"SQL panel: {sqls(c)[-1]!r} | {sqls(u)[-1]!r} | {sqls(d)[-1]!r}")

# TC-23 faceted filter ------------------------------------------------------------
r = manager.get(f"{BASE}/api/orders", params={"state": "SP", "status": "delivered", "facets": "1"}).json()
rows_ok = all(x["customer_state"] == "SP" and x["order_status"] == "delivered" for x in r["data"])
delivered_n = {v["value"]: v["n"] for v in r["facets"]["status"]["values"]}.get("delivered", 0)
check("TC-23", "filter orders by state=SP and status=delivered",
      r["ok"] and rows_ok and delivered_n > 0,
      f"{len(r['data'])} rows on page 1, all SP/delivered={rows_ok}; facet count delivered (SP)={delivered_n}")

# TC-24 all reports ------------------------------------------------------------
reports = analyst.get(f"{BASE}/api/reports").json()["data"]
bad = []
counts = {}
for q in reports:
    rr = analyst.post(f"{BASE}/api/reports/{q['id']}", json={}).json()
    if not rr["ok"] or not rr["data"]["rows"]:
        bad.append(q["id"])
    else:
        counts[q["id"]] = rr["data"]["row_count"] if "row_count" in rr["data"] else len(rr["data"]["rows"])
check("TC-24", f"run every report ({len(reports)} queries)", not bad,
      f"failed/empty: {bad or 'none'}; rows: {counts}")

# TC-25 EXPLAIN + CSV on Q5 ------------------------------------------------------
e = analyst.post(f"{BASE}/api/reports/Q5/explain", json={}).json()
rows = analyst.post(f"{BASE}/api/reports/Q5", json={}).json()["data"]["rows"]
csv = analyst.get(f"{BASE}/api/reports/Q5/csv")
csv_rows = len(csv.text.strip().splitlines()) - 1
check("TC-25", "EXPLAIN and CSV export on Q5",
      e["ok"] and "Execution Time" in e["data"]["plan"] and csv.headers["Content-Type"].startswith("text/csv")
      and csv_rows == len(rows),
      f"plan has {len(e['data']['plan'].splitlines())} lines; CSV rows={csv_rows}, UI rows={len(rows)}")

# TC-26 schema endpoint ----------------------------------------------------------
sc = admin.get(f"{BASE}/api/schema").json()
check("TC-26", "ER model & schema data from the live catalog", sc["ok"],
      f"keys returned: {sorted(sc['data'].keys()) if isinstance(sc.get('data'), dict) else type(sc.get('data'))}")

# TC-27 lost update ---------------------------------------------------------------
a = manager.post(f"{BASE}/api/lab/lost_update", json={"locking": False}).json()["data"]
b = manager.post(f"{BASE}/api/lab/lost_update", json={"locking": True}).json()["data"]
check("TC-27", "lost update without and with SELECT ... FOR UPDATE",
      (a["start"] - a["end"]) == 1 and (b["start"] - b["end"]) == 2,
      f"without lock: {a['start']} -> {a['end']}; with FOR UPDATE: {b['start']} -> {b['end']}")

# TC-28 search performance ---------------------------------------------------------
times = []
for params in ({}, {"state": "SP"}, {"status": "delivered", "facets": "1"}, {"state": "RJ", "late": "yes"}):
    t = time.perf_counter()
    manager.get(f"{BASE}/api/orders", params=params)
    times.append(round((time.perf_counter() - t) * 1000))
check("TC-28", "order search response time < 1 s", max(times) < 1000, f"response times (ms): {times}")

# TC-30 place an order with ML score ------------------------------------------------
cust = manager.get(f"{BASE}/api/lookup/customers").json()["data"][0]["customer_id"]
prod = manager.get(f"{BASE}/api/lookup/products").json()["data"][0]
o = manager.post(f"{BASE}/api/orders", json={"customer_id": cust, "payment_type": "credit_card", "installments": 1,
                                            "items": [{"product_id": prod["product_id"], "seller_id": prod["seller_id"]}]}).json()
oid = o["data"]["order_id"]
detail = manager.get(f"{BASE}/api/orders/{oid}").json()
check("TC-30", "place an order in the UI -> risk + predicted days stored",
      o["ok"] and o["data"]["prediction"] is not None,
      f"order {oid}: prediction={o['data']['prediction']}; SQL: {sqls(o)}")

# TC-31 predict only ---------------------------------------------------------------
before = admin.post(f"{BASE}/api/sql", json={"sql": "SELECT COUNT(*) AS n FROM orders"}).json()["data"]["rows"][0]["n"]
p = manager.post(f"{BASE}/api/ml/predict", json={"customer_id": cust, "product_id": prod["product_id"],
                                                "seller_id": prod["seller_id"]}).json()
after = admin.post(f"{BASE}/api/sql", json={"sql": "SELECT COUNT(*) AS n FROM orders"}).json()["data"]["rows"][0]["n"]
check("TC-31", "'Predict risk only' does not save the order",
      p["ok"] and p["data"]["prediction"] is not None and before == after,
      f"prediction={p['data']['prediction']}; orders before={before}, after={after}")

passed = sum(1 for _, ok in results if ok)
print(f"\n{passed}/{len(results)} API test cases passed")
sys.exit(0 if passed == len(results) else 1)
