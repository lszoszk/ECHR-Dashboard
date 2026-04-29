"""Extract P19 audit samples — 50 A + all 4 B + 50 C with full parent/child text + joined + context."""
import sqlite3, json, random
from collections import Counter
random.seed(2026)

DB = "/data/echr_search.db"
conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

with open("/tmp/p19_pairs.json") as f:
    pairs = json.load(f)
print({k: len(v) for k, v in pairs.items()})

plan = {"A": 50, "B": len(pairs["B"]), "C": 50}
sampled = []
for ptn, n in plan.items():
    pop = pairs[ptn]
    pick = pop if len(pop) <= n else random.sample(pop, n)
    sampled.extend([(ptn, *p) for p in pick])

samples = []
for ptn, prid, crid, cid in sampled:
    # Full parent/child rows + section + numbering_block + hudoc_para_no
    cur.execute("SELECT rowid, section, numbering_block, hudoc_para_no, text FROM paragraphs WHERE rowid IN (?, ?) ORDER BY rowid", (prid, crid))
    rows = cur.fetchall()
    if len(rows) != 2: continue
    parent, child = rows[0], rows[1]
    cur.execute("SELECT title FROM cases WHERE case_id=?", (cid,))
    title_row = cur.fetchone()
    title = (title_row[0] if title_row else "")[:80]
    # Surrounding context: 2 paragraphs before parent, 2 after child
    cur.execute("SELECT rowid, section, substr(text, 1, 200) AS preview FROM paragraphs WHERE case_id=? AND rowid BETWEEN ? AND ? ORDER BY rowid", (cid, prid - 5, crid + 5))
    ctx = cur.fetchall()
    before, after = [], []
    for r in ctx:
        if r["rowid"] < prid: before.append({"rowid": r["rowid"], "section": r["section"], "preview": (r["preview"] or "").replace("\n", " ")})
        elif r["rowid"] > crid: after.append({"rowid": r["rowid"], "section": r["section"], "preview": (r["preview"] or "").replace("\n", " ")})
    joined_text = ((parent["text"] or "").strip() + " " + (child["text"] or "").strip())[:2000]
    samples.append({
        "pattern": ptn,
        "case_id": cid,
        "case_title": title,
        "parent": {
            "rowid": parent["rowid"], "section": parent["section"],
            "numbering_block": parent["numbering_block"], "hudoc_para_no": parent["hudoc_para_no"],
            "text": (parent["text"] or "")[:1500],
        },
        "child": {
            "rowid": child["rowid"], "section": child["section"],
            "numbering_block": child["numbering_block"], "hudoc_para_no": child["hudoc_para_no"],
            "text": (child["text"] or "")[:1500],
        },
        "joined_text_preview": joined_text,
        "context_before": before[-2:],  # last 2 paragraphs before parent
        "context_after": after[:2],      # first 2 paragraphs after child
    })

with open("/tmp/p19_audit_samples.json", "w") as f:
    json.dump(samples, f, ensure_ascii=False, indent=1)

print(f"Wrote {len(samples)} samples")
print("Pattern dist:", Counter(s["pattern"] for s in samples))
print("Same vs diff section:")
for s in samples[:0]: pass
same = sum(1 for s in samples if s["parent"]["section"] == s["child"]["section"])
print(f"  same={same} diff={len(samples)-same}")
conn.close()
