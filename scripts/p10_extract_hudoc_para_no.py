"""
P10 EXTRACT: extract HUDOC paragraph numbers from text into hudoc_para_no column.

Rule:
  1. Match `^\s*(\d+)\.\s+` regex at paragraph start
  2. Reject N=0 (HUDOC numbering starts at 1)
  3. Reject N > max(2 * case_paragraph_count, 200)
     - Numbers larger than reasonable for the case are likely money amounts,
       law numbers, dates, table data — not paragraph numbers.
     - Floor of 200 prevents over-rejection in tiny cases where a paragraph
       legitimately has number > paragraph count (rare but possible).

Usage:
  python p10_extract.py            # dry-run with stats
  python p10_extract.py --apply    # add column + populate
"""
import sqlite3
import sys
import re
from collections import defaultdict

DRY_RUN = "--apply" not in sys.argv
DB = "/data/echr_search.db"

HUDOC_RE = re.compile(r"^\s*(\d+)\.\s+")

if DRY_RUN:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
else:
    conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# 1. Pre-compute paragraph count per case
print("Computing per-case paragraph counts...")
cur.execute("SELECT case_id, COUNT(*) FROM paragraphs GROUP BY case_id")
case_para_count = dict(cur.fetchall())
print(f"  {len(case_para_count):,} cases")

# 2. Walk all paragraphs, extract candidates
print("Extracting paragraph numbers...")
matches = {}        # rowid -> int
rejected_zero = 0
rejected_too_big = 0
matched_total = 0
no_match = 0

cur.execute("SELECT rowid, case_id, text FROM paragraphs")
for r in cur.fetchall():
    text = r["text"]
    if not text:
        no_match += 1
        continue
    m = HUDOC_RE.match(text)
    if not m:
        no_match += 1
        continue
    n = int(m.group(1))
    matched_total += 1
    if n < 1:
        rejected_zero += 1
        continue
    case_count = case_para_count.get(r["case_id"], 100)
    cap = max(2 * case_count, 200)
    if n > cap:
        rejected_too_big += 1
        continue
    matches[r["rowid"]] = n

print(f"\n  raw regex matches:          {matched_total:>10,}")
print(f"  rejected N=0:               {rejected_zero:>10,}")
print(f"  rejected N>cap:             {rejected_too_big:>10,}")
print(f"  ACCEPTED (will populate):   {len(matches):>10,}")
print(f"  no regex match:             {no_match:>10,}")
print(f"  total paragraphs:           {matched_total + no_match:>10,}")
print(f"  coverage:                   {100*len(matches)/(matched_total+no_match):.1f}%")

# 3. Distribution check
print("\n--- Distribution of extracted numbers ---")
buckets = defaultdict(int)
for n in matches.values():
    if n <= 10: buckets["1-10"] += 1
    elif n <= 50: buckets["11-50"] += 1
    elif n <= 100: buckets["51-100"] += 1
    elif n <= 200: buckets["101-200"] += 1
    elif n <= 500: buckets["201-500"] += 1
    elif n <= 1000: buckets["501-1000"] += 1
    else: buckets["1000+"] += 1
for b in ["1-10", "11-50", "51-100", "101-200", "201-500", "501-1000", "1000+"]:
    n = buckets[b]
    print(f"  {b:<10} {n:>10,}  {100*n/len(matches):>5.1f}%")

# 4. Coverage by section
print("\n--- Coverage by section ---")
cur.execute("SELECT rowid, section FROM paragraphs")
sec_total = defaultdict(int)
sec_matched = defaultdict(int)
for r in cur.fetchall():
    sec_total[r["section"]] += 1
    if r["rowid"] in matches:
        sec_matched[r["section"]] += 1

print(f"  {'SECTION':<28} {'TOTAL':>10} {'MATCHED':>10} {'%':>6}")
for sec in sorted(sec_total, key=lambda s: -sec_total[s]):
    tot = sec_total[sec]
    mat = sec_matched[sec]
    print(f"  {sec:<28} {tot:>10,} {mat:>10,} {100*mat/tot if tot else 0:>5.1f}%")

# 5. Spot check — was N=5275 case correctly rejected?
print("\n--- Spot check: false-positive rejection ---")
# Probably-rejected examples from probe2:
test_cases = [
    ("001-228359", 5275),  # "5275. Proceedings brought" — should be rejected
    ("001-235139", 1000),  # Ukraine v Russia — 1000 should be ACCEPTED (case has ~1474 paras)
    ("001-244292", 998),   # Ukraine vs Netherlands — should be ACCEPTED (1834 paras)
    ("001-247133", 0),     # "0. 1,200" — should be rejected (N=0)
]
for cid, n in test_cases:
    cnt = case_para_count.get(cid, 0)
    cap = max(2 * cnt, 200)
    rejected = n < 1 or n > cap
    status = "REJECTED" if rejected else "accepted"
    print(f"  case={cid} N={n} (case has {cnt} paras, cap={cap}) → {status}")

if DRY_RUN:
    print("\nDRY-RUN — no schema/data changes. Run with --apply to commit.")
    conn.close()
    sys.exit(0)

# === APPLY ===
print("\nAPPLYING...")
print("Adding hudoc_para_no column...")
try:
    cur.execute("ALTER TABLE paragraphs ADD COLUMN hudoc_para_no INTEGER")
    conn.commit()
    print("  Column added.")
except sqlite3.OperationalError as e:
    if "duplicate column" in str(e).lower():
        print("  Column already exists, continuing.")
    else:
        raise

# No need for backup since we're only ADDING data, not overwriting any existing values
# (column starts NULL and we set non-NULL values where we have confidence).

print(f"Populating {len(matches):,} rows...")
BATCH = 5000
rowid_n_pairs = list(matches.items())
done = 0
conn.execute("BEGIN")
for start in range(0, len(rowid_n_pairs), BATCH):
    batch = rowid_n_pairs[start:start+BATCH]
    # use executemany for efficiency
    conn.executemany(
        "UPDATE paragraphs SET hudoc_para_no = ? WHERE rowid = ?",
        [(n, rid) for rid, n in batch]
    )
    done += len(batch)
    if done % 100000 == 0:
        print(f"  ... {done:,} / {len(rowid_n_pairs):,}")
conn.commit()
print(f"  done. {done:,} updates committed.")

# Verify
cur.execute("SELECT COUNT(*) FROM paragraphs WHERE hudoc_para_no IS NOT NULL")
populated = cur.fetchone()[0]
print(f"\n  hudoc_para_no populated: {populated:,}")
cur.execute("SELECT COUNT(*) FROM paragraphs")
total = cur.fetchone()[0]
print(f"  total paragraphs: {total:,}")
print(f"  coverage: {100*populated/total:.1f}%")

# Sanity: a few samples
print("\n  Sample populated rows (random 5):")
cur.execute("""
    SELECT case_id, section, para_idx, hudoc_para_no, substr(text, 1, 100) AS t
    FROM paragraphs WHERE hudoc_para_no IS NOT NULL
    ORDER BY RANDOM() LIMIT 5
""")
for r in cur.fetchall():
    print(f"    case={r['case_id']} idx={r['para_idx']} hudoc={r['hudoc_para_no']}: {r['t']}")

conn.close()
print("\nDONE.")
