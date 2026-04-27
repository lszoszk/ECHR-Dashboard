"""
Regenerate docs/data/echr_cases_sample50.jsonl from production DB.

Picks 50 stratified cases (by document_type and era) to give offline-mode
users a representative slice of the corpus with current (post-Phase 2)
section labels.

Run inside the echr-search-api container:
  docker exec echr-search-api python /tmp/generate_sample50.py
"""
import json
import sqlite3
from collections import defaultdict

DB = "/data/echr_search.db"
OUT = "/tmp/echr_cases_sample50.jsonl"

STRATA = [
    # (label, where_clause, count)
    ("classical", "substr(c.judgment_date,7,4) BETWEEN '1975' AND '1998' AND c.importance IN ('1','2')", 8),
    ("chamber_modern", "c.document_type = 'Judgment (Merits and Just Satisfaction)' AND substr(c.judgment_date,7,4) BETWEEN '2005' AND '2020' AND c.importance IN ('1','2','3')", 16),
    ("grand_chamber", "c.originating_body LIKE '%Grand Chamber%' AND substr(c.judgment_date,7,4) BETWEEN '2010' AND '2025'", 8),
    ("committee", "c.document_type = 'Judgment (Committee)' AND substr(c.judgment_date,7,4) BETWEEN '2015' AND '2025'", 10),
    ("press_release", "c.document_type LIKE '%Press Release%' AND substr(c.judgment_date,7,4) BETWEEN '2015' AND '2025'", 4),  # state-cap may trim this
    ("recent_2024", "substr(c.judgment_date,7,4) IN ('2024','2025') AND c.document_type NOT LIKE '%Press Release%' AND c.document_type != 'Judgment (Committee)'", 4),
]

TARGET_TOTAL = 50

conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

case_ids = []
seen_states = defaultdict(int)
seen_total = 0

for label, where, n in STRATA:
    # diversify by state: cap at 2 cases per respondent_state per stratum
    cur.execute(f"""
        SELECT c.case_id, c.respondent_state
        FROM cases c
        WHERE {where}
        ORDER BY RANDOM()
        LIMIT {n * 4}
    """)
    rows = cur.fetchall()
    picked = 0
    used_states = defaultdict(int)
    for r in rows:
        if picked >= n:
            break
        st = r["respondent_state"] or "?"
        if used_states[st] >= 2:
            continue
        case_ids.append(r["case_id"])
        used_states[st] += 1
        seen_states[st] += 1
        picked += 1
    print(f"  {label:<18} picked {picked}/{n}")
    seen_total += picked

print(f"\nTotal cases selected: {seen_total}")
print(f"States covered: {len(seen_states)}")

# top up to TARGET_TOTAL with extra modern chamber cases (no state cap on top-up)
shortfall = TARGET_TOTAL - seen_total
if shortfall > 0:
    cur.execute("""
        SELECT c.case_id FROM cases c
        WHERE c.document_type = 'Judgment (Merits and Just Satisfaction)'
          AND substr(c.judgment_date,7,4) BETWEEN '2010' AND '2024'
          AND c.case_id NOT IN ({})
        ORDER BY RANDOM() LIMIT ?
    """.format(",".join("?" * len(case_ids))), [*case_ids, shortfall])
    for r in cur.fetchall():
        case_ids.append(r["case_id"])
    print(f"  topped up with {shortfall} extra modern chamber cases")

# now serialize each case
records = []
for cid in case_ids:
    cur.execute("""
        SELECT case_id, case_no, title, hudoc_url, judgment_date, ecli,
               respondent_state, importance, conclusion, violation, non_violation,
               keywords, originating_body, document_type
        FROM cases WHERE case_id = ?
    """, (cid,))
    case_row = cur.fetchone()
    if not case_row:
        continue
    case = dict(case_row)

    # parse JSON-array fields back to lists
    for field in ("violation", "non_violation", "keywords", "originating_body"):
        v = case.get(field) or "[]"
        try:
            parsed = json.loads(v) if isinstance(v, str) else v
        except (json.JSONDecodeError, TypeError):
            parsed = [v] if v else []
        case[field] = parsed if isinstance(parsed, list) else [parsed] if parsed else []

    # rename for frontend convention
    case["non-violation"] = case.pop("non_violation")
    # originating_body in sample was a string; keep as string for back-compat
    case["originating_body"] = case["originating_body"][0] if case["originating_body"] else ""

    # legacy fields the frontend tolerates as empty
    case["article_no"] = ""
    case["chamber_composed_of"] = []
    case["represented_by"] = ""
    case["applicability"] = []
    case["separate_opinion"] = False
    case["rules_of_court"] = ""
    case["domestic_law"] = ""
    case["strasbourg_caselaw"] = []
    case["international_law"] = ""

    # paragraphs
    cur.execute("""
        SELECT section, text, para_idx FROM paragraphs
        WHERE case_id = ? ORDER BY COALESCE(para_idx, 0)
    """, (cid,))
    paras = []
    for p in cur.fetchall():
        paras.append({
            "section": p["section"],
            "text": p["text"],
            "para_idx": p["para_idx"] if p["para_idx"] is not None else len(paras),
        })
    # mark separate_opinion if any para tagged as such
    case["separate_opinion"] = any(p["section"] == "Separate Opinion" for p in paras)
    case["paragraphs"] = paras

    # articles from case_articles table
    cur.execute("SELECT article FROM case_articles WHERE case_id = ?", (cid,))
    articles = [r[0] for r in cur.fetchall()]
    case["article_no"] = ";".join(articles)

    records.append(case)

# write
with open(OUT, "w") as f:
    for r in records:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")

print(f"\nWrote {len(records)} cases to {OUT}")

# section distribution sanity check
from collections import Counter
sec_count = Counter()
for r in records:
    for p in r["paragraphs"]:
        sec_count[p["section"]] += 1
print("\nSection distribution in sample:")
for s, n in sec_count.most_common():
    print(f"  {n:>5} {s}")

conn.close()
