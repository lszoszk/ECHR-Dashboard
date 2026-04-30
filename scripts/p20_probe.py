"""Phase 2d: tighter R2 anti-prose."""
import sqlite3, re
from collections import Counter
DB = "/data/echr_search.db"
conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

RE_PROSE = re.compile(
    r"\b(?:the\s+Court\s+(?:considers|finds|holds|notes|reiterates|observes|concludes|recalls|points\s+out|examined|gave\s+a\s+judgment|decided\s+that|ordered|granted|awarded)"
    r"|applicant(?:s)?\s+(?:complained|alleged|submitted|claimed|argued|sought|maintained|requested|was\s+convicted|was\s+tried|was\s+sentenced|was\s+fined|was\s+detained|was\s+not|appealed|states|maintains|refers|stresses)"
    r"|(?:According|Pursuant)\s+to\s+the\s+applicant"
    r"|during\s+(?:his|her|the\s+applicant['']?s)\s+detention"
    r"|he\s+was\s+(?:detained|not\s+|provided|placed|taken|brought|arrested|kept|held)"
    r"|she\s+was\s+(?:detained|not\s+|provided|placed|taken|brought|arrested|kept|held)"
    r"|the\s+applicant\s+(?:was|had|did|has|stayed|spent|underwent)"
    r"|throughout\s+the\s+time"
    r"|Government(?:s)?\s+(?:contested|argued|submitted|maintained|claimed|considered|disputed|relied|raised\s+a)"
    r"|was\s+born\s+in\s+\d{4}|were\s+born\s+in\s+\d{4}"
    r"|is\s+a\s+(?:Russian|Ukrainian|Polish|German|French|British|Romanian|Bulgarian|Bosnian|Serbian|Croatian|Greek|Hungarian|Turkish|Italian|Slovak|Czech|Lithuanian|Latvian|Estonian|Albanian|Moldovan|Macedonian|Slovenian)\s+national"
    r"|on\s+\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}"
    r"|(?:Following|Pursuant\s+to|In\s+accordance\s+with)\s+(?:the\s+)?(?:amendment|regulation|provision)"
    r"|the\s+(?:national|domestic)\s+(?:minimum|maximum|standard|provisions)"
    r"|the\s+case\s+(?:originated|concerns|file)"
    r"|case\s+originated\s+in\s+(?:a|an|six)\s+application"
    r"|(?:see|see\s+also|see,\s+for\s+instance)\s+[A-Z][a-zA-Z]+\s+v\."
    r"|in\s+applications?\s+nos?\."
    r"|the\s+Chamber\s+(?:took|noted|held|considered)"
    r")",
    re.IGNORECASE,
)

RE_LEADING_NUM = re.compile(r"^\s*(?:[IVX]+\.|\d+\.)\s+")
RE_APPNO = re.compile(r"\b\d{4,5}/\d{2}\b")
RE_CAPS_SURNAME = re.compile(r"\b[A-ZÀ-ŸА-ЯĄĆĘŁŃÓŚŻŹÇŠŽĐČĆĞİÖÜ]{4,}\b")
RE_DATE = re.compile(r"\b\d{1,2}/\d{1,2}/\d{4}\b")
RE_M2 = re.compile(r"\b(?:m\s*²|m\s*2)(?:\s+(?:overcrowding|insufficient|lack))?", re.IGNORECASE)
RE_PRISON_TOKEN = re.compile(r"\b(overcrowding|infestation|bunk\s+beds|warm\s+water|passive\s+smoking|toiletries|hygienic\s+facilities|fresh\s+air|mouldy|natural\s+light|electric\s+light|cell\s+with|toilet|food\s+quality|food,\s+lack)\b", re.IGNORECASE)
RE_CAO_RUB = re.compile(r"\bArt(?:icle)?\.?\s*\d{1,2}\.\d{1,2}\s*§|\bof\s+CAO\b|\barticle\s+\d{1,2}\.\d{1,2}\s+§\s+\d", re.IGNORECASE)
RE_RUB_AMOUNT = re.compile(r"\bRUB\s+[\d,]+", re.IGNORECASE)
RE_COURT_NAME = re.compile(r"\b(?:City|Regional|District|Cantonal|Municipal|Town)\s+Court\b", re.IGNORECASE)
RE_DOB_FORMAT = re.compile(r"\b\d{2}/\d{2}/(?:19|20)\d{2}\b")

def classify(text):
    if not text: return None
    t = text.strip()
    L = len(t)
    if L < 30 or L > 1500: return None
    if RE_PROSE.search(t): return None
    has_leading_num = bool(RE_LEADING_NUM.match(t))
    has_appno = bool(RE_APPNO.search(t))
    has_caps = bool(RE_CAPS_SURNAME.search(t))
    has_date = bool(RE_DATE.search(t))
    has_m2 = bool(RE_M2.search(t))
    prison_count = len(RE_PRISON_TOKEN.findall(t))
    has_cao = bool(RE_CAO_RUB.search(t))
    has_rub = bool(RE_RUB_AMOUNT.search(t))
    has_court_name = bool(RE_COURT_NAME.search(t))
    has_dob = bool(RE_DOB_FORMAT.search(t))

    if has_cao and has_rub and (has_court_name or has_leading_num):
        return "R1_cao_admin"
    if (has_m2 or prison_count >= 3) and (has_appno or has_leading_num):
        return "R2_prison_cond"
    if has_appno and has_caps and has_leading_num and has_date:
        return "R4_appno_caps"
    if has_leading_num and has_dob and has_court_name and L < 250:
        return "R6_dob_city"
    return None

print("Scanning...")
cur.execute("""
    SELECT rowid, case_id, section, length(text) AS L, text FROM paragraphs
    WHERE section IN ('Introduction', 'Relevant legal framework', 'Facts', 'Merits',
                      'Facts Background', 'Facts Proceedings')
    AND text IS NOT NULL
""")
hits = {}
for r in cur.fetchall():
    res = classify(r["text"])
    if res:
        hits.setdefault(res, []).append((r["rowid"], r["case_id"], r["section"], r["L"], r["text"]))

print("\n=== Hits ===")
total = 0
for k in ("R1_cao_admin", "R2_prison_cond", "R4_appno_caps", "R6_dob_city"):
    n = len(hits.get(k, []))
    total += n
    print(f"  {k}: {n:,}")
print(f"  TOTAL: {total:,}")

all_hits = [h for v in hits.values() for h in v]
sec_counts = Counter(h[2] for h in all_hits)
print("\n=== By section ===")
for s, n in sec_counts.most_common():
    print(f"  {s}: {n:,}")

flagged = {1393560, 1562084, 1452133, 1559670, 1557745, 1790389, 1469570, 1585510,
           1429545, 1959301, 1406493, 1857075, 1831817, 1518586, 1551764, 1734188}
caught = {h[0] for v in hits.values() for h in v}
print(f"\nCaught {len(flagged & caught)}/{len(flagged)} audit-flagged")

# Sample 5 R2 to verify FP fixed
import random
random.seed(7)
print(f"\n=== R2_prison_cond ({len(hits.get('R2_prison_cond', [])):,}, sample 5) ===")
for rid, cid, sec, L, t in random.sample(hits.get("R2_prison_cond", []), 5):
    print(f"  [{rid}] sec={sec} len={L}: {t[:300]!r}")

import json
out = []
for rule, items in hits.items():
    for rid, cid, sec, L, t in items:
        out.append({"rowid": rid, "case_id": cid, "section": sec, "rule": rule})
with open("/tmp/rec5_pairs.json", "w") as f:
    json.dump(out, f)
print(f"\nSaved {len(out):,} pairs")
