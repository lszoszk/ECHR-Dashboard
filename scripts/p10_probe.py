"""P10 probe: verify HUDOC paragraph number extraction rule."""
import sqlite3
import re
from collections import Counter, defaultdict

DB = "/data/echr_search.db"
conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# Candidate regex: number + period + whitespace at paragraph start
HUDOC_RE = re.compile(r"^\s*(\d+)\.\s+", re.IGNORECASE)

# Patterns that LOOK like numbers but should NOT be extracted:
# - "(a) that..." sub-clause format
# - "A. Damage" letter sub-section
# - "I. ALLEGED VIOLATION" Roman numeral
# - "1)" closing paren format
SHOULDNT_EXTRACT = re.compile(
    r"^\s*(\([a-z]\)|\([ivxIVX]+\)|[A-Z]\.\s|[IVX]+\.\s|\d+\))",
)

# 1. Coverage by population & section (Python-side regex matching)
print("=== Coverage by population × section ===\n")
cur.execute("SELECT section, para_idx IS NULL AS pop_c, text FROM paragraphs")
section_counts = defaultdict(lambda: [0, 0])  # [total, matched]
for r in cur.fetchall():
    sec = r["section"]
    pop = "C" if r["pop_c"] else "AB"
    key = (pop, sec)
    section_counts[key][0] += 1
    if HUDOC_RE.match(r["text"] or ""):
        section_counts[key][1] += 1

print(f"{'POP':<4} {'SECTION':<28} {'TOTAL':>10} {'MATCHED':>10} {'%':>6}")
print("-" * 64)
for (pop, sec), (tot, mat) in sorted(section_counts.items(), key=lambda x: (x[0][0], -x[1][0])):
    pct = 100.0 * mat / tot if tot else 0
    print(f"{pop:<4} {sec:<28} {tot:>10,} {mat:>10,} {pct:>5.1f}%")

# Overall
total = sum(t for t, _ in section_counts.values())
matched = sum(m for _, m in section_counts.values())
print(f"\n  TOTAL: {total:,} | matched: {matched:,} ({100*matched/total:.1f}%)")

# 2. Distribution of extracted numbers — sanity check (should mostly be 1-300)
print("\n=== Distribution of extracted numbers ===")
extracted = []
cur.execute("SELECT text FROM paragraphs WHERE text IS NOT NULL")
for r in cur.fetchall():
    m = HUDOC_RE.match(r["text"])
    if m:
        n = int(m.group(1))
        if n < 10000:  # filter obviously-not-paragraph-numbers
            extracted.append(n)

if extracted:
    extracted.sort()
    print(f"  count: {len(extracted):,}")
    print(f"  min: {extracted[0]}  max: {extracted[-1]}  median: {extracted[len(extracted)//2]}")
    print(f"  P95: {extracted[int(len(extracted)*0.95)]}  P99: {extracted[int(len(extracted)*0.99)]}")
    # Buckets
    bucket = Counter()
    for n in extracted:
        if n <= 10: b = "1-10"
        elif n <= 50: b = "11-50"
        elif n <= 100: b = "51-100"
        elif n <= 200: b = "101-200"
        elif n <= 500: b = "201-500"
        else: b = "500+"
        bucket[b] += 1
    print("\n  Bucket distribution:")
    for b in ["1-10", "11-50", "51-100", "101-200", "201-500", "500+"]:
        print(f"    {b:<10} {bucket[b]:>10,}  {100*bucket[b]/len(extracted):>5.1f}%")

# 3. False-positive risk: extracted number > 1000 or > 10000
print("\n=== Suspicious extractions (number > 1000) ===")
big = [(n, t[:120]) for n in extracted if n > 1000 for t in [None]]
# Re-collect with text for spot-check
big_samples = []
cur.execute("SELECT case_id, para_idx, substr(text,1,200) FROM paragraphs WHERE text IS NOT NULL")
for r in cur.fetchall():
    m = HUDOC_RE.match(r[2] or "")
    if m and int(m.group(1)) > 1000:
        big_samples.append((r[0], r[1], int(m.group(1)), r[2]))
        if len(big_samples) >= 5:
            break

print(f"  Total: {len([n for n in extracted if n > 1000]):,} paragraphs with extracted N > 1000")
print(f"  Samples (first 5):")
for cid, pidx, n, t in big_samples:
    print(f"    case={cid} para_idx={pidx} extracted={n}: {t[:100]}")

# 4. Sample 30 paragraphs across sections, manually verify
print("\n=== 30 random samples (5 per population/section bucket) ===")
import random
random.seed(42)
buckets = [
    ("Pop A/B Merits", "section='Merits' AND para_idx IS NOT NULL"),
    ("Pop A/B Facts Proceedings", "section='Facts Proceedings' AND para_idx IS NOT NULL"),
    ("Pop A/B Just Satisfaction", "section='Just Satisfaction' AND para_idx IS NOT NULL"),
    ("Pop A/B Operative Part", "section='Operative Part' AND para_idx IS NOT NULL"),
    ("Pop A/B Separate Opinion", "section='Separate Opinion'"),
    ("Pop C Facts", "section='Facts' AND para_idx IS NULL"),
]
for label, where in buckets:
    cur.execute(f"SELECT case_id, section, substr(text, 1, 150) AS t FROM paragraphs WHERE {where} ORDER BY RANDOM() LIMIT 5")
    print(f"\n--- {label} ---")
    for r in cur.fetchall():
        t = (r["t"] or "").replace("\n", " ").strip()
        m = HUDOC_RE.match(t)
        extracted_n = m.group(1) if m else "(none)"
        suspicious = " [⚠]" if SHOULDNT_EXTRACT.match(t) and m else ""
        print(f"  → extracted={extracted_n}{suspicious}: {t[:120]}")

conn.close()
print("\nDONE.")
