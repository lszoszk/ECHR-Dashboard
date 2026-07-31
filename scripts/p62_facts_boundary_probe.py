#!/usr/bin/env python3
"""P62 probe — how far does an expanded heading vocabulary get us on the
PROCEDURE / CIRCUMSTANCES split?

Read-only. Answers one question before any LLM spend is committed:

    Of the 19,808 cases holding Facts-family paragraphs, how many carry a
    heading that marks where the administrative PROCEDURE block ends and the
    substantive narrative begins?

The April coverage sketch only looked for `PROCEDURE` and
`I. THE CIRCUMSTANCES OF THE CASE`, and left 5,306 cases (26.8%) with no
structural heading at all. This probe adds the boundary markers that the
corpus actually contains — `THE FACTS` (17,355 heading rows), `AS TO THE
FACTS`, and the pre-Protocol-11 Commission-era headings — and re-measures.

Any *one* facts-start marker is enough: within the Facts family, everything
before it is PROCEDURE and everything from it onward is CIRCUMSTANCES. So a
case is deterministically splittable if it has at least one such marker.

Run:  ssh amuvmuser@150.254.115.204 'docker exec -i echr-api python3 -' < p62_facts_boundary_probe.py
"""
import re
import sqlite3
from collections import Counter, defaultdict

DB = "/data/echr_search.db"
FACTS_SECTIONS = ("Facts", "Facts Background", "Facts Proceedings")

# ---------------------------------------------------------------- normalise

_LEAD_NUM = re.compile(r"^\s*(?:[IVXLC]+|[0-9]+|[A-Z])\s*[.)]\s*", re.I)
_WS = re.compile(r"\s+")


def norm(text):
    """Upper-case, collapse whitespace, strip leading numbering and trailing dots."""
    t = _WS.sub(" ", (text or "")).strip().upper()
    t = t.replace("’", "'").replace("‘", "'")
    prev = None
    while prev != t:                      # "I. A. FOO" -> "FOO"
        prev = t
        t = _LEAD_NUM.sub("", t)
    return t.strip(" .:")


# ------------------------------------------------------------------ markers
# Order matters: SUBJ is tested first because "FACTS AND PROCEDURE" would
# otherwise be caught by the PROC test.

FACTS_START_EXACT = {"THE FACTS", "AS TO THE FACTS", "FACTS"}
PROC_EXACT = {"PROCEDURE", "PROCEDURE AND FACTS", "AS TO THE PROCEDURE"}


def marker_class(h):
    """Return 'SUBJ' | 'FACTS_START' | 'PROC' | None for a normalised heading."""
    if "SUBJECT MATTER OF THE CASE" in h or h.startswith("FACTS AND PROCEDURE"):
        return "SUBJ"
    if h in FACTS_START_EXACT or "CIRCUMSTANCES OF THE CASE" in h:
        return "FACTS_START"
    if h in PROC_EXACT or "PROCEEDINGS BEFORE THE COMMISSION" in h:
        return "PROC"
    return None


# --------------------------------------------------------------------- load

conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
cur = conn.cursor()

ph = ",".join("?" * len(FACTS_SECTIONS))

# First marker of each class per case (earliest para_idx wins).
first = defaultdict(dict)            # case_id -> {cls: para_idx}
fired = Counter()                    # which literal heading fired, for the report
cur.execute(
    f"""SELECT case_id, para_idx, text FROM paragraphs
        WHERE section IN ({ph}) AND row_role LIKE 'heading%'
        ORDER BY case_id, para_idx""",
    FACTS_SECTIONS,
)
for case_id, para_idx, text in cur:
    h = norm(text)
    cls = marker_class(h)
    if cls is None:
        continue
    if cls not in first[case_id]:
        first[case_id][cls] = para_idx
        fired[(cls, h[:44])] += 1

# Facts-family paragraph index list per case.
counts = Counter()                   # case_id -> n facts paragraphs
idxs = defaultdict(list)
cur.execute(
    f"SELECT case_id, para_idx FROM paragraphs WHERE section IN ({ph})",
    FACTS_SECTIONS,
)
for case_id, para_idx in cur:
    counts[case_id] += 1
    idxs[case_id].append(para_idx)

# Era per case, for stratifying the residue.
# NB: `cases.judgment_date` is stored DD/MM/YYYY, not ISO — the year is the
# LAST four characters. Slicing the first four silently buckets every case by
# day-of-month instead (the same lexical trap fixed frontend-side in 13b487d).
_YEAR = re.compile(r"(\d{4})\s*$")

era = {}
for case_id, jd in cur.execute("SELECT case_id, judgment_date FROM cases"):
    m = _YEAR.search(jd or "")
    y = m.group(1) if m else ""
    if not y:
        era[case_id] = "9 unknown"
    elif y < "1995":
        era[case_id] = "1 pre1995"
    elif y < "2011":
        era[case_id] = "2 1995-2010"
    elif y < "2022":
        era[case_id] = "3 2011-2021"
    else:
        era[case_id] = "4 2022+"

# ---------------------------------------------------------------- classify

BUCKETS = {
    "A. committee subject_matter": "deterministic",
    "B. facts-start marker present": "deterministic",
    "C. PROC marker only (no end)": "needs boundary",
    "D. no structural heading": "needs boundary",
}
bucket_cases = Counter()
bucket_paras = Counter()
residue_era = Counter()
proc_len = []            # procedure-block length for bucket B, sanity check

for case_id, n in counts.items():
    m = first.get(case_id, {})
    if "SUBJ" in m:
        b = "A. committee subject_matter"
    elif "FACTS_START" in m:
        b = "B. facts-start marker present"
        cut = m["FACTS_START"]
        proc_len.append(sum(1 for i in idxs[case_id] if i < cut))
    elif "PROC" in m:
        b = "C. PROC marker only (no end)"
    else:
        b = "D. no structural heading"
    bucket_cases[b] += 1
    bucket_paras[b] += n
    if b.startswith(("C.", "D.")):
        residue_era[(b[:1], era.get(case_id, "9 unknown"))] += n

# ------------------------------------------------------------------ report

tc = sum(bucket_cases.values())
tp = sum(bucket_paras.values())

print("P62 — Facts-family boundary coverage with expanded heading vocabulary")
print("=" * 72)
print(f"{'bucket':32s} {'cases':>7s} {'':>7s} {'paragraphs':>11s}")
det_c = det_p = 0
for b in sorted(BUCKETS):
    cs, ps = bucket_cases[b], bucket_paras[b]
    if BUCKETS[b] == "deterministic":
        det_c += cs
        det_p += ps
    print(f"{b:32s} {cs:>7,} {100.0*cs/tc:>6.1f}% {ps:>11,} {100.0*ps/tp:>6.1f}%")
print("-" * 72)
print(f"{'TOTAL':32s} {tc:>7,} {'':>7s} {tp:>11,}")
print()
print(f"DETERMINISTIC (A+B):   {det_c:,} cases ({100.0*det_c/tc:.1f}%)   "
      f"{det_p:,} paragraphs ({100.0*det_p/tp:.1f}%)")
print(f"NEEDS BOUNDARY (C+D):  {tc-det_c:,} cases ({100.0*(tc-det_c)/tc:.1f}%)   "
      f"{tp-det_p:,} paragraphs ({100.0*(tp-det_p)/tp:.1f}%)")

print()
print("--- residue (C+D) by era ---")
for (b, e), ps in sorted(residue_era.items()):
    print(f"  {b}  {e:12s} {ps:>9,} paras")

print()
print("--- sanity check: PROCEDURE block length in bucket B ---")
print("    (HUDOC convention says ~5-15 short administrative paragraphs)")
if proc_len:
    proc_len.sort()
    n = len(proc_len)
    for label, q in (("p10", 0.10), ("median", 0.50), ("p90", 0.90), ("p99", 0.99)):
        print(f"    {label:7s} {proc_len[min(n-1, int(q*n))]:>5,}")
    print(f"    zero-length (marker is first row): "
          f"{sum(1 for x in proc_len if x == 0):,} / {n:,}")

print()
print("--- markers that fired (top 25) ---")
for (cls, h), n in fired.most_common(25):
    print(f"  {n:>7,}  {cls:12s} {h}")

conn.close()
