# Test Plan & Test Report

**Project:** E-Commerce & Order Management System (Olist)
**Course:** Software Engineering & Project Management (SEPM)
**Test lead:** Tanishq Mahajan · **Testers:** all team members
**Version:** 1.0 (mid-semester)

---

## 1. Objectives
Check that the system meets the requirements in [SRS.md](SRS.md): business rules are enforced by the database, every role sees only what it is allowed to, transactions behave per ACID, the UI shows the SQL it runs, and the ML model is evaluated correctly.

## 2. Scope
| In scope | Out of scope |
|---|---|
| Database constraints, triggers, procedures, RLS, grants | Load/stress testing beyond the Olist dataset |
| Flask API endpoints through the UI | Cross-browser testing beyond Chrome/Edge |
| All UI pages and role-specific behaviour | Penetration testing by third parties |
| ML pipeline and metrics | |

## 3. Test levels and approach

| Level | Approach | Tools |
|---|---|---|
| Unit (DB) | Run SQL scripts that deliberately violate each rule and check the error | psql, `db/10`–`14` |
| Unit (ML) | Time-series cross-validation, held-out test months, baseline comparison | `ml/train.py` |
| Integration | Each UI action → check the SQL panel and the DB state | Browser + psql |
| System | End-to-end use cases UC-1 … UC-9 for each role | Browser |
| Security | Negative tests with low-privilege roles and malicious input | Browser, psql |
| Regression | Rebuild the DB from scratch and rerun the full suite after each sprint | `setup_db.bat` |

## 4. Environment
Windows 11 laptop, PostgreSQL 16, Python 3.12, Flask 3, Chrome. Full Olist dataset (99,441 orders).

## 5. Entry / exit criteria
- **Entry:** the database builds without errors, the app starts, and the model is trained.
- **Exit:** all High-priority test cases pass; any failures are logged with a fix or a documented limitation.

---

## 6. Test cases

**Priority:** H = high, M = medium, L = low. **Result:** ✅ pass · ❌ fail · ⏳ not run yet

### 6.1 Database build and data

| ID | Requirement | Test | Expected result | Pri | Result |
|---|---|---|---|---|---|
| TC-01 | NFR-7 | Run `setup_db.bat` on an empty server | All 8 steps finish, no errors | H | ⏳ |
| TC-02 | Data | Compare row counts with the CSVs | orders 99,441 · order_item 112,650 · payment 103,886 · review 99,224 | H | ⏳ |
| TC-03 | NFR-3 | Insert an order_item with an unknown product_id | FK violation, row rejected | H | ⏳ |
| TC-04 | NFR-3 | Insert a payment with a negative value | CHECK violation | M | ⏳ |
| TC-05 | Data | `SELECT * FROM v_data_quality` | Anomalies listed (missing coordinates, etc.) | L | ⏳ |

### 6.2 Business rules (triggers and procedures)

| ID | Requirement | Test | Expected result | Pri | Result |
|---|---|---|---|---|---|
| TC-06 | FR-6 | Change a delivered order back to `shipped` | Error "cannot change", status unchanged | H | ⏳ |
| TC-07 | FR-6 | Move an order `approved → shipped` | Allowed (forward move) | H | ⏳ |
| TC-08 | FR-7 | Change any order's status | New row in `order_status_log` with old/new status and role | H | ⏳ |
| TC-09 | FR-8 | Delete a delivered order | Error "was delivered and cannot be deleted" | H | ⏳ |
| TC-10 | FR-9 | Add a review for an order in `processing` | Error "can be reviewed only after delivery" | M | ⏳ |
| TC-11 | FR-5 | `CALL sp_place_order` with a valid customer and 2 items | Order + 2 items + payment inserted; stock reduced | H | ⏳ |
| TC-12 | FR-5 | `sp_place_order` with an unknown customer | Error; nothing inserted (atomicity) | H | ⏳ |
| TC-13 | FR-10 | Order more units than in stock | CHECK `stock_qty >= 0` fails; whole order rolled back | H | ⏳ |
| TC-14 | FR-5 | `CALL sp_cancel_order` on a delivered order | Error "cannot be canceled" | M | ⏳ |

### 6.3 Security and RBAC

| ID | Requirement | Test | Expected result | Pri | Result |
|---|---|---|---|---|---|
| TC-15 | FR-1 | Log in with a wrong password | "Wrong username or password", no session | H | ⏳ |
| TC-16 | FR-1 | `SELECT password_hash FROM app_user` as `olist_app` | Permission denied | H | ⏳ |
| TC-17 | FR-16 | Log in as `seller`, open Orders | Only orders containing that seller's items | H | ⏳ |
| TC-18 | FR-16 | As `analyst`, select `zip_code.lat` | Permission denied (column privilege) | H | ⏳ |
| TC-19 | FR-2 | As `analyst`, try to delete a product | 403, error from PostgreSQL (42501) | H | ⏳ |
| TC-20 | NFR-2 | Search orders with `' OR 1=1 --` | Treated as a literal string; no extra rows | H | ⏳ |
| TC-21 | FR-20 | SQL console: `DELETE FROM orders` | Rejected (read-only transaction) | H | ⏳ |

### 6.4 Front end and reports

| ID | Requirement | Test | Expected result | Pri | Result |
|---|---|---|---|---|---|
| TC-22 | FR-3 | Create, edit and delete a product from the UI | Each action succeeds; SQL panel shows INSERT/UPDATE/DELETE | H | ⏳ |
| TC-23 | FR-11 | Filter orders by state = SP and status = delivered | Row counts on the dropdowns update; results match the SQL | M | ⏳ |
| TC-24 | FR-12 | Run each report Q1–Q16 | Rows returned, no error | H | ⏳ |
| TC-25 | FR-12 | EXPLAIN and CSV export on Q5 | Plan shown; CSV downloads with the same rows | M | ⏳ |
| TC-26 | FR-14 | Click "ER model & schema" | ER diagram and live catalog tables shown | H | ⏳ |
| TC-27 | FR-15 | Transactions lab: lost update without and with `FOR UPDATE` | First loses one update; second keeps both | H | ⏳ |
| TC-28 | NFR-5 | Order search on the full data | Response < 1 s | M | ⏳ |

### 6.5 ML component

| ID | Requirement | Test | Expected result | Pri | Result |
|---|---|---|---|---|---|
| TC-29 | NFR-10 | Run `train_model.bat` | Models compared with CV; best model saved; metrics in `ml_model` | H | ⏳ |
| TC-30 | FR-17 | Place an order in the UI | Risk level and predicted days shown; row in `ml_prediction` | H | ⏳ |
| TC-31 | FR-18 | "Predict risk only" | Prediction shown; order not saved (ROLLBACK) | M | ⏳ |

---

## 7. Defect log

| ID | Found in | Description | Severity | Fix | Status |
|---|---|---|---|---|---|
| D-01 | System test | Opening `http://localhost:5000/` returned 404 (no route for `/`) | Medium | Added an index route in `backend/app.py` | Fixed |
| D-02 | Installation test | With PostgreSQL not running, login failed with a timeout that was hard to understand | Low | `run_app.bat` now checks `pg_isready` first and explains the fix | Fixed |

## 8. Evidence
Screenshots of each page under test are in [`screenshots/`](screenshots/): dashboard, faceted order search, order detail with audit trail, reports with EXPLAIN, transactions lab, ML insights, what-if prediction, seller view (RLS) and the ER page.
