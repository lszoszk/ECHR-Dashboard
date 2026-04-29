"""Extract 50 random P14 samples for Sonnet audit (post-redesign apply)."""
import sqlite3, json, random
from collections import Counter
random.seed(2026)
DB = "/data/echr_search.db"
conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
cur = conn.cursor()
cur.execute("SELECT rowid, section as old_section FROM _p14_backup")
rows = cur.fetchall()
pick = random.sample(rows, min(50, len(rows)))

samples = []
for r in pick:
    rowid = r["rowid"]
    cur.execute("SELECT p.case_id, p.section, p.text, c.title FROM paragraphs p JOIN cases c ON c.case_id=p.case_id WHERE p.rowid=?", (rowid,))
    row = cur.fetchone()
    if not row: continue
    cur.execute("SELECT rowid, section, substr(text, 1, 200) AS preview FROM paragraphs WHERE case_id=? AND rowid BETWEEN ? AND ? ORDER BY rowid", (row["case_id"], rowid - 30, rowid + 30))
    ctx = cur.fetchall()
    target_idx = next((i for i, c in enumerate(ctx) if c["rowid"] == rowid), None)
    before, after = [], []
    if target_idx is not None:
        before = [{"section": c["section"], "preview": (c["preview"] or "").replace("\n", " ")} for c in ctx[max(0, target_idx-3):target_idx]]
        after = [{"section": c["section"], "preview": (c["preview"] or "").replace("\n", " ")} for c in ctx[target_idx+1:target_idx+4]]
    samples.append({
        "pass": "P14_v2", "rowid": rowid, "case_id": row["case_id"],
        "case_title": (row["title"] or "")[:80],
        "original_section": r["old_section"], "new_section": row["section"],
        "text": (row["text"] or "")[:1500],
        "context_before": before, "context_after": after,
    })
print(f"Wrote {len(samples)} samples")
print("Target distribution:")
for sec, n in Counter(s["new_section"] for s in samples).most_common():
    print(f"  {sec}: {n}")
with open("/tmp/p14_audit_samples_v2.json", "w") as f:
    json.dump(samples, f, ensure_ascii=False, indent=1)
conn.close()
