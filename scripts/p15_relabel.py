"""
P15 RELABEL: Just Satisfaction → Operative Part residual cleanup.

Rec-2 from recall-audit.md. P13 already targeted dispositif content in
JS but capped at 400 chars and only treated paragraphs in numbering_block
= operative_dispositif. The recall audit and post-P13 probe surface
~579 residual paragraphs in JS that are clearly Operative content but
were missed by P13:

  - 81 numbered Holds/Decides/Declares/Dismisses paragraphs in
    numbering_block = main_judgment (P13 only relabeled
    operative_dispositif block)
  - 498 signature-block paragraphs (Rule 77 + Registrar/Done in)
    in long fused-paragraph form (Pop A pre-1998 classical format
    where the entire dispositif was extracted as one paragraph
    > 400 chars).

Conservative — does NOT propagate forward. Each paragraph judged on
its own merits.

Detection rules (paragraph in 'Just Satisfaction'):

  R1 — numbered dispositif clause:
       ^\\s*\\d+\\.\\s*(Holds|Decides|Declares|Dismisses)\\b
       NO length cap (Pop A operative paragraphs are often very long
       because the entire dispositif was extracted as one fused block).
       Risk: low — this format is the canonical operative dispositif.
       JS reasoning paragraphs are not numbered with these verbs.

  R2 — signature / closing block (when R1 did not match):
       Contains BOTH (Rule 77 OR Rules of Court reference)
       AND (Registrar OR "Done in [Lang]")
       AND length < 700
       Risk: low — these tokens appear together only in operative
       closings.

Skip:
  - Long paragraphs (> 700 chars) without R1 match are skipped under
    R2 because they may be JS reasoning that quotes the operative
    closing (rare but possible).
  - We do NOT expand to paragraphs that just contain "Holds" mid-text
    (false positives in JS analysis).

Per-case operative casing is mirrored (Operative Part vs Operative part)
matching the existing per-case label.

Usage:
  python p15_relabel.py            # dry-run
  python p15_relabel.py --apply    # commit
"""
import sqlite3
import sys
import re

DRY_RUN = "--apply" not in sys.argv
DB = "/data/echr_search.db"

# R1: numbered dispositif clause anchor
R1 = re.compile(r"^\s*\d+\.\s*(Holds|Decides|Declares|Dismisses)\b", re.IGNORECASE)

# R2 components — STRICT 'Rule 77' anchor only (NOT generic 'Rules of Court').
# The generic 'Rules of Court' pattern matches JS reasoning paragraphs that
# cite Rule 60 (just satisfaction submission), Rule 38 (evidence), Rule 61
# (third-party intervention) — not dispositif content. 'Rule 77' specifically
# governs delivery and signature, which only appears in operative closings.
R2_RULE77 = re.compile(r"\bRule\s*77\b", re.IGNORECASE)
R2_REG = re.compile(r"\bRegistrar\b", re.IGNORECASE)
R2_DONE = re.compile(r"\bDone in\s+(English|French|German|Spanish|Italian)", re.IGNORECASE)

# Length cap for R2 (signature block / continuation clauses) — long JS
# reasoning paragraphs that happen to mention Rule 77 (rare) should be
# excluded. Empirically all true positives are < 700 chars.
MAX_LEN_R2 = 700

def classify(text):
    """Return 'operative' or None."""
    if not text:
        return None
    t = text.strip()
    L = len(t)

    # R1 — numbered dispositif anchor (no length cap; long fused-operative
    # paragraphs are common in Pop A pre-1998 PDF extractions).
    if R1.match(t):
        return "operative"

    # R2 — signature/closing block (only short paragraphs, strict Rule 77)
    if L < MAX_LEN_R2 and R2_RULE77.search(t):
        if R2_REG.search(t) or R2_DONE.search(t):
            return "operative"

    return None

if DRY_RUN:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
else:
    conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# Per-case operative casing preference
cur.execute("""
    SELECT case_id,
           SUM(CASE WHEN section='Operative Part' THEN 1 ELSE 0 END) AS up,
           SUM(CASE WHEN section='Operative part' THEN 1 ELSE 0 END) AS lo
    FROM paragraphs
    WHERE section IN ('Operative Part', 'Operative part')
    GROUP BY case_id
""")
operative_casing = {}
for r in cur.fetchall():
    operative_casing[r["case_id"]] = "Operative Part" if r["up"] >= r["lo"] else "Operative part"

print("Scanning Just Satisfaction paragraphs...")
cur.execute("""
    SELECT rowid, case_id, text FROM paragraphs
    WHERE section = 'Just Satisfaction'
""")

relabels = {}
target_counts = {"Operative Part": 0, "Operative part": 0}
rule_counts = {"R1_numbered": 0, "R2_signature": 0}

for r in cur.fetchall():
    target = classify(r["text"])
    if target is None:
        continue
    # Resolve casing
    target = operative_casing.get(r["case_id"], "Operative Part")
    relabels[r["rowid"]] = target
    target_counts[target] += 1
    # Count rule (re-detect for stats)
    t = (r["text"] or "").strip()
    if R1.match(t):
        rule_counts["R1_numbered"] += 1
    else:
        rule_counts["R2_signature"] += 1

print(f"\nTotal candidates: {len(relabels):,}")
print(f"  R1 (numbered dispositif): {rule_counts['R1_numbered']:,}")
print(f"  R2 (signature block):     {rule_counts['R2_signature']:,}")
print(f"\nTarget casing breakdown:")
for tgt, n in target_counts.items():
    print(f"  → {tgt}: {n:,}")

# Spot check
print("\n=== Spot check: 6 R1 + 6 R2 ===")
shown_r1 = shown_r2 = 0
samples = []
for rid, tgt in relabels.items():
    cur.execute("SELECT case_id, length(text) AS L, substr(text,1,250) AS t FROM paragraphs WHERE rowid=?", (rid,))
    r = cur.fetchone()
    text_full = None
    cur.execute("SELECT text FROM paragraphs WHERE rowid=?", (rid,))
    text_full = cur.fetchone()[0] or ""
    is_r1 = bool(R1.match(text_full.strip()))
    if is_r1 and shown_r1 < 6:
        samples.append(("R1", tgt, rid, r["case_id"], r["L"], r["t"]))
        shown_r1 += 1
    elif not is_r1 and shown_r2 < 6:
        samples.append(("R2", tgt, rid, r["case_id"], r["L"], r["t"]))
        shown_r2 += 1
    if shown_r1 >= 6 and shown_r2 >= 6:
        break

for rule, tgt, rid, cid, L, t in samples:
    print(f"\n  {rule} → {tgt} | rowid={rid} case={cid} len={L}")
    print(f"  {t}")

if DRY_RUN:
    print("\nDRY-RUN — no changes written. Run with --apply to commit.")
    conn.close()
    sys.exit(0)

# === APPLY ===
print("\nAPPLYING...")
cur.execute("DROP TABLE IF EXISTS _p15_backup")
rowid_list = list(relabels.keys())
cur.execute(f"""
    CREATE TABLE _p15_backup AS
    SELECT rowid, section, numbering_block FROM paragraphs
    WHERE rowid IN ({','.join(str(r) for r in rowid_list)})
""")
print(f"Backup _p15_backup: {cur.execute('SELECT COUNT(*) FROM _p15_backup').fetchone()[0]:,} rows")

# Group by target casing
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
        # Move to operative_dispositif numbering block
        conn.execute(
            f"UPDATE paragraphs SET numbering_block = 'operative_dispositif' "
            f"WHERE rowid IN ({','.join(str(r) for r in batch)})"
        )
        total += len(batch)
conn.commit()
print(f"COMMITTED. {total:,} paragraphs relabeled.")

print("\n=== Final counts ===")
for sec in ("Just Satisfaction", "Operative Part", "Operative part"):
    cur.execute("SELECT COUNT(*) FROM paragraphs WHERE section=?", (sec,))
    print(f"  {sec:<28} {cur.fetchone()[0]:>10,}")

conn.close()
print("DONE.")
