#!/usr/bin/env python3
"""
ECHR HUDOC Scraper — Judgment-Level Extraction with Proper Paragraph Handling

Fetches ECHR judgments from HUDOC and produces a JSONL file with clean,
properly-segmented paragraphs. Addresses known fragmentation issues in
prior scraping approaches.

Usage:
    python scraper_hudoc.py                          # Scrape recent 100 judgments
    python scraper_hudoc.py --count 500              # Scrape 500 judgments
    python scraper_hudoc.py --ids 001-246126,001-248200  # Scrape specific cases
    python scraper_hudoc.py --from-date 2025-01-01   # Scrape from date
    python scraper_hudoc.py --clean-only input.jsonl  # Clean existing JSONL only

Requires: requests, lxml (pip install requests lxml)
"""

import argparse
import json
import os
import re
import sys
import time
from collections import defaultdict
from typing import Optional

try:
    import requests
except ImportError:
    print("Install: pip install requests")
    sys.exit(1)

try:
    from lxml import html as lxml_html
    HAS_LXML = True
except ImportError:
    from html.parser import HTMLParser
    HAS_LXML = False


# ═══════════════════════════════════════════════════════════════════════════════
# HUDOC API Configuration
# ═══════════════════════════════════════════════════════════════════════════════

HUDOC_SEARCH_URL = "https://hudoc.echr.coe.int/app/query/results"
HUDOC_DOC_URL = "https://hudoc.echr.coe.int/app/conversion/docx/"

SEARCH_FIELDS = (
    "itemid,docname,appno,conclusion,importance,originatingbody,"
    "doctypebranch,respondent,respondentOrderEng,article,violation,"
    "nonviolation,judgementdate,languageisocode,ecli,separateopinion,"
    "kpthesaurus,scl"
)

HEADERS = {
    "Accept": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://hudoc.echr.coe.int/eng",
}

# Batch size for search API (HUDOC max is 500)
BATCH_SIZE = 50
REQUEST_DELAY = 1.5  # seconds between requests


# ═══════════════════════════════════════════════════════════════════════════════
# HUDOC Search API
# ═══════════════════════════════════════════════════════════════════════════════

def search_hudoc(count=100, from_date=None, to_date=None, language="ENG",
                 item_ids=None, session=None):
    """
    Query HUDOC search API for judgment metadata.
    Returns list of result dicts.
    """
    if session is None:
        session = requests.Session()
        session.headers.update(HEADERS)

    if item_ids:
        # Fetch specific cases by ID
        id_clauses = " OR ".join(f'itemid:"{iid}"' for iid in item_ids)
        query = f'contentsitename:ECHR AND ({id_clauses})'
        results = _run_search(session, query, len(item_ids), language)
        return results

    # Build date-filtered query for judgments only
    query_parts = [
        'contentsitename:ECHR',
        '(NOT (doctype:PR OR doctype:HFCOMOLD OR doctype:HECOMOLD))',
        '(doctypebranch:JUDGMENTS OR doctypebranch:CHAMBER OR doctypebranch:GRANDCHAMBER)',
        f'languageisocode:"{language}"',
    ]
    if from_date:
        query_parts.append(f'kpdate>="{from_date}T00:00:00.0Z"')
    if to_date:
        query_parts.append(f'kpdate<="{to_date}T23:59:59.0Z"')

    query = " AND ".join(query_parts)
    return _run_search(session, query, count, language)


def _run_search(session, query, count, language):
    """Execute paginated HUDOC search."""
    all_results = []
    start = 0

    while start < count:
        batch_size = min(BATCH_SIZE, count - start)
        params = {
            "query": query,
            "select": SEARCH_FIELDS,
            "sort": "kpdate Descending",
            "start": start,
            "length": batch_size,
        }

        try:
            resp = session.get(HUDOC_SEARCH_URL, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            results = data.get("results", [])
            if not results:
                break

            for r in results:
                doc = r.get("columns", {})
                all_results.append(doc)

            total_available = data.get("resultcount", 0)
            print(f"  Fetched {start + len(results)}/{min(count, total_available)} results")

            start += batch_size
            if start >= total_available:
                break

            time.sleep(REQUEST_DELAY)

        except Exception as e:
            print(f"  Search error at offset {start}: {e}")
            time.sleep(5)
            start += batch_size

    return all_results


# ═══════════════════════════════════════════════════════════════════════════════
# Document Text Extraction
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_document_html(item_id, session=None):
    """
    Fetch the full HTML text of an ECHR judgment from HUDOC.
    Returns raw HTML string.
    """
    if session is None:
        session = requests.Session()
        session.headers.update(HEADERS)

    # HUDOC serves documents via the conversion endpoint
    url = f"https://hudoc.echr.coe.int/app/conversion/docx/?library=ECHR&id={item_id}"

    try:
        resp = session.get(url, timeout=30)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        print(f"  Failed to fetch document {item_id}: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# HTML → Structured Paragraphs Parser
# ═══════════════════════════════════════════════════════════════════════════════

# ECHR paragraph number pattern: "1.", "2.", etc at start of paragraph
RE_PARA_NUM = re.compile(r'^(\d+)\.\s+')

# Section heading patterns in ECHR judgments
SECTION_HEADINGS = {
    'introduction': re.compile(r'^INTRODUCTION$', re.IGNORECASE),
    'facts': re.compile(r'^THE\s+FACTS$', re.IGNORECASE),
    'legal_framework': re.compile(
        r'^(RELEVANT\s+(DOMESTIC\s+)?(LEGAL\s+FRAMEWORK|LAW)|'
        r'RELEVANT\s+LEGAL\s+FRAMEWORK\s+AND\s+PRACTICE|'
        r'RELEVANT\s+FRAMEWORK)$',
        re.IGNORECASE
    ),
    'law': re.compile(r'^THE\s+LAW$', re.IGNORECASE),
    'operative': re.compile(r'^FOR\s+THESE\s+REASONS', re.IGNORECASE),
}

# Sub-heading patterns within sections
SUB_HEADINGS = re.compile(
    r'^(\d+\.\s+)?(ALLEGED\s+VIOLATION|APPLICATION\s+OF\s+ARTICLE|'
    r'ADMISSIBILITY|MERITS|PRELIMINARY\s+OBJECTION|'
    r'BACKGROUND\s+INFORMATION|VETTING\s+PROCEEDINGS|'
    r'CISD\s+REPORT|IQC|SAC|OTHER\s+PROCEEDINGS|'
    r'GENERAL\s+PRINCIPLES|JUST\s+SATISFACTION|'
    r'CONCURRING\s+OPINION|DISSENTING\s+OPINION|SEPARATE\s+OPINION)',
    re.IGNORECASE
)


def parse_echr_html(html_content):
    """
    Parse ECHR judgment HTML into properly segmented paragraphs and sections.
    Returns dict with section arrays.
    """
    if HAS_LXML:
        return _parse_with_lxml(html_content)
    else:
        return _parse_with_regex(html_content)


def _parse_with_lxml(html_content):
    """Parse using lxml for robust HTML handling."""
    tree = lxml_html.fromstring(html_content)

    # Extract paragraphs from the document body
    paragraphs = []
    for elem in tree.iter():
        if elem.tag in ('p', 'div'):
            text = elem.text_content().strip()
            if text:
                paragraphs.append(text)

    return _segment_paragraphs(paragraphs)


def _parse_with_regex(html_content):
    """Fallback: parse using regex for environments without lxml."""
    # Strip HTML tags, preserving paragraph breaks
    text = re.sub(r'<br\s*/?>', '\n', html_content)
    text = re.sub(r'</p>', '\n\n', text)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'&nbsp;', ' ', text)
    text = re.sub(r'&amp;', '&', text)
    text = re.sub(r'&lt;', '<', text)
    text = re.sub(r'&gt;', '>', text)
    text = re.sub(r'&#\d+;', '', text)

    # Split into paragraphs
    raw_paras = re.split(r'\n{2,}', text)
    paragraphs = [p.strip() for p in raw_paras if p.strip()]

    return _segment_paragraphs(paragraphs)


def _segment_paragraphs(paragraphs):
    """
    Given a list of raw text paragraphs, segment them into ECHR sections.
    Returns dict: {section_name: [paragraph_text, ...]}.
    """
    sections = defaultdict(list)
    current_section = 'header'

    for para in paragraphs:
        # Check for section heading transitions
        new_section = _detect_section(para)
        if new_section:
            current_section = new_section
            # Some headings are standalone (e.g. "THE FACTS") — don't add as content
            if len(para) < 80 and not RE_PARA_NUM.match(para):
                continue

        sections[current_section].append(para)

    return dict(sections)


def _detect_section(text):
    """Detect if a paragraph is a section heading. Returns section name or None."""
    clean = text.strip()

    for section_name, pattern in SECTION_HEADINGS.items():
        if pattern.search(clean):
            return section_name

    return None


# ═══════════════════════════════════════════════════════════════════════════════
# Paragraph Merger — Fixes fragmentation in existing scraped data
# ═══════════════════════════════════════════════════════════════════════════════

# Patterns that indicate a fragment (not a real paragraph start):
# These should be merged with the preceding paragraph.
RE_FRAGMENT_START = re.compile(
    r'^('
    # Bare number-dot from split cross-references: "61. (2)", "6. § 1", "53. ‑"
    r'\d{1,3}\.\s*[\(\§‑\-–]'
    # Single letter-dot-space (name fragments): "E. I.", "A. I.", "A. S."
    r'|[A-Z]\.\s+[A-Z]'
    # Continuation of Article reference: "6. § 1"
    r'|\d\.\s*§'
    # Bare section/subsection number from split statute quotes: "(1) of Law", "(2) and (3)"
    r'|\(\d+\)\s+(of|and|or)\s'
    # Semicolon or closing punctuation starting a fragment
    r'|[;,]\s*(\.\.\.|")'
    # Very short fragments that are clearly continuations
    r'|[a-z]'  # starts with lowercase = continuation
    r')',
    re.UNICODE
)

# Patterns for legitimate paragraph starts
RE_VALID_PARA_START = re.compile(
    r'^('
    # Numbered paragraph: "22. The IQC..."
    r'\d+\.\s+[A-Z]'
    # Sub-point: "(a) The", "(b) It", "(i) Alleged"
    r'|\([a-z]\)\s+[A-Z]'
    r'|\([ivxlcdm]+\)\s+[A-Z]'
    # Section heading in caps
    r'|[A-Z]{2,}'
    # Roman numeral sub-heading
    r'|\d+\.\s+[A-Z]{2,}'
    r')',
    re.UNICODE
)

# Names that cause false splits: "A. I.", "E. I.", "A. S.", "A. M.", etc.
RE_NAME_INITIAL = re.compile(r'^[A-Z]\.\s+[A-Z]\.\s')

# Cross-reference fragments: "6. § 1", "53. ‑", "61. (2)"
RE_CROSS_REF_FRAGMENT = re.compile(
    r'^(\d{1,3})\.\s*'
    r'(§|‑|\-|–|\(|\)|of\s|and\s|or\s|The\s+provisions)',
    re.UNICODE
)

# Short fragments from statute quotes: "(1) of Law no."
RE_STATUTE_FRAGMENT = re.compile(r'^\(\d+\)\s+(of|and|or)\s')


def should_merge_with_previous(text, prev_text):
    """
    Determine if `text` is a fragment that should be merged with `prev_text`.

    Returns True if the paragraph appears to be a continuation/fragment
    rather than a standalone paragraph.
    """
    if not text or not prev_text:
        return False

    stripped = text.strip()
    if not stripped:
        return False

    # Very short fragments (≤3 chars) are always fragments
    if len(stripped) <= 3:
        return True

    # Starts with lowercase letter → continuation
    if stripped[0].islower():
        return True

    # Starts with punctuation continuation: ";", ",", "..."
    if stripped[0] in ';,':
        return True

    # Name initial fragment: "A. I. had been" or "E. I. as chairperson"
    if RE_NAME_INITIAL.match(stripped):
        # But only if the previous paragraph ends mid-sentence
        prev_end = prev_text.rstrip()[-1] if prev_text.rstrip() else ''
        if prev_end not in '.!?"':
            return True
        # Also merge if prev ends with a name start: "Judge" or "composed of Judge"
        if re.search(r'(Judge|of|Mr|Ms|Dr|Sir|Lord|composed\s+of)\s*$', prev_text.rstrip()):
            return True

    # Cross-reference fragment: "6. § 1 of the Convention"
    # These look like paragraph starts (number-dot) but are really mid-sentence references
    m = RE_CROSS_REF_FRAGMENT.match(stripped)
    if m:
        num = int(m.group(1))
        # Real ECHR paragraph numbers are sequential; cross-refs to articles are small numbers
        # If the "paragraph number" is very small (1-10) and followed by §, it's Article reference
        if num <= 15 and '§' in stripped[:20]:
            return True
        # If previous text ends mid-sentence (no terminal punctuation)
        prev_end = prev_text.rstrip()[-1] if prev_text.rstrip() else ''
        if prev_end not in '.!?"':
            return True
        # "53. ‑" or "73. The provisions" after a cross-ref like "§§ 93-"
        if prev_text.rstrip().endswith(('‑', '-', '–', ',', '§§')):
            return True

    # Statute reference fragment: "(1) of Law no."
    if RE_STATUTE_FRAGMENT.match(stripped):
        return True

    # Previous paragraph ends without terminal punctuation → merge
    prev_end_char = prev_text.rstrip()[-1] if prev_text.rstrip() else '.'
    if prev_end_char in (',', ';', ':') and not stripped.startswith(('(a)', '(b)', '(c)')):
        return True

    # Previous paragraph ends with "section" or "Article" → number follows
    if re.search(r'\b(section|Article|articles?|§§?|paragraph|paragraphs)\s*$',
                 prev_text.rstrip(), re.IGNORECASE):
        return True

    return False


def merge_paragraphs(paragraphs):
    """
    Post-process a list of paragraph strings to fix fragmentation.
    Merges fragments with their preceding paragraph.

    Returns a new list of properly-formed paragraphs.
    """
    if not paragraphs:
        return []

    merged = [paragraphs[0]]

    for i in range(1, len(paragraphs)):
        current = paragraphs[i]
        if not current.strip():
            continue

        if should_merge_with_previous(current, merged[-1]):
            # Merge: add space between fragments
            sep = ' ' if merged[-1].rstrip()[-1:] not in ('-', '–', '‑') else ''
            merged[-1] = merged[-1].rstrip() + sep + current.strip()
        else:
            merged.append(current)

    return merged


# ═══════════════════════════════════════════════════════════════════════════════
# JSONL Processing — Clean existing dataset
# ═══════════════════════════════════════════════════════════════════════════════

def clean_case(case):
    """
    Clean a single case by merging fragmented paragraphs in all text fields.
    Returns a new case dict with merged paragraphs.
    """
    cleaned = dict(case)

    text_fields = [
        'introduction', 'facts', 'law',
        'relevant_legal_framework_practice',
        'legal_context', 'reasons_the_court_unanimously',
    ]

    for field in text_fields:
        if field in cleaned and isinstance(cleaned[field], list):
            original_count = len(cleaned[field])
            cleaned[field] = merge_paragraphs(cleaned[field])
            merged_count = original_count - len(cleaned[field])
            if merged_count > 0:
                pass  # tracking done at caller level

    return cleaned


def clean_jsonl(input_path, output_path):
    """
    Read a JSONL file, clean all cases, write to new JSONL.
    Reports statistics on merges performed.
    """
    print(f"\n{'='*60}")
    print(f"Paragraph Merger — Cleaning JSONL")
    print(f"{'='*60}")
    print(f"Input:  {input_path}")
    print(f"Output: {output_path}")

    cases = []
    with open(input_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(json.loads(line))

    print(f"Loaded {len(cases)} cases")

    total_before = 0
    total_after = 0
    field_stats = defaultdict(lambda: {'before': 0, 'after': 0})

    cleaned_cases = []
    for case in cases:
        cleaned = clean_case(case)
        cleaned_cases.append(cleaned)

        for field in ['introduction', 'facts', 'law',
                      'relevant_legal_framework_practice',
                      'legal_context', 'reasons_the_court_unanimously']:
            orig = case.get(field, [])
            new = cleaned.get(field, [])
            field_stats[field]['before'] += len(orig)
            field_stats[field]['after'] += len(new)
            total_before += len(orig)
            total_after += len(new)

    with open(output_path, 'w', encoding='utf-8') as f:
        for case in cleaned_cases:
            f.write(json.dumps(case, ensure_ascii=False) + '\n')

    total_merged = total_before - total_after
    print(f"\nTotal paragraphs: {total_before} → {total_after} ({total_merged} merged, {total_merged/total_before*100:.1f}%)")
    print(f"\n{'Field':<45} {'Before':>7} {'After':>7} {'Merged':>7}")
    print("-" * 70)
    for field, stats in sorted(field_stats.items()):
        merged = stats['before'] - stats['after']
        if merged > 0:
            print(f"  {field:<43} {stats['before']:>7} {stats['after']:>7} {merged:>7}")

    return cleaned_cases


# ═══════════════════════════════════════════════════════════════════════════════
# Full Pipeline — Scrape + Clean
# ═══════════════════════════════════════════════════════════════════════════════

def build_case_record(meta, text_sections=None):
    """
    Build a case record from HUDOC metadata (and optionally parsed text).
    """
    record = {
        'case_id': meta.get('itemid', ''),
        'case_no': meta.get('appno', ''),
        'title': meta.get('docname', ''),
        'judgment_date': _parse_date(meta.get('judgementdate', '')),
        'article_no': meta.get('article', ''),
        'defendants': _parse_list(meta.get('respondent', '')),
        'document_type': _parse_list(meta.get('doctypebranch', '')),
        'originating_body': _parse_list(meta.get('originatingbody', '')),
        'court': ['European Court of Human Rights'],
        'organisation': ['Council of Europe'],
        'chamber_composed_of': [],
        'violation': _parse_list(meta.get('violation', '')),
        'non-violation': _parse_list(meta.get('nonviolation', '')),
        'court_assessment_references': {},
    }

    if text_sections:
        record['introduction'] = text_sections.get('introduction', [])
        record['facts'] = text_sections.get('facts', [])
        record['law'] = text_sections.get('law', [])
        record['relevant_legal_framework_practice'] = text_sections.get('legal_framework', [])
        record['legal_context'] = []
        record['reasons_the_court_unanimously'] = text_sections.get('operative', [])
    else:
        for field in ['introduction', 'facts', 'law',
                      'relevant_legal_framework_practice',
                      'legal_context', 'reasons_the_court_unanimously']:
            record[field] = []

    return record


def _parse_date(date_str):
    """Parse HUDOC date format to YYYY-MM-DD."""
    if not date_str:
        return ''
    # HUDOC uses ISO format: "2025-11-25T00:00:00"
    m = re.match(r'(\d{4}[/-]\d{2}[/-]\d{2})', date_str)
    return m.group(1) if m else date_str[:10]


def _parse_list(value):
    """Parse HUDOC semicolon/comma-separated list."""
    if isinstance(value, list):
        return value
    if not value or not isinstance(value, str):
        return []
    return [v.strip() for v in re.split(r'[;]', value) if v.strip()]


def scrape_hudoc(count=100, from_date=None, to_date=None, item_ids=None,
                 output_path=None, fetch_text=True):
    """
    Full scraping pipeline: search → fetch documents → parse → clean → save.
    """
    print(f"\n{'='*60}")
    print(f"ECHR HUDOC Scraper")
    print(f"{'='*60}")

    session = requests.Session()
    session.headers.update(HEADERS)

    # 1. Search for cases
    print(f"\n[1/3] Searching HUDOC...")
    if item_ids:
        print(f"  Fetching {len(item_ids)} specific cases")
    else:
        print(f"  Fetching up to {count} judgments" +
              (f" from {from_date}" if from_date else ""))

    results = search_hudoc(
        count=count, from_date=from_date, to_date=to_date,
        item_ids=item_ids, session=session
    )

    if not results:
        print("  No results found!")
        return []

    print(f"  Found {len(results)} cases")

    # 2. Fetch and parse documents
    print(f"\n[2/3] Fetching document texts...")
    cases = []
    for i, meta in enumerate(results):
        item_id = meta.get('itemid', '')
        title = meta.get('docname', '')[:60]
        print(f"  [{i+1}/{len(results)}] {item_id} — {title}")

        text_sections = None
        if fetch_text:
            html = fetch_document_html(item_id, session=session)
            if html:
                text_sections = parse_echr_html(html)
            time.sleep(REQUEST_DELAY)

        record = build_case_record(meta, text_sections)
        cases.append(record)

    # 3. Clean paragraphs (merge fragments)
    print(f"\n[3/3] Cleaning paragraphs (merging fragments)...")
    cleaned = []
    total_merged = 0
    for case in cases:
        before = sum(len(case.get(f, []))
                     for f in ['introduction', 'facts', 'law',
                              'relevant_legal_framework_practice',
                              'legal_context', 'reasons_the_court_unanimously'])
        case = clean_case(case)
        after = sum(len(case.get(f, []))
                    for f in ['introduction', 'facts', 'law',
                             'relevant_legal_framework_practice',
                             'legal_context', 'reasons_the_court_unanimously'])
        total_merged += before - after
        cleaned.append(case)

    print(f"  Merged {total_merged} fragments across {len(cleaned)} cases")

    # 4. Save
    if output_path:
        with open(output_path, 'w', encoding='utf-8') as f:
            for case in cleaned:
                f.write(json.dumps(case, ensure_ascii=False) + '\n')
        print(f"\nSaved {len(cleaned)} cases to {output_path}")

    return cleaned


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="ECHR HUDOC Scraper with proper paragraph handling"
    )
    parser.add_argument('--count', type=int, default=100,
                       help='Number of judgments to scrape (default: 100)')
    parser.add_argument('--ids', type=str, default=None,
                       help='Comma-separated case IDs to scrape')
    parser.add_argument('--from-date', type=str, default=None,
                       help='Start date (YYYY-MM-DD)')
    parser.add_argument('--to-date', type=str, default=None,
                       help='End date (YYYY-MM-DD)')
    parser.add_argument('--output', '-o', type=str, default=None,
                       help='Output JSONL path')
    parser.add_argument('--no-text', action='store_true',
                       help='Skip fetching full text (metadata only)')
    parser.add_argument('--clean-only', type=str, default=None,
                       help='Clean an existing JSONL file (no scraping)')

    args = parser.parse_args()

    if args.clean_only:
        # Just clean existing data
        output = args.output or args.clean_only.replace('.jsonl', '_cleaned.jsonl')
        clean_jsonl(args.clean_only, output)
        return

    # Full scrape
    item_ids = args.ids.split(',') if args.ids else None
    output = args.output or f'echr_cases_{time.strftime("%Y%m%d_%H%M%S")}.jsonl'

    scrape_hudoc(
        count=args.count,
        from_date=args.from_date,
        to_date=args.to_date,
        item_ids=item_ids,
        output_path=output,
        fetch_text=not args.no_text,
    )


if __name__ == '__main__':
    main()
