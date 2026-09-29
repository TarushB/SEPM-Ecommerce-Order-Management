<div align="center">

# 🛒 E-Commerce & Order Management System

**SEPM course project: a database-centric order management system built on 100k real Brazilian e-commerce orders (Olist), with a web front end that shows every SQL query it runs and an ML model that predicts late deliveries.**

![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791?logo=postgresql&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-3.x-000000?logo=flask&logoColor=white)
![scikit-learn](https://img.shields.io/badge/scikit--learn-ML-F7931E?logo=scikitlearn&logoColor=white)
![Process](https://img.shields.io/badge/Process-Agile%20Scrum-6f42c1)
![Status](https://img.shields.io/badge/Status-Mid--semester%20release%20v1.0-2ea44f)

<img src="docs/screenshots/dashboard.png" alt="Dashboard with the live SQL panel" width="900">

</div>

---

## 📑 Table of contents

1. [Team](#-team)
2. [Problem statement & objectives](#-problem-statement--objectives)
3. [Scope](#-scope)
4. [Software process model](#-software-process-model)
5. [Requirements](#-requirements)
6. [System design](#-system-design)
7. [Features](#-features)
8. [Getting started](#-getting-started)
9. [Demo users & roles](#-demo-users--roles)
10. [Testing](#-testing)
11. [Project management](#-project-management)
12. [Repository structure](#-repository-structure)
13. [Screenshots](#-screenshots)
14. [Individual contributions](#-individual-contributions)
15. [Troubleshooting](#-troubleshooting)
16. [Acknowledgements](#-acknowledgements)

---

## 👥 Team

| Member | Role in the project | GitHub email |
|---|---|---|
| **Tarush Banke** | Project lead · Database architect (design, schema, data pipeline) | tarushbanke123@gmail.com |
| **Tanishk Varshney** | Back-end & database-logic developer (API, triggers, procedures, security) | tanishkvarshney370@gmail.com |
| **Tanishq Mahajan** | Front-end & ML developer · QA lead (UI, ML model, testing) | tanishqmahajan.dev@gmail.com |

---

## 🎯 Problem statement & objectives

Online marketplaces handle thousands of orders a day across many sellers, customers, payment methods and delivery routes. Kept in flat spreadsheets (as the raw Olist export is), this data suffers from **redundancy, update anomalies, no access control and no way to spot orders that are about to go wrong**.

**Goal:** design and build a system that stores this data correctly, lets different staff roles work with it safely through a web interface, and uses the data to predict late deliveries.

| # | Objective | Measured by |
|---|---|---|
| O1 | Model the domain and store it in a normalized (BCNF) relational database | ER model, keys, FDs, 16 tables in BCNF |
| O2 | Enforce business rules and security inside the DBMS | Constraints, 6 triggers, stored procedures, 5 roles + row-level security |
| O3 | Provide a web UI for insert, search, update, delete and reports that shows the SQL it executes | CRUD for 6 entities, 16 reports, SQL panel on every page |
| O4 | Demonstrate transactions, ACID and concurrency control | Transactions lab + SQL demo scripts |
| O5 | Add one useful AI/ML feature integrated with the DB and UI | Late-delivery classifier + delivery-time regressor, ROC-AUC 0.72 |
| O6 | Run the work as a managed software project | Sprints, task board, risk register, meeting minutes, Git history |

---

## 📐 Scope

**In scope:** order, product, customer, seller, review and category management; role-based access; reporting; transactions demo; late-delivery prediction; ER/schema viewer.

**Out of scope (this release):** real payment processing, customer-facing storefront, e-mail notifications, cloud deployment, mobile app.

**Constraints:** 3-member team, ~2 weeks for the mid-semester release, free/open-source tools only, must run on a Windows laptop.

---

## 🔄 Software process model

We followed **Agile Scrum** with short sprints, because requirements were clear at the top level (course rubric) but the details (which queries, which ML task, which UI pages) had to be discovered while exploring the data.

| Sprint | Dates (2026) | Sprint goal | Main owners |
|---|---|---|---|
| **Sprint 0** | 18 – 19 Sep | Requirements, dataset profiling, ER model, repo setup | Tarush |
| **Sprint 1** | 20 – 23 Sep | Schema, data loading & cleaning, indexes, views, triggers, procedures, security | Tarush, Tanishk |
| **Sprint 2** | 24 – 27 Sep | Flask API, front end, report queries, ML model | Tanishk, Tanishq |
| **Sprint 3** | 28 Sep – 1 Oct | Transactions/concurrency demos, integration testing, documentation, mid-sem release | All |

Scrum practices used: a product backlog and task board, short online stand-ups, a sprint review and retrospective at the end of each sprint, and small commits to `main` after a teammate had looked at the change. Details, Gantt chart, risk register and meeting minutes are in **[docs/ProjectPlan.md](docs/ProjectPlan.md)**.

---

## 📋 Requirements

Full Software Requirements Specification: **[docs/SRS.md](docs/SRS.md)** (IEEE 830-style).

**Key functional requirements**

| ID | Requirement |
|---|---|
| FR-1 | Users log in; the system maps each user to a database role (admin, manager, analyst, seller, support) |
| FR-2 | Create, search, update and delete orders, products, customers, sellers, reviews and categories |
| FR-3 | Place an order atomically (order + items + payment) through a stored procedure |
| FR-4 | Order status can only move forward (created → … → delivered); every change is audited |
| FR-5 | Run 16 predefined reports, view their EXPLAIN plan and export them as CSV |
| FR-6 | Show every SQL statement executed for each user action |
| FR-7 | Show the ER model and live database schema from the UI |
| FR-8 | Predict late-delivery risk and delivery time for an order |
| FR-9 | Sellers see only their own orders (row-level security) |

**Key non-functional requirements:** security (bcrypt passwords, least privilege, SQL-injection-safe parameter binding), performance (search < 1 s on 100k orders using indexes), reliability (ACID transactions), usability (no install beyond PostgreSQL + Python), maintainability (one SQL file per concern).

---

## 🏗️ System design

Full design document: **[docs/Design.md](docs/Design.md)** (architecture, ER model, keys, FDs, normalization, SQL catalogue, ML design).

```mermaid
flowchart LR
    U([Browser<br/>HTML + JS]) -- "fetch /api/..." --> F[Flask API<br/>backend/app.py]
    F -- "BEGIN<br/>SET LOCAL ROLE olist_*<br/>parameterized SQL<br/>COMMIT / ROLLBACK" --> P[(PostgreSQL 16<br/>olist)]
    P -- rows + errors --> F
    F -- "rows + SQL log" --> U
    subgraph DB[Inside PostgreSQL]
      direction TB
      T[Tables · Views · Triggers<br/>Procedures · RLS policies]
      MV[v_order_features /<br/>mv_order_features]
      MP[ml_model · ml_prediction]
    end
    P --- DB
    ML[ml/train.py<br/>scikit-learn] -- "SELECT features" --> MV
    ML -- "INSERT metrics / COPY scores" --> MP
    F -- "live scoring of new orders" --> MP
```

**ER model:** 16 tables in BCNF, including `orders`, `order_item`, `payment`, `review`, `product`, `category`, `seller`, `customer`, `customer_account`, `zip_code`, `state`, `order_status_log`, `app_user`, `ml_model` and `ml_prediction`. See [docs/Design.md → ER model](docs/Design.md#3-er-model) or the static image [`docs/er_diagram.png`](docs/er_diagram.png).

---

## ✨ Features
### 🗄️ Database (the core)
- **16 tables in BCNF**, with 27 states, 19,177 zip codes, 96k customers, 3k sellers, 33k products, 112k order lines, 104k payments and 99k reviews.
- **Real data cleaning:** 1,000,163 geolocation rows → one row per zip prefix, outliers removed, missing zips and category translations added, and anomalies kept visible in `v_data_quality`.
- **Constraints everywhere:** PK, FK (`RESTRICT` / `CASCADE` / `SET NULL` chosen per relationship), `UNIQUE` candidate keys and `CHECK` rules.
- **8 views**, including an updatable view `WITH CHECK OPTION`, plus **2 materialized views** that feed the ML model.
- **Indexes:** B-tree, composite, partial, expression and **GIN full-text** (Portuguese) indexes, with `EXPLAIN ANALYZE` before/after demos.
- **6 triggers:** forward-only order status, an audit log, a delete guard, review-after-delivery, stock control and ML prediction invalidation.
- **Stored procedures:** `sp_place_order` (atomic order + items + payment), `sp_update_status`, `sp_cancel_order`, plus scalar functions.
- **Security:** 5 group roles, a least-privilege login role, `SET LOCAL ROLE` per request, **row-level security** for sellers, **column privileges** for analysts and **bcrypt** password hashing inside PostgreSQL (`pgcrypto`).

### 🌐 Web application
- **CRUD** for orders, products, customers, sellers, reviews and categories.
- **Faceted search:** every dropdown shows how many rows each option returns with your other filters. Options are sorted by count, and empty ones are greyed out.
- **Reports Q1–Q16**, each demonstrating one SQL concept, with **EXPLAIN ANALYZE** and **CSV export**.
- A **read-only SQL console** (`SET TRANSACTION READ ONLY`, 15 s timeout).
- A **Transactions lab** with live demos of atomicity, consistency, isolation levels and a lost update with and without `SELECT … FOR UPDATE`.
- An **ER model & schema** page: the Mermaid ER diagram plus tables, keys, constraints, triggers, routines, indexes, RLS policies and grants, all read live from the catalog.

### 🤖 Machine learning
- **Late-delivery risk** (classification) and **delivery-time estimate** (regression) at checkout.
- Features are built **in SQL**; results are stored **in the database** and used live when an order is placed.
- A **"Predict risk only"** button places the order inside a transaction, scores it, then **ROLLBACKs**.

---

## 🚀 Getting started
### Prerequisites
- **PostgreSQL 16**, with `psql` on your `PATH` (Windows: add `C:\Program Files\PostgreSQL\16\bin`)
- **Python 3.10+**
- The 9 Olist CSV files

### 1. Get the code and the data
```bash
git clone https://github.com/TarushB/SEPM-Ecommerce-Order-Management.git
```
Download the 9 CSV files from [Kaggle](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce) (they are not committed).
The scripts expect the CSVs in the folder **above** the project:
```
Dataset/
├── olist_orders_dataset.csv   … (all 9 CSVs)
└── SEPM-Ecommerce-Order-Management/   ← this repository
```

### 2. Install Python packages
```bash
pip install -r requirements.txt
```
> `lightgbm` is optional. If it fails to install, delete that line and training compares the other models.

### 3. Build, train, run (Windows)
```bat
setup_db.bat       :: creates DB "olist", loads ~560k rows, views, triggers, procedures, security (~1 min)
train_model.bat    :: trains + evaluates the model, stores results in the DB (~1.5 min)
run_app.bat        :: starts the app and opens http://localhost:5000
```

<details>
<summary><b>macOS / Linux (manual commands)</b></summary>

```bash
createdb -U postgres olist
psql -U postgres -d olist -v ON_ERROR_STOP=1 \
     -v datadir="$(cd .. && pwd)" -v dbdir="$(pwd)/db" -f "$(pwd)/db/00_run_all.sql"
PGUSER=postgres PGDATABASE=olist python ml/train.py
python backend/app.py        # → http://localhost:5000
```
Use **absolute** paths for `-f`, `datadir` and `dbdir`.
</details>

### 4. Explore the SQL demo scripts
```bash
psql -U postgres -d olist -f db/09_queries.sql            # Q1–Q16
psql -U postgres -d olist -f db/10_transactions_demo.sql  # ACID
psql -U postgres -d olist -f db/13_index_demo.sql         # EXPLAIN ANALYZE with / without indexes
psql -U postgres -d olist -f db/14_normalization_demo.sql # anomalies + FD checks
```
`db/11_concurrency_demo.sql` is a step-by-step script for **two psql windows**.

---

## 👤 Demo users & roles
Password = username + `123` (e.g. `admin` / `admin123`).

| User | PostgreSQL role | What the database allows |
|---|---|---|
| `admin` | `olist_admin` | everything, including user management |
| `manager` | `olist_manager` | CRUD on business tables, stored procedures, all views |
| `analyst` | `olist_analyst` | read-only; `zip_code.lat/lng` hidden by **column privileges** |
| `seller` | `olist_seller` | only orders containing its own items (**row-level security**); can update status |
| `support` | `olist_support` | reads orders and a privacy view of customers; can mark reviews answered |

The app logs in as **`olist_app`** (`NOINHERIT`, no data privileges of its own) and runs `SET LOCAL ROLE` for every request, so **PostgreSQL enforces the permissions, not the app**.
⚠️ Demo passwords (`olist_app_pw`, `*123`) are for coursework only.

---

## 🧪 Testing

Full test plan and results: **[docs/TestPlan.md](docs/TestPlan.md)**.

| Level | What was tested | How |
|---|---|---|
| Unit (database) | constraints, triggers, procedures, RLS policies | SQL test scripts in `db/10`–`14`, expected errors checked |
| Unit (ML) | feature pipeline, model metrics | time-series cross-validation + held-out test months |
| Integration | Front end → API → SQL → DB → result | manual test cases per page, SQL panel checked |
| System / acceptance | end-to-end flows for each role | test cases TC-01 … TC-30 in the test plan |
| Security | privilege escalation, SQL injection, RLS bypass | negative test cases with the `seller` / `analyst` roles |

Evidence (screenshots of every page) is in [`docs/screenshots/`](docs/screenshots/).

---

## 📊 Project management

| Artifact | Where |
|---|---|
| Project plan, WBS, Gantt chart | [docs/ProjectPlan.md](docs/ProjectPlan.md#2-work-breakdown-structure) |
| Effort estimation (COCOMO) | [docs/ProjectPlan.md](docs/ProjectPlan.md#4-effort-estimation) |
| Risk register | [docs/ProjectPlan.md](docs/ProjectPlan.md#5-risk-management) |
| Meeting minutes | [docs/ProjectPlan.md](docs/ProjectPlan.md#6-meeting-minutes) |
| Version control | this Git repository: feature commits from all three members, 18 Sep → 1 Oct 2026 |
| Configuration management | `.gitignore` (no data, no secrets, no build outputs), `requirements.txt`, scripted DB build |

---

## 🗂️ Repository structure
```
SEPM-Ecommerce-Order-Management/
├── setup_db.bat · train_model.bat · run_app.bat · requirements.txt
├── db/                              ← pure SQL, run by psql
│   ├── 00_run_all.sql               runs 01–08 in order
│   ├── 01_schema.sql                DDL: tables + PK / FK / UNIQUE / CHECK
│   ├── 02_staging_load.sql          \copy the 9 CSVs into schema "staging"
│   ├── 03_transform.sql             clean + INSERT … SELECT into normalized tables
│   ├── 04_indexes.sql               B-tree, composite, partial, expression, GIN
│   ├── 05_views.sql                 views, WITH CHECK OPTION, materialized feature views
│   ├── 06_triggers.sql              business-rule and audit triggers
│   ├── 07_procedures.sql            procedures + functions (incl. fn_login)
│   ├── 08_security.sql              roles, grants, column privileges, RLS, demo users
│   ├── 09_queries.sql               Q1–Q16 (generated from backend/queries.py)
│   ├── 10_transactions_demo.sql     ACID
│   ├── 11_concurrency_demo.sql      lost update, isolation levels, serializable, deadlock
│   ├── 12_ddl_dml_demo.sql          ALTER / RENAME / TRUNCATE / DROP + DML (rolled back)
│   ├── 13_index_demo.sql            EXPLAIN ANALYZE with vs. without indexes
│   └── 14_normalization_demo.sql    update / insert / delete anomalies, FD checks
├── backend/
│   ├── app.py                       Flask API (every response includes the SQL log)
│   ├── db.py                        per-request transaction + SET LOCAL ROLE + SQL log
│   ├── queries.py                   the 16 report queries
│   ├── ml_service.py                loads the model, scores orders
│   └── export_queries.py            regenerates db/09_queries.sql
├── ml/
│   ├── common.py                    feature lists, DB I/O
│   ├── train.py                     time-series CV, test evaluation, writes results to DB
│   └── models/                      trained model (created by train_model.bat, git-ignored)
├── frontend/                        index.html · app.js · style.css · er.js · vendor/mermaid
└── docs/                            SRS · Design · TestPlan · ProjectPlan · er_diagram.png · screenshots/
```

---

## 📸 Screenshots

| | |
|---|---|
| **Faceted order search + SQL panel**<br><img src="docs/screenshots/orders_search.png" width="440"> | **Order detail with ML risk + audit trail**<br><img src="docs/screenshots/order_detail.png" width="440"> |
| **Reports (Q1–Q16) with EXPLAIN**<br><img src="docs/screenshots/reports.png" width="440"> | **Transactions & concurrency lab**<br><img src="docs/screenshots/transactions_lab.png" width="440"> |
| **ML insights**<br><img src="docs/screenshots/ml_insights.png" width="440"> | **What-if prediction (ROLLBACK)**<br><img src="docs/screenshots/prediction.png" width="440"> |
| **Row-level security: seller view**<br><img src="docs/screenshots/seller_rls.png" width="440"> | **ER model inside the app**<br><img src="docs/screenshots/er_in_app.png" width="440"> |

---

## 🤝 Individual contributions

| Member | Responsibilities | Main files |
|---|---|---|
| **Tarush Banke** | Project planning & coordination; requirements (SRS); ER/EER model; relational schema; keys & functional dependencies; normalization to BCNF; CSV staging load & data cleaning; indexes; views & materialized views; DDL/DML, index and normalization demos; README & design doc | `db/00`–`05`, `db/12`–`14`, `setup_db.bat`, `docs/SRS.md`, `docs/Design.md`, `docs/ProjectPlan.md`, `docs/er_diagram.png` |
| **Tanishk Varshney** | Triggers (status guard, audit, stock, review rule, delete guard); stored procedures & functions; roles, GRANT/REVOKE, column privileges, row-level security; 16 report queries; transactions/ACID & concurrency demos; Flask API and DB access layer | `db/06`–`11`, `backend/app.py`, `backend/db.py`, `backend/queries.py`, `backend/export_queries.py`, `run_app.bat`, `requirements.txt` |
| **Tanishq Mahajan** | Front end (CRUD pages, faceted search, reports, SQL console, transactions lab, ER/schema page); ML problem framing, feature engineering, model selection, training & evaluation; ML service integration; test plan, test execution & screenshots | `frontend/`, `ml/`, `backend/ml_service.py`, `train_model.bat`, `docs/TestPlan.md`, `docs/screenshots/` |

All members took part in sprint planning, code reviews and testing, and each can explain the complete flow **Front end → SQL → Database → Result**. The commit history of this repository shows each member's work.

---

## 🛠️ Troubleshooting

| Problem | Fix |
|---|---|
| `psql is not recognized` | Add `C:\Program Files\PostgreSQL\16\bin` to PATH and open a **new** terminal |
| `Could not find the Olist CSV files` | Put the project folder inside the folder that holds the CSVs, or edit `DATADIR` in `setup_db.bat` |
| Login says `Cannot connect to PostgreSQL` | PostgreSQL is not installed or its service is stopped: start `postgresql-x64-16` in `services.msc` |
| `password authentication failed for user "olist_app"` | Re-run `setup_db.bat` (it recreates roles and privileges) |
| ML page says "No trained model yet" | Run `train_model.bat`, then reload the page |
| Page looks outdated after an update | Restart `run_app.bat` and press **Ctrl + F5** in the browser |

---

## 🙏 Acknowledgements

- Data: [Olist Brazilian E-Commerce Public Dataset](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce) (CC BY-NC-SA 4.0)
- ER diagrams rendered with [Mermaid](https://mermaid.js.org/)
- Built as a DBMS course project: *E-Commerce and Order Management* (Software Engineering & Project Management)
