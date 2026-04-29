"""Extract all 96 P15 samples (small enough — audit them all)."""
import sqlite3, json
from collections import Counter
DB = "/data/echr_search.db"
conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
cur = conn.cursor()
cur.execute("SELECT rowid, section as old_section FROM _p15_backup")
rows = cur.fetchall()

samples = []
for r in rows:
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
        "pass": "P15", "rowid": rowid, "case_id": row["case_id"],
        "case_title": (row["title"] or "")[:80],
        "original_section": r["old_section"], "new_section": row["section"],
        "text": (row["text"] or "")[:1500],
        "context_before": before, "context_after": after,
    })
print(f"Extracted {len(samples)}")
print("Target distribution:")
for sec, n in Counter(s["new_section"] for s in samples).most_common():
    print(f"  {sec}: {n}")
with open("/tmp/p15_audit_samples.json", "w") as f:
    json.dump(samples, f, ensure_ascii=False, indent=1)
conn.close()
