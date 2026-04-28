"""
B2 PILOT: extract Merits paragraphs for LLM sub-typing classification.

Sample 30 cases (10 from each population A/B/C) with their Merits
paragraphs (max 10 per case, random if more). Output JSON for the
LLM classifier.

Population definitions:
  A = classical (1960-1998), Header present, para_idx populated
  B = modern Chamber (1999+), Header present, para_idx populated
  C = Committee/joined (2009+), para_idx IS NULL

Stratification ensures the schema works across all three structural
populations, not just one.
"""
import sqlite3
import json
import random

DB = "/data/echr_search.db"
OUT = "/tmp/b2_pilot_samples.json"
PARAS_PER_CASE = 10
random.seed(2024)

conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

def pick_cases(where, n):
    """Pick n distinct cases matching the SQL where clause."""
    cur.execute(f"""
        SELECT DISTINCT c.case_id, c.title, c.judgment_date
        FROM cases c
        WHERE {where}
        AND EXISTS (SELECT 1 FROM paragraphs p
                    WHERE p.case_id = c.case_id AND p.section = 'Merits'
                    LIMIT 12)
        ORDER BY RANDOM()
        LIMIT ?
    """, (n,))
    return [dict(r) for r in cur.fetchall()]

# Population A: classical, 1980-1995, importance 1-2 (notable cases)
pop_a = pick_cases(
    "substr(c.judgment_date, 7, 4) BETWEEN '1980' AND '1995' "
    "AND c.importance IN ('1', '2') "
    "AND c.document_type NOT LIKE '%Press Release%'",
    10,
)
# Population B: modern Chamber, 2005-2018
pop_b = pick_cases(
    "c.document_type = 'Judgment (Merits and Just Satisfaction)' "
    "AND substr(c.judgment_date, 7, 4) BETWEEN '2005' AND '2018' "
    "AND c.importance IN ('1', '2', '3')",
    10,
)
# Population C: Committee, 2017-2024
pop_c = pick_cases(
    "c.document_type = 'Judgment (Committee)' "
    "AND substr(c.judgment_date, 7, 4) BETWEEN '2017' AND '2024'",
    10,
)

print(f"Population A (classical): {len(pop_a)}")
print(f"Population B (modern):    {len(pop_b)}")
print(f"Population C (committee): {len(pop_c)}")

samples = []
for pop_label, cases in [("A", pop_a), ("B", pop_b), ("C", pop_c)]:
    for case in cases:
        cid = case["case_id"]
        cur.execute("""
            SELECT rowid, para_idx, text FROM paragraphs
            WHERE case_id = ? AND section = 'Merits'
              AND text IS NOT NULL AND length(text) > 30
            ORDER BY rowid
        """, (cid,))
        merits = cur.fetchall()
        if len(merits) > PARAS_PER_CASE:
            merits = random.sample(merits, PARAS_PER_CASE)
            # restore order by rowid
            merits = sorted(merits, key=lambda r: r["rowid"])

        for p in merits:
            rowid = p["rowid"]
            # context: 2 before + 2 after (rowid order)
            cur.execute("""
                SELECT rowid, section, substr(text, 1, 180) AS preview
                FROM paragraphs
                WHERE case_id = ? AND rowid BETWEEN ? AND ?
                ORDER BY rowid
            """, (cid, rowid - 20, rowid + 20))
            ctx = cur.fetchall()
            target_idx = next((i for i, c in enumerate(ctx) if c["rowid"] == rowid), None)
            before, after = [], []
            if target_idx is not None:
                before = [{"section": c["section"], "preview": (c["preview"] or "").replace("\n", " ")}
                          for c in ctx[max(0, target_idx-2):target_idx]]
                after = [{"section": c["section"], "preview": (c["preview"] or "").replace("\n", " ")}
                         for c in ctx[target_idx+1:target_idx+3]]

            samples.append({
                "population": pop_label,
                "case_id": cid,
                "case_title": (case["title"] or "")[:100],
                "case_date": case["judgment_date"],
                "rowid": rowid,
                "para_idx": p["para_idx"],
                "text": (p["text"] or "")[:1500],
                "context_before": before,
                "context_after": after,
            })

print(f"\nTotal Merits paragraphs to classify: {len(samples)}")
with open(OUT, "w") as f:
    json.dump(samples, f, ensure_ascii=False, indent=1)
print(f"Wrote {OUT}")
conn.close()
