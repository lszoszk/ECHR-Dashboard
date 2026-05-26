"""
Analyze ECHR judgment section structures across years.
Samples 10 random cases per year, extracts section sequences,
and identifies structural patterns/changes over time.
"""
import sqlite3
import json
import random
from collections import Counter, defaultdict

DB_PATH = "/data/echr_search.db"

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# Group years into periods for analysis
# Focus on: early (pre-1998 old Court), transition (1998-2001),
# modern early (2002-2010), modern late (2011-2025)
# Sample from representative years in each era

SAMPLE_YEARS = [
    # Pre-Protocol 11 (old Court + Commission)
    1975, 1980, 1985, 1990, 1995,
    # Transition to new permanent Court (Nov 1998)
    1998, 1999, 2000, 2001,
    # Modern era
    2003, 2005, 2007, 2010,
    2013, 2015, 2018, 2020, 2023, 2025,
]

print("=" * 100)
print("ECHR JUDGMENT SECTION STRUCTURE ANALYSIS")
print("=" * 100)

# For each year, get 10 random cases and their section structure
for year in SAMPLE_YEARS:
    cur.execute("""
        SELECT case_id, title, judgment_date
        FROM cases
        WHERE substr(judgment_date, 7, 4) = ?
        ORDER BY RANDOM() LIMIT 10
    """, (str(year),))
    cases = cur.fetchall()

    if not cases:
        print(f"\n{'─' * 100}")
        print(f"YEAR {year}: NO CASES")
        continue

    print(f"\n{'━' * 100}")
    print(f"YEAR {year} — {len(cases)} sampled cases")
    print(f"{'━' * 100}")

    section_sequences = []

    for i, case in enumerate(cases):
        case_id = case["case_id"]
        title = case["title"] or "Untitled"
        date = case["judgment_date"] or "?"

        # Get all paragraphs for this case, ordered by para_idx
        cur.execute("""
            SELECT section, para_idx, substr(text, 1, 120) as text_preview
            FROM paragraphs
            WHERE case_id = ?
            ORDER BY para_idx
        """, (case_id,))
        paras = cur.fetchall()

        # Build section sequence (unique, in order of first appearance)
        seen = set()
        section_seq = []
        section_ranges = {}

        for p in paras:
            sec = p["section"]
            idx = p["para_idx"]
            if sec not in seen:
                seen.add(sec)
                section_seq.append(sec)
                section_ranges[sec] = {"start": idx, "end": idx, "count": 1}
            else:
                section_ranges[sec]["end"] = idx
                section_ranges[sec]["count"] += 1

        section_sequences.append(tuple(section_seq))

        # Print case details
        short_title = title[:70] + ("…" if len(title) > 70 else "")
        print(f"\n  [{i+1}] {short_title}")
        print(f"      Date: {date} | ID: {case_id} | Total ¶: {len(paras)}")
        print(f"      Sections ({len(section_seq)}):")

        for sec in section_seq:
            r = section_ranges[sec]
            s = r['start'] if r['start'] is not None else -1
            e = r['end'] if r['end'] is not None else -1
            print(f"        {sec:<25} ¶{s:>4}–{e:<4}  ({r['count']} paras)")

        # Show first 2 paragraphs of each section to identify misclassification
        print(f"      ── First paragraphs per section ──")
        shown_sections = set()
        for p in paras:
            sec = p["section"]
            if sec not in shown_sections:
                shown_sections.add(sec)
                preview = (p["text_preview"] or "").replace("\n", " ").strip()
                print(f"        [{sec}] ¶{p['para_idx']}: {preview[:100]}{'…' if len(preview) > 100 else ''}")

    # Summary of section patterns for this year
    seq_counter = Counter(section_sequences)
    print(f"\n  ── Year {year} Pattern Summary ──")
    for seq, count in seq_counter.most_common(5):
        print(f"    {count}x: {' → '.join(seq)}")

# Global analysis: section presence by year
print(f"\n{'━' * 100}")
print("SECTION PRESENCE BY YEAR (% of cases)")
print(f"{'━' * 100}")

all_years = sorted(set(str(y) for y in range(1960, 2027)))
sections_of_interest = [
    "Header", "Introduction", "Facts Background", "Facts Proceedings",
    "Legal Framework", "Legal Context", "Admissibility", "Merits",
    "Just Satisfaction", "Article 46", "Operative Part", "Separate Opinion", "Appendix"
]

# Sample more years for the trend analysis
for decade_start in range(1960, 2030, 5):
    yr = str(decade_start)
    cur.execute("""
        SELECT COUNT(DISTINCT c.case_id) as total
        FROM cases c
        WHERE substr(c.judgment_date, 7, 4) = ?
    """, (yr,))
    total = cur.fetchone()[0]
    if total == 0:
        continue

    presence = {}
    for sec in sections_of_interest:
        cur.execute("""
            SELECT COUNT(DISTINCT p.case_id)
            FROM paragraphs p
            JOIN cases c ON c.case_id = p.case_id
            WHERE substr(c.judgment_date, 7, 4) = ? AND p.section = ?
        """, (yr, sec))
        cnt = cur.fetchone()[0]
        presence[sec] = round(100 * cnt / total) if total else 0

    row = f"  {yr} (n={total:>4}): "
    for sec in sections_of_interest:
        pct = presence.get(sec, 0)
        marker = "█" if pct > 80 else "▓" if pct > 50 else "░" if pct > 10 else "·"
        row += f" {marker}{pct:>3}%"
    print(row)

print(f"\n  Legend: {'  '.join(s[:8] for s in sections_of_interest)}")

# Check for paragraphs that look like section headers but are misclassified
print(f"\n{'━' * 100}")
print("POTENTIAL SECTION HEADER MISCLASSIFICATIONS")
print("(Paragraphs containing known section header patterns)")
print(f"{'━' * 100}")

header_patterns = [
    ("AS TO THE LAW", "should be Merits or separate section"),
    ("THE LAW", "should be Merits/Law section"),
    ("THE FACTS", "should be Facts"),
    ("AS TO THE FACTS", "should be Facts"),
    ("PROCEDURE", "should be Procedure/Facts Proceedings"),
    ("ALLEGED VIOLATION", "should be Merits"),
    ("FOR THESE REASONS", "should be Operative Part"),
    ("OPERATIVE PROVISIONS", "should be Operative Part"),
    ("JUST SATISFACTION", "should be Just Satisfaction"),
    ("APPLICATION OF ARTICLE 50", "old-style Just Satisfaction"),
    ("APPLICATION OF ARTICLE 41", "Just Satisfaction"),
    ("DISSENTING OPINION", "should be Separate Opinion"),
    ("CONCURRING OPINION", "should be Separate Opinion"),
    ("JOINT DISSENTING", "should be Separate Opinion"),
    ("PARTLY DISSENTING", "should be Separate Opinion"),
]

for pattern, note in header_patterns:
    cur.execute("""
        SELECT p.section, COUNT(*) as cnt,
               MIN(substr(c.judgment_date, 7, 4)) as yr_min,
               MAX(substr(c.judgment_date, 7, 4)) as yr_max
        FROM paragraphs p
        JOIN cases c ON c.case_id = p.case_id
        WHERE UPPER(p.text) LIKE ?
        AND length(p.text) < 80
        GROUP BY p.section
        ORDER BY cnt DESC
    """, (f"%{pattern}%",))
    rows = cur.fetchall()
    if rows:
        print(f'\n  "{pattern}" ({note}):')
        for r in rows:
            print(f"    Currently in [{r[0]}]: {r[1]} occurrences ({r[2]}–{r[3]})")

conn.close()
