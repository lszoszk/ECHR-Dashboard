#!/usr/bin/env python3
"""
Classifier for ECHR Introduction section paragraphs.
Distinguishes procedural content from applicant-table data.
"""
import json
import re
from collections import Counter

with open('scripts/b3_intro_samples.json') as f:
    data = json.load(f)

# ─────────────────────────────────────────────────────────────────────────────
# Pattern library
# ─────────────────────────────────────────────────────────────────────────────

# Column header patterns (exact match against stripped text)
COLUMN_HEADER_RE = re.compile(
    r"^("
    r"Applicant.?s?\s*name|Year of birth(/registration)?|Date of (birth|detention|application)|"
    r"Representative.?s?\s*name(\s*and\s*location)?|Facility|Start\s*(and\s*end\s*)?date|"
    r"End date( of non-enforcement period)?|Duration|Location|Date|"
    r"Amount awarded(\s*for.*)?|"
    r"No\. of application|Application no\.|"
    r"Sq\.?\s*m\.?(\s*per\s*inmate)?|"
    r"Number of (toilets|inmates|sleeping places) per (brigade|cell)?|"
    r"(Pecuniary|Non-pecuniary|Total)\s*damage|Costs\s*and\s*expenses|"
    r"Other complaints( under well)?|"
    r"Domestic (decision|award|court|law|court decisions?)|"
    r"Relevant domestic (court\s*)?decision|"
    r"Name of the court|Court Name|Penalty|Awar[d]|Award|Key issues|"
    r"Heir|Test purchase date|Start of proceedings|Length of detention|"
    r"Total length|Start date of non-enforcement( period)?|"
    r"Number of toilets per brigade|Detention with disability(: facility and periods)?|"
    r"Shortcomings in medical treatment|"
    r"monthly compensation for health harm|Sq\. m\. per inmate|"
    r"(in euros?)|per applicant|per application|"
    r"Plus any tax that may be chargeable to the applicants?\.|"
    r"Relevant domestic court|"
    r"\[\d+\]"
    r")$",
    re.IGNORECASE
)

FOOTNOTE_RE = re.compile(r'^\[\d+\]$')

APP_NO_RE = re.compile(r'\b\d{4,6}/\d{2}\b')
DATE_RE = re.compile(r'\b\d{2}/\d{2}/\d{4}\b')
PRISON_CODE_RE = re.compile(r'\b(IK|SIZO|ITT|PSC|PCB|PTD|RU)-?\d+\b', re.IGNORECASE)
SQM_RE = re.compile(r'<?\d[\d.]*\s*m[²2]|sq\.?\s*m', re.IGNORECASE)
CAO_RE = re.compile(r'\bCAO\b|article 20\.2|article\s+\d+[\.\s]+§\s+\d+\s+of\s+CA')
DISPOSITIF_RE = re.compile(r'^\d+\.\s+(Declares?|Holds?|Dismisses?|Decides?)\b', re.IGNORECASE)

# Named row: 3-4 digit number + dot + Cyrillic/Latin capital
NAMED_ROW_RE = re.compile(r'^\d{3,4}\.\s+[A-ZÀ-ÖØ-öø-ÿА-ЯЁ]')

# Numeric row leading with number + date data
NUM_DATE_ROW_RE = re.compile(r'^\d{1,4}\.\s+\d{2}/\d{2}/\d{4}')

PROCEDURAL_PATTERNS = [
    re.compile(r'\bthe Court\b', re.IGNORECASE),
    re.compile(r'\bthe applicant\b', re.IGNORECASE),
    re.compile(r'\bthe Government\b', re.IGNORECASE),
    re.compile(r'\bArticle \d+\b', re.IGNORECASE),
    re.compile(r'\bconvention\b', re.IGNORECASE),
    re.compile(r'\bviolation\b', re.IGNORECASE),
    re.compile(r'\bjudgment\b', re.IGNORECASE),
    re.compile(r'\badmissib', re.IGNORECASE),
    re.compile(r'\bdeclares?\b', re.IGNORECASE),
    re.compile(r'\bholds?\b', re.IGNORECASE),
    re.compile(r'\bprotocol\b', re.IGNORECASE),
    re.compile(r'\bobserves?\b', re.IGNORECASE),
    re.compile(r'\bnotes?\b', re.IGNORECASE),
]

TABLE_CTX_RE = re.compile(
    r"(Applicant.?s?\s*name|Year of birth|Representative|Facility|IK-\d|SIZO|"
    r"\d{4,6}/\d{2}|Amount awarded|pecuniary|non-pecuniary|\[\d+\]|"
    r"Sq\.?\s*m|overcrowding|inmate|pre-trial detention|\d{2}/\d{2}/\d{4}|"
    r"month\(s\)|day\(s\)|year\(s\)|level\(s\)\s*of\s*jurisdiction)",
    re.IGNORECASE
)

PROC_CTX_RE = re.compile(
    r"(the Court|the Government|the applicant|violation|Article \d|Convention|Protocol|"
    r"judgment|admissib|application no\.|§\s*\d|paragraph \d|damages|award|"
    r"observes|finds|considers|reiterates)",
    re.IGNORECASE
)


def ctx_str(record, side):
    items = record.get(f'context_{side}', [])
    return ' '.join(i.get('preview', '') for i in items)


def proc_score(text):
    return sum(1 for p in PROCEDURAL_PATTERNS if p.search(text))


def classify(record):
    text = record['text'].strip()
    tlen = record['text_length']
    ctx_b = ctx_str(record, 'before')
    ctx_a = ctx_str(record, 'after')
    ctx_all = ctx_b + ' ' + ctx_a

    tc = len(TABLE_CTX_RE.findall(ctx_all))   # table context signal count
    pc_ctx = len(PROC_CTX_RE.findall(ctx_all)) # procedural context signal count
    ps = proc_score(text)                       # procedural signals in text itself

    # ── COLUMN HEADER (exact) ────────────────────────────────────────────────
    if COLUMN_HEADER_RE.match(text):
        return ('applicant_table', 'high', 'Exact column header / footer text.')

    # ── FOOTNOTE ─────────────────────────────────────────────────────────────
    if FOOTNOTE_RE.match(text):
        return ('applicant_table', 'high', 'Footnote marker [N].')

    # ── NAMED APPLICANT ROW (RowNum. Name ... dates/app-no) ──────────────────
    if NAMED_ROW_RE.match(text):
        has_data = APP_NO_RE.search(text) or DATE_RE.search(text) or len(text) < 250
        if has_data and (tc >= 2 or APP_NO_RE.search(ctx_all)):
            return ('applicant_table', 'high',
                    'Numbered applicant-name row with date/app-no data.')
        elif has_data and tc >= 1:
            return ('applicant_table', 'medium',
                    'Numbered applicant-name row; moderate table context.')
        elif has_data and ps == 0:
            return ('applicant_table', 'medium',
                    'Numbered applicant row without procedural language.')

    # ── NUMERIC DATE ROW (RowNum. dd/mm/yyyy ...) ────────────────────────────
    if NUM_DATE_ROW_RE.match(text) and ps == 0:
        return ('applicant_table', 'high',
                'Numeric-prefixed row beginning with date, no procedural language.')

    # ── SQ-METRE PRISON CONDITIONS ROW ──────────────────────────────────────
    if SQM_RE.search(text) and (
            PRISON_CODE_RE.search(text) or
            'overcrowding' in text.lower() or
            'inmate' in text.lower()):
        if ps <= 1:
            return ('applicant_table', 'high',
                    'Prison conditions data row with m² measurements.')

    # ── CAO ADMINISTRATIVE OFFENCE ROWS ─────────────────────────────────────
    if CAO_RE.search(text) and NAMED_ROW_RE.match(text):
        return ('applicant_table', 'high',
                'Administrative offence (CAO) applicant row.')
    if CAO_RE.search(text) and tc >= 3 and ps <= 2:
        return ('applicant_table', 'high',
                'CAO data fragment in strong table context.')

    # ── PRISON CONDITIONS CONTINUATION ──────────────────────────────────────
    overcrowding = 'overcrowding' in text.lower()
    lack_pattern = bool(re.search(
        r'lack of (fresh air|or (restricted|inadequate)|requisite medical|privacy|or insufficient)',
        text, re.IGNORECASE))
    if (overcrowding or lack_pattern) and ps <= 1 and tc >= 2:
        return ('applicant_table', 'high',
                'Prison conditions enumeration in table context.')
    if (overcrowding or lack_pattern) and ps <= 1:
        return ('applicant_table', 'medium',
                'Prison conditions enumeration without clear table context.')

    # ── PLUS ANY TAX FOOTNOTE ────────────────────────────────────────────────
    if re.match(r'^Plus any tax that may be chargeable', text, re.IGNORECASE):
        return ('applicant_table', 'high', 'Table footnote: "Plus any tax...".')

    # ── AMOUNT AWARDED COLUMN ────────────────────────────────────────────────
    if re.search(r'amount awarded', text, re.IGNORECASE) and tlen < 120:
        return ('applicant_table', 'high', '"Amount awarded" column header/caption.')

    # ── SHORT TEXT IN STRONG TABLE CONTEXT ──────────────────────────────────
    if tlen < 30 and tc >= 3 and ps == 0:
        return ('applicant_table', 'high',
                'Short fragment in strong table context.')
    if tlen < 30 and tc >= 2 and ps == 0:
        return ('applicant_table', 'medium',
                'Short fragment in moderate table context.')

    # ── STANDALONE DATE IN TABLE CONTEXT ────────────────────────────────────
    if re.match(r'^\d{2}/\d{2}/\d{4}$', text) and tc >= 1:
        return ('applicant_table', 'high',
                'Standalone date in table context.')

    # ── STANDALONE APP NUMBER IN TABLE CONTEXT ───────────────────────────────
    if APP_NO_RE.match(text) and tlen < 20 and ps == 0 and tc >= 1:
        return ('applicant_table', 'high',
                'Standalone application number in table context.')

    # ── DURATION FRAGMENTS ───────────────────────────────────────────────────
    if re.match(r'^\d+\s+year\(s\)', text, re.IGNORECASE) and tc >= 1:
        return ('applicant_table', 'high', 'Duration fragment (year(s)...) in table context.')
    if re.match(r'^\d+\s+month\(s\)', text, re.IGNORECASE) and tc >= 1:
        return ('applicant_table', 'high', 'Duration fragment (month(s)...) in table context.')
    if re.match(r'^\d+\s+day\(s\)', text, re.IGNORECASE) and tc >= 1:
        return ('applicant_table', 'high', 'Duration fragment (day(s)...) in table context.')

    # ── DASH CONTINUATION ────────────────────────────────────────────────────
    if text in ('‑', '-', '–', '—') and tc >= 2:
        return ('applicant_table', 'high', 'Dash continuation fragment in table context.')

    # ── (IN EUROS) / PER APPLICANT SUFFIXES ─────────────────────────────────
    if re.match(r'^\(in euros?\)$', text, re.IGNORECASE):
        return ('applicant_table', 'high', '"(in euros)" column suffix.')
    if re.match(r'^per (applicant|application)$', text, re.IGNORECASE):
        return ('applicant_table', 'high', '"per applicant/application" header fragment.')

    # ── ROWS WITH MULTIPLE APPLICATION NUMBERS ───────────────────────────────
    app_nos = APP_NO_RE.findall(text)
    if len(app_nos) >= 2 and ps <= 1 and tc >= 1:
        return ('applicant_table', 'high',
                'Multiple application numbers with low procedural signal.')

    # ── LARGE NUMERIC PREFIX + AMOUNT (table row with numbers) ───────────────
    if re.match(r'^\d{1,4}\.\s+\d[\d\s,.]+\d{4,6}/\d{2}', text) and ps == 0:
        return ('applicant_table', 'high',
                'Table row: sequential number + amount + app-no.')

    # ── OPERATIVE / DISPOSITIF ───────────────────────────────────────────────
    if DISPOSITIF_RE.match(text):
        return ('procedural', 'high', 'Operative part / dispositif paragraph.')

    # ── HIGH PROCEDURAL SIGNAL IN TEXT ──────────────────────────────────────
    if ps >= 4 and tc <= 1:
        return ('procedural', 'high', 'High density of procedural language markers.')
    if ps >= 6:
        return ('procedural', 'high', 'Very high procedural signal despite some table context.')
    if ps >= 3 and tc <= 2:
        return ('procedural', 'medium', 'Moderate-to-high procedural signals.')
    if ps >= 2 and tc <= 1:
        return ('procedural', 'medium', 'Moderate procedural language, minimal table context.')
    if ps >= 1 and pc_ctx >= 3 and tc <= 1:
        return ('procedural', 'medium', 'Procedural language + procedural context.')

    # ── AMBIGUOUS ────────────────────────────────────────────────────────────
    if tc >= 2 and ps >= 2:
        return ('unclear', 'low', 'Mixed procedural and table signals.')
    if tc >= 1 and ps >= 1:
        return ('unclear', 'medium', 'Conflicting procedural and table signals.')
    if tlen < 30 and tc == 0 and ps == 0:
        return ('unclear', 'low', 'Very short text with no context signals.')
    if tlen >= 30 and tc <= 1 and ps <= 1:
        return ('unclear', 'medium', 'Insufficient signals for confident classification.')

    return ('unclear', 'low', 'Could not determine category from available signals.')


verdicts = []
for record in data:
    cat, conf, reason = classify(record)
    verdicts.append({
        'rowid': record['rowid'],
        'case_id': record['case_id'],
        'category': cat,
        'confidence': conf,
        'reason': reason,
    })

with open('scripts/b3_intro_verdicts.json', 'w') as f:
    json.dump(verdicts, f, indent=2, ensure_ascii=False)

# ── Statistics ────────────────────────────────────────────────────────────────
cats = Counter(v['category'] for v in verdicts)
confs = Counter((v['category'], v['confidence']) for v in verdicts)

print(f"Total classified: {len(verdicts)}")
print(f"\nCategory distribution:")
for cat, cnt in sorted(cats.items()):
    pct = 100 * cnt / len(verdicts)
    print(f"  {cat:20s}: {cnt:4d}  ({pct:.1f}%)")

print(f"\nBy category × confidence:")
for (cat, conf), cnt in sorted(confs.items()):
    print(f"  {cat:20s} / {conf:6s}: {cnt}")

# By length bucket
print(f"\nBy length bucket:")
buckets = {'<30': [], '30-80': [], '81-200': [], '>200': []}
for record, verdict in zip(data, verdicts):
    l = record['text_length']
    if l < 30:
        buckets['<30'].append(verdict['category'])
    elif l <= 80:
        buckets['30-80'].append(verdict['category'])
    elif l <= 200:
        buckets['81-200'].append(verdict['category'])
    else:
        buckets['>200'].append(verdict['category'])

for bname, cats_list in buckets.items():
    c = Counter(cats_list)
    n = len(cats_list)
    print(f"  Bucket {bname:6s} (n={n}): "
          f"applicant_table={c.get('applicant_table',0)} ({100*c.get('applicant_table',0)/n:.0f}%),  "
          f"procedural={c.get('procedural',0)} ({100*c.get('procedural',0)/n:.0f}%),  "
          f"unclear={c.get('unclear',0)} ({100*c.get('unclear',0)/n:.0f}%)")
