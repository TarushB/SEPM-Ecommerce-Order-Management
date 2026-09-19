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
