"""Extract 100 stratified P20 samples (25 per rule) for Sonnet audit."""
import sqlite3, json, random
random.seed(2026)
DB = "/data/echr_search.db"
conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

with open("/tmp/rec5_pairs.json") as f:
    pairs = json.load(f)

# Group by rule
by_rule = {}
for p in pairs:
    by_rule.setdefault(p["rule"], []).append(p)
print({r: len(v) for r, v in by_rule.items()})

sampled = []
for rule, items in by_rule.items():
    pick = random.sample(items, min(25, len(items)))
    sampled.extend(pick)

samples = []
for p in sampled:
    cur.execute("SELECT p.text, p.section, c.title FROM paragraphs p JOIN cases c ON c.case_id=p.case_id WHERE p.rowid=?", (p["rowid"],))
    row = cur.fetchone()
    if not row: continue
    cur.execute("SELECT rowid, section, substr(text,1,200) AS preview FROM paragraphs WHERE case_id=? AND rowid BETWEEN ? AND ? ORDER BY rowid", (p["case_id"], p["rowid"]-30, p["rowid"]+30))
    ctx = cur.fetchall()
    ti = next((i for i, c in enumerate(ctx) if c["rowid"] == p["rowid"]), None)
    before, after = [], []
    if ti is not None:
        before = [{"section": c["section"], "preview": (c["preview"] or "").replace("\n", " ")} for c in ctx[max(0, ti-3):ti]]
        after = [{"section": c["section"], "preview": (c["preview"] or "").replace("\n", " ")} for c in ctx[ti+1:ti+4]]
    samples.append({
        "pass": "P20", "rule": p["rule"], "rowid": p["rowid"], "case_id": p["case_id"],
        "case_title": (row["title"] or "")[:80],
        "current_section": p["section"], "proposed_section": "Appendix",
        "text": (row["text"] or "")[:1500],
        "context_before": before, "context_after": after,
    })

print(f"Total samples: {len(samples)}")
with open("/tmp/rec5_audit_samples.json", "w") as f:
    json.dump(samples, f, ensure_ascii=False, indent=1)
conn.close()
