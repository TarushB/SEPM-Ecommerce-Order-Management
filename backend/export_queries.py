"""Writes db/09_queries.sql from backend/queries.py (keeps both in sync).
Run:  python backend/export_queries.py"""
import os, re
from queries import QUERIES

def literal(v):
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"

out = ["-- =====================================================================",
       "-- 09_queries.sql  --  demonstration queries (generated from backend/queries.py)",
       "-- Parameters are filled with their default values.",
       "-- =====================================================================", ""]
for q in QUERIES:
    sql = re.sub(r"%\((\w+)\)s", lambda m: literal(q["params"][m.group(1)]), q["sql"].strip())
    out += [f"-- {q['id']}  [{q['concept']}]  {q['title']}", f"\\echo {q['id']}: {q['title']}", sql + ";", ""]
path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "db", "09_queries.sql")
with open(path, "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print("wrote", os.path.normpath(path), "with", len(QUERIES), "queries")
