"""
P7 RELABEL: glued JOINDER OF THE APPLICATIONS headings in Population C.

The segmenter sometimes glued the JOINDER section heading with the
following Court ruling sentence into a single paragraph (>120 chars,
so P4's heading detector skipped it):

  "I. JOINDER OF THE APPLICATIONS 47. In accordance with Rule 42 § 1
   of the Rules of Court, the Court decides to join the applications,
   given their factual and legal similarities."

Detection: paragraph starts with optional roman-numeral prefix +
"JOINDER OF THE APPLICATIONS". Conservative — does NOT detect
"ALLEGED VIOLATION" glued because the phrase commonly appears inline
in body text (e.g. "the alleged violation of the Convention").

Effect: relabel that paragraph + propagate Merits mode forward through
subsequent Facts paragraphs (same termination logic as P5).

Walks Population C only.

Usage:
  python p7_relabel_joinder_glued.py            # dry-run
  python p7_relabel_joinder_glued.py --apply    # commit
"""
import sqlite3
import sys
import re

DRY_RUN = "--apply" not in sys.argv
DB = "/data/echr_search.db"

# Trigger: paragraph STARTS with optional roman numeral + JOINDER OF THE APPLICATIONS
TRIGGER_RE = re.compile(
    r"^\s*(?:[IVX]+\.\s+)?JOINDER\s+OF\s+THE\s+APPLICATIONS\b",
    re.IGNORECASE,
)

# Block end patterns
END_RE = re.compile(
    r"(\b(FOR THESE REASONS|OPERATIVE PROVISIONS)\b)"
    r"|(^\s*\d+\.\s*(Decides|Declares|Holds)\b)",
    re.IGNORECASE,
)
HARD_ENDERS = frozenset({
    "Operative Part", "Operative part",
    "Separate Opinion", "Appendix", "Article 46",
})
SOFT_INTERRUPT = frozenset({"Admissibility"})
MAX_INTERRUPTION = 5
SOURCE = "Facts"
TARGET = "Merits"

# Trigger only on long paragraphs (glued case); short ones already
# handled by P4's heading detection.
MIN_LEN_FOR_GLUED = 120

def is_block_ender(text):
    if not text:
        return False
    return bool(END_RE.search(text))

if DRY_RUN:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
else:
    conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# Find candidate cases
cur.execute("""
    SELECT DISTINCT case_id FROM paragraphs
    WHERE para_idx IS NULL AND section = 'Facts'
      AND length(text) >= ?
      AND substr(upper(text), 1, 80) LIKE '%JOINDER OF THE APPLICATIONS%'
""", (MIN_LEN_FOR_GLUED,))
candidate_cases = [r[0] for r in cur.fetchall()]
print(f"Candidate cases: {len(candidate_cases):,}")

relabels = {}
trigger_count = 0
continuation_count = 0

cur2 = conn.cursor()
for case_id in candidate_cases:
    cur2.execute("""
        SELECT rowid, section, text FROM paragraphs
        WHERE case_id=? AND para_idx IS NULL
        ORDER BY rowid
    """, (case_id,))
    paras = cur2.fetchall()

    active_mode = None
    interrupt_count = 0

    for p in paras:
        sec = p["section"]
        text = p["text"] or ""
        rowid = p["rowid"]

        # Hard ends
        if sec in HARD_ENDERS:
            active_mode = None
            interrupt_count = 0
            continue
        if is_block_ender(text):
            active_mode = None
            interrupt_count = 0
            continue

        # Trigger detection (only for glued paragraphs, length >= 120)
        if (sec == SOURCE and len(text) >= MIN_LEN_FOR_GLUED
            and TRIGGER_RE.match(text)):
            relabels[rowid] = TARGET
            active_mode = TARGET
            interrupt_count = 0
            trigger_count += 1
            continue

        # Existing Merits/Just-Satisfaction paragraphs ride along
        if sec in ("Merits", "Just Satisfaction"):
            active_mode = sec
            interrupt_count = 0
            continue

        if active_mode is None:
            continue

        if sec == SOURCE:
            relabels[rowid] = active_mode
            interrupt_count = 0
            continuation_count += 1
            continue

        if sec in SOFT_INTERRUPT:
            interrupt_count += 1
            if interrupt_count > MAX_INTERRUPTION:
                active_mode = None
                interrupt_count = 0
            continue

        active_mode = None
        interrupt_count = 0

print(f"\nTotal relabel rowids: {len(relabels):,}")
print(f"  Direct triggers (glued JOINDER): {trigger_count:,}")
print(f"  Continuations:                    {continuation_count:,}")

# Distribution
if relabels:
    rowid_list = list(relabels.keys())
    BATCH = 9000
    by_target = {}
    for start in range(0, len(rowid_list), BATCH):
        batch = rowid_list[start:start+BATCH]
        for rid in batch:
            tgt = relabels[rid]
            by_target.setdefault(tgt, 0)
            by_target[tgt] += 1
    print("\nMoves by target:")
    for tgt, cnt in sorted(by_target.items(), key=lambda x: -x[1]):
        print(f"  {cnt:>6,}  Facts → {tgt}")

# Spot check
print("\n── SPOT CHECK: 2 cases ──")
sample_cases = []
for rid in relabels:
    cur.execute("SELECT case_id FROM paragraphs WHERE rowid=?", (rid,))
    cid = cur.fetchone()[0]
    if cid not in sample_cases:
        sample_cases.append(cid)
    if len(sample_cases) >= 2:
        break

for cid in sample_cases:
    cur.execute("SELECT title FROM cases WHERE case_id=?", (cid,))
    title = (cur.fetchone()[0] or "")[:60]
    print(f"\n  [{cid}] {title}")
    cur.execute("""
        SELECT rowid, section, substr(text,1,90) AS t
        FROM paragraphs WHERE case_id=? AND para_idx IS NULL
        ORDER BY rowid
    """, (cid,))
    for p in cur.fetchall():
        rid = p["rowid"]
        new = relabels.get(rid)
        marker = f" → {new} (P7)" if new else ""
        print(f"    [{p['section']:<22}{marker:<22}] {p['t']}")

if DRY_RUN:
    print("\nDRY-RUN — no changes written.")
    conn.close()
    sys.exit(0)

# APPLY
print("\nAPPLYING...")
cur.execute("DROP TABLE IF EXISTS _p7_backup")
cur.execute(f"""
    CREATE TABLE _p7_backup AS
    SELECT rowid, section FROM paragraphs
    WHERE rowid IN ({','.join(str(r) for r in relabels.keys())})
""")
print(f"Backup _p7_backup: {cur.execute('SELECT COUNT(*) FROM _p7_backup').fetchone()[0]:,} rows")

# group by target
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
conn.close()
print("DONE.")
