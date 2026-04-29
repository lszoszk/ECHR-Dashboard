"""Extract stratified P16 samples for Sonnet audit.
Strategy: audit all of small-population rules (R0a, R0b),
sample 12 each from R1/R2/R3/R4."""
import sqlite3, json, random, re
random.seed(2026)

R0A = re.compile(r"^\s*(?:[IVX]+\.\s+)?APPLICATION\s+OF\s+ARTICLE\s+41", re.IGNORECASE)
R0B = re.compile(r"Article\s+41\s+of\s+the\s+Convention\s+provides", re.IGNORECASE)
R1 = re.compile(r"^\s*\d+\.\s*(Holds|Decides|Declares|Dismisses)\b", re.IGNORECASE)
R2 = re.compile(r"\(a\)\s*that\s+the\s+respondent\s+State\s+is\s+to\s+pay", re.IGNORECASE)
R3H = re.compile(r"\(b\)\s*that\s+from\s+the\s+expiry\s+of\s+the\s+above-mentioned\s+three\s+months", re.IGNORECASE)
R3B = re.compile(r"simple\s+interest\s+shall\s+be\s+payable", re.IGNORECASE)
R4A = re.compile(r"\b(Court\s+awards|the\s+Court\s+considers\s+it\s+reasonable\s+to\s+award)\b", re.IGNORECASE)

def detect_rule(text):
    if not text: return None
    t = text.strip(); L = len(t)
    if L < 200 and R0A.match(t): return "R0a"
    if L < 800 and R0B.search(t): return "R0b"
    if R1.match(t): return "R1"
    if L < 1500 and R2.search(t): return "R2"
    if L < 700 and R3H.search(t) and R3B.search(t): return "R3"
    if R4A.search(t): return "R4"
    return None

DB = "/data/echr_search.db"
conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
cur = conn.cursor()
cur.execute("SELECT rowid, section as old_section FROM _p16_backup")
rows = cur.fetchall()

bucketed = {"R0a": [], "R0b": [], "R1": [], "R2": [], "R3": [], "R4": []}
for r in rows:
    cur.execute("SELECT text FROM paragraphs WHERE rowid=?", (r["rowid"],))
    t = (cur.fetchone()[0] or "")
    rule = detect_rule(t)
    if rule:
        bucketed[rule].append(r["rowid"])

print("Population by rule:", {k: len(v) for k, v in bucketed.items()})

# Sample plan: audit all of R0a/R0b (7 total); 12 each from R1/R2/R3/R4 = 48; total 55
sample_plan = {"R0a": 1, "R0b": 6, "R1": 12, "R2": 12, "R3": 12, "R4": 12}
sampled = []
for rule, n in sample_plan.items():
    pop = bucketed[rule]
    pick = pop if len(pop) <= n else random.sample(pop, n)
    sampled.extend([(rule, rid) for rid in pick])

print(f"Total samples: {len(sampled)}")

samples = []
for rule, rowid in sampled:
    cur.execute("SELECT p.case_id, p.section, p.text, c.title FROM paragraphs p JOIN cases c ON c.case_id=p.case_id WHERE p.rowid=?", (rowid,))
    row = cur.fetchone()
    if not row: continue
    cur.execute("SELECT section AS old FROM _p16_backup WHERE rowid=?", (rowid,))
    old_section = cur.fetchone()["old"]

    cur.execute("SELECT rowid, section, substr(text, 1, 200) AS preview FROM paragraphs WHERE case_id=? AND rowid BETWEEN ? AND ? ORDER BY rowid", (row["case_id"], rowid - 30, rowid + 30))
    ctx = cur.fetchall()
    target_idx = next((i for i, c in enumerate(ctx) if c["rowid"] == rowid), None)
    before, after = [], []
    if target_idx is not None:
        before = [{"section": c["section"], "preview": (c["preview"] or "").replace("\n", " ")} for c in ctx[max(0, target_idx-3):target_idx]]
        after = [{"section": c["section"], "preview": (c["preview"] or "").replace("\n", " ")} for c in ctx[target_idx+1:target_idx+4]]
    samples.append({
        "pass": "P16", "rule": rule, "rowid": rowid, "case_id": row["case_id"],
        "case_title": (row["title"] or "")[:80],
        "original_section": old_section, "new_section": row["section"],
        "text": (row["text"] or "")[:1500],
        "context_before": before, "context_after": after,
    })

with open("/tmp/p16_audit_samples.json", "w") as f:
    json.dump(samples, f, ensure_ascii=False, indent=1)

from collections import Counter
print("Target distribution:", Counter(s["new_section"] for s in samples))
print("Rule distribution:", Counter(s["rule"] for s in samples))
conn.close()
