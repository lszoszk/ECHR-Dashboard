"""
P20 RELABEL: Pop C mass-applicant table rows → Appendix.

Recall-audit-v2 Rec-5. Detects 4 high-confidence patterns of mass-
applicant table rows currently misclassified as Introduction / Relevant
legal framework / Facts / Merits / Facts Background / Facts Proceedings.

Rules (anti-prose filter applied first to all):

  R1 — CAO admin offense table row (Russian Anti-war/Free Navalnyy etc.)
       Pattern: contains CAO article reference AND RUB amount AND
                (City/Regional/District/Cantonal/Municipal/Town Court OR leading num)
       Length 30–1500.

  R2 — Prison conditions table row
       Pattern: m² OR 3+ prison-condition tokens (overcrowding, infestation,
                bunk beds, warm water, passive smoking, mouldy, hygienic,
                fresh air, cell with, food quality)
       AND (appno OR leading num).

  R4 — Numbered + appno + CAPS surname + date
       Bosnian/Serbian/Greek/Russian/Ukrainian Committee mass-app rows.

  R6 — Numbered + DOB + court name (short)
       Length < 250.

LLM precision audit (Sonnet 4.6, 100 stratified samples):
  Overall 97/98 = 99.0% precision; per-rule R1 100% / R2 96% / R4 100% /
  R6 100%.

Conservative — does not propagate. Each paragraph judged on its own.

Backup table _p20_backup with rowid + section + numbering_block.

Usage:
  python p20_apply.py            # dry-run
  python p20_apply.py --apply    # commit
"""
import sqlite3, sys, re

DRY_RUN = "--apply" not in sys.argv
DB = "/data/echr_search.db"

RE_PROSE = re.compile(
    r"\b(?:the\s+Court\s+(?:considers|finds|holds|notes|reiterates|observes|concludes|recalls|points\s+out|examined|gave\s+a\s+judgment|decided\s+that|ordered|granted|awarded)"
    r"|applicant(?:s)?\s+(?:complained|alleged|submitted|claimed|argued|sought|maintained|requested|was\s+convicted|was\s+tried|was\s+sentenced|was\s+fined|was\s+detained|was\s+not|appealed|states|maintains|refers|stresses)"
    r"|(?:According|Pursuant)\s+to\s+the\s+applicant"
    r"|during\s+(?:his|her|the\s+applicant['']?s)\s+detention"
    r"|he\s+was\s+(?:detained|not\s+|provided|placed|taken|brought|arrested|kept|held)"
    r"|she\s+was\s+(?:detained|not\s+|provided|placed|taken|brought|arrested|kept|held)"
    r"|the\s+applicant\s+(?:was|had|did|has|stayed|spent|underwent)"
    r"|throughout\s+the\s+time"
    r"|Government(?:s)?\s+(?:contested|argued|submitted|maintained|claimed|considered|disputed|relied|raised\s+a|contended|stated)"
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

if DRY_RUN:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
else:
    conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

print("Scanning candidate sections...")
cur.execute("""
    SELECT rowid, case_id, section, text FROM paragraphs
    WHERE section IN ('Introduction', 'Relevant legal framework', 'Facts', 'Merits',
                      'Facts Background', 'Facts Proceedings')
    AND text IS NOT NULL
""")

relabels = {}
rule_counts = {"R1_cao_admin": 0, "R2_prison_cond": 0, "R4_appno_caps": 0, "R6_dob_city": 0}
sec_counts = {}
for r in cur.fetchall():
    res = classify(r["text"])
    if res:
        relabels[r["rowid"]] = res
        rule_counts[res] += 1
        sec_counts[r["section"]] = sec_counts.get(r["section"], 0) + 1

print(f"\nTotal: {len(relabels):,}")
for k, v in rule_counts.items():
    print(f"  {k}: {v:,}")
print(f"\nBy origin section:")
for s, n in sorted(sec_counts.items(), key=lambda x: -x[1]):
    print(f"  {s}: {n:,}")

if DRY_RUN:
    print("\nDRY-RUN — no changes written.")
    conn.close()
    sys.exit(0)

print("\nAPPLYING...")
cur.execute("DROP TABLE IF EXISTS _p20_backup")
cur.execute("CREATE TABLE _p20_backup (rowid INTEGER PRIMARY KEY, section TEXT, numbering_block TEXT, rule TEXT)")
rowid_list = list(relabels.keys())
BATCH = 5000
for start in range(0, len(rowid_list), BATCH):
    chunk = rowid_list[start:start+BATCH]
    rule_map = {rid: relabels[rid] for rid in chunk}
    # Backup
    cur.execute(f"""
        INSERT INTO _p20_backup (rowid, section, numbering_block, rule)
        SELECT rowid, section, numbering_block, ? FROM paragraphs
        WHERE rowid IN ({','.join(str(r) for r in chunk)})
    """, ('mixed',))
conn.commit()
# Update rule column per-row (mixed placeholder above; correct it now)
for rid, rule in relabels.items():
    cur.execute("UPDATE _p20_backup SET rule = ? WHERE rowid = ?", (rule, rid))
conn.commit()
print(f"Backup _p20_backup: {cur.execute('SELECT COUNT(*) FROM _p20_backup').fetchone()[0]:,}")

conn.execute("BEGIN")
total = 0
for start in range(0, len(rowid_list), BATCH):
    batch = rowid_list[start:start+BATCH]
    conn.execute(
        f"UPDATE paragraphs SET section = 'Appendix', numbering_block = 'main_judgment' "
        f"WHERE rowid IN ({','.join(str(r) for r in batch)})"
    )
    total += len(batch)
conn.commit()
print(f"COMMITTED. {total:,} paragraphs relabeled.")

print("\n=== Final counts ===")
for sec in ("Introduction", "Relevant legal framework", "Facts", "Merits", "Facts Background", "Facts Proceedings", "Appendix"):
    cur.execute("SELECT COUNT(*) FROM paragraphs WHERE section=?", (sec,))
    print(f"  {sec:<28} {cur.fetchone()[0]:>10,}")
conn.close()
print("DONE.")
