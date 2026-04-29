"""Extract P17 audit samples — 30 R1 + all 3 R2."""
import sqlite3, json, random, re
from collections import Counter
random.seed(2026)

P_GOV = re.compile(r"(?:^|\.\s+)(?:The\s+)?Government(?:s)?\s+(?:was|were|is|are)\s+represented\s+by\s+", re.IGNORECASE)
P_APP = re.compile(r"(?:^|\.\s+)(?:The\s+)?applicant(?:s)?\s+(?:was|were|is|are)\s+represented\s+by\s+", re.IGNORECASE)

DB = "/data/echr_search.db"
conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
cur = conn.cursor()
cur.execute("SELECT rowid, section as old_section FROM _p17_backup")
rows = cur.fetchall()

bucketed = {"R1": [], "R2": []}
for r in rows:
    cur.execute("SELECT text FROM paragraphs WHERE rowid=?", (r["rowid"],))
    t = (cur.fetchone()[0] or "").strip()
    has_gov = bool(P_GOV.search(t))
    has_app = bool(P_APP.search(t))
    if has_gov and has_app and len(t) < 500:
        bucketed["R2"].append(r["rowid"])
    else:
        bucketed["R1"].append(r["rowid"])

print(f"Pop: R1={len(bucketed['R1'])} R2={len(bucketed['R2'])}")
plan = {"R1": min(30, len(bucketed["R1"])), "R2": len(bucketed["R2"])}
sampled = []
for rule, n in plan.items():
    pop = bucketed[rule]
    pick = pop if len(pop) <= n else random.sample(pop, n)
    sampled.extend([(rule, rid) for rid in pick])

samples = []
for rule, rowid in sampled:
    cur.execute("SELECT p.case_id, p.section, p.text, c.title FROM paragraphs p JOIN cases c ON c.case_id=p.case_id WHERE p.rowid=?", (rowid,))
    row = cur.fetchone()
    if not row: continue
    cur.execute("SELECT section AS old FROM _p17_backup WHERE rowid=?", (rowid,))
    old_section = cur.fetchone()["old"]
    cur.execute("SELECT rowid, section, substr(text, 1, 200) AS preview FROM paragraphs WHERE case_id=? AND rowid BETWEEN ? AND ? ORDER BY rowid", (row["case_id"], rowid - 30, rowid + 30))
    ctx = cur.fetchall()
    target_idx = next((i for i, c in enumerate(ctx) if c["rowid"] == rowid), None)
    before, after = [], []
    if target_idx is not None:
        before = [{"section": c["section"], "preview": (c["preview"] or "").replace("\n", " ")} for c in ctx[max(0, target_idx-3):target_idx]]
        after = [{"section": c["section"], "preview": (c["preview"] or "").replace("\n", " ")} for c in ctx[target_idx+1:target_idx+4]]
    samples.append({
        "pass": "P17", "rule": rule, "rowid": rowid, "case_id": row["case_id"],
        "case_title": (row["title"] or "")[:80],
        "original_section": old_section, "new_section": row["section"],
        "text": (row["text"] or "")[:1500],
        "context_before": before, "context_after": after,
    })
print(f"Samples: {len(samples)}; rule dist={Counter(s['rule'] for s in samples)}")
with open("/tmp/p17_audit_samples.json", "w") as f:
    json.dump(samples, f, ensure_ascii=False, indent=1)
conn.close()
