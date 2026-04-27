"""
P1 VALIDATION (read-only): Just Satisfaction section recovery.
Measures scope of paragraphs to relabel before any UPDATE.

Strategy:
  Pass A - heading paragraphs: short (<80 chars) lines matching Article 41/50
            headings currently in wrong sections -> these are certain relabels
  Pass B - content blocks: for Population B (para_idx NOT NULL), paragraphs
            that FOLLOW an Article 41 heading in the same section, up to the
            next section-level heading or end of section
  Pass C - Population C (para_idx NULL): heading-only, no block detection possible
"""
import sqlite3
import re

DB = "/data/echr_search.db"
conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

WRONG_SECTIONS = frozenset([
    "Merits", "Admissibility", "Facts", "Operative part",
    "Operative Part", "Facts Proceedings", "Relevant legal framework",
])
HEADING_RE = re.compile(
    r"^[A-ZÉÀÈÙÂÊÎÔÛÇ0-9\s.()/,\"'""''–—:-]+$", re.UNICODE
)

def is_section_heading(text):
    t = (text or "").strip()
    return len(t) < 100 and bool(HEADING_RE.match(t))

ART41_PATTERNS = [
    "APPLICATION OF ARTICLE 41",
    "APPLICATION OF ARTICLE 50",
]
JS_HEADING_PATTERNS = ART41_PATTERNS + ["JUST SATISFACTION"]

print("=" * 80)
print("P1 VALIDATION: Just Satisfaction recovery")
print("=" * 80)

# ── PASS A: heading-paragraph counts ─────────────────────────────────────────
print("\n── PASS A: heading paragraphs currently in wrong sections ──\n")
print(f"  {'Pattern':<45} {'Section':<22} {'Count':>7}  Years")
print("  " + "-" * 85)

total_heading = 0
for pat in JS_HEADING_PATTERNS:
    cur.execute("""
        SELECT p.section,
               COUNT(*) as cnt,
               MIN(substr(c.judgment_date, 7, 4)) as yr_min,
               MAX(substr(c.judgment_date, 7, 4)) as yr_max
        FROM paragraphs p
        JOIN cases c ON c.case_id = p.case_id
        WHERE UPPER(p.text) LIKE ?
          AND length(p.text) < 80
          AND p.section NOT IN ('Just Satisfaction', 'Header', 'Introduction',
                                'Separate Opinion', 'Appendix')
        GROUP BY p.section
        ORDER BY cnt DESC
    """, (f"%{pat}%",))
    for r in cur.fetchall():
        if r["section"] in WRONG_SECTIONS:
            print(f"  '{pat:<43}'  {r['section']:<22} {r['cnt']:>7,}  {r['yr_min']}–{r['yr_max']}")
            total_heading += r["cnt"]

print(f"\n  TOTAL heading paragraphs (Pass A): {total_heading:,}")

# ── PASS B: content blocks in Population B (para_idx NOT NULL) ───────────────
print("\n── PASS B: content paragraphs after heading (Population B, ordered) ──")
print("   (paragraphs in same section following the Art.41 heading until next")
print("    section-level heading or section boundary)\n")

cur.execute("""
    SELECT DISTINCT p.case_id
    FROM paragraphs p
    WHERE UPPER(p.text) LIKE '%APPLICATION OF ARTICLE 41%'
      AND length(p.text) < 80
      AND p.section IN ('Merits', 'Admissibility', 'Facts Proceedings')
      AND p.para_idx IS NOT NULL
    ORDER BY p.case_id
""")
case_ids = [r[0] for r in cur.fetchall()]

section_stats = {}   # section -> {cases, content_paras}

cur2 = conn.cursor()
for case_id in case_ids:
    cur2.execute("""
        SELECT para_idx, section, text
        FROM paragraphs
        WHERE case_id = ? AND para_idx IS NOT NULL
        ORDER BY para_idx
    """, (case_id,))
    paras = cur2.fetchall()

    in_art41_section = False
    art41_db_section = None

    for p in paras:
        txt = (p["text"] or "").strip()
        upper = txt.upper()
        sec = p["section"]

        if not in_art41_section:
            if ("APPLICATION OF ARTICLE 41" in upper or "APPLICATION OF ARTICLE 50" in upper) \
               and len(txt) < 80 and sec in WRONG_SECTIONS:
                in_art41_section = True
                art41_db_section = sec
                st = section_stats.setdefault(sec, {"cases": set(), "content": 0})
                st["cases"].add(case_id)
        else:
            if sec != art41_db_section:
                # left the DB section
                in_art41_section = False
                art41_db_section = None
            elif is_section_heading(txt) and (
                "FOR THESE REASONS" in upper or
                "THE LAW" in upper or
                "ALLEGED VIOLATION" in upper or
                "ADMISSIBILITY" in upper
            ):
                # hit a different top-level heading -> stop
                in_art41_section = False
                art41_db_section = None
            else:
                section_stats[art41_db_section]["content"] += 1

total_content_b = 0
for sec, st in sorted(section_stats.items(), key=lambda x: -x[1]["content"]):
    n_cases = len(st["cases"])
    n_paras = st["content"]
    print(f"  {sec:<25} cases: {n_cases:>5,}  content paras after heading: {n_paras:>7,}")
    total_content_b += n_paras
print(f"\n  TOTAL content paragraphs (Pass B): {total_content_b:,}")

# ── PASS C: Population C (para_idx NULL) ─────────────────────────────────────
print("\n── PASS C: Population C (para_idx NULL) — heading paragraphs only ──\n")
cur.execute("""
    SELECT p.section,
           COUNT(DISTINCT p.case_id) as cases,
           COUNT(*) as paras
    FROM paragraphs p
    WHERE UPPER(p.text) LIKE '%APPLICATION OF ARTICLE 41%'
      AND length(p.text) < 80
      AND p.para_idx IS NULL
      AND p.section NOT IN ('Just Satisfaction')
    GROUP BY p.section
    ORDER BY paras DESC
""")
total_c = 0
for r in cur.fetchall():
    print(f"  {r['section']:<25} cases: {r['cases']:>5,}  paras: {r['paras']:>7,}")
    total_c += r["paras"]
print(f"\n  TOTAL (Pass C): {total_c:,}")

# ── SUMMARY ───────────────────────────────────────────────────────────────────
print("\n── SUMMARY ──\n")
print(f"  Pass A  heading paragraphs (all populations):   {total_heading:>8,}")
print(f"  Pass B  content paragraphs (Population B only): {total_content_b:>8,}")
print(f"  Pass C  heading paragraphs (Population C only): {total_c:>8,}")
print(f"  ─────────────────────────────────────────────────────────")
print(f"  Grand total paragraphs to relabel:              {total_heading + total_content_b:>8,}")
print(f"  (Pass A includes Pass C headings)")

# ── SPOT CHECK: 3 full examples ───────────────────────────────────────────────
print("\n── SPOT CHECK: 3 examples (Population B) ──")
cur.execute("""
    SELECT DISTINCT p.case_id, c.title
    FROM paragraphs p JOIN cases c ON c.case_id = p.case_id
    WHERE UPPER(p.text) LIKE '%APPLICATION OF ARTICLE 41%'
      AND length(p.text) < 80
      AND p.section = 'Merits'
      AND p.para_idx IS NOT NULL
    ORDER BY RANDOM()
    LIMIT 3
""")
examples = cur.fetchall()
cur3 = conn.cursor()
for ex in examples:
    print(f"\n  [{ex['case_id']}] {(ex['title'] or '')[:65]}")
    cur3.execute("""
        SELECT para_idx, section, substr(text, 1, 100) as t
        FROM paragraphs WHERE case_id = ? AND para_idx IS NOT NULL
        ORDER BY para_idx
    """, (ex["case_id"],))
    paras = cur3.fetchall()
    in_block = False
    shown = 0
    for p in paras:
        txt = (p["t"] or "").strip()
        sec = p["section"]
        upper = txt.upper()
        if not in_block and "APPLICATION OF ARTICLE 41" in upper and len(txt) < 80 and sec == "Merits":
            in_block = True
            print(f"    ¶{p['para_idx']:>4} [{sec}] HEADING ▶ {txt}")
            shown += 1
        elif in_block:
            if sec != "Merits":
                print(f"    ¶{p['para_idx']:>4} [{sec}] ← section boundary, STOP")
                break
            if shown < 4:
                print(f"    ¶{p['para_idx']:>4} [{sec}]         {txt[:95]}")
            shown += 1
    if in_block:
        print(f"    → {shown} paragraphs would move to Just Satisfaction")

conn.close()
print("\nDONE.")
