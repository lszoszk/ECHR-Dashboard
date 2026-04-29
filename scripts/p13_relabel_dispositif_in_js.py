"""
P13 RELABEL: revert Just Satisfaction → Operative Part for dispositif paragraphs.

Recall audit (recall-audit.md) Pattern B identified that 12% (3/25) of
Just Satisfaction paragraphs are actually Operative Part dispositif:
  - "FOR THESE REASONS, THE COURT" opening line
  - Numbered "X. Dismisses/Decides/Declares/Holds" clauses
  - Closing "Rule 77 §§ 2 and 3... Registrar... President" signature block

Most of these are P1 over-capture: P1's heuristic grabbed paragraphs
containing "just satisfaction" or Article 41 phrases and moved them
from Operative Part → Just Satisfaction. This pass reverts the
mistakes that left genuine dispositif content in Just Satisfaction.

Detection rules (paragraph in 'Just Satisfaction', length<400):

  R1: ^\s*FOR THESE REASONS,?\s*THE COURT\b           → Operative Part
  R2: ^\s*\d+\.\s*(Decides|Declares|Holds|Dismisses)  → Operative Part
  R3: contains "Rule 77" AND ("Registrar" OR "Done in ")   → Operative Part

Restrictions:
  - Length cap (400) prevents matches inside long Merits-style paragraphs
    that quote the operative dispositif when discussing prior judgments.
  - Anchor regex at paragraph start avoids in-body "the Court holds that"
    constructions (which appear in legitimate Merits/JS analysis).

Usage:
  python p13_relabel.py            # dry-run
  python p13_relabel.py --apply    # commit
"""
import sqlite3
import sys
import re

DRY_RUN = "--apply" not in sys.argv
DB = "/data/echr_search.db"

# Determine target section (Operative Part vs Operative part) per case.
# We mirror the case's existing operative-part casing where possible;
# fall back to "Operative Part" (uppercase, classical format) for cases
# without one.

R2 = re.compile(r"^\s*\d+\.\s*(Decides|Declares|Holds|Dismisses)\b", re.IGNORECASE)
R3_REGISTRAR = re.compile(r"\bRegistrar\b", re.IGNORECASE)
R3_PRESIDENT = re.compile(r"\bPresident\b", re.IGNORECASE)
R3_RULE_HINT = re.compile(r"(Rule\s*77|§§?\s*2 and 3 of the Rules of Court|Rules of Court)", re.IGNORECASE)
DONE_IN = re.compile(r"\bDone in [A-Z]", re.IGNORECASE)

MAX_LEN = 400

def starts_with_for_these_reasons(text):
    """PDF-artefact-tolerant check for dispositif opening line.
    Strips whitespace and checks if first ~30 compacted chars match
    'FORTHESEREASONS' (allows splits like 'FOR THESE REAS O NS')."""
    if not text:
        return False
    compact = ''.join(c for c in text[:60] if not c.isspace())
    return compact[:15].upper() == "FORTHESEREASONS"

def detect(text):
    """Return 'R1'|'R2'|'R3' if matched, else None."""
    if not text:
        return None
    if len(text) >= MAX_LEN:
        return None
    if starts_with_for_these_reasons(text):
        return "R1"
    if R2.match(text):
        return "R2"
    # R3: signature block. Either:
    #   a) explicit Rule 77 / Rules of Court pattern + signature names
    #   b) both Registrar AND President in a short paragraph (definitive
    #      pattern for dispositif close)
    has_registrar = bool(R3_REGISTRAR.search(text))
    has_president = bool(R3_PRESIDENT.search(text))
    has_rule_hint = bool(R3_RULE_HINT.search(text))
    has_done_in = bool(DONE_IN.search(text))
    if (has_registrar and has_president) or (has_rule_hint and (has_registrar or has_done_in)):
        return "R3"
    return None

if DRY_RUN:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
else:
    conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# Find target operative-part casing per case (mirror what's already there)
print("Building per-case operative-section preferences...")
cur.execute("""
    SELECT case_id,
           SUM(CASE WHEN section = 'Operative Part' THEN 1 ELSE 0 END) AS upper_count,
           SUM(CASE WHEN section = 'Operative part' THEN 1 ELSE 0 END) AS lower_count
    FROM paragraphs
    WHERE section IN ('Operative Part', 'Operative part')
    GROUP BY case_id
""")
case_preferences = {}
for r in cur.fetchall():
    if r["upper_count"] >= r["lower_count"]:
        case_preferences[r["case_id"]] = "Operative Part"
    else:
        case_preferences[r["case_id"]] = "Operative part"
print(f"  {len(case_preferences):,} cases with existing operative section")

# Walk JS paragraphs
print("Scanning Just Satisfaction paragraphs...")
cur.execute("""
    SELECT rowid, case_id, section, text
    FROM paragraphs WHERE section = 'Just Satisfaction'
""")
relabels = {}      # rowid -> target_section
rule_counts = {"R1": 0, "R2": 0, "R3": 0}
for r in cur.fetchall():
    rule = detect(r["text"])
    if rule is None:
        continue
    target = case_preferences.get(r["case_id"], "Operative Part")
    relabels[r["rowid"]] = target
    rule_counts[rule] += 1

print(f"\nTotal candidates: {len(relabels):,}")
print(f"  R1 'FOR THESE REASONS, THE COURT':    {rule_counts['R1']:,}")
print(f"  R2 numbered dispositif (Decides...):  {rule_counts['R2']:,}")
print(f"  R3 'Rule 77' + Registrar/Done in...:  {rule_counts['R3']:,}")

# Distribution by target section
target_counts = {"Operative Part": 0, "Operative part": 0}
for tgt in relabels.values():
    target_counts[tgt] += 1
print(f"\nTarget breakdown:")
print(f"  Just Satisfaction → Operative Part:  {target_counts['Operative Part']:,}")
print(f"  Just Satisfaction → Operative part:  {target_counts['Operative part']:,}")

# Spot check
print("\n=== SPOT CHECK: 5 examples per rule ===")
shown = {"R1": 0, "R2": 0, "R3": 0}
cur.execute("""
    SELECT rowid, case_id, substr(text, 1, 200) AS t
    FROM paragraphs WHERE section = 'Just Satisfaction'
""")
for r in cur.fetchall():
    rule = detect(r["t"])
    if rule and shown[rule] < 3:
        target = relabels.get(r["rowid"], "?")
        print(f"  [{rule}] case={r['case_id']} → {target}")
        print(f"    text: {r['t'][:150]}")
        shown[rule] += 1
    if all(v >= 3 for v in shown.values()):
        break

# Verify against the 3 audit examples
print("\n=== Verifying against audit examples ===")
audit_rowids = [72047, 1703182, 1961353]
for rid in audit_rowids:
    cur.execute("SELECT case_id, section, substr(text, 1, 120) FROM paragraphs WHERE rowid=?", (rid,))
    r = cur.fetchone()
    if r is None:
        print(f"  rowid={rid}: not found")
        continue
    tgt = relabels.get(rid, "(NOT CAUGHT)")
    print(f"  rowid={rid} [{r[1]}]: {r[2]}")
    print(f"    → would be relabeled to: {tgt}")

if DRY_RUN:
    print("\nDRY-RUN — no changes written. Run with --apply to commit.")
    conn.close()
    sys.exit(0)

# === APPLY ===
print("\nAPPLYING...")
cur.execute("DROP TABLE IF EXISTS _p13_backup")
rowid_list = list(relabels.keys())
cur.execute(f"""
    CREATE TABLE _p13_backup AS
    SELECT rowid, section FROM paragraphs
    WHERE rowid IN ({','.join(str(r) for r in rowid_list)})
""")
print(f"Backup _p13_backup: {cur.execute('SELECT COUNT(*) FROM _p13_backup').fetchone()[0]:,} rows")

# Group by target
by_t = {}
for rid, tgt in relabels.items():
    by_t.setdefault(tgt, []).append(rid)

conn.execute("BEGIN")
total = 0
for tgt, rowids in by_t.items():
    BATCH = 9000
    for start in range(0, len(rowids), BATCH):
        batch = rowids[start:start+BATCH]
        conn.execute(
            f"UPDATE paragraphs SET section = ? WHERE rowid IN ({','.join(str(r) for r in batch)})",
            (tgt,)
        )
        total += len(batch)
conn.commit()
print(f"COMMITTED. {total:,} paragraphs relabeled.")

# Also update numbering_block for moved paragraphs
print("Updating numbering_block for moved rows (operative_dispositif)...")
conn.execute("BEGIN")
for start in range(0, len(rowid_list), 9000):
    batch = rowid_list[start:start+9000]
    conn.execute(
        f"UPDATE paragraphs SET numbering_block = 'operative_dispositif' "
        f"WHERE rowid IN ({','.join(str(r) for r in batch)})"
    )
conn.commit()

cur.execute("SELECT COUNT(*) FROM paragraphs WHERE section = 'Operative Part'")
print(f"\n  Operative Part total now: {cur.fetchone()[0]:,}")
cur.execute("SELECT COUNT(*) FROM paragraphs WHERE section = 'Operative part'")
print(f"  Operative part total now: {cur.fetchone()[0]:,}")
cur.execute("SELECT COUNT(*) FROM paragraphs WHERE section = 'Just Satisfaction'")
print(f"  Just Satisfaction total now: {cur.fetchone()[0]:,}")

conn.close()
print("\nDONE.")
