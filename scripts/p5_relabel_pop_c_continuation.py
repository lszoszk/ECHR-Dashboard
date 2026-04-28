"""
P5 RELABEL: continuation of merits/just-satisfaction blocks across
soft interruptions in Population C.

After P4, Pop C cases like Popova have this structure:

  [Facts]             4. The applicants are pensioners...               (genuine facts)
  [Facts → Merits]    II. ALLEGED VIOLATION OF ARTICLE 6  (P4 relabel)
  [Facts → Merits]    9. The applicants complained...     (P4 relabel)
  [Admissibility]     A. Admissibility 10. argued...
  [Facts]             11. arguments              ← STILL Facts, should be Merits
  [Facts]             12. Court notes...         ← STILL Facts, should be Merits
  [Facts]             B. Merits 13. ...          ← STILL Facts, should be Merits
  [Facts]             14. In present case...     ← STILL Facts, should be Merits
  [Facts]             15. It follows that...     ← STILL Facts, should be Merits
  [Just Satisfaction] III. APPLICATION OF ARTICLE 41   ← end Merits block
  [Facts]             16. Article 41 provides...       ← Article 41 reasoning (P6 territory)
  ...

P5 logic: walk each Pop C case by rowid. Trigger 'merits propagation' or
'just-satisfaction propagation' mode whenever we encounter a paragraph
ALREADY labeled Merits or Just Satisfaction (regardless of how it got
that label). Then for each subsequent Facts paragraph in the case,
relabel to the active target — provided the interruption (Admissibility)
is short (≤K=5).

Block ends when: hard-ender section appears (Operative Part/part,
Separate Opinion, Appendix, Article 46), or Just Satisfaction appears
(switches mode), or the active mode itself appears as section (no-op
relabel).

Walks Population C only (para_idx IS NULL).

Usage:
  python p5_relabel_pop_c_continuation.py            # dry-run
  python p5_relabel_pop_c_continuation.py --apply    # commit
"""
import sqlite3
import sys
import re

DRY_RUN = "--apply" not in sys.argv
DB = "/data/echr_search.db"

MAX_INTERRUPTION = 5  # consecutive Admissibility paragraphs allowed
SOURCE_SECTION = "Facts"  # paragraphs we're willing to RElabel

# Sections that trigger propagation modes
TRIGGER_TO_MODE = {
    "Merits": "Merits",
    "Just Satisfaction": "Just Satisfaction",
}
# Allowed soft interruptions for each mode
SOFT_INTERRUPT = frozenset({"Admissibility"})
# Hard enders — when seen, current block ends immediately
HARD_ENDERS = frozenset({
    "Operative Part", "Operative part",
    "Separate Opinion", "Appendix", "Article 46",
})
# Patterns in text that end the block regardless of section.
# The first alternation matches anywhere; the second matches a numbered
# operative-dispositif sentence at paragraph start (e.g. "1. Decides to...").
END_RE = re.compile(
    r"(\b(FOR THESE REASONS|OPERATIVE PROVISIONS)\b)"
    r"|(^\s*\d+\.\s*(Decides|Declares|Holds)\b)",
    re.IGNORECASE,
)
MAX_HEADING_LEN = 120

def is_block_ender(text):
    if not text or len(text) >= MAX_HEADING_LEN:
        return False
    return bool(END_RE.search(text))

# Connect (read-only for dry-run, RW for apply)
if DRY_RUN:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
else:
    conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# Walk Population C cases
cur.execute("SELECT DISTINCT case_id FROM paragraphs WHERE para_idx IS NULL")
case_ids = [r[0] for r in cur.fetchall()]
print(f"Population C cases to process: {len(case_ids):,}")

# rowid -> new section
relabels = {}
trigger_count = 0
continuation_count = 0  # paragraphs relabeled via continuation (not direct trigger)

cur2 = conn.cursor()
for i, case_id in enumerate(case_ids):
    if i % 1000 == 0 and i > 0:
        print(f"  ... {i:,} / {len(case_ids):,}")
    cur2.execute("""
        SELECT rowid, section, text FROM paragraphs
        WHERE case_id=? AND para_idx IS NULL
        ORDER BY rowid
    """, (case_id,))
    paras = cur2.fetchall()

    active_mode = None     # "Merits" or "Just Satisfaction" — what we're propagating
    interrupt_count = 0    # consecutive soft-interruption paragraphs

    for p in paras:
        sec = p["section"]
        text = p["text"] or ""
        rowid = p["rowid"]

        # End block on hard ender
        if sec in HARD_ENDERS:
            active_mode = None
            interrupt_count = 0
            continue
        # End block on operative-dispositif text
        if is_block_ender(text):
            active_mode = None
            interrupt_count = 0
            continue

        # If this paragraph itself is a trigger section, set/switch active mode
        if sec in TRIGGER_TO_MODE:
            new_mode = TRIGGER_TO_MODE[sec]
            if active_mode != new_mode:
                trigger_count += 1
            active_mode = new_mode
            interrupt_count = 0
            continue  # don't relabel an already-correct paragraph

        # Not in an active mode → nothing to do
        if active_mode is None:
            continue

        # We're propagating active_mode.  Source-section paragraph → relabel.
        if sec == SOURCE_SECTION:
            relabels[rowid] = active_mode
            interrupt_count = 0
            continuation_count += 1
            continue

        # Soft interruption — don't relabel, increment counter
        if sec in SOFT_INTERRUPT:
            interrupt_count += 1
            if interrupt_count > MAX_INTERRUPTION:
                active_mode = None
                interrupt_count = 0
            continue

        # Anything else (e.g. Header, Introduction, Legal Framework) — end the block
        active_mode = None
        interrupt_count = 0

# Subtract any rowids that were already relabeled by P4 (so we count NEW work)
existing_p4 = set()
cur.execute("SELECT rowid FROM _p4_backup")
existing_p4 = {r[0] for r in cur.fetchall()}

# rowids we'd touch that weren't already touched by P4
new_rowids = {rid: tgt for rid, tgt in relabels.items() if rid not in existing_p4}

print(f"\nTotal relabel rowids (this pass): {len(relabels):,}")
print(f"  - of which already done by P4:  {len(relabels) - len(new_rowids):,}")
print(f"  - NEW work (continuations):     {len(new_rowids):,}")
print(f"  Direct triggers:                {trigger_count:,}")
print(f"  Continuation paragraphs:        {continuation_count:,}")

# Distribution of new rowids by current section
if new_rowids:
    rowid_list = list(new_rowids.keys())
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
            new = new_rowids[r["rowid"]]
            key = f"{old} → {new}"
            move_counter[key] = move_counter.get(key, 0) + 1
    print("\nNew moves (current → new):")
    for k, v in sorted(move_counter.items(), key=lambda x: -x[1]):
        print(f"  {v:>7,}  {k}")

# Spot check: 3 cases where continuation kicked in
print("\n── SPOT CHECK: 3 cases with continuation relabels ──")
sample_cases = []
for rid in new_rowids:
    cur.execute("SELECT case_id FROM paragraphs WHERE rowid=?", (rid,))
    cid = cur.fetchone()[0]
    if cid not in sample_cases:
        sample_cases.append(cid)
    if len(sample_cases) >= 3:
        break

for cid in sample_cases:
    cur.execute("SELECT title FROM cases WHERE case_id=?", (cid,))
    title = (cur.fetchone()[0] or "")[:60]
    print(f"\n  [{cid}] {title}")
    cur.execute("""
        SELECT rowid, section, substr(text,1,80) AS t
        FROM paragraphs WHERE case_id=? AND para_idx IS NULL
        ORDER BY rowid LIMIT 30
    """, (cid,))
    for p in cur.fetchall():
        rid = p["rowid"]
        new = relabels.get(rid)
        was_p4 = rid in existing_p4
        marker = ""
        if new and not was_p4:
            marker = f" → {new} (P5)"
        elif was_p4:
            marker = " (P4)"
        print(f"    [{p['section']:<22}{marker:<22}] {p['t']}")

if DRY_RUN:
    print("\nDRY-RUN — no changes written. Run with --apply to commit.")
    conn.close()
    sys.exit(0)

# ── APPLY ──────────────────────────────────────────────────────────────────
if not new_rowids:
    print("\nNo new work to apply.")
    conn.close()
    sys.exit(0)

print("\nAPPLYING changes...")
cur.execute("DROP TABLE IF EXISTS _p5_backup")
cur.execute(f"""
    CREATE TABLE _p5_backup AS
    SELECT rowid, section FROM paragraphs
    WHERE rowid IN ({','.join(str(r) for r in new_rowids.keys())})
""")
backup_count = cur.execute("SELECT COUNT(*) FROM _p5_backup").fetchone()[0]
print(f"Backup _p5_backup: {backup_count:,} rows")

# Group by target section
by_target = {}
for rid, tgt in new_rowids.items():
    by_target.setdefault(tgt, []).append(rid)

conn.execute("BEGIN")
total_updated = 0
for tgt, rowids in by_target.items():
    BATCH = 9000
    for start in range(0, len(rowids), BATCH):
        batch = rowids[start:start+BATCH]
        conn.execute(
            f"UPDATE paragraphs SET section = ? WHERE rowid IN ({','.join(str(r) for r in batch)})",
            (tgt,)
        )
        total_updated += len(batch)
conn.commit()
print(f"COMMITTED. {total_updated:,} paragraphs relabeled.")

# Verify
for tgt in sorted(set(new_rowids.values())):
    cur.execute("SELECT COUNT(*) FROM paragraphs WHERE section=?", (tgt,))
    print(f"  '{tgt}' total now: {cur.fetchone()[0]:,}")

conn.close()
print("DONE.")
