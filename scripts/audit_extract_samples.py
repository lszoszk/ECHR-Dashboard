"""
Extract stratified random sample of relabeled paragraphs for LLM precision audit.

For each pass _pN_backup, sample N=70 random rowids. For each:
  - text of the relabeled paragraph
  - original section (from _pN_backup)
  - new section (current paragraphs.section)
  - surrounding context (3 paragraphs before, 3 after, by rowid order)
  - case title and case_id

Outputs JSON to /tmp/audit_samples.json for the LLM judge.
"""
import sqlite3
import json
import random

DB = "/data/echr_search.db"
OUT = "/tmp/audit_samples.json"
SAMPLES_PER_PASS = 70
random.seed(42)

PASSES = ["_p1_backup", "_p2_backup", "_p3_backup", "_p4_backup",
          "_p5_backup", "_p6_backup", "_p7_backup"]

PASS_DESCR = {
    "_p1_backup": "P1: 'APPLICATION OF ARTICLE 41' headings + content blocks → Just Satisfaction",
    "_p2_backup": "P2: dissenting/concurring opinions in Operative Part → Separate Opinion",
    "_p3_backup": "P3: 'RELEVANT DOMESTIC LAW' subsections from Facts Proceedings → Legal Framework",
    "_p4_backup": "P4: ALLEGED VIOLATION/JOINDER in Pop C Facts → Merits/Just Satisfaction",
    "_p5_backup": "P5: continuation across short Admissibility interruption in Pop C",
    "_p6_backup": "P6: 'Article 41 of the Convention provides' text anchor in Pop C Facts → Just Satisfaction",
    "_p7_backup": "P7: glued 'I. JOINDER OF THE APPLICATIONS' in Pop C Facts → Merits",
}

conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

samples = []

for table in PASSES:
    cur.execute(f"SELECT rowid, section as old_section FROM {table}")
    rows = cur.fetchall()
    if not rows:
        continue
    pick = random.sample(rows, min(SAMPLES_PER_PASS, len(rows)))
    for r in pick:
        rowid = r["rowid"]
        old_sec = r["old_section"]

        # current state
        cur.execute("""
            SELECT p.rowid, p.case_id, p.section, p.text, p.para_idx, c.title
            FROM paragraphs p JOIN cases c ON c.case_id = p.case_id
            WHERE p.rowid = ?
        """, (rowid,))
        row = cur.fetchone()
        if not row:
            continue

        case_id = row["case_id"]
        new_sec = row["section"]
        text = row["text"]

        # surrounding context: 3 before, 3 after by rowid in same case
        cur.execute("""
            SELECT rowid, section, substr(text, 1, 200) AS preview
            FROM paragraphs
            WHERE case_id = ? AND rowid BETWEEN ? AND ?
            ORDER BY rowid
        """, (case_id, rowid - 30, rowid + 30))
        ctx = cur.fetchall()
        # Find target index, pick window around it
        target_idx = None
        for i, c in enumerate(ctx):
            if c["rowid"] == rowid:
                target_idx = i
                break
        before = []
        after = []
        if target_idx is not None:
            before = [{"section": c["section"], "preview": (c["preview"] or "").replace("\n", " ")}
                     for c in ctx[max(0, target_idx-3):target_idx]]
            after = [{"section": c["section"], "preview": (c["preview"] or "").replace("\n", " ")}
                    for c in ctx[target_idx+1:target_idx+4]]

        samples.append({
            "pass": table,
            "pass_descr": PASS_DESCR[table],
            "case_id": case_id,
            "case_title": (row["title"] or "")[:100],
            "rowid": rowid,
            "original_section": old_sec,
            "new_section": new_sec,
            "text": text[:1500] if text else "",  # cap to keep prompt size reasonable
            "context_before": before,
            "context_after": after,
        })

print(f"Extracted {len(samples)} samples across {len(PASSES)} passes")
with open(OUT, "w") as f:
    json.dump(samples, f, ensure_ascii=False, indent=1)
print(f"Wrote {OUT}")

# Per-pass count
from collections import Counter
counts = Counter(s["pass"] for s in samples)
for p, n in counts.most_common():
    print(f"  {p}: {n}")

conn.close()
