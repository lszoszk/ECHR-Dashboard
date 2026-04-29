"""
End-to-end recall audit: extract stratified random sample for LLM judgment.

Unlike the P1-P7 precision audit (which only sampled paragraphs that WERE
relabeled), this samples from the CURRENT state across all sections,
asking the LLM whether each paragraph belongs in its section.

Goal: measure false negatives — paragraphs that should have been
relabeled but weren't (e.g., remnants of misclassification that
slipped through P1-P12).

Design: 25 samples per major section × 12 sections = 300 samples.
Smaller sections get fewer samples (10).
"""
import sqlite3
import json
import random
import re

DB = "/data/echr_search.db"
OUT = "/tmp/recall_audit_samples.json"
random.seed(424242)

# Sections to audit + samples per section
SECTION_SAMPLES = [
    ("Merits", 30),
    ("Facts Proceedings", 25),
    ("Introduction", 25),
    ("Admissibility", 20),
    ("Facts", 20),
    ("Just Satisfaction", 25),
    ("Legal Framework", 25),
    ("Operative Part", 20),
    ("Operative part", 15),
    ("Facts Background", 15),
    ("Separate Opinion", 20),
    ("Relevant legal framework", 15),
    ("Commission Proceedings", 15),
    ("Final Submissions", 10),
    ("Appendix", 10),
    ("Article 46", 10),
]

conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

samples = []

for sec, n in SECTION_SAMPLES:
    # Skip very short / fragment-y paragraphs that are noise
    cur.execute("""
        SELECT rowid, case_id, para_idx, hudoc_para_no, numbering_block, text
        FROM paragraphs
        WHERE section = ? AND text IS NOT NULL AND length(text) >= 30
        ORDER BY RANDOM() LIMIT ?
    """, (sec, n))
    rows = cur.fetchall()
    print(f"  {sec:<26} {len(rows)} samples")

    for r in rows:
        rowid = r["rowid"]
        case_id = r["case_id"]

        # Get case title
        cur.execute("SELECT title FROM cases WHERE case_id = ?", (case_id,))
        title_row = cur.fetchone()
        case_title = (title_row["title"] if title_row else "") or ""

        # Surrounding context (3 before, 3 after)
        cur.execute("""
            SELECT rowid, section, substr(text, 1, 200) AS preview
            FROM paragraphs
            WHERE case_id = ? AND rowid BETWEEN ? AND ?
            ORDER BY rowid
        """, (case_id, rowid - 30, rowid + 30))
        ctx = cur.fetchall()
        target_idx = next((i for i, c in enumerate(ctx) if c["rowid"] == rowid), None)
        before = []
        after = []
        if target_idx is not None:
            before = [{"section": c["section"], "preview": (c["preview"] or "").replace("\n", " ")[:200]}
                      for c in ctx[max(0, target_idx-3):target_idx]]
            after = [{"section": c["section"], "preview": (c["preview"] or "").replace("\n", " ")[:200]}
                     for c in ctx[target_idx+1:target_idx+4]]

        samples.append({
            "rowid": rowid,
            "case_id": case_id,
            "case_title": case_title[:80],
            "current_section": sec,
            "para_idx": r["para_idx"],
            "hudoc_para_no": r["hudoc_para_no"],
            "numbering_block": r["numbering_block"],
            "text": (r["text"] or "")[:1500],
            "context_before": before,
            "context_after": after,
        })

print(f"\nTotal: {len(samples)} samples")
with open(OUT, "w") as f:
    json.dump(samples, f, ensure_ascii=False, indent=1)
print(f"Wrote {OUT}")

conn.close()
