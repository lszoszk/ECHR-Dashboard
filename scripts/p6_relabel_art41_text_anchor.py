"""
P6 RELABEL: Article 41 reasoning anchored on canonical text quote.

After P5, ~770 Population C cases still have the literal Article 41
introduction sentence ("Article 41 of the Convention provides...") in
their Facts section. These cases lack a Just Satisfaction anchor
paragraph from P1, so P5's mode-switch logic didn't fire.

P6 uses the canonical Article 41 quote as a TEXT anchor: when a Facts
paragraph in Pop C contains:

  "Article 41 of the Convention provides"

we treat it as a Just-Satisfaction-mode trigger, relabel that paragraph,
and propagate the active mode forward through subsequent Facts
paragraphs until the block ends (same termination logic as P5).

Walks Population C only.

Usage:
  python p6_relabel_art41_text_anchor.py            # dry-run
  python p6_relabel_art41_text_anchor.py --apply    # commit
"""
import sqlite3
import sys
import re

DRY_RUN = "--apply" not in sys.argv
DB = "/data/echr_search.db"

# Anchor text: appears in the canonical Article 41 introduction paragraph
ANCHOR_RE = re.compile(
    r"Article\s+41\s+of\s+the\s+Convention\s+provides",
    re.IGNORECASE,
)

# Block ender: dispositif (operative dispositif sentences)
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
SOURCE_SECTION = "Facts"
TARGET = "Just Satisfaction"

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

# Find candidate cases: Pop C cases with Article 41 quote in Facts
cur.execute("""
    SELECT DISTINCT case_id FROM paragraphs
    WHERE para_idx IS NULL
      AND section = 'Facts'
      AND text LIKE '%Article 41 of the Convention provides%'
""")
candidate_cases = [r[0] for r in cur.fetchall()]
print(f"Candidate cases (Pop C with Article 41 quote in Facts): {len(candidate_cases):,}")

relabels = {}
trigger_count = 0
continuation_count = 0

cur2 = conn.cursor()
for i, case_id in enumerate(candidate_cases):
    if i % 200 == 0 and i > 0:
        print(f"  ... {i:,} / {len(candidate_cases):,}")
    cur2.execute("""
        SELECT rowid, section, text FROM paragraphs
        WHERE case_id=? AND para_idx IS NULL
        ORDER BY rowid
    """, (case_id,))
    paras = cur2.fetchall()

    active = False
    interrupt_count = 0

    for p in paras:
        sec = p["section"]
        text = p["text"] or ""
        rowid = p["rowid"]

        # Hard end
        if sec in HARD_ENDERS:
            active = False
            interrupt_count = 0
            continue
        if is_block_ender(text):
            active = False
            interrupt_count = 0
            continue

        # Already in Just Satisfaction (e.g. from P1) — ride along (don't end)
        if sec == TARGET:
            active = True
            interrupt_count = 0
            continue

        # Trigger detection: Facts paragraph containing the Article 41 quote
        if sec == SOURCE_SECTION and ANCHOR_RE.search(text):
            relabels[rowid] = TARGET
            active = True
            interrupt_count = 0
            trigger_count += 1
            continue

        if not active:
            continue

        # Active and we see source section → relabel
        if sec == SOURCE_SECTION:
            relabels[rowid] = TARGET
            interrupt_count = 0
            continuation_count += 1
            continue

        # Soft interruption
        if sec in SOFT_INTERRUPT:
            interrupt_count += 1
            if interrupt_count > MAX_INTERRUPTION:
                active = False
                interrupt_count = 0
            continue

        # Anything else — end block
        active = False
        interrupt_count = 0

print(f"\nTotal relabel rowids: {len(relabels):,}")
print(f"  Direct triggers (Article 41 quote): {trigger_count:,}")
print(f"  Continuations:                       {continuation_count:,}")

# Distribution check
if relabels:
    rowid_list = list(relabels.keys())
    BATCH = 9000
    move_counter = {}
    for start in range(0, len(rowid_list), BATCH):
        batch = rowid_list[start:start+BATCH]
        cur.execute(
            "SELECT rowid, section FROM paragraphs WHERE rowid IN ({})".format(
                ",".join(str(r) for r in batch)
            )
        )
        for r in cur.fetchall():
            old = r["section"]
            key = f"{old} → {TARGET}"
            move_counter[key] = move_counter.get(key, 0) + 1
    print("\nMoves:")
    for k, v in sorted(move_counter.items(), key=lambda x: -x[1]):
        print(f"  {v:>7,}  {k}")

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
        marker = f" → {new} (P6)" if new else ""
        print(f"    [{p['section']:<22}{marker:<26}] {p['t']}")

if DRY_RUN:
    print("\nDRY-RUN — no changes written. Run with --apply to commit.")
    conn.close()
    sys.exit(0)

# APPLY
print("\nAPPLYING...")
cur.execute("DROP TABLE IF EXISTS _p6_backup")
cur.execute(f"""
    CREATE TABLE _p6_backup AS
    SELECT rowid, section FROM paragraphs
    WHERE rowid IN ({','.join(str(r) for r in relabels.keys())})
""")
print(f"Backup _p6_backup: {cur.execute('SELECT COUNT(*) FROM _p6_backup').fetchone()[0]:,} rows")

rowid_list = list(relabels.keys())
BATCH = 9000
conn.execute("BEGIN")
total = 0
for start in range(0, len(rowid_list), BATCH):
    batch = rowid_list[start:start+BATCH]
    conn.execute(
        f"UPDATE paragraphs SET section = ? WHERE rowid IN ({','.join(str(r) for r in batch)})",
        (TARGET,)
    )
    total += len(batch)
conn.commit()
print(f"COMMITTED. {total:,} paragraphs relabeled to Just Satisfaction.")

cur.execute("SELECT COUNT(*) FROM paragraphs WHERE section='Just Satisfaction'")
print(f"'Just Satisfaction' total: {cur.fetchone()[0]:,}")
conn.close()
print("DONE.")
