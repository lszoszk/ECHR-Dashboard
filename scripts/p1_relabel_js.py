"""
P1 RELABEL: Just Satisfaction section recovery.

Usage:
  python p1_relabel_js.py            # dry-run: prints what would change
  python p1_relabel_js.py --apply    # writes changes in one transaction

Pass A: heading paragraphs (APPLICATION OF ARTICLE 41/50, JUST SATISFACTION,
        length < 80) currently in wrong sections -> Just Satisfaction
Pass B: content paragraphs that follow an Art.41 heading in the same
        DB-section (Population B, para_idx NOT NULL), up to the next
        top-level section heading or section boundary
"""
import sqlite3
import sys
import re

DRY_RUN = "--apply" not in sys.argv
DB = "/data/echr_search.db"

WRONG_SECTIONS = frozenset([
    "Merits", "Admissibility", "Facts", "Operative part",
    "Operative Part", "Facts Proceedings", "Relevant legal framework",
])

# Headings that end an Art.41 block (another top-level heading in same section)
STOP_HEADINGS = re.compile(
    r"(FOR THESE REASONS|THE LAW|ALLEGED VIOLATION|AS TO THE LAW"
    r"|ADMISSIBILITY|OPERATIVE PART|JOINDER|SEPARATE OPINION"
    r"|DISSENTING OPINION|CONCURRING OPINION)",
    re.IGNORECASE,
)

def is_art41_heading(text):
    t = (text or "").strip()
    u = t.upper()
    return len(t) < 80 and (
        "APPLICATION OF ARTICLE 41" in u or
        "APPLICATION OF ARTICLE 50" in u or
        "JUST SATISFACTION" in u
    )

def is_stop_heading(text):
    t = (text or "").strip()
    return len(t) < 100 and bool(STOP_HEADINGS.search(t))

# ── collect all rowids to relabel ────────────────────────────────────────────
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

relabel_rowids = set()

# Pass A: heading paragraphs in wrong sections (both populations)
cur.execute("""
    SELECT rowid FROM paragraphs
    WHERE length(text) < 80
      AND section IN (
          'Merits','Admissibility','Facts','Operative part',
          'Operative Part','Facts Proceedings','Relevant legal framework'
      )
      AND (
          UPPER(text) LIKE '%APPLICATION OF ARTICLE 41%'
       OR UPPER(text) LIKE '%APPLICATION OF ARTICLE 50%'
       OR UPPER(text) LIKE '%JUST SATISFACTION%'
      )
""")
pass_a_rowids = {r[0] for r in cur.fetchall()}
relabel_rowids |= pass_a_rowids
print(f"Pass A headings collected:         {len(pass_a_rowids):>8,}")

# Pass B: content blocks in Population B (para_idx NOT NULL)
cur.execute("""
    SELECT DISTINCT case_id FROM paragraphs
    WHERE para_idx IS NOT NULL
      AND rowid IN ({})
""".format(",".join(str(r) for r in pass_a_rowids)))
case_ids_b = [r[0] for r in cur.fetchall()]
print(f"Cases to process for Pass B:       {len(case_ids_b):>8,}")

cur2 = conn.cursor()
pass_b_count = 0
for i, case_id in enumerate(case_ids_b):
    if i % 1000 == 0 and i > 0:
        print(f"  ... processed {i:,} / {len(case_ids_b):,} cases")
    cur2.execute("""
        SELECT rowid, para_idx, section, text
        FROM paragraphs
        WHERE case_id = ? AND para_idx IS NOT NULL
        ORDER BY para_idx
    """, (case_id,))
    paras = cur2.fetchall()

    in_art41 = False
    art41_section = None

    for p in paras:
        txt = (p["text"] or "").strip()
        sec = p["section"]
        rowid = p["rowid"]

        if not in_art41:
            if rowid in pass_a_rowids and sec in WRONG_SECTIONS:
                in_art41 = True
                art41_section = sec
                # heading already in relabel_rowids via Pass A
        else:
            if sec != art41_section:
                # section boundary -> stop
                in_art41 = False
                art41_section = None
                # check if this para starts a new Art.41 block
                if rowid in pass_a_rowids and sec in WRONG_SECTIONS:
                    in_art41 = True
                    art41_section = sec
            elif is_stop_heading(txt) and not is_art41_heading(txt):
                # another top-level heading ends the Art.41 block
                in_art41 = False
                art41_section = None
            else:
                relabel_rowids.add(rowid)
                pass_b_count += 1

print(f"Pass B content paragraphs found:   {pass_b_count:>8,}")
print(f"Total rowids to relabel:           {len(relabel_rowids):>8,}")

# ── dry-run or apply ─────────────────────────────────────────────────────────
if DRY_RUN:
    print("\nDRY-RUN — no changes written.")
    print("Run with --apply to commit changes.")

    # spot-check: current distribution
    print("\nCurrent section distribution of rows to relabel:")
    cur.execute(f"""
        SELECT section, COUNT(*) as n FROM paragraphs
        WHERE rowid IN ({','.join(str(r) for r in relabel_rowids)})
        GROUP BY section ORDER BY n DESC
    """)
    for r in cur.fetchall():
        print(f"  {r['section']:<25} {r['n']:>8,}")

    # current Just Satisfaction count for reference
    cur.execute("SELECT COUNT(*) FROM paragraphs WHERE section = 'Just Satisfaction'")
    current_js = cur.fetchone()[0]
    print(f"\nCurrent 'Just Satisfaction' paragraphs: {current_js:,}")
    print(f"After relabel (estimate):               {current_js + len(relabel_rowids):,}")
    conn.close()
    sys.exit(0)

# ── APPLY ────────────────────────────────────────────────────────────────────
print("\nAPPLYING changes...")

# backup in a separate table
cur.execute("DROP TABLE IF EXISTS _p1_backup")
cur.execute("""
    CREATE TABLE _p1_backup AS
    SELECT rowid, section FROM paragraphs
    WHERE rowid IN ({})
""".format(",".join(str(r) for r in relabel_rowids)))
backup_count = cur.execute("SELECT COUNT(*) FROM _p1_backup").fetchone()[0]
print(f"Backup table _p1_backup created: {backup_count:,} rows")

# update in batches of 10,000 to avoid SQLite expression limit
rowid_list = list(relabel_rowids)
BATCH = 9000
updated = 0
conn.execute("BEGIN")
for start in range(0, len(rowid_list), BATCH):
    batch = rowid_list[start:start + BATCH]
    conn.execute(
        "UPDATE paragraphs SET section = 'Just Satisfaction' WHERE rowid IN ({})".format(
            ",".join(str(r) for r in batch)
        )
    )
    updated += len(batch)
    if updated % 50000 == 0:
        print(f"  ... {updated:,} updated so far")

conn.commit()
print(f"COMMITTED. {updated:,} paragraphs relabeled to 'Just Satisfaction'.")

# verify
cur.execute("SELECT COUNT(*) FROM paragraphs WHERE section = 'Just Satisfaction'")
new_js = cur.fetchone()[0]
print(f"New 'Just Satisfaction' count: {new_js:,}")

# rollback helper hint
print("\nTo rollback (if needed):")
print("  UPDATE paragraphs SET section = b.section")
print("  FROM _p1_backup b WHERE paragraphs.rowid = b.rowid;")
print("  (SQLite syntax: UPDATE p SET section = (SELECT section FROM _p1_backup b WHERE b.rowid = p.rowid) WHERE p.rowid IN (SELECT rowid FROM _p1_backup))")

conn.close()
print("DONE.")
