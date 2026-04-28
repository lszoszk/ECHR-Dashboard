"""P12 probe: structure of Separate Opinion sequences and numbering blocks."""
import sqlite3
import re
from collections import Counter

DB = "/data/echr_search.db"
conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# 1. How many cases have multiple separate opinions?
print("=== Cases with Separate Opinion paragraphs ===")
cur.execute("""
    SELECT COUNT(DISTINCT case_id), COUNT(*)
    FROM paragraphs WHERE section = 'Separate Opinion'
""")
n_cases, n_paras = cur.fetchone()
print(f"  {n_cases:,} cases, {n_paras:,} paragraphs total")

# Opinion-title pattern (must be at paragraph start)
TITLE_RE = re.compile(
    r"^\s*(?:JOINT\s+)?(?:PARTLY\s+|PARTIALLY\s+)?(?:DISSENTING|CONCURRING|SEPARATE)\s+OPINION\s+OF\s+",
    re.IGNORECASE,
)

# 2. Count opinion-title paragraphs
print("\n=== Opinion-title paragraphs ===")
cur.execute("SELECT case_id, para_idx, substr(text, 1, 200) AS t FROM paragraphs WHERE section = 'Separate Opinion'")
title_count = 0
case_titles = Counter()
sample_titles = []
for r in cur.fetchall():
    if TITLE_RE.match(r["t"] or ""):
        title_count += 1
        case_titles[r["case_id"]] += 1
        if len(sample_titles) < 8:
            sample_titles.append(r["t"][:100])
print(f"  Total opinion-title paragraphs: {title_count:,}")
print(f"  Distinct cases with at least one title: {len(case_titles):,}")
print(f"\n  Distribution of title-count per case:")
title_dist = Counter(case_titles.values())
for n in sorted(title_dist.keys())[:10]:
    print(f"    {n} title(s): {title_dist[n]:,} cases")
print(f"\n  Sample titles:")
for t in sample_titles:
    print(f"    {t}")

# 3. Show one case in detail with multiple separate opinions
print("\n=== Sample case with 4+ separate opinions ===")
cases_with_many = [cid for cid, n in case_titles.items() if n >= 4]
if cases_with_many:
    cid = cases_with_many[0]
    cur.execute("SELECT title FROM cases WHERE case_id=?", (cid,))
    title = (cur.fetchone()[0] or "")[:60]
    print(f"  [{cid}] {title}")
    cur.execute("""
        SELECT para_idx, hudoc_para_no, substr(text, 1, 90) AS t
        FROM paragraphs
        WHERE case_id = ? AND section = 'Separate Opinion'
        ORDER BY para_idx LIMIT 30
    """, (cid,))
    for p in cur.fetchall():
        is_title = "TITLE" if TITLE_RE.match(p["t"] or "") else ""
        h = p["hudoc_para_no"] if p["hudoc_para_no"] is not None else "—"
        print(f"    ¶{p['para_idx']:>4} hudoc={str(h):<5} {is_title:<6} {p['t']}")

# 4. Operative Part numbering pattern
print("\n=== Operative Part dispositif structure (sample case) ===")
cur.execute("""
    SELECT case_id, MAX(para_idx) AS mx FROM paragraphs
    WHERE section = 'Operative Part' AND hudoc_para_no IS NOT NULL
    GROUP BY case_id ORDER BY mx DESC LIMIT 1
""")
r = cur.fetchone()
if r:
    cid = r["case_id"]
    cur.execute("""
        SELECT para_idx, hudoc_para_no, substr(text, 1, 80) AS t
        FROM paragraphs
        WHERE case_id = ? AND section IN ('Operative Part', 'Operative part')
        ORDER BY para_idx LIMIT 15
    """, (cid,))
    print(f"  [{cid}]")
    for p in cur.fetchall():
        h = p["hudoc_para_no"] if p["hudoc_para_no"] is not None else "—"
        print(f"    ¶{p['para_idx']:>4} hudoc={str(h):<5} {p['t']}")

conn.close()
