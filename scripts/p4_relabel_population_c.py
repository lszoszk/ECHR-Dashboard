"""
P4 RELABEL: rule-based segmentation of Population C (committee/joined cases
with para_idx IS NULL) using rowid as a proxy for document order.

When a paragraph in section S contains a known section-boundary heading
(e.g. "ALLEGED VIOLATION OF ARTICLE X" while the paragraph is in 'Facts'),
we relabel that heading + all following same-section paragraphs in the
same case (rowid-ordered) to the target section, until a different
section appears or another known boundary heading takes over.

Boundary rules (all length<120, case-insensitive):
  In Facts → Merits:
    - 'ALLEGED VIOLATION'
    - 'JOINDER OF THE APPLICATIONS'
  In Facts/Merits → Just Satisfaction:
    - 'APPLICATION OF ARTICLE 41'
  In Merits → Operative part:
    - 'FOR THESE REASONS' / 'OPERATIVE PROVISIONS'

Population C only (para_idx IS NULL).

Usage:
  python p4_relabel_population_c.py            # dry-run
  python p4_relabel_population_c.py --apply    # commit
"""
import sqlite3
import sys
import re

DRY_RUN = "--apply" not in sys.argv
DB = "/data/echr_search.db"

# (heading_pattern_regex, current_section, new_section, max_heading_len)
RULES = [
    # In Facts → Merits  (segmenter wrongly placed merits content in Facts)
    (re.compile(r"\bALLEGED VIOLATION\b", re.IGNORECASE),       "Facts",  "Merits"),
    (re.compile(r"\bJOINDER OF THE APPLICATIONS\b", re.IGNORECASE), "Facts",  "Merits"),
    # In Facts/Merits → Just Satisfaction
    (re.compile(r"\bAPPLICATION OF ARTICLE 41\b", re.IGNORECASE), "Facts",  "Just Satisfaction"),
    (re.compile(r"\bAPPLICATION OF ARTICLE 41\b", re.IGNORECASE), "Merits", "Just Satisfaction"),
    # In Merits → Operative part (the operative dispositif sometimes leaks into Merits)
    (re.compile(r"\b(FOR THESE REASONS|OPERATIVE PROVISIONS)\b", re.IGNORECASE), "Merits", "Operative part"),
]

MAX_HEADING_LEN = 120

# Patterns that should be considered "still part of an Article 41 block"
# even if they look like sub-headings (so we don't prematurely stop)
ART41_INTERNAL = re.compile(
    r"\b(damage|costs and expenses|default interest|article 41|"
    r"pecuniary|non-pecuniary)\b",
    re.IGNORECASE,
)

def find_first_match(text):
    """Return (rule_index, new_section) for the first matching rule, or None."""
    if not text or len(text) >= MAX_HEADING_LEN:
        return None
    for i, (pat, src, tgt) in enumerate(RULES):
        if pat.search(text):
            return (i, src, tgt)
    return None

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# Walk Population C cases
cur.execute("""
    SELECT DISTINCT case_id FROM paragraphs WHERE para_idx IS NULL
""")
case_ids = [r[0] for r in cur.fetchall()]
print(f"Population C cases to process: {len(case_ids):,}")

# rowid -> new_section
relabels = {}
boundary_hits = 0
boundary_per_rule = [0] * len(RULES)

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

    # Active relabel: while inside a triggered block, relabel paragraphs in
    # the source section to the target section, until section actually
    # changes (= the next paragraph's stored section is different from
    # the source) or another boundary heading takes over.
    active_src = None
    active_tgt = None

    for p in paras:
        sec = p["section"]
        text = p["text"] or ""
        rowid = p["rowid"]

        # Check whether THIS paragraph's text triggers a NEW boundary rule
        m = find_first_match(text)
        if m is not None:
            rule_idx, src, tgt = m
            if sec == src:
                # heading paragraph itself relabels
                active_src = src
                active_tgt = tgt
                relabels[rowid] = tgt
                boundary_hits += 1
                boundary_per_rule[rule_idx] += 1
                continue

        # No new boundary triggered here. If we're in an active block:
        if active_src is not None:
            if sec == active_src:
                # Belongs to the still-active block → relabel
                relabels[rowid] = active_tgt
            else:
                # Section changed naturally, end the active block
                active_src = None
                active_tgt = None

print(f"\nTotal relabel rowids: {len(relabels):,}")
print(f"Boundary heading hits: {boundary_hits:,}")
for i, (pat, src, tgt) in enumerate(RULES):
    print(f"  rule {i}: {pat.pattern!r:<50} in {src!r:<8} → {tgt!r:<22} : {boundary_per_rule[i]:,} hits")

# Distribution of moves
print("\nMove distribution (current → new):")
move_counter = {}
if relabels:
    rowid_list = list(relabels.keys())
    BATCH = 9000
    for start in range(0, len(rowid_list), BATCH):
        batch = rowid_list[start:start+BATCH]
        cur.execute(
            "SELECT rowid, section FROM paragraphs WHERE rowid IN ({})".format(
                ",".join(str(r) for r in batch)
            )
        )
        for r in cur.fetchall():
            old = r["section"]
            new = relabels[r["rowid"]]
            key = f"{old} → {new}"
            move_counter[key] = move_counter.get(key, 0) + 1
    for k, v in sorted(move_counter.items(), key=lambda x: -x[1]):
        print(f"  {v:>7,}  {k}")

# spot check
print("\n── SPOT CHECK: 3 cases with relabels ──")
sample_cases = set()
for rid, tgt in list(relabels.items())[:200]:
    cur.execute("SELECT case_id FROM paragraphs WHERE rowid=?", (rid,))
    sample_cases.add(cur.fetchone()[0])
    if len(sample_cases) >= 3:
        break
for cid in sample_cases:
    cur.execute("SELECT title FROM cases WHERE case_id=?", (cid,))
    title = (cur.fetchone()[0] or "")[:60]
    print(f"\n  [{cid}] {title}")
    cur.execute("""
        SELECT rowid, section, substr(text,1,80) AS t
        FROM paragraphs WHERE case_id=? AND para_idx IS NULL
        ORDER BY rowid LIMIT 25
    """, (cid,))
    shown = 0
    for p in cur.fetchall():
        rid = p["rowid"]
        new = relabels.get(rid)
        marker = f" → {new}" if new else ""
        print(f"    [{p['section']:<22}{marker:<28}] {p['t']}")
        shown += 1

if DRY_RUN:
    print("\nDRY-RUN — no changes written. Run with --apply to commit.")
    conn.close()
    sys.exit(0)

# ── APPLY ──────────────────────────────────────────────────────────────────
print("\nAPPLYING changes...")
cur.execute("DROP TABLE IF EXISTS _p4_backup")
cur.execute(f"""
    CREATE TABLE _p4_backup AS
    SELECT rowid, section FROM paragraphs
    WHERE rowid IN ({','.join(str(r) for r in relabels.keys())})
""")
backup_count = cur.execute("SELECT COUNT(*) FROM _p4_backup").fetchone()[0]
print(f"Backup _p4_backup: {backup_count:,} rows")

# Group relabels by target section to do per-target batches
by_target = {}
for rid, tgt in relabels.items():
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
for tgt in sorted(set(relabels.values())):
    cur.execute("SELECT COUNT(*) FROM paragraphs WHERE section=?", (tgt,))
    print(f"  '{tgt}' total now: {cur.fetchone()[0]:,}")

conn.close()
print("DONE.")
