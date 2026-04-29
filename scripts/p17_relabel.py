"""
P17 RELABEL: Representation paragraphs in Facts → Introduction.

Recall-audit Rec-4 (medium-confidence): "The Government were represented
by their Agent" / "The applicant was represented by ..." paragraphs that
appear in Facts / Facts Background / Facts Proceedings should be in
Introduction.

Background context:
  - 7,088 representation paragraphs (3.8% of Introduction) ALREADY sit in
    `Introduction` — predominantly older Pop A/B cases where the Court's
    pre-2009 PROCEDURE block put representation directly in the intro.
  - In modern Chamber format (post-2020-ish), the Court structure is:
      INTRODUCTION
      1. The case concerns ...
      THE FACTS
      2. The applicant was born in [year] and lives in [city]. They were
         represented by Ms X, a lawyer practising in [city].
      3. The Government were represented by their Agent, Mr Y.
      I. THE CIRCUMSTANCES OF THE CASE
      4. The facts of the case may be summarised as follows.
  - The segmenter labelled paragraphs 2-3 as `Facts Background` because
    they appear under "THE FACTS" header. The recall audit (medium
    confidence) considers this a misclassification: representation is
    procedural metadata, not "facts of the case".
  - Of 500 sampled gov-rep paragraphs in Facts/etc, 89% are in cases that
    already have an Introduction section — so we are merging adjacent
    procedural metadata with the existing Introduction.

Detection rules (paragraph in Facts / Facts Background / Facts Proceedings):

  R1 — Gov-rep alone, short paragraph
       Pattern:
         (?:^|\\.\\s+)(?:The\\s+)?Government(?:s)?\\s+(?:was|were|is|are)\\s+
         represented\\s+by\\s+
       Length: < 300
       Risk: very low — this exact phrasing only appears in procedural
       intro context (Government's representation of itself before ECHR).
       Domestic court narratives don't use "Government were represented".

  R2 — Pure gov+app rep, short paragraph
       Pattern: BOTH gov-rep AND applicant-rep regex match
       Length: < 500
       Risk: very low — same phrasing constraints as R1.

Rejected pattern:
  R3 — App-only rep
       Pattern: applicant-rep alone
       REJECTED because of FP risk: "the applicant was represented by
       a State-appointed lawyer" appears legitimately in Facts narrative
       describing domestic proceedings (e.g. "On 11 July 2004 the police
       arrested the applicant. The applicant was represented by K., a
       State-appointed lawyer."). Cannot reliably distinguish without
       semantic analysis.

Target: Introduction (no casing variants).

Usage:
  python p17_relabel.py            # dry-run
  python p17_relabel.py --apply    # commit
"""
import sqlite3
import sys
import re

DRY_RUN = "--apply" not in sys.argv
DB = "/data/echr_search.db"

P_GOV = re.compile(
    r"(?:^|\.\s+)(?:The\s+)?Government(?:s)?\s+(?:was|were|is|are)\s+represented\s+by\s+",
    re.IGNORECASE,
)
P_APP = re.compile(
    r"(?:^|\.\s+)(?:The\s+)?applicant(?:s)?\s+(?:was|were|is|are)\s+represented\s+by\s+",
    re.IGNORECASE,
)

MAX_LEN_R1 = 300
MAX_LEN_R2 = 500

def classify(text):
    """Return 'Introduction' or None."""
    if not text:
        return None
    t = text.strip()
    L = len(t)

    has_gov = bool(P_GOV.search(t))
    has_app = bool(P_APP.search(t))

    # R2: pure gov+app paragraph (both representation patterns)
    if has_gov and has_app and L < MAX_LEN_R2:
        return "Introduction"

    # R1: gov-rep alone, short paragraph
    if has_gov and L < MAX_LEN_R1:
        return "Introduction"

    return None

if DRY_RUN:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
else:
    conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

print("Scanning Facts / Facts Background / Facts Proceedings...")
cur.execute("""
    SELECT rowid, case_id, section, text
    FROM paragraphs
    WHERE section IN ('Facts', 'Facts Background', 'Facts Proceedings')
""")

relabels = {}
rule_counts = {"R1_gov_only": 0, "R2_gov_and_app": 0}
sec_counts = {"Facts": 0, "Facts Background": 0, "Facts Proceedings": 0}

for r in cur.fetchall():
    target = classify(r["text"])
    if target is None:
        continue
    relabels[r["rowid"]] = target
    sec_counts[r["section"]] = sec_counts.get(r["section"], 0) + 1
    t = (r["text"] or "").strip()
    has_app = bool(P_APP.search(t))
    if has_app and len(t) < MAX_LEN_R2:
        rule_counts["R2_gov_and_app"] += 1
    else:
        rule_counts["R1_gov_only"] += 1

print(f"\nTotal candidates: {len(relabels):,}")
for k, v in rule_counts.items():
    print(f"  {k}: {v:,}")
print(f"\nBy origin section:")
for s, n in sec_counts.items():
    print(f"  {s}: {n:,}")

# Spot check 5 per rule
import random
random.seed(17)
buckets = {"R1": [], "R2": []}
for rid in relabels:
    cur.execute("SELECT case_id, section, length(text) AS L, substr(text,1,300) AS p FROM paragraphs WHERE rowid=?", (rid,))
    row = cur.fetchone()
    cur.execute("SELECT text FROM paragraphs WHERE rowid=?", (rid,))
    text_full = (cur.fetchone()[0] or "").strip()
    has_app = bool(P_APP.search(text_full))
    L = len(text_full)
    if has_app and L < MAX_LEN_R2:
        buckets["R2"].append((rid, row["case_id"], row["section"], row["L"], row["p"]))
    else:
        buckets["R1"].append((rid, row["case_id"], row["section"], row["L"], row["p"]))

for rule in ["R1", "R2"]:
    items = buckets[rule]
    if not items: continue
    sample_n = min(5, len(items))
    print(f"\n--- {rule} ({len(items):,} hits, showing {sample_n}) ---")
    for rid, cid, sec, L, p in random.sample(items, sample_n):
        print(f"  [{rid}] sec={sec} case={cid} len={L}")
        print(f"  {p}")

if DRY_RUN:
    print("\nDRY-RUN — no changes written. Run with --apply to commit.")
    conn.close()
    sys.exit(0)

# === APPLY ===
print("\nAPPLYING...")
cur.execute("DROP TABLE IF EXISTS _p17_backup")
rowid_list = list(relabels.keys())
cur.execute("CREATE TABLE _p17_backup (rowid INTEGER PRIMARY KEY, section TEXT, numbering_block TEXT)")
BATCH = 5000
for start in range(0, len(rowid_list), BATCH):
    chunk = rowid_list[start:start+BATCH]
    cur.execute(f"""
        INSERT INTO _p17_backup (rowid, section, numbering_block)
        SELECT rowid, section, numbering_block FROM paragraphs
        WHERE rowid IN ({','.join(str(r) for r in chunk)})
    """)
conn.commit()
print(f"Backup _p17_backup: {cur.execute('SELECT COUNT(*) FROM _p17_backup').fetchone()[0]:,} rows")

conn.execute("BEGIN")
total = 0
for start in range(0, len(rowid_list), BATCH):
    batch = rowid_list[start:start+BATCH]
    conn.execute(
        f"UPDATE paragraphs SET section = 'Introduction', numbering_block = 'main_judgment' "
        f"WHERE rowid IN ({','.join(str(r) for r in batch)})"
    )
    total += len(batch)
conn.commit()
print(f"COMMITTED. {total:,} paragraphs relabeled.")

print("\n=== Final counts ===")
for sec in ("Introduction", "Facts", "Facts Background", "Facts Proceedings"):
    cur.execute("SELECT COUNT(*) FROM paragraphs WHERE section=?", (sec,))
    print(f"  {sec:<22} {cur.fetchone()[0]:>10,}")

conn.close()
print("DONE.")
