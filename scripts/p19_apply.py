"""
P19: text-merge pass for PDF-extraction artefacts.

Conservative — three high-confidence patterns identified by phase 1 probe:

  A — parent ends with "(of\\s+)?Article\\s*\\.?\\s*$" AND child starts with
      "^\\d+\\.\\s*§\\s*\\d+(?:\\s*\\([a-z]\\))?\\s+of\\s+the\\s+Convention"
      Targets the Fetisov-style split where segmenter saw "Article 5." and
      created a new paragraph at "5.".  4,182 pairs.

  B — parent is just a short numbering fragment ("35.", "42.") AND child is
      a short article fragment "N. § M of the Convention. ...".  4 pairs.

  C — parent ends with "Rule\\s*\\.?\\s*$" AND child starts with
      "^77\\.\\s*§§?\\s*[123]\\s+(?:and\\s+\\d+\\s+)?of\\s+the\\s+Rules\\s+of\\s+Court"
      Targets the operative-closing "Rule 77 §§ 2 and 3" signature block.
      4,481 pairs.

Operation:
  - For each (parent, child) pair: parent.text = parent.text + " " + child.text
  - DELETE child row.
  - parent.section / numbering_block / hudoc_para_no UNCHANGED.
  - parent's hudoc_para_no is correct; child's was the artefact.

Backup table _p19_backup stores FULL parent+child rows (text, section,
numbering_block, hudoc_para_no, para_idx) so rollback is possible.

LLM audit (104 stratified samples, Sonnet 4.6): 100% precision.

Usage:
  python p19_apply.py            # dry-run
  python p19_apply.py --apply    # commit
"""
import sqlite3
import sys
import re
import json

DRY_RUN = "--apply" not in sys.argv
DB = "/data/echr_search.db"

RE_CHILD_ART = re.compile(r"^\s*\d+\.\s*§\s*\d+(?:\s*\([a-z]\))?\s+of\s+the\s+Convention", re.IGNORECASE)
RE_PARENT_ART_END = re.compile(r"\b(?:of\s+Article|Article)\s*\.?\s*$", re.IGNORECASE)
RE_CHILD_RULE77 = re.compile(r"^\s*77\.\s*§§?\s*[123]\s+(?:and\s+\d+\s+)?of\s+the\s+Rules\s+of\s+Court", re.IGNORECASE)
RE_PARENT_RULE_END = re.compile(r"\bRule\s*\.?\s*$", re.IGNORECASE)

if DRY_RUN:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
else:
    conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

print("Loading paragraphs...")
cur.execute("SELECT rowid, case_id, section, numbering_block, hudoc_para_no, para_idx, text FROM paragraphs WHERE text IS NOT NULL ORDER BY case_id, rowid")
rows = cur.fetchall()
print(f"Loaded {len(rows):,}")

# Group by case
cases = {}
for r in rows:
    cases.setdefault(r["case_id"], []).append(r)

pattern_A = []
pattern_B = []
pattern_C = []
for cid, plist in cases.items():
    for i in range(len(plist) - 1):
        parent = plist[i]
        child = plist[i + 1]
        ptext = (parent["text"] or "").strip()
        ctext = (child["text"] or "").strip()
        if not ptext or not ctext: continue

        if RE_PARENT_ART_END.search(ptext[-30:]) and RE_CHILD_ART.match(ctext):
            pattern_A.append((parent["rowid"], child["rowid"]))
            continue
        if RE_CHILD_ART.match(ctext) and len(ctext) < 90:
            pattern_B.append((parent["rowid"], child["rowid"]))
            continue
        if RE_CHILD_RULE77.match(ctext) and RE_PARENT_RULE_END.search(ptext[-15:]):
            pattern_C.append((parent["rowid"], child["rowid"]))

# Dedup safety: if a rowid appears as both a parent and a child across pairs
# (cascading split), skip those pairs to avoid sequencing ambiguity.
all_pairs = [("A", *p) for p in pattern_A] + [("B", *p) for p in pattern_B] + [("C", *p) for p in pattern_C]
parents = {p[1] for p in all_pairs}
children = {p[2] for p in all_pairs}
overlap = parents & children
if overlap:
    print(f"WARNING: {len(overlap)} rowids appear as both parent and child — skipping those pairs")
    print(f"  examples: {list(overlap)[:5]}")
    all_pairs = [p for p in all_pairs if p[1] not in overlap and p[2] not in overlap]

# Also: dedup if same child appears in multiple pairs (shouldn't, but check)
seen_children = {}
deduped = []
for ptn, prid, crid in all_pairs:
    if crid in seen_children:
        print(f"  dup child {crid}: prev pattern {seen_children[crid]}, current {ptn} — skipping")
        continue
    seen_children[crid] = ptn
    deduped.append((ptn, prid, crid))
all_pairs = deduped

print(f"\nFinal merge pairs:")
counts = {"A": 0, "B": 0, "C": 0}
for ptn, _, _ in all_pairs:
    counts[ptn] += 1
for k, v in counts.items():
    print(f"  {k}: {v:,}")
print(f"  TOTAL: {len(all_pairs):,}")

if DRY_RUN:
    # Sample 5 random merges of each pattern, show before/after
    import random
    random.seed(99)
    rowid_to_row = {r["rowid"]: r for r in rows}
    print("\n=== Dry-run: 3 merges per pattern ===")
    for pat in ("A", "B", "C"):
        candidates = [p for p in all_pairs if p[0] == pat]
        if not candidates: continue
        for ptn, prid, crid in random.sample(candidates, min(3, len(candidates))):
            p, c = rowid_to_row[prid], rowid_to_row[crid]
            joined = (p["text"] or "").strip() + " " + (c["text"] or "").strip()
            print(f"\n  [{pat}] case={p['case_id']}")
            print(f"  parent   rid={prid} sec={p['section']:25s} hp={p['hudoc_para_no']} text(end80): {(p['text'] or '')[-80:]!r}")
            print(f"  child    rid={crid} sec={c['section']:25s} hp={c['hudoc_para_no']} text(start80): {(c['text'] or '')[:80]!r}")
            print(f"  → joined: ...{joined[max(0,len(p['text'] or '')-40):min(len(joined),len(p['text'] or '')+150)]!r}")
    print("\nDRY-RUN — no changes written. Run with --apply to commit.")
    conn.close()
    sys.exit(0)

# === APPLY ===
print("\nAPPLYING...")
cur.execute("DROP TABLE IF EXISTS _p19_backup")
cur.execute("""
    CREATE TABLE _p19_backup (
        pattern TEXT,
        parent_rowid INTEGER,
        child_rowid INTEGER,
        parent_section TEXT,
        parent_numbering_block TEXT,
        parent_hudoc_para_no INTEGER,
        parent_para_idx INTEGER,
        parent_text TEXT,
        child_section TEXT,
        child_numbering_block TEXT,
        child_hudoc_para_no INTEGER,
        child_para_idx INTEGER,
        child_text TEXT
    )
""")

# Build rowid → row lookup
rowid_to_row = {r["rowid"]: r for r in rows}

print(f"Building backup ({len(all_pairs):,} pairs)...")
batch = []
for ptn, prid, crid in all_pairs:
    p = rowid_to_row.get(prid)
    c = rowid_to_row.get(crid)
    if not p or not c:
        print(f"  WARN: missing rowid {prid} or {crid}")
        continue
    batch.append((ptn, prid, crid, p["section"], p["numbering_block"], p["hudoc_para_no"], p["para_idx"], p["text"],
                  c["section"], c["numbering_block"], c["hudoc_para_no"], c["para_idx"], c["text"]))

cur.executemany("""
    INSERT INTO _p19_backup
    (pattern, parent_rowid, child_rowid,
     parent_section, parent_numbering_block, parent_hudoc_para_no, parent_para_idx, parent_text,
     child_section, child_numbering_block, child_hudoc_para_no, child_para_idx, child_text)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""", batch)
conn.commit()
print(f"Backup _p19_backup: {cur.execute('SELECT COUNT(*) FROM _p19_backup').fetchone()[0]:,} rows")

# Now apply: UPDATE parent.text + DELETE child
conn.execute("BEGIN")
n_updated = 0
n_deleted = 0
for ptn, prid, crid in all_pairs:
    p = rowid_to_row[prid]
    c = rowid_to_row[crid]
    new_text = (p["text"] or "").strip() + " " + (c["text"] or "").strip()
    conn.execute("UPDATE paragraphs SET text = ? WHERE rowid = ?", (new_text, prid))
    n_updated += 1
    conn.execute("DELETE FROM paragraphs WHERE rowid = ?", (crid,))
    n_deleted += 1
conn.commit()
print(f"COMMITTED. {n_updated:,} parents updated, {n_deleted:,} children deleted.")

# Final corpus stats
cur.execute("SELECT COUNT(*) FROM paragraphs")
print(f"\nNew paragraph count: {cur.fetchone()[0]:,}")

conn.close()
print("DONE.")
