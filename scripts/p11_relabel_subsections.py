"""
P11 RELABEL: split missing canonical sub-sections out of Facts catch-all.

Discovered during expert manual review M3 (2026-04-28). In Population A
pre-1998 judgments, our schema collapses several HUDOC-canonical
sub-sections into Facts Background/Facts Proceedings:

  PROCEDURE                              → Introduction (already correct)
  AS TO THE FACTS / I. CIRCUMSTANCES     → Facts Background/Proceedings (already correct)
  II. RELEVANT DOMESTIC LAW              → SHOULD BE Legal Framework (P3 partial coverage)
  III. PROCEEDINGS BEFORE THE COMMISSION → SHOULD BE NEW: Commission Proceedings
  IV. FINAL SUBMISSIONS MADE TO THE COURT → SHOULD BE NEW: Final Submissions
  V. AS TO THE LAW (Merits)              → Merits (already correct)

Plus residual international/European/comparative law headings that
P3 didn't catch (they sit in Facts Proceedings/Background).

This pass walks each case (Pop A/B with para_idx) in document order,
detects canonical heading paragraphs (length<120), and relabels the
heading + all subsequent same-section paragraphs to the target,
until the block ends.

Two NEW section labels introduced:
  - 'Commission Proceedings' — pre-Protocol-11 procedural history
                                before the European Commission
  - 'Final Submissions'      — parties' final arguments to the Court
                                before merits analysis

Usage:
  python p11_relabel.py            # dry-run
  python p11_relabel.py --apply    # commit
"""
import sqlite3
import sys
import re

DRY_RUN = "--apply" not in sys.argv
DB = "/data/echr_search.db"

# Detection rules: (regex, source_sections, target_section)
# Source section restrictions prevent false matches in already-correct sections.
RULES = [
    # 1. Domestic law residue (P3 didn't catch some Pop A in Facts Background)
    (re.compile(r"^\s*(?:[IVX]+\.\s+)?RELEVANT DOMESTIC LAW\b", re.IGNORECASE),
     {"Facts Background", "Facts Proceedings", "Facts"}, "Legal Framework"),
    (re.compile(r"^\s*(?:[IVX]+\.\s+)?(?:RELEVANT )?DOMESTIC LAW AND PRACTICE\b", re.IGNORECASE),
     {"Facts Background", "Facts Proceedings", "Facts"}, "Legal Framework"),
    (re.compile(r"^\s*(?:[IVX]+\.\s+)?(?:RELEVANT )?DOMESTIC LAW AND REGULATION", re.IGNORECASE),
     {"Facts Background", "Facts Proceedings", "Facts"}, "Legal Framework"),
    (re.compile(r"^\s*(?:[IVX]+\.\s+)?(?:RELEVANT )?DOMESTIC LEGISLATION\b", re.IGNORECASE),
     {"Facts Background", "Facts Proceedings", "Facts"}, "Legal Framework"),

    # 2. International / European / Comparative law residue
    (re.compile(r"^\s*(?:[IVX]+\.\s+)?(?:RELEVANT )?INTERNATIONAL LAW\b", re.IGNORECASE),
     {"Facts Background", "Facts Proceedings", "Facts"}, "Legal Framework"),
    (re.compile(r"^\s*(?:[IVX]+\.\s+)?RELEVANT INTERNATIONAL", re.IGNORECASE),
     {"Facts Background", "Facts Proceedings", "Facts"}, "Legal Framework"),
    (re.compile(r"^\s*(?:[IVX]+\.\s+)?RELEVANT EUROPEAN", re.IGNORECASE),
     {"Facts Background", "Facts Proceedings", "Facts"}, "Legal Framework"),
    (re.compile(r"^\s*(?:[IVX]+\.\s+)?(?:RELEVANT )?EUROPEAN UNION LAW\b", re.IGNORECASE),
     {"Facts Background", "Facts Proceedings", "Facts"}, "Legal Framework"),
    (re.compile(r"^\s*(?:[IVX]+\.\s+)?(?:RELEVANT )?COMPARATIVE LAW\b", re.IGNORECASE),
     {"Facts Background", "Facts Proceedings", "Facts"}, "Legal Framework"),
    (re.compile(r"^\s*(?:[IVX]+\.\s+)?(?:THE )?CASE-LAW OF THE COURT OF JUSTICE\b", re.IGNORECASE),
     {"Facts Background", "Facts Proceedings", "Facts"}, "Legal Framework"),

    # 3. NEW: Commission Proceedings (pre-Protocol-11 procedural)
    (re.compile(r"^\s*(?:[IVX]+\.\s+)?PROCEEDINGS BEFORE THE COMMISSION\b", re.IGNORECASE),
     {"Facts Background", "Facts Proceedings", "Facts", "Introduction"}, "Commission Proceedings"),

    # 4. NEW: Final Submissions to the Court
    (re.compile(r"^\s*(?:[IVX]+\.\s+)?FINAL SUBMISSIONS\s+(?:TO|MADE TO|BEFORE)\s+THE COURT\b", re.IGNORECASE),
     {"Facts Background", "Facts Proceedings", "Facts", "Introduction"}, "Final Submissions"),
]

# Stop patterns — when seen, the active block ends (different sub-section starts)
# Word-boundary aware to avoid false positives.
STOP_RE = re.compile(
    r"^\s*(?:[IVX]+\.\s+)?("
    r"AS TO THE LAW|THE LAW(?!\w)|ALLEGED VIOLATION|FOR THESE REASONS|"
    r"OPERATIVE PROVISIONS|JOINDER OF THE APPLICATIONS|APPLICATION OF ARTICLE|"
    r"AS TO THE FACTS|THE FACTS(?!\w)|THE CIRCUMSTANCES OF THE CASE|"
    r"PROCEDURE(?!\s*S)"
    r")",
    re.IGNORECASE,
)
MAX_HEADING_LEN = 120

def find_rule_match(text):
    """Return (rule_index, target_section) for the first matching rule, or None."""
    if not text or len(text) >= MAX_HEADING_LEN:
        return None
    t = text.strip()
    for i, (pat, src_sections, tgt) in enumerate(RULES):
        if pat.match(t):
            return (i, src_sections, tgt)
    return None

def is_stop_heading(text, current_target):
    """Check if this paragraph is a stop heading (different sub-section starts)."""
    if not text or len(text) >= MAX_HEADING_LEN:
        return False
    if STOP_RE.match(text):
        return True
    # Also any other rule's heading that targets a DIFFERENT section
    m = find_rule_match(text)
    if m and m[2] != current_target:
        return True
    return False

if DRY_RUN:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
else:
    conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# Walk all cases that have para_idx (Pop A and Pop B)
cur.execute("SELECT DISTINCT case_id FROM paragraphs WHERE para_idx IS NOT NULL")
case_ids = [r[0] for r in cur.fetchall()]
print(f"Cases to scan: {len(case_ids):,}")

relabels = {}            # rowid -> target_section
trigger_count_per_rule = [0] * len(RULES)
continuation_count = 0
target_summary = {}      # target -> direct_triggers, continuations

cur2 = conn.cursor()
for i, case_id in enumerate(case_ids):
    if i % 5000 == 0 and i > 0:
        print(f"  ... {i:,} / {len(case_ids):,}")
    cur2.execute("""
        SELECT rowid, para_idx, section, text FROM paragraphs
        WHERE case_id = ? AND para_idx IS NOT NULL
        ORDER BY para_idx
    """, (case_id,))
    paras = cur2.fetchall()

    active_src_section = None
    active_target = None

    for p in paras:
        sec = p["section"]
        text = p["text"] or ""
        rowid = p["rowid"]

        # Check trigger
        m = find_rule_match(text)
        if m is not None:
            rule_idx, src_sections, tgt = m
            if sec in src_sections:
                # heading itself relabels
                relabels[rowid] = tgt
                active_src_section = sec
                active_target = tgt
                trigger_count_per_rule[rule_idx] += 1
                target_summary.setdefault(tgt, [0, 0])[0] += 1
                continue

        # In active block?
        if active_src_section is None:
            continue

        # Section column changed -> end block
        if sec != active_src_section:
            active_src_section = None
            active_target = None
            continue

        # Stop heading -> end block
        if is_stop_heading(text, active_target):
            active_src_section = None
            active_target = None
            continue

        # Same source section, no stop -> propagate
        relabels[rowid] = active_target
        target_summary[active_target][1] += 1
        continuation_count += 1

print(f"\nTotal relabel rowids: {len(relabels):,}")
print(f"Direct heading triggers: {sum(trigger_count_per_rule):,}")
print(f"Continuation paragraphs: {continuation_count:,}")

print("\n=== Per-rule trigger counts ===")
for i, (pat, src_sections, tgt) in enumerate(RULES):
    if trigger_count_per_rule[i] > 0:
        print(f"  rule {i}: {pat.pattern[:50]:<50} → {tgt:<22} : {trigger_count_per_rule[i]:>5} triggers")

print("\n=== Per-target summary ===")
for tgt, (triggers, conts) in sorted(target_summary.items(), key=lambda x: -(x[1][0]+x[1][1])):
    print(f"  {tgt:<22} {triggers:>5} triggers + {conts:>6} continuations = {triggers+conts:>6} total")

# Distribution by source section
print("\n=== Source-section distribution ===")
if relabels:
    rowid_list = list(relabels.keys())
    BATCH = 9000
    by_move = {}
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
            key = f"{old:<22} → {new}"
            by_move[key] = by_move.get(key, 0) + 1
    for k, n in sorted(by_move.items(), key=lambda x: -x[1]):
        print(f"  {n:>6,}  {k}")

# Spot check: 3 cases
print("\n=== SPOT CHECK: 3 cases with Commission Proceedings or Final Submissions ===")
sample_cases = []
for rid, tgt in relabels.items():
    if tgt in ("Commission Proceedings", "Final Submissions"):
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
        SELECT rowid, para_idx, section, substr(text,1,80) AS t
        FROM paragraphs WHERE case_id=? AND para_idx IS NOT NULL
        ORDER BY para_idx
    """, (cid,))
    for p in cur.fetchall():
        rid = p["rowid"]
        new = relabels.get(rid)
        marker = f" → {new}" if new else ""
        print(f"    ¶{p['para_idx']:>4} [{p['section']:<22}{marker:<26}] {p['t']}")

if DRY_RUN:
    print("\nDRY-RUN — no changes written. Run with --apply to commit.")
    conn.close()
    sys.exit(0)

# === APPLY ===
print("\nAPPLYING...")
cur.execute("DROP TABLE IF EXISTS _p11_backup")
rowid_list = list(relabels.keys())
cur.execute(f"""
    CREATE TABLE _p11_backup AS
    SELECT rowid, section FROM paragraphs
    WHERE rowid IN ({','.join(str(r) for r in rowid_list)})
""")
print(f"Backup _p11_backup: {cur.execute('SELECT COUNT(*) FROM _p11_backup').fetchone()[0]:,} rows")

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

# Verify per-target
print("\n=== Final counts ===")
for tgt in sorted(set(relabels.values())):
    cur.execute("SELECT COUNT(*) FROM paragraphs WHERE section=?", (tgt,))
    print(f"  '{tgt}' total now: {cur.fetchone()[0]:,}")

conn.close()
print("DONE.")
