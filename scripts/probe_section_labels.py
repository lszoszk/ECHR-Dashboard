"""Probe what's actually in the orphan section labels (read-only)."""
import sqlite3
conn = sqlite3.connect("file:/data/echr_search.db?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

print("=== sample Facts paragraphs (random 8) ===")
cur.execute(
    "SELECT case_id, para_idx, substr(text,1,180) AS t FROM paragraphs "
    "WHERE section = ? ORDER BY RANDOM() LIMIT 8", ("Facts",))
for r in cur:
    cid = (r["case_id"] or "")[:32]
    pi = r["para_idx"] if r["para_idx"] is not None else -1
    t = (r["t"] or "").replace("\n", " ")
    print(f"  [{cid:<32}] idx={pi:<5} {t}")

print()
print("=== Facts: cases vs paragraphs ===")
cur.execute("SELECT COUNT(DISTINCT case_id), COUNT(*) FROM paragraphs WHERE section = ?", ("Facts",))
nc, np_ = cur.fetchone()
print(f"  cases: {nc:,}  paragraphs: {np_:,}  avg/case: {np_/max(nc,1):.1f}")

print()
print("=== overlap with other Facts* labels ===")
for other in ["Facts Background", "Facts Proceedings"]:
    cur.execute(
        "SELECT COUNT(DISTINCT a.case_id) FROM paragraphs a "
        "WHERE a.section = ? AND EXISTS "
        "(SELECT 1 FROM paragraphs b WHERE b.case_id = a.case_id AND b.section = ?)",
        ("Facts", other))
    print(f"  cases with both Facts AND {other}: {cur.fetchone()[0]:,}")

print()
print("=== Facts paragraphs per year (recent 15) ===")
cur.execute(
    "SELECT substr(c.judgment_date, 7, 4) AS y, COUNT(*) AS n "
    "FROM paragraphs p JOIN cases c ON c.case_id = p.case_id "
    "WHERE p.section = ? GROUP BY y ORDER BY y", ("Facts",))
rows = cur.fetchall()
for r in rows[-15:]:
    print(f"  {r[0]}  {r[1]:>7,}")

print()
print("=== Operative Part (upper) vs Operative part (lower) by year ===")
cur.execute(
    "SELECT substr(c.judgment_date, 7, 4) AS y, "
    "SUM(CASE WHEN p.section = 'Operative Part' THEN 1 ELSE 0 END) AS U, "
    "SUM(CASE WHEN p.section = 'Operative part' THEN 1 ELSE 0 END) AS L "
    "FROM paragraphs p JOIN cases c ON c.case_id = p.case_id "
    "WHERE p.section IN ('Operative Part', 'Operative part') "
    "GROUP BY y ORDER BY y")
rows = cur.fetchall()
for r in rows[-12:]:
    print(f"  {r[0]}  Upper={r[1]:>5,}  lower={r[2]:>5,}")

print()
print("=== Relevant legal framework: do cases also have Legal Framework? ===")
cur.execute(
    "SELECT COUNT(DISTINCT a.case_id) FROM paragraphs a "
    "WHERE a.section = 'Relevant legal framework' AND EXISTS "
    "(SELECT 1 FROM paragraphs b WHERE b.case_id = a.case_id AND b.section = 'Legal Framework')")
print(f"  cases with both: {cur.fetchone()[0]:,}")
cur.execute("SELECT COUNT(DISTINCT case_id) FROM paragraphs WHERE section = 'Relevant legal framework'")
print(f"  cases with Relevant legal framework: {cur.fetchone()[0]:,}")
cur.execute("SELECT COUNT(DISTINCT case_id) FROM paragraphs WHERE section = 'Legal Framework'")
print(f"  cases with Legal Framework: {cur.fetchone()[0]:,}")
