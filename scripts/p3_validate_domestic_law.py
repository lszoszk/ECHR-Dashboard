"""
P3 VALIDATION (read-only): Extract domestic law sub-sections from Facts Proceedings.

In Population B, 'Facts Proceedings' contains both:
  I.  THE CIRCUMSTANCES OF THE CASE  (facts)
  II. RELEVANT DOMESTIC LAW ...      (domestic law -> should be Legal Framework)

This script measures scope and shows examples before any changes.
"""
import sqlite3
import re

DB = "/data/echr_search.db"
conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# Heading patterns that signal a domestic law sub-section
DOMESTIC_LAW_RE = re.compile(
    r"(RELEVANT DOMESTIC LAW|DOMESTIC LAW AND PRACTICE|DOMESTIC LAW AND REGULATION"
    r"|RELEVANT NATIONAL LAW|RELEVANT DOMESTIC AND INTERNATIONAL"
    r"|DOMESTIC AND INTERNATIONAL LAW|RELEVANT LEGAL FRAMEWORK"
    r"|RELEVANT DOMESTIC LEGISLATION)",
    re.IGNORECASE,
)

# Headings that end a domestic law block (back to facts or into merits)
STOP_RE = re.compile(
    r"(THE LAW|ALLEGED VIOLATION|AS TO THE LAW|FOR THESE REASONS"
    r"|ADMISSIBILITY|JUST SATISFACTION|APPLICATION OF ARTICLE)",
    re.IGNORECASE,
)

def is_domestic_law_heading(text):
    t = (text or "").strip()
    return len(t) < 120 and bool(DOMESTIC_LAW_RE.search(t))

def is_stop(text):
    t = (text or "").strip()
    return len(t) < 100 and bool(STOP_RE.search(t))

print("=" * 80)
print("P3 VALIDATION: Domestic law extraction from Facts Proceedings")
print("=" * 80)

# Pass A: count heading paragraphs
print("\n── PASS A: heading paragraphs in Facts Proceedings ──\n")
cur.execute("""
    SELECT substr(c.judgment_date,7,4) as yr, COUNT(*) as cnt
    FROM paragraphs p JOIN cases c ON c.case_id=p.case_id
    WHERE p.section = 'Facts Proceedings'
      AND p.para_idx IS NOT NULL
      AND length(p.text) < 120
      AND (
          UPPER(p.text) LIKE '%RELEVANT DOMESTIC LAW%'
       OR UPPER(p.text) LIKE '%DOMESTIC LAW AND PRACTICE%'
       OR UPPER(p.text) LIKE '%DOMESTIC LAW AND REGULATION%'
       OR UPPER(p.text) LIKE '%RELEVANT NATIONAL LAW%'
       OR UPPER(p.text) LIKE '%DOMESTIC AND INTERNATIONAL LAW%'
       OR UPPER(p.text) LIKE '%RELEVANT DOMESTIC LEGISLATION%'
      )
    GROUP BY yr ORDER BY yr
""")
rows = cur.fetchall()
total_heading = sum(r["cnt"] for r in rows)
print(f"  {'Year':<6} {'Headings':>8}")
for r in rows:
    print(f"  {r['yr']:<6} {r['cnt']:>8,}")
print(f"\n  TOTAL heading paragraphs: {total_heading:,}")

# Pass B: content blocks
print("\n── PASS B: content blocks (para_idx ordered) ──\n")

cur.execute("""
    SELECT DISTINCT case_id FROM paragraphs
    WHERE section = 'Facts Proceedings'
      AND para_idx IS NOT NULL
      AND length(text) < 120
      AND (
          UPPER(text) LIKE '%RELEVANT DOMESTIC LAW%'
       OR UPPER(text) LIKE '%DOMESTIC LAW AND PRACTICE%'
       OR UPPER(text) LIKE '%RELEVANT NATIONAL LAW%'
      )
""")
case_ids = [r[0] for r in cur.fetchall()]
print(f"  Cases with domestic law headings in Facts Proceedings: {len(case_ids):,}")

cur2 = conn.cursor()
content_count = 0
affected_cases = 0
para_counts = []

for case_id in case_ids:
    cur2.execute("""
        SELECT rowid, para_idx, section, text
        FROM paragraphs
        WHERE case_id = ? AND para_idx IS NOT NULL
        ORDER BY para_idx
    """, (case_id,))
    paras = cur2.fetchall()

    in_domestic = False
    case_content = 0

    for p in paras:
        txt = (p["text"] or "").strip()
        sec = p["section"]

        if not in_domestic:
            if sec == "Facts Proceedings" and is_domestic_law_heading(txt):
                in_domestic = True
                # heading itself
                case_content += 1
        else:
            if sec != "Facts Proceedings":
                in_domestic = False
            elif is_stop(txt):
                in_domestic = False
            elif is_domestic_law_heading(txt):
                # another domestic law sub-heading, continue block
                case_content += 1
            else:
                case_content += 1

    if case_content > 0:
        affected_cases += 1
        content_count += case_content
        para_counts.append(case_content)

para_counts.sort()
median = para_counts[len(para_counts)//2] if para_counts else 0
p90 = para_counts[int(len(para_counts)*0.9)] if para_counts else 0
print(f"  Affected cases:             {affected_cases:,}")
print(f"  Total paragraphs to move:   {content_count:,}")
print(f"  Avg per case:               {content_count/max(affected_cases,1):.1f}")
print(f"  Median per case:            {median}")
print(f"  P90 per case:               {p90}")

# Current counts
cur.execute("SELECT COUNT(*) FROM paragraphs WHERE section='Legal Framework'")
lf = cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM paragraphs WHERE section='Relevant legal framework'")
rlf = cur.fetchone()[0]
print(f"\n  Current 'Legal Framework' paragraphs:           {lf:,}")
print(f"  Current 'Relevant legal framework' paragraphs:  {rlf:,}")
print(f"  After relabel (estimate):                       {lf + content_count:,}")

# Spot check: 3 cases
print("\n── SPOT CHECK: 3 examples ──")
cur.execute("""
    SELECT DISTINCT p.case_id, c.title
    FROM paragraphs p JOIN cases c ON c.case_id=p.case_id
    WHERE p.section='Facts Proceedings'
      AND p.para_idx IS NOT NULL
      AND length(p.text) < 120
      AND UPPER(p.text) LIKE '%RELEVANT DOMESTIC LAW%'
    ORDER BY RANDOM() LIMIT 3
""")
examples = cur.fetchall()
cur3 = conn.cursor()
for ex in examples:
    print(f"\n  [{ex['case_id']}] {(ex['title'] or '')[:65]}")
    cur3.execute("""
        SELECT rowid, para_idx, section, substr(text,1,100) as t
        FROM paragraphs WHERE case_id=? AND para_idx IS NOT NULL
        ORDER BY para_idx
    """, (ex["case_id"],))
    paras3 = cur3.fetchall()
    in_block = False
    shown = 0
    for p in paras3:
        txt = (p["t"] or "").strip()
        sec = p["section"]
        if not in_block and sec == "Facts Proceedings" and is_domestic_law_heading(txt):
            in_block = True
            print(f"    ¶{p['para_idx']:>4} [{sec}] HEADING ▶ {txt}")
            shown += 1
        elif in_block:
            if sec != "Facts Proceedings":
                print(f"    ¶{p['para_idx']:>4} [{sec}] ← boundary STOP")
                break
            if is_stop(txt):
                print(f"    ¶{p['para_idx']:>4} [{sec}] ← stop heading: {txt[:60]}")
                break
            if shown < 5:
                print(f"    ¶{p['para_idx']:>4} [{sec}]         {txt[:90]}")
            shown += 1
    if in_block:
        print(f"    → {shown} paragraphs would move to Legal Framework")

conn.close()
print("\nDONE.")
