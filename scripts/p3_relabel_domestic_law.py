"""
P3 RELABEL: Extract domestic law sub-sections from Facts Proceedings -> Legal Framework.

In Population B, 'Facts Proceedings' mixes:
  I.  THE CIRCUMSTANCES OF THE CASE  (keep as Facts Proceedings)
  II. RELEVANT DOMESTIC LAW ...      (move to Legal Framework)

Stop condition uses word-boundary matching to avoid false positives
like "THE LAWS AND CUSTOMS OF WAR" triggering on "THE LAW".

Usage:
  python p3_relabel_domestic_law.py            # dry-run
  python p3_relabel_domestic_law.py --apply    # commit
"""
import sqlite3
import sys
import re

DRY_RUN = "--apply" not in sys.argv
DB = "/data/echr_search.db"

DOMESTIC_LAW_RE = re.compile(
    r"(RELEVANT DOMESTIC LAW|DOMESTIC LAW AND PRACTICE|DOMESTIC LAW AND REGULATION"
    r"|RELEVANT NATIONAL LAW|RELEVANT DOMESTIC AND INTERNATIONAL"
    r"|DOMESTIC AND INTERNATIONAL LAW|RELEVANT DOMESTIC LEGISLATION)",
    re.IGNORECASE,
)

# Word-boundary aware stop patterns — these must be essentially standalone headings
STOP_RE = re.compile(
    r"(?<!\w)(THE LAW|AS TO THE LAW|ALLEGED VIOLATION|FOR THESE REASONS"
    r"|ADMISSIBILITY|JUST SATISFACTION|APPLICATION OF ARTICLE"
    r"|JOINDER OF THE APPLICATIONS)(?!\w)",
    re.IGNORECASE,
)

def is_domestic_law_heading(text):
    t = (text or "").strip()
    return len(t) < 120 and bool(DOMESTIC_LAW_RE.search(t))

def is_stop_heading(text):
    t = (text or "").strip()
    if len(t) >= 120:
        return False
    return bool(STOP_RE.search(t))

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# ── collect cases with domestic law headings in Facts Proceedings ────────────
cur.execute("""
    SELECT DISTINCT case_id FROM paragraphs
    WHERE section = 'Facts Proceedings'
      AND para_idx IS NOT NULL
      AND length(text) < 120
      AND (
          UPPER(text) LIKE '%RELEVANT DOMESTIC LAW%'
       OR UPPER(text) LIKE '%DOMESTIC LAW AND PRACTICE%'
       OR UPPER(text) LIKE '%DOMESTIC LAW AND REGULATION%'
       OR UPPER(text) LIKE '%RELEVANT NATIONAL LAW%'
       OR UPPER(text) LIKE '%DOMESTIC AND INTERNATIONAL LAW%'
       OR UPPER(text) LIKE '%RELEVANT DOMESTIC LEGISLATION%'
      )
""")
case_ids = [r[0] for r in cur.fetchall()]
print(f"Cases to process: {len(case_ids):,}")

# ── walk each case, collect rowids to relabel ────────────────────────────────
relabel_rowids = set()
cur2 = conn.cursor()

for i, case_id in enumerate(case_ids):
    if i % 2000 == 0 and i > 0:
        print(f"  ... {i:,} / {len(case_ids):,} cases")
    cur2.execute("""
        SELECT rowid, para_idx, section, text
        FROM paragraphs
        WHERE case_id = ? AND para_idx IS NOT NULL
        ORDER BY para_idx
    """, (case_id,))
    paras = cur2.fetchall()

    in_domestic = False

    for p in paras:
        txt = (p["text"] or "").strip()
        sec = p["section"]
        rowid = p["rowid"]

        if not in_domestic:
            if sec == "Facts Proceedings" and is_domestic_law_heading(txt):
                in_domestic = True
                relabel_rowids.add(rowid)
        else:
            if sec != "Facts Proceedings":
                in_domestic = False
                # might be a new domestic law block in a different section — skip
            elif is_stop_heading(txt) and not is_domestic_law_heading(txt):
                in_domestic = False
            else:
                # continue block (including sub-headings within domestic law)
                relabel_rowids.add(rowid)

print(f"Total rowids to relabel: {len(relabel_rowids):,}")

# current distribution of rows to relabel
cur.execute(f"""
    SELECT section, COUNT(*) as n FROM paragraphs
    WHERE rowid IN ({','.join(str(r) for r in relabel_rowids)})
    GROUP BY section ORDER BY n DESC
""")
print("\nCurrent section distribution:")
for r in cur.fetchall():
    print(f"  {r['section']:<25} {r['n']:>8,}")

cur.execute("SELECT COUNT(*) FROM paragraphs WHERE section='Legal Framework'")
lf_before = cur.fetchone()[0]
print(f"\nCurrent 'Legal Framework': {lf_before:,}")
print(f"After relabel (estimate):  {lf_before + len(relabel_rowids):,}")

# spot check
print("\n── SPOT CHECK: 3 examples ──")
cur.execute("""
    SELECT DISTINCT p.case_id, c.title
    FROM paragraphs p JOIN cases c ON c.case_id=p.case_id
    WHERE p.section='Facts Proceedings'
      AND p.para_idx IS NOT NULL
      AND length(p.text) < 120
      AND UPPER(p.text) LIKE '%RELEVANT DOMESTIC LAW%'
    ORDER BY RANDOM() LIMIT 3
""")
examples = cur.fetchall()
cur3 = conn.cursor()
for ex in examples:
    print(f"\n  [{ex['case_id']}] {(ex['title'] or '')[:65]}")
    cur3.execute("""
        SELECT rowid, para_idx, section, substr(text,1,100) as t
        FROM paragraphs WHERE case_id=? AND para_idx IS NOT NULL
        ORDER BY para_idx
    """, (ex["case_id"],))
    paras3 = cur3.fetchall()
    in_block = False
    shown = 0
    for p in paras3:
        txt = (p["t"] or "").strip()
        sec = p["section"]
        if not in_block and sec == "Facts Proceedings" and is_domestic_law_heading(txt):
            in_block = True
            print(f"    ¶{p['para_idx']:>4} [{sec}] HEADING ▶ {txt}")
            shown += 1
        elif in_block:
            if sec != "Facts Proceedings":
                print(f"    ¶{p['para_idx']:>4} [{sec}] ← boundary STOP")
                break
            if is_stop_heading(txt) and not is_domestic_law_heading(txt):
                print(f"    ¶{p['para_idx']:>4} [{sec}] ← stop: {txt[:60]}")
                break
            if shown < 5:
                print(f"    ¶{p['para_idx']:>4} [{sec}]         {txt[:90]}")
            shown += 1
    if in_block:
        print(f"    → {shown} paragraphs would move to Legal Framework")

if DRY_RUN:
    print("\nDRY-RUN — no changes written. Run with --apply to commit.")
    conn.close()
    sys.exit(0)

# ── APPLY ────────────────────────────────────────────────────────────────────
print("\nAPPLYING changes...")

cur.execute("DROP TABLE IF EXISTS _p3_backup")
cur.execute(f"""
    CREATE TABLE _p3_backup AS
    SELECT rowid, section FROM paragraphs
    WHERE rowid IN ({','.join(str(r) for r in relabel_rowids)})
""")
backup_count = cur.execute("SELECT COUNT(*) FROM _p3_backup").fetchone()[0]
print(f"Backup table _p3_backup created: {backup_count:,} rows")

rowid_list = list(relabel_rowids)
BATCH = 9000
updated = 0
conn.execute("BEGIN")
for start in range(0, len(rowid_list), BATCH):
    batch = rowid_list[start:start + BATCH]
    conn.execute(
        "UPDATE paragraphs SET section = 'Legal Framework' WHERE rowid IN ({})".format(
            ",".join(str(r) for r in batch)
        )
    )
    updated += len(batch)
    if updated % 40000 == 0:
        print(f"  ... {updated:,} updated")

conn.commit()
print(f"COMMITTED. {updated:,} paragraphs relabeled to 'Legal Framework'.")

cur.execute("SELECT COUNT(*) FROM paragraphs WHERE section='Legal Framework'")
print(f"New 'Legal Framework' count: {cur.fetchone()[0]:,}")

conn.close()
print("DONE.")
