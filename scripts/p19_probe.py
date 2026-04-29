"""P19 phase 1: detect merge-pair candidates for 3 patterns."""
import sqlite3, re
DB = "/data/echr_search.db"
conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# Pattern A: parent ends with "Article" (no number); child starts with "N. § M of the Convention"
# Pattern B: child is just "N. § M of the Convention." (parent ending more flexible)
# Pattern C: child starts "77. §§ 2 and 3 of the Rules of Court"; parent ends with "Rule"

# Detection regexes
RE_CHILD_ART = re.compile(r"^\s*\d+\.\s*§\s*\d+(?:\s*\([a-z]\))?\s+of\s+the\s+Convention", re.IGNORECASE)
RE_PARENT_ART_END = re.compile(r"\b(?:of\s+Article|Article)\s*\.?\s*$", re.IGNORECASE)

RE_CHILD_RULE77 = re.compile(r"^\s*77\.\s*§§?\s*[123]\s+(?:and\s+\d+\s+)?of\s+the\s+Rules\s+of\s+Court", re.IGNORECASE)
RE_PARENT_RULE_END = re.compile(r"\b(?:Rule|to\s+Rule|under\s+Rule|pursuant\s+to\s+Rule|in\s+accordance\s+with\s+Rule)\s*\.?\s*$", re.IGNORECASE)

# Build a per-case rowid-ordered list to find adjacent neighbours quickly
print("Loading paragraphs...")
cur.execute("SELECT rowid, case_id, section, length(text) AS L, text FROM paragraphs WHERE text IS NOT NULL ORDER BY case_id, rowid")
rows = cur.fetchall()
print(f"Loaded {len(rows):,} paragraphs")

# Group by case
cases = {}
for r in rows:
    cases.setdefault(r["case_id"], []).append(r)

# Find merge candidates
pattern_A_pairs = []  # parent ends Article + child Article+§
pattern_B_pairs = []  # child = standalone "N. § M of Convention." (less restrictive parent)
pattern_C_pairs = []  # child Rule 77 + parent ends "Rule"

for cid, plist in cases.items():
    for i in range(len(plist) - 1):
        parent = plist[i]
        child = plist[i + 1]
        ptext = (parent["text"] or "").strip()
        ctext = (child["text"] or "").strip()
        if not ptext or not ctext: continue

        # Pattern A: parent ends "Article" + child starts "§"
        if RE_PARENT_ART_END.search(ptext[-30:]) and RE_CHILD_ART.match(ctext):
            pattern_A_pairs.append((parent["rowid"], child["rowid"], cid, parent["section"], child["section"], len(ptext), len(ctext)))
            continue  # avoid double-counting in B

        # Pattern B: child is essentially just "N. § M of Convention." (less restrictive parent)
        # Use length cap on child to avoid catching legit paragraphs
        if RE_CHILD_ART.match(ctext) and len(ctext) < 90:
            pattern_B_pairs.append((parent["rowid"], child["rowid"], cid, parent["section"], child["section"], len(ptext), len(ctext)))
            continue

        # Pattern C: child Rule 77 + parent ends "Rule"
        if RE_CHILD_RULE77.match(ctext) and RE_PARENT_RULE_END.search(ptext[-15:]):
            pattern_C_pairs.append((parent["rowid"], child["rowid"], cid, parent["section"], child["section"], len(ptext), len(ctext)))

print(f"\n=== Merge-pair candidates ===")
print(f"  Pattern A (Article-split, parent ends 'Article' + child '§ N'): {len(pattern_A_pairs):,}")
print(f"  Pattern B (standalone short fragment 'N. § M of Convention.'):  {len(pattern_B_pairs):,}")
print(f"  Pattern C (Rule 77 split, parent ends 'Rule' + child '77.'):    {len(pattern_C_pairs):,}")
print(f"  TOTAL MERGE PAIRS: {len(pattern_A_pairs)+len(pattern_B_pairs)+len(pattern_C_pairs):,}")

# Section-cross check: does parent and child share section? When they don't, merge might confuse section.
def cross_check(name, pairs):
    same = sum(1 for p in pairs if p[3] == p[4])
    diff = len(pairs) - same
    print(f"  {name}: same-section {same:,}, different-section {diff:,}")
print(f"\n=== Section consistency ===")
cross_check("A", pattern_A_pairs)
cross_check("B", pattern_B_pairs)
cross_check("C", pattern_C_pairs)

# Spot samples
import random
random.seed(7)
def sample(name, pairs, n=5):
    print(f"\n=== Sample {n} {name} pairs ===")
    if not pairs: return
    for prid, crid, cid, psec, csec, pL, cL in random.sample(pairs, min(n, len(pairs))):
        cur.execute("SELECT text FROM paragraphs WHERE rowid IN (?, ?) ORDER BY rowid", (prid, crid))
        ptxt, ctxt = [r[0].strip() for r in cur.fetchall()]
        merged = ptxt + " " + ctxt
        print(f"\n  [parent rid={prid} sec={psec} len={pL}] [child rid={crid} sec={csec} len={cL}] case={cid}")
        print(f"    PARENT: {ptxt[-100:]!r}")
        print(f"    CHILD:  {ctxt[:150]!r}")
        print(f"    MERGED: {merged[max(0,len(ptxt)-50):min(len(merged),len(ptxt)+200)]!r}")

sample("A", pattern_A_pairs, 5)
sample("B", pattern_B_pairs, 5)
sample("C", pattern_C_pairs, 5)

# Save lists
import json
with open("/tmp/p19_pairs.json", "w") as f:
    json.dump({
        "A": [[p[0], p[1], p[2]] for p in pattern_A_pairs],
        "B": [[p[0], p[1], p[2]] for p in pattern_B_pairs],
        "C": [[p[0], p[1], p[2]] for p in pattern_C_pairs],
    }, f)
print(f"\nSaved /tmp/p19_pairs.json")
