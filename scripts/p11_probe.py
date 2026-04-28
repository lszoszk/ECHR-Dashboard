"""P11 probe: scale of missing sub-section types in Facts Background/Proceedings."""
import sqlite3
import re
from collections import Counter, defaultdict

DB = "/data/echr_search.db"
conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# Patterns for canonical heading detection — must be at paragraph start
# and the paragraph must be short (heading-only, not glued with body)
PATTERNS = [
    # Already-handled by P3 (Pop B) — re-check residual in Pop A
    ("RELEVANT DOMESTIC LAW", r"^\s*(?:[IVX]+\.\s+)?RELEVANT DOMESTIC LAW\b"),
    ("DOMESTIC LAW AND PRACTICE", r"^\s*(?:[IVX]+\.\s+)?(?:RELEVANT )?DOMESTIC LAW AND PRACTICE\b"),
    # New candidates
    ("PROCEEDINGS BEFORE THE COMMISSION", r"^\s*(?:[IVX]+\.\s+)?PROCEEDINGS BEFORE THE COMMISSION\b"),
    ("FINAL SUBMISSIONS TO THE COURT", r"^\s*(?:[IVX]+\.\s+)?FINAL SUBMISSIONS (?:TO|MADE TO|BEFORE) THE COURT\b"),
    ("CASE-LAW OF THE COURT OF JUSTICE", r"^\s*(?:[IVX]+\.\s+)?(?:THE )?CASE-LAW OF THE COURT OF JUSTICE\b"),
    ("INTERNATIONAL LAW", r"^\s*(?:[IVX]+\.\s+)?(?:RELEVANT )?INTERNATIONAL LAW\b"),
    ("RELEVANT INTERNATIONAL", r"^\s*(?:[IVX]+\.\s+)?RELEVANT INTERNATIONAL"),
    ("RELEVANT EUROPEAN", r"^\s*(?:[IVX]+\.\s+)?RELEVANT EUROPEAN"),
    ("EUROPEAN UNION LAW", r"^\s*(?:[IVX]+\.\s+)?(?:RELEVANT )?EUROPEAN UNION LAW\b"),
    ("COMPARATIVE LAW", r"^\s*(?:[IVX]+\.\s+)?(?:RELEVANT )?COMPARATIVE LAW\b"),
]

print("=== Heading-paragraph occurrences (length<120) by current section ===\n")
for label, pat in PATTERNS:
    rx = re.compile(pat, re.IGNORECASE)
    by_section = Counter()
    cur.execute("""
        SELECT section, text FROM paragraphs
        WHERE length(text) < 120
    """)
    for r in cur.fetchall():
        if rx.match(r["text"] or ""):
            by_section[r["section"]] += 1
    total = sum(by_section.values())
    if total == 0:
        print(f"  '{label:<35}' {total:>5} matches  (none)")
        continue
    by_str = ", ".join(f"{sec}:{n}" for sec, n in by_section.most_common(5))
    print(f"  '{label:<35}' {total:>5} matches  {by_str}")

# Detailed look: PROCEEDINGS BEFORE THE COMMISSION
print("\n=== Sample: PROCEEDINGS BEFORE THE COMMISSION (5 cases) ===")
cur.execute("""
    SELECT case_id, para_idx, section, substr(text, 1, 100) AS t
    FROM paragraphs
    WHERE length(text) < 120 AND text LIKE 'PROCEEDINGS BEFORE THE COMMISSION%'
    LIMIT 5
""")
for r in cur.fetchall():
    print(f"  {r['case_id']} idx={r['para_idx']} [{r['section']}]: {r['t']}")

print("\n=== Sample: FINAL SUBMISSIONS TO THE COURT (5 cases) ===")
cur.execute("""
    SELECT case_id, para_idx, section, substr(text, 1, 100) AS t
    FROM paragraphs
    WHERE length(text) < 120 AND (
        text LIKE 'FINAL SUBMISSIONS TO THE COURT%' OR
        text LIKE 'FINAL SUBMISSIONS MADE TO THE COURT%' OR
        text LIKE '%. FINAL SUBMISSIONS%'
    )
    LIMIT 5
""")
for r in cur.fetchall():
    print(f"  {r['case_id']} idx={r['para_idx']} [{r['section']}]: {r['t']}")

print("\n=== Sample: RELEVANT DOMESTIC LAW (residual after P3) — 5 in Facts/Facts Proceedings ===")
cur.execute("""
    SELECT case_id, para_idx, section, substr(text, 1, 100) AS t
    FROM paragraphs
    WHERE length(text) < 120
      AND section IN ('Facts Proceedings', 'Facts Background', 'Facts')
      AND (text LIKE 'RELEVANT DOMESTIC LAW%' OR text LIKE 'I.%RELEVANT DOMESTIC%' OR text LIKE 'II.%RELEVANT DOMESTIC%' OR text LIKE 'III.%RELEVANT DOMESTIC%')
    LIMIT 5
""")
for r in cur.fetchall():
    print(f"  {r['case_id']} idx={r['para_idx']} [{r['section']}]: {r['t']}")

# Year distribution for proceedings before commission
print("\n=== Year distribution: PROCEEDINGS BEFORE THE COMMISSION ===")
cur.execute("""
    SELECT substr(c.judgment_date, 7, 4) AS yr, COUNT(*) AS n
    FROM paragraphs p JOIN cases c ON c.case_id = p.case_id
    WHERE length(p.text) < 120 AND p.text LIKE 'PROCEEDINGS BEFORE THE COMMISSION%'
    GROUP BY yr ORDER BY yr
""")
for r in cur.fetchall():
    print(f"  {r['yr']}: {r['n']}")

conn.close()
