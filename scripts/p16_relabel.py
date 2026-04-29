"""
P16 RELABEL: Facts / Facts Proceedings / Facts Background → JS or Operative
in Pop C compressed cases.

Recall-audit Rec-3 + post-P14/P15 probe found that Pop C (Committee /
mass cases, NULL para_idx) compressed-format judgments dumped the entire
JS reasoning + operative dispositif into the `Facts` block. P4 and P7
already moved boundary-marked content (`ALLEGED VIOLATION`, `JOINDER`)
to Merits / JS, but the operative dispositif and JS award reasoning
that follow are still in `Facts`.

Six tight rules, applied in order. All anchors are precision-first
(immune to FP in Facts narrative because the exact phrasings are
unique to ECHR dispositif / JS reasoning):

  R0a — `APPLICATION OF ARTICLE 41` heading → Just Satisfaction
        Pattern: ^\\s*(?:[IVX]+\\.\\s+)?APPLICATION\\s+OF\\s+ARTICLE\\s+41
        Length: < 200

  R0b — `Article 41 ... provides:` boilerplate quote → Just Satisfaction
        Pattern: Article\\s+41\\s+of\\s+the\\s+Convention\\s+provides
        Length: < 800

  R1 — Numbered dispositif clause → Operative Part / Operative part
       Pattern: ^\\s*\\d+\\.\\s*(Holds|Decides|Declares|Dismisses)\\b
       NO length cap (Pop A pre-1998 fused-paragraph operative blocks)

  R2 — Operative payment clause → Operative
       Pattern: \\(a\\)\\s*that\\s+the\\s+respondent\\s+State\\s+is\\s+to\\s+pay
       Length: < 1500
       This exact phrasing only appears in ECHR operative dispositif;
       domestic court awards use different formats.

  R3 — Default-interest continuation → Operative
       Pattern: \\(b\\)\\s*that\\s+from\\s+the\\s+expiry\\s+of\\s+the\\s+above-mentioned\\s+three\\s+months
                AND simple\\s+interest\\s+shall\\s+be\\s+payable
       Length: < 700

  R4 — ECHR Court awards + currency → Just Satisfaction
       Pattern: \\b(Court\\s+awards|the\\s+Court\\s+considers\\s+it\\s+reasonable\\s+to\\s+award)\\b
                AND (EUR\\s*\\d|non-?pecuniary\\s+damage|costs\\s+and\\s+expenses)
       Length: < 600
       Restriction: Pop C only (para_idx IS NULL) — in Pop A/B,
       narrative may describe domestic court awards.

Skip rules:
  - Pop A/B paragraphs with R4 markers (handled by P1/P6/etc.; FP risk
    in Facts narrative)
  - "Equitable basis" + EUR alone — too risky, Italian/Bulgarian
    Court of Appeal narrative uses same formula

Per-case operative casing mirrored (Operative Part vs Operative part).

Usage:
  python p16_relabel.py            # dry-run
  python p16_relabel.py --apply    # commit
"""
import sqlite3
import sys
import re

DRY_RUN = "--apply" not in sys.argv
DB = "/data/echr_search.db"

# Patterns
R0A_HEADING = re.compile(r"^\s*(?:[IVX]+\.\s+)?APPLICATION\s+OF\s+ARTICLE\s+41", re.IGNORECASE)
R0B_PROVIDES = re.compile(r"Article\s+41\s+of\s+the\s+Convention\s+provides", re.IGNORECASE)
R1_NUMBERED = re.compile(r"^\s*\d+\.\s*(Holds|Decides|Declares|Dismisses)\b", re.IGNORECASE)
R2_PAY = re.compile(r"\(a\)\s*that\s+the\s+respondent\s+State\s+is\s+to\s+pay", re.IGNORECASE)
R3_INTEREST_HEAD = re.compile(r"\(b\)\s*that\s+from\s+the\s+expiry\s+of\s+the\s+above-mentioned\s+three\s+months", re.IGNORECASE)
R3_INTEREST_BODY = re.compile(r"simple\s+interest\s+shall\s+be\s+payable", re.IGNORECASE)
R4_AWARDS = re.compile(r"\b(Court\s+awards|the\s+Court\s+considers\s+it\s+reasonable\s+to\s+award)\b", re.IGNORECASE)
R4_CURRENCY = re.compile(r"\b(EUR\s*\d|non-?pecuniary\s+damage|costs\s+and\s+expenses)\b", re.IGNORECASE)

def classify(text, para_idx):
    """Return target section label or None.

    For operative targets returns 'operative' placeholder; caller resolves
    per-case casing. For JS returns 'Just Satisfaction'.
    """
    if not text:
        return None
    t = text.strip()
    L = len(t)

    # R0a: heading
    if L < 200 and R0A_HEADING.match(t):
        return "Just Satisfaction"

    # R0b: boilerplate quote
    if L < 800 and R0B_PROVIDES.search(t):
        return "Just Satisfaction"

    # R1: numbered dispositif
    if R1_NUMBERED.match(t):
        return "operative"

    # R2: operative payment clause "(a) that the respondent State is to pay..."
    if L < 1500 and R2_PAY.search(t):
        return "operative"

    # R3: default-interest continuation "(b) that from the expiry..."
    if L < 700 and R3_INTEREST_HEAD.search(t) and R3_INTEREST_BODY.search(t):
        return "operative"

    # R4: ECHR Court awards reasoning. Pop C only (para_idx IS NULL).
    if para_idx is None and L < 600 and R4_AWARDS.search(t) and R4_CURRENCY.search(t):
        return "Just Satisfaction"

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

print("Scanning Facts / Facts Proceedings / Facts Background...")
cur.execute("""
    SELECT rowid, case_id, section, para_idx, text FROM paragraphs
    WHERE section IN ('Facts', 'Facts Proceedings', 'Facts Background')
""")

relabels = {}
target_counts = {"Just Satisfaction": 0, "Operative Part": 0, "Operative part": 0}
rule_counts = {"R0a_heading": 0, "R0b_provides": 0, "R1_numbered": 0, "R2_pay": 0, "R3_interest": 0, "R4_awards": 0}

for r in cur.fetchall():
    target = classify(r["text"], r["para_idx"])
    if target is None:
        continue

    # Resolve operative casing
    final_target = target
    if target == "operative":
        # Default to lowercase for Pop C cases (no para_idx); fallback to Operative Part
        if r["para_idx"] is None:
            final_target = operative_casing.get(r["case_id"], "Operative part")
        else:
            final_target = operative_casing.get(r["case_id"], "Operative Part")

    relabels[r["rowid"]] = final_target
    target_counts[final_target] += 1

    # Tally rules (re-detect for stats)
    t = (r["text"] or "").strip()
    L = len(t)
    if L < 200 and R0A_HEADING.match(t):
        rule_counts["R0a_heading"] += 1
    elif L < 800 and R0B_PROVIDES.search(t):
        rule_counts["R0b_provides"] += 1
    elif R1_NUMBERED.match(t):
        rule_counts["R1_numbered"] += 1
    elif L < 1500 and R2_PAY.search(t):
        rule_counts["R2_pay"] += 1
    elif L < 700 and R3_INTEREST_HEAD.search(t) and R3_INTEREST_BODY.search(t):
        rule_counts["R3_interest"] += 1
    else:
        rule_counts["R4_awards"] += 1

print(f"\nTotal candidates: {len(relabels):,}")
for k, v in rule_counts.items():
    print(f"  {k}: {v:,}")
print(f"\nTarget breakdown:")
for tgt, n in target_counts.items():
    print(f"  → {tgt}: {n:,}")

# Spot check 4 per rule
import random
random.seed(99)
print("\n=== Spot check ===")
buckets = {}
for rid, tgt in relabels.items():
    cur.execute("SELECT case_id, section, para_idx, length(text) AS L, substr(text,1,250) AS p FROM paragraphs WHERE rowid=?", (rid,))
    row = cur.fetchone()
    cur.execute("SELECT text FROM paragraphs WHERE rowid=?", (rid,))
    text_full = (cur.fetchone()[0] or "").strip()
    L = len(text_full)
    # Determine which rule fired
    if L < 200 and R0A_HEADING.match(text_full): rule = "R0a"
    elif L < 800 and R0B_PROVIDES.search(text_full): rule = "R0b"
    elif R1_NUMBERED.match(text_full): rule = "R1"
    elif L < 1500 and R2_PAY.search(text_full): rule = "R2"
    elif L < 700 and R3_INTEREST_HEAD.search(text_full) and R3_INTEREST_BODY.search(text_full): rule = "R3"
    else: rule = "R4"
    buckets.setdefault(rule, []).append((rid, tgt, row["case_id"], row["L"], row["p"]))

for rule in ["R0a", "R0b", "R1", "R2", "R3", "R4"]:
    items = buckets.get(rule, [])
    if not items: continue
    sample_n = min(4, len(items))
    print(f"\n--- {rule} ({len(items):,} hits, showing {sample_n}) ---")
    for rid, tgt, cid, L, p in random.sample(items, sample_n):
        print(f"  [{rid} → {tgt}] case={cid} len={L}")
        print(f"  {p}")

if DRY_RUN:
    print("\nDRY-RUN — no changes written. Run with --apply to commit.")
    conn.close()
    sys.exit(0)

# === APPLY ===
print("\nAPPLYING...")
cur.execute("DROP TABLE IF EXISTS _p16_backup")
rowid_list = list(relabels.keys())
# Backup in chunks (large list — must avoid SQLite IN-list overflow)
cur.execute("CREATE TABLE _p16_backup (rowid INTEGER PRIMARY KEY, section TEXT, numbering_block TEXT)")
BATCH = 5000
for start in range(0, len(rowid_list), BATCH):
    chunk = rowid_list[start:start+BATCH]
    cur.execute(f"""
        INSERT INTO _p16_backup (rowid, section, numbering_block)
        SELECT rowid, section, numbering_block FROM paragraphs
        WHERE rowid IN ({','.join(str(r) for r in chunk)})
    """)
conn.commit()  # commit backup before starting apply transaction
print(f"Backup _p16_backup: {cur.execute('SELECT COUNT(*) FROM _p16_backup').fetchone()[0]:,} rows")

# Group by target
by_t = {}
for rid, tgt in relabels.items():
    by_t.setdefault(tgt, []).append(rid)

conn.execute("BEGIN")
total = 0
for tgt, rowids in by_t.items():
    new_block = "operative_dispositif" if tgt in ("Operative Part", "Operative part") else "main_judgment"
    for start in range(0, len(rowids), BATCH):
        batch = rowids[start:start+BATCH]
        conn.execute(
            f"UPDATE paragraphs SET section = ?, numbering_block = ? WHERE rowid IN ({','.join(str(r) for r in batch)})",
            (tgt, new_block)
        )
        total += len(batch)
conn.commit()
print(f"COMMITTED. {total:,} paragraphs relabeled.")

print("\n=== Final counts ===")
for sec in ("Facts", "Facts Proceedings", "Facts Background", "Just Satisfaction", "Operative Part", "Operative part"):
    cur.execute("SELECT COUNT(*) FROM paragraphs WHERE section=?", (sec,))
    print(f"  {sec:<28} {cur.fetchone()[0]:>10,}")

conn.close()
print("DONE.")
