"""
P14 RELABEL: clean up Relevant legal framework — three target sections.

Recall audit (Pattern A, recall-audit.md) found that RLF paragraphs
contain three different misclassified content types, not just one:

  Should-be       Audit examples
  ─────────────   ─────────────────────────────────────────────────────
  Merits          rowid 1540851, 1456499, 1695553, 1877956
                  ("It follows that there has been a violation...",
                   proportionality analyses, Court's assessment)
  Just Satisfaction rowid 1971871
                    (equitable JS award)
  Operative Part  rowid 1965493
                  (numbered operative clause)

A naive "RLF → Merits" rule would have ~25-37% precision (probe of 8
random flagged showed dispositif + JS + Merits all mixed). P14 uses
three precise rules instead, applied in order (Operative checked
first because it has the cleanest signal).

Detection rules (paragraph in 'Relevant legal framework'):

  R1 — Operative Part / Operative part (dispositif clauses)
       Pattern: ^\\s*\\d+\\.\\s*(Holds|Decides|Declares|Dismisses)\\b
       Length: < 400
       The dispositif format is unambiguous — numbered clause + verb.

  R2 — Just Satisfaction (award reasoning)
       Pattern: contains ("Court awards" OR "the Court awards") AND
                contains (EUR, euros, currency in respect of) AND
                NOT operative dispositif (no R1 match)
       Length: < 800

  R3 — Merits (violation finding / Court's substantive assessment)
       Pattern: contains violation finding language with reasoning
                ("there has been a violation", "Court concludes",
                "It follows that", proportionality discussion)
       NOT R1 / NOT R2 caught.
       Length: >= 150 (genuine reasoning paragraphs are not short)
       NOT a citation of prior judgment ("see X v. Y, no. NNN/NN")

Conservative — does NOT propagate forward. Each paragraph judged on
its own merits.

Usage:
  python p14_relabel.py            # dry-run
  python p14_relabel.py --apply    # commit
"""
import sqlite3
import sys
import re

DRY_RUN = "--apply" not in sys.argv
DB = "/data/echr_search.db"

# R0: Article 41 boilerplate quote — these paragraphs are part of the
# canonical Just Satisfaction introduction ("Article 41 of the Convention
# provides..." / "If the Court finds that there has been a violation of
# the Convention..."). Always JS, regardless of other content.
# This MUST be checked before R3 because the boilerplate contains
# "there has been a violation" which would otherwise trigger R3 → Merits.
R0_BOILERPLATE = re.compile(
    r"(Article\s+41\s+of\s+the\s+Convention\s+provides|"
    r"If\s+the\s+Court\s+finds\s+that\s+there\s+has\s+been\s+a\s+violation\s+of\s+the\s+Convention)",
    re.IGNORECASE,
)

# R1: Operative dispositif format (numbered Holds/Decides/Declares/Dismisses).
R1 = re.compile(r"^\s*\d+\.\s*(Holds|Decides|Declares|Dismisses)\b", re.IGNORECASE)

# R2: Just Satisfaction award language. Must have BOTH the Court-awards verb
# AND a currency/damage reference.
R2_AWARDS = re.compile(r"\b(Court\s+awards|the\s+Court\s+considers\s+it\s+reasonable\s+to\s+award)\b", re.IGNORECASE)
R2_DAMAGE = re.compile(r"\b(EUR|euros?|in\s+respect\s+of\s+(?:non-)?pecuniary|costs\s+and\s+expenses)\b", re.IGNORECASE)

# R3: Merits substantive assessment. TIGHT version — explicit violation
# finding only, no broader "assessment" / "proportionality" patterns
# (those produced JS-content false positives in dry-run).
R3_VIOLATION = re.compile(
    r"(there\s+has\s+been\s+(?:no\s+)?(?:a\s+)?violation\s+of\s+Article|"
    r"It\s+follows\s+that\s+there\s+has\s+been\s+(?:no\s+)?(?:a\s+)?violation|"
    r"the\s+Court\s+(?:concludes?|finds)\s+that\s+there\s+has\s+been|"
    r"finds?\s+(?:no\s+)?(?:a\s+)?violation\s+of\s+Article)",
    re.IGNORECASE,
)

# Citation pattern — when a paragraph is mostly a citation of prior judgments,
# it's likely legitimate RLF (cited as legal framework / prior case-law).
# Skip relabeling these.
CITATION_HEAVY = re.compile(
    r"\bsee\s+[A-Z][a-zA-Z\-']+\s+v\.\s+[A-Z]",  # "see X v. Y"
    re.IGNORECASE,
)
CASE_NUMBER = re.compile(r"\b(no\.\s*\d{1,5}/\d{2}|nos?\.\s*\d{1,5}/\d{2})", re.IGNORECASE)

# Fused multi-clause dispositif (PDF-extraction artefact).
# A paragraph that contains TWO+ dispositif verbs at sentence boundaries is
# likely several operative clauses concatenated. Hard to classify cleanly
# (mix of Operative + JS + Admissibility content). Skip — leave in RLF for
# manual review.
FUSED_DISPOSITIF = re.compile(
    r"(?:^|[.;]\s+)(Holds|Decides|Declares|Dismisses)\s+(?:that|to|by\s+)",
    re.IGNORECASE,
)

# Looser dispositif marker — catches "Declares the complaint admissible",
# "Decides to strike", "Dismisses the remainder", etc. Used together with
# JS award marker to detect mixed JS-then-operative paragraphs.
DISPOSITIF_LOOSE = re.compile(
    r"(?:^|[.;]\s+)(Holds|Decides|Declares|Dismisses)\b",
    re.IGNORECASE,
)
# JS-award token (any award/equity reference suggesting paragraph contains
# Just Satisfaction reasoning). Broader than R2_AWARDS — used only to
# detect mixed paragraphs in conjunction with dispositif marker.
JS_TOKEN = re.compile(
    r"\b(awards?\s+(?:the\s+)?(?:applicants?|her|him|them|EUR)|"
    r"non-?pecuniary\s+damage|"
    r"in\s+respect\s+of\s+(?:non-)?pecuniary|"
    r"Court\s+considers\s+it\s+reasonable\s+to\s+award|"
    r"costs\s+and\s+expenses)",
    re.IGNORECASE,
)

MAX_LEN_R1 = 400
MAX_LEN_R2 = 800
MIN_LEN_R3 = 80   # violation finding paragraphs can be short; "There has been a violation" alone is ~30 chars

def classify(text):
    """Return target section, or None if no clean match."""
    if not text:
        return None
    t = text.strip()
    L = len(t)

    # R0 (NEW): Article 41 boilerplate quote → Just Satisfaction
    # Must be checked BEFORE R3 because the boilerplate contains
    # "there has been a violation of the Convention" which would
    # otherwise trigger R3 → Merits (false positive — these
    # paragraphs are the JS section opener, not Merits content).
    if R0_BOILERPLATE.search(t):
        # Only relabel as JS if reasonable length (boilerplate paragraphs
        # are usually < 600 chars — the canonical Article 41 quote is ~400)
        if L < 800:
            return "Just Satisfaction"

    # R1: numbered dispositif (highest precision)
    if L < MAX_LEN_R1 and R1.match(t):
        return "operative"  # placeholder — will resolve casing per case

    # R2: Just Satisfaction award
    if L < MAX_LEN_R2 and R2_AWARDS.search(t) and R2_DAMAGE.search(t):
        # Avoid R1 overlap
        if not R1.match(t):
            return "Just Satisfaction"

    # R3: Merits — violation finding (tight pattern only).
    if L >= MIN_LEN_R3 and R3_VIOLATION.search(t):
        # Skip if heavy citation (likely RLF citing case-law, not Merits content)
        if CITATION_HEAVY.search(t) and CASE_NUMBER.search(t) and L < 400:
            return None
        # Skip if fused multi-clause dispositif (PDF artefact — has 2+ Holds/Decides/Declares
        # at sentence boundaries). These mix Merits + JS + Operative content and can't be
        # cleanly assigned a single label. Better to leave in RLF for human review.
        fused_matches = FUSED_DISPOSITIF.findall(t)
        if len(fused_matches) >= 2:
            return None
        # Skip if paragraph mixes JS award content with operative dispositif tail
        # (e.g. "...awards her EUR 12,500. Declares the complaint admissible; Holds...").
        # These paragraphs have a violation finding but are mostly JS+Operative content
        # — can't be cleanly labelled Merits.
        if JS_TOKEN.search(t) and DISPOSITIF_LOOSE.search(t):
            return None
        return "Merits"

    return None

if DRY_RUN:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
else:
    conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# Per-case operative casing preference (mirror existing operative section)
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

# Walk RLF paragraphs
print("Scanning Relevant legal framework paragraphs...")
cur.execute("""
    SELECT rowid, case_id, text FROM paragraphs
    WHERE section = 'Relevant legal framework'
""")
relabels = {}
target_counts = {"Merits": 0, "Just Satisfaction": 0, "Operative Part": 0, "Operative part": 0}
rule_counts = {"R1_operative": 0, "R2_js": 0, "R3_merits": 0}

for r in cur.fetchall():
    target = classify(r["text"])
    if target is None:
        continue
    if target == "operative":
        target = operative_casing.get(r["case_id"], "Operative Part")
        rule_counts["R1_operative"] += 1
    elif target == "Just Satisfaction":
        rule_counts["R2_js"] += 1
    elif target == "Merits":
        rule_counts["R3_merits"] += 1
    relabels[r["rowid"]] = target
    target_counts[target] += 1

print(f"\nTotal candidates: {len(relabels):,}")
print(f"  R1 (→ Operative): {rule_counts['R1_operative']:,}")
print(f"  R2 (→ Just Satisfaction): {rule_counts['R2_js']:,}")
print(f"  R3 (→ Merits): {rule_counts['R3_merits']:,}")
print()
print(f"Target breakdown:")
for tgt, n in target_counts.items():
    print(f"  → {tgt}: {n:,}")

# Verify against audit examples
print("\n=== Verifying against recall-audit examples ===")
audit_rowids = {
    1540851: "Merits",
    1456499: "Merits",
    1877956: "Merits",
    1695553: "Merits",
    1971871: "Just Satisfaction",
    1965493: "Operative Part / Operative part",
}
for rid, expected in audit_rowids.items():
    cur.execute("SELECT case_id, section, substr(text, 1, 100) FROM paragraphs WHERE rowid=?", (rid,))
    r = cur.fetchone()
    if r is None:
        print(f"  rowid={rid}: not found")
        continue
    actual = relabels.get(rid, "(NOT CAUGHT)")
    match = "✓" if expected.split(" / ")[0] in str(actual) else "✗"
    print(f"  rowid={rid} expected={expected:<30} actual={actual:<22} {match}")
    print(f"    text: {r[2]}")

# Spot check 5 per rule
print("\n=== Spot check: 3 per rule ===")
shown = {"Merits": 0, "Just Satisfaction": 0, "Operative Part": 0, "Operative part": 0}
sampled = []
for rid, tgt in relabels.items():
    if shown[tgt] < 3:
        cur.execute("SELECT case_id, substr(text,1,180) FROM paragraphs WHERE rowid=?", (rid,))
        r = cur.fetchone()
        sampled.append((tgt, r[0], rid, r[1]))
        shown[tgt] += 1
    if all(v >= 3 for v in shown.values()):
        break

for tgt, cid, rid, t in sorted(sampled, key=lambda x: x[0]):
    print(f"\n  → {tgt} | rowid={rid} | case={cid}")
    print(f"  {t}")

if DRY_RUN:
    print("\nDRY-RUN — no changes written. Run with --apply to commit.")
    conn.close()
    sys.exit(0)

# === APPLY ===
print("\nAPPLYING...")
cur.execute("DROP TABLE IF EXISTS _p14_backup")
rowid_list = list(relabels.keys())
cur.execute(f"""
    CREATE TABLE _p14_backup AS
    SELECT rowid, section, numbering_block FROM paragraphs
    WHERE rowid IN ({','.join(str(r) for r in rowid_list)})
""")
print(f"Backup _p14_backup: {cur.execute('SELECT COUNT(*) FROM _p14_backup').fetchone()[0]:,} rows")

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
        # Update section
        conn.execute(
            f"UPDATE paragraphs SET section = ? WHERE rowid IN ({','.join(str(r) for r in batch)})",
            (tgt,)
        )
        # Update numbering_block to match new section
        new_block = "operative_dispositif" if tgt in ("Operative Part", "Operative part") else "main_judgment"
        conn.execute(
            f"UPDATE paragraphs SET numbering_block = ? WHERE rowid IN ({','.join(str(r) for r in batch)})",
            (new_block,)
        )
        total += len(batch)
conn.commit()
print(f"COMMITTED. {total:,} paragraphs relabeled.")

print("\n=== Final counts ===")
for sec in ("Relevant legal framework", "Merits", "Just Satisfaction", "Operative Part", "Operative part"):
    cur.execute("SELECT COUNT(*) FROM paragraphs WHERE section=?", (sec,))
    print(f"  {sec:<28} {cur.fetchone()[0]:>10,}")

conn.close()
print("DONE.")
