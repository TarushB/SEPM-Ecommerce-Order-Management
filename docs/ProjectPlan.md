# Project Management Plan & Records

**Project:** E-Commerce & Order Management System (Olist)
**Course:** Software Engineering & Project Management (SEPM)
**Team:** Tarush Banke (project lead) · Tanishk Varshney · Tanishq Mahajan
**Period covered:** 18 Sep 2026 → 1 Oct 2026 (mid-semester release)

---

## 1. Process model and team organisation

**Model:** Agile Scrum with 4 short sprints. We picked Scrum over Waterfall because the high-level requirements (course rubric) were fixed, but the details depended on what we found in the data. For example, the ML task changed from *product recommendation* to *late-delivery prediction* once profiling showed that only 3.1% of customers order twice.

| Scrum role | Member |
|---|---|
| Product owner (represents course requirements) | Tarush Banke |
| Scrum master (runs stand-ups, tracks the board) | Tarush Banke |
| Development team | Tarush Banke, Tanishk Varshney, Tanishq Mahajan |

**Team structure:** each member owns one layer (database, back end, front end + ML), and all three review and test each other's work.

**Communication:** online stand-up on most days (about 15 min), a group chat for quick questions, and a sprint review + retrospective call at the end of each sprint.

**Tools:** Git + GitHub (version control), a shared task board (backlog → in progress → review → done), VS Code, PostgreSQL 16 / psql, Python, Mermaid (diagrams).

---

## 2. Work breakdown structure

```
1 E-Commerce & Order Management System
├── 1.1 Project management
│   ├── 1.1.1 Planning, sprint planning, task board           (Tarush)
│   ├── 1.1.2 Risk register, meeting minutes                  (Tarush)
│   └── 1.1.3 Mid-semester report and demo video              (All)
├── 1.2 Requirements
│   ├── 1.2.1 Dataset profiling                               (Tarush, Tanishq)
│   └── 1.2.2 SRS: functional / non-functional requirements   (Tarush)
├── 1.3 Database design & implementation
│   ├── 1.3.1 ER/EER model, relational schema                 (Tarush)
│   ├── 1.3.2 Keys, FDs, normalization to BCNF                (Tarush)
│   ├── 1.3.3 Staging load, cleaning, transform               (Tarush)
│   ├── 1.3.4 Indexes and views                               (Tarush)
│   ├── 1.3.5 Triggers and stored procedures                  (Tanishk)
│   ├── 1.3.6 Security: roles, grants, RLS                    (Tanishk)
│   └── 1.3.7 Transactions and concurrency demos              (Tanishk)
├── 1.4 Application
│   ├── 1.4.1 DB access layer + Flask API                     (Tanishk)
│   ├── 1.4.2 Report queries Q1–Q16                           (Tanishk)
│   ├── 1.4.3 Front end: CRUD, search, reports, lab           (Tanishq)
│   └── 1.4.4 ER model & schema page                          (Tanishq)
├── 1.5 AI/ML
│   ├── 1.5.1 Problem framing, feature view in SQL            (Tanishq, Tarush)
│   ├── 1.5.2 Training, model selection, evaluation           (Tanishq)
│   └── 1.5.3 Integration with DB and UI                      (Tanishq, Tanishk)
└── 1.6 Testing & documentation
    ├── 1.6.1 Test plan and test execution                    (Tanishq)
    ├── 1.6.2 Design document, README                         (Tarush)
    └── 1.6.3 Screenshots / evidence                          (Tanishq)
```

---
