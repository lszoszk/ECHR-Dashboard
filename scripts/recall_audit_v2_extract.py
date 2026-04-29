"""End-to-end recall audit v2 (post-P19) — same allocation, fresh seed."""
import sqlite3, json, random
DB = "/data/echr_search.db"
OUT = "/tmp/recall_audit_v2_samples.json"
random.seed(20260430)  # new seed for fresh draw

SECTION_SAMPLES = [
    ("Merits", 30), ("Facts Proceedings", 25), ("Introduction", 25),
    ("Admissibility", 20), ("Facts", 20), ("Just Satisfaction", 25),
    ("Legal Framework", 25), ("Operative Part", 20), ("Operative part", 15),
    ("Facts Background", 15), ("Separate Opinion", 20),
    ("Relevant legal framework", 15), ("Commission Proceedings", 15),
    ("Final Submissions", 10), ("Appendix", 10), ("Article 46", 10),
]

conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
cur = conn.cursor()
samples = []

for sec, n in SECTION_SAMPLES:
    cur.execute("""
        SELECT rowid, case_id, para_idx, hudoc_para_no, numbering_block, text
        FROM paragraphs
        WHERE section = ? AND text IS NOT NULL AND length(text) >= 30
        ORDER BY RANDOM() LIMIT ?
    """, (sec, n))
    rows = cur.fetchall()
    print(f"  {sec:<26} {len(rows)} samples")
    for r in rows:
        rowid = r["rowid"]; case_id = r["case_id"]
        cur.execute("SELECT title FROM cases WHERE case_id = ?", (case_id,))
        tr = cur.fetchone()
        case_title = (tr["title"] if tr else "") or ""
        cur.execute("SELECT rowid, section, substr(text, 1, 200) AS preview FROM paragraphs WHERE case_id = ? AND rowid BETWEEN ? AND ? ORDER BY rowid", (case_id, rowid - 30, rowid + 30))
        ctx = cur.fetchall()
        ti = next((i for i, c in enumerate(ctx) if c["rowid"] == rowid), None)
        before, after = [], []
        if ti is not None:
            before = [{"section": c["section"], "preview": (c["preview"] or "").replace("\n", " ")[:200]} for c in ctx[max(0, ti-3):ti]]
            after = [{"section": c["section"], "preview": (c["preview"] or "").replace("\n", " ")[:200]} for c in ctx[ti+1:ti+4]]
        samples.append({
            "rowid": rowid, "case_id": case_id, "case_title": case_title[:80],
            "current_section": sec, "para_idx": r["para_idx"],
            "hudoc_para_no": r["hudoc_para_no"], "numbering_block": r["numbering_block"],
            "text": (r["text"] or "")[:1500],
            "context_before": before, "context_after": after,
        })

print(f"\nTotal: {len(samples)}")
with open(OUT, "w") as f:
    json.dump(samples, f, ensure_ascii=False, indent=1)
print(f"Wrote {OUT}")
conn.close()
