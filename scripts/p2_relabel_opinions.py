"""
P2 RELABEL: Separate Opinion recovery from Operative Part.

Paragraphs with DISSENTING/CONCURRING/PARTLY DISSENTING headings
currently in 'Operative Part' or 'Operative part' -> 'Separate Opinion'.

Pass A: heading paragraphs (short, LIKE-match)
Pass B: content blocks that follow the heading in the same DB-section
        (Population B, para_idx NOT NULL)

Usage:
  python p2_relabel_opinions.py            # dry-run
  python p2_relabel_opinions.py --apply    # commit
"""
import sqlite3
import sys
import re

DRY_RUN = "--apply" not in sys.argv
DB = "/data/echr_search.db"

OPINION_HEADINGS_RE = re.compile(
    r"(DISSENTING OPINION|CONCURRING OPINION|PARTLY DISSENTING|JOINT DISSENTING"
    r"|SEPARATE OPINION OF|PARTLY CONCURRING)",
    re.IGNORECASE,
)

# headings that end an opinion block
STOP_RE = re.compile(
    r"(FOR THESE REASONS|OPERATIVE PROVISIONS|DECLARES|HOLDS|DECIDES"
    r"|THE LAW|ALLEGED VIOLATION|JUST SATISFACTION|APPLICATION OF ARTICLE)",
    re.IGNORECASE,
)

def is_opinion_heading(text):
    t = (text or "").strip()
    return len(t) < 120 and bool(OPINION_HEADINGS_RE.search(t))

def is_stop(text):
    t = (text or "").strip()
    return len(t) < 100 and bool(STOP_RE.search(t))

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# Pass A: heading paragraphs in Operative Part / Operative part
cur.execute("""
    SELECT rowid FROM paragraphs
    WHERE section IN ('Operative Part', 'Operative part')
      AND length(text) < 120
      AND (
          UPPER(text) LIKE '%DISSENTING OPINION%'
       OR UPPER(text) LIKE '%CONCURRING OPINION%'
       OR UPPER(text) LIKE '%PARTLY DISSENTING%'
       OR UPPER(text) LIKE '%JOINT DISSENTING%'
       OR UPPER(text) LIKE '%SEPARATE OPINION OF%'
       OR UPPER(text) LIKE '%PARTLY CONCURRING%'
      )
""")
pass_a_rowids = {r[0] for r in cur.fetchall()}
print(f"Pass A headings collected:         {len(pass_a_rowids):>8,}")

# Pass B: content blocks (Population B)
cur.execute(f"""
    SELECT DISTINCT case_id FROM paragraphs
    WHERE para_idx IS NOT NULL
      AND rowid IN ({','.join(str(r) for r in pass_a_rowids)})
""")
case_ids_b = [r[0] for r in cur.fetchall()]
print(f"Cases to process for Pass B:       {len(case_ids_b):>8,}")

relabel_rowids = set(pass_a_rowids)
cur2 = conn.cursor()
pass_b_count = 0

for case_id in case_ids_b:
    cur2.execute("""
        SELECT rowid, para_idx, section, text
        FROM paragraphs
        WHERE case_id = ? AND para_idx IS NOT NULL
        ORDER BY para_idx
    """, (case_id,))
    paras = cur2.fetchall()

    in_opinion = False
    opinion_section = None

    for p in paras:
        txt = (p["text"] or "").strip()
        sec = p["section"]
        rowid = p["rowid"]

        if not in_opinion:
            if rowid in pass_a_rowids:
                in_opinion = True
                opinion_section = sec
        else:
            if sec != opinion_section:
                in_opinion = False
                opinion_section = None
                if rowid in pass_a_rowids:
                    in_opinion = True
                    opinion_section = sec
            elif is_opinion_heading(txt) and rowid not in pass_a_rowids:
                # another judge's opinion header — stays in block but is also a heading
                relabel_rowids.add(rowid)
                pass_b_count += 1
            elif is_stop(txt):
                in_opinion = False
                opinion_section = None
            else:
                relabel_rowids.add(rowid)
                pass_b_count += 1

print(f"Pass B content paragraphs found:   {pass_b_count:>8,}")
print(f"Total rowids to relabel:           {len(relabel_rowids):>8,}")

# Current distribution
cur.execute(f"""
    SELECT section, COUNT(*) as n FROM paragraphs
    WHERE rowid IN ({','.join(str(r) for r in relabel_rowids)})
    GROUP BY section ORDER BY n DESC
""")
print("\nCurrent section distribution of rows to relabel:")
for r in cur.fetchall():
    print(f"  {r['section']:<25} {r['n']:>8,}")

cur.execute("SELECT COUNT(*) FROM paragraphs WHERE section = 'Separate Opinion'")
current_so = cur.fetchone()[0]
print(f"\nCurrent 'Separate Opinion' paragraphs: {current_so:,}")
print(f"After relabel (estimate):               {current_so + len(relabel_rowids):,}")

# Spot check
print("\n── SPOT CHECK: 3 examples ──")
cur.execute(f"""
    SELECT DISTINCT p.case_id, c.title
    FROM paragraphs p JOIN cases c ON c.case_id = p.case_id
    WHERE p.rowid IN ({','.join(str(r) for r in pass_a_rowids)})
      AND p.para_idx IS NOT NULL
    ORDER BY RANDOM() LIMIT 3
""")
examples = cur.fetchall()
cur3 = conn.cursor()
for ex in examples:
    print(f"\n  [{ex['case_id']}] {(ex['title'] or '')[:65]}")
    cur3.execute("""
        SELECT rowid, para_idx, section, substr(text, 1, 100) as t
        FROM paragraphs WHERE case_id = ? AND para_idx IS NOT NULL
        ORDER BY para_idx
    """, (ex["case_id"],))
    paras = cur3.fetchall()
    in_block = False
    shown = 0
    for p in paras:
        txt = (p["t"] or "").strip()
        sec = p["section"]
        if not in_block and p["rowid"] in pass_a_rowids:
            in_block = True
            print(f"    ¶{p['para_idx']:>4} [{sec}] HEADING ▶ {txt}")
            shown += 1
        elif in_block:
            if sec not in ("Operative Part", "Operative part"):
                print(f"    ¶{p['para_idx']:>4} [{sec}] ← boundary STOP")
                break
            if shown < 4:
                print(f"    ¶{p['para_idx']:>4} [{sec}]         {txt[:90]}")
            shown += 1
    if in_block:
        print(f"    → {shown} paragraphs would move to Separate Opinion")

if DRY_RUN:
    print("\nDRY-RUN — no changes written. Run with --apply to commit.")
    conn.close()
    sys.exit(0)

# ── APPLY ────────────────────────────────────────────────────────────────────
print("\nAPPLYING changes...")

cur.execute("DROP TABLE IF EXISTS _p2_backup")
cur.execute(f"""
    CREATE TABLE _p2_backup AS
    SELECT rowid, section FROM paragraphs
    WHERE rowid IN ({','.join(str(r) for r in relabel_rowids)})
""")
backup_count = cur.execute("SELECT COUNT(*) FROM _p2_backup").fetchone()[0]
print(f"Backup table _p2_backup created: {backup_count:,} rows")

rowid_list = list(relabel_rowids)
BATCH = 9000
updated = 0
conn.execute("BEGIN")
for start in range(0, len(rowid_list), BATCH):
    batch = rowid_list[start:start + BATCH]
    conn.execute(
        "UPDATE paragraphs SET section = 'Separate Opinion' WHERE rowid IN ({})".format(
            ",".join(str(r) for r in batch)
        )
    )
    updated += len(batch)

conn.commit()
print(f"COMMITTED. {updated:,} paragraphs relabeled to 'Separate Opinion'.")

cur.execute("SELECT COUNT(*) FROM paragraphs WHERE section = 'Separate Opinion'")
print(f"New 'Separate Opinion' count: {cur.fetchone()[0]:,}")

conn.close()
print("DONE.")
