#!/usr/bin/env python3
"""
ECHR Case Law Dashboard — Paragraph-Level Search (Option B Schema)
A local Flask application for searching through European Court of Human Rights
judicial decisions at the paragraph level, with structural section classification.
"""

from flask import Flask, render_template, request, jsonify, send_file
import json
import re
import os
import time
from datetime import datetime
from collections import Counter, defaultdict
import io
import csv

# ── Configuration ────────────────────────────────────────────────────────────

app = Flask(__name__)

def resolve_data_file():
    """Resolve the dataset path with optional environment override."""
    base_dir = os.path.dirname(__file__)

    env_path = os.getenv('ECHR_DATA_FILE')
    if env_path:
        env_path = os.path.abspath(env_path)
        if os.path.exists(env_path):
            return env_path
        print(f"Warning: ECHR_DATA_FILE was set but not found: {env_path}")

    candidates = [
        os.path.join(base_dir, '..', 'echr_cases_20260217_103005.jsonl'),
        os.path.join(base_dir, '..', 'data', 'echr_decisions_sample.jsonl'),
        os.path.join(base_dir, '..', 'echr_cases_optionB.jsonl'),
        os.path.join(base_dir, '..', 'echr_cases_20260207_121847.jsonl'),
    ]

    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate

    raise FileNotFoundError(
        "No dataset found. Provide ECHR_DATA_FILE or add one of: "
        + ", ".join(os.path.abspath(path) for path in candidates)
    )


DATA_FILE = resolve_data_file()

# ── Data Loading ─────────────────────────────────────────────────────────────

CASES = []
PARAGRAPH_INDEX = []  # list of dicts: {case_idx, section, para_idx, text_lower, text}
ARTICLES_SET = set()
COUNTRIES_SET = set()

# Option B sections (structural)
SECTIONS = [
    'introduction', 'facts_background', 'facts_proceedings',
    'legal_framework', 'admissibility', 'merits',
    'just_satisfaction', 'article_46', 'operative_part', 'separate_opinion',
]
SECTION_LABELS = {
    'header': 'Header',
    'introduction': 'Introduction',
    'facts_background': 'Facts (Background)',
    'facts_proceedings': 'Facts (Proceedings)',
    'legal_framework': 'Legal Framework',
    'admissibility': 'Admissibility',
    'merits': 'Merits',
    'just_satisfaction': 'Just Satisfaction',
    'article_46': 'Article 46 (Execution)',
    'operative_part': 'Operative Part',
    'separate_opinion': 'Separate Opinion',
}

# Section colors for the UI
SECTION_COLORS = {
    'header': '#718096',
    'introduction': '#4C72B0',
    'facts_background': '#DD8452',
    'facts_proceedings': '#C44E52',
    'legal_framework': '#937860',
    'admissibility': '#8172B3',
    'merits': '#55A868',
    'just_satisfaction': '#DA8BC3',
    'article_46': '#CCB974',
    'operative_part': '#64B5CD',
    'separate_opinion': '#8C8C8C',
}


def load_data():
    """Load Option B JSONL and build paragraph-level index."""
    global CASES, PARAGRAPH_INDEX, ARTICLES_SET, COUNTRIES_SET
    print(f"Loading ECHR case data from {DATA_FILE}...")
    t0 = time.time()

    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                CASES.append(json.loads(line))

    # Build paragraph index from Option B 'paragraphs' array
    for ci, case in enumerate(CASES):
        # Extract articles
        art = case.get('article_no', '')
        for a in re.split(r'[;,]', art):
            a = a.strip()
            if a:
                ARTICLES_SET.add(a)

        # Extract countries
        for d in case.get('defendants', []):
            COUNTRIES_SET.add(d)

        # Index paragraphs — Option B uses 'paragraphs' array of objects
        for para_obj in case.get('paragraphs', []):
            text = para_obj.get('text', '').strip()
            section = para_obj.get('section', 'unknown')
            if text and section != 'header':  # skip header fragments
                PARAGRAPH_INDEX.append({
                    'case_idx': ci,
                    'section': section,
                    'para_idx': para_obj.get('para_idx', 0),
                    'text_lower': text.lower(),
                    'text': text,
                })

    ARTICLES_SET = sorted(ARTICLES_SET, key=lambda x: (len(x), x))
    COUNTRIES_SET = sorted(COUNTRIES_SET)

    # Count sections
    sec_counts = Counter(p['section'] for p in PARAGRAPH_INDEX)
    elapsed = time.time() - t0
    print(f"Loaded {len(CASES)} cases, {len(PARAGRAPH_INDEX)} paragraphs in {elapsed:.2f}s")
    print(f"  Sections: {dict(sec_counts.most_common())}")


# ── Search Logic ─────────────────────────────────────────────────────────────

def parse_query(query):
    """Parse query into AND terms and OR groups. Supports quoted phrases and OR."""
    if not query or not query.strip():
        return [], []

    phrases = re.findall(r'"([^"]+)"', query)
    remaining = re.sub(r'"[^"]*"', '', query).strip()

    and_terms = []
    or_groups = []

    parts = re.split(r'\s+[Oo][Rr]\s+', remaining)
    if len(parts) > 1:
        or_groups.append([p.strip().lower() for p in parts if p.strip()])
    else:
        for word in remaining.split():
            w = word.strip()
            if w:
                and_terms.append(w.lower())

    for p in phrases:
        and_terms.append(p.lower())

    return and_terms, or_groups


def highlight_terms(text, terms):
    """Highlight matched terms in text."""
    for term in sorted(terms, key=len, reverse=True):
        pattern = re.escape(term)
        text = re.sub(
            pattern,
            r'<mark class="hl">\g<0></mark>',
            text,
            flags=re.IGNORECASE
        )
    return text


def parse_judgment_date(value):
    """Parse judgment dates across known formats."""
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None

    for fmt in ('%d/%m/%Y', '%Y-%m-%d', '%Y/%m/%d'):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def percentile(sorted_values, q):
    """Linear percentile from a pre-sorted numeric list."""
    if not sorted_values:
        return 0
    if len(sorted_values) == 1:
        return float(sorted_values[0])

    pos = (len(sorted_values) - 1) * q
    low = int(pos)
    high = min(low + 1, len(sorted_values) - 1)
    weight = pos - low
    return sorted_values[low] * (1 - weight) + sorted_values[high] * weight


def search_paragraphs(query, sections_filter=None, articles_filter=None,
                       countries_filter=None, date_from=None, date_to=None,
                       case_type_filter=None, limit=500):
    """Search through paragraphs. Returns grouped results by case."""
    and_terms, or_groups = parse_query(query)
    all_search_terms = and_terms + [t for grp in or_groups for t in grp]

    if not all_search_terms:
        return {}, [], 0

    results = defaultdict(lambda: {'case': None, 'paragraphs': [], 'hit_count': 0})
    total_hits = 0

    for entry in PARAGRAPH_INDEX:
        if sections_filter and entry['section'] not in sections_filter:
            continue

        case = CASES[entry['case_idx']]

        if articles_filter:
            case_articles = set(a.strip() for a in re.split(r'[;,]', case.get('article_no', '')))
            if not case_articles.intersection(articles_filter):
                continue

        if countries_filter:
            if not set(case.get('defendants', [])).intersection(countries_filter):
                continue

        jdate = case.get('judgment_date', '')
        if date_from and jdate < date_from:
            continue
        if date_to and jdate > date_to:
            continue

        if case_type_filter:
            doc_types = case.get('document_type', [])
            if not any(ct in doc_types for ct in case_type_filter):
                continue

        text_lower = entry['text_lower']

        if not all(t in text_lower for t in and_terms):
            continue

        or_match = True
        for grp in or_groups:
            if not any(t in text_lower for t in grp):
                or_match = False
                break
        if not or_match:
            continue

        case_id = case['case_id']
        if results[case_id]['case'] is None:
            results[case_id]['case'] = case

        highlighted = highlight_terms(entry['text'], all_search_terms)
        results[case_id]['paragraphs'].append({
            'section': entry['section'],
            'section_label': SECTION_LABELS.get(entry['section'], entry['section']),
            'section_color': SECTION_COLORS.get(entry['section'], '#718096'),
            'para_idx': entry['para_idx'],
            'text': highlighted,
            'raw_text': entry['text'],
        })
        results[case_id]['hit_count'] += 1
        total_hits += 1

        if total_hits >= limit:
            break

    sorted_results = dict(sorted(results.items(), key=lambda x: x[1]['hit_count'], reverse=True))
    return sorted_results, all_search_terms, total_hits


# ── Analytics helpers ────────────────────────────────────────────────────────

def compute_analytics(results):
    """Compute sidebar analytics from search results."""
    country_counts = Counter()
    article_counts = Counter()
    section_counts = Counter()
    word_counts = Counter()

    stopwords = {'the', 'of', 'and', 'to', 'in', 'a', 'that', 'is', 'was',
                 'for', 'it', 'on', 'with', 'as', 'by', 'at', 'an', 'be',
                 'this', 'which', 'or', 'from', 'had', 'has', 'have', 'its',
                 'not', 'but', 'are', 'were', 'been', 'also', 'they', 'their',
                 'would', 'could', 'should', 'may', 'can', 'will', 'shall',
                 'no', 'any', 'all', 'each', 'other', 'such', 'than', 'more',
                 'if', 'there', 'these', 'those', 'he', 'she', 'his', 'her',
                 'who', 'him', 'them', 'did', 'about', 'between', 'through',
                 'after', 'before', 'under', 'over', 'into', 'only', 'see',
                 'see,', 'cited', 'above', 'above,', 'paragraph', 'paragraphs',
                 'no.', 'nos.', '§§', '§', 'pp.', 'ibid.', 'ibid.,', 'et',
                 'al.', 'v.', 'article', 'articles'}

    for case_id, data in results.items():
        case = data['case']
        for d in case.get('defendants', []):
            country_counts[d] += data['hit_count']
        for a in re.split(r'[;,]', case.get('article_no', '')):
            a = a.strip()
            if a:
                article_counts[a] += data['hit_count']
        for p in data['paragraphs']:
            section_counts[p['section_label']] += 1
            words = re.findall(r'\b[a-zA-Z]{4,}\b', p['raw_text'].lower())
            for w in words:
                if w not in stopwords:
                    word_counts[w] += 1

    return {
        'countries': country_counts.most_common(15),
        'articles': article_counts.most_common(15),
        'sections': section_counts.most_common(10),
        'words': word_counts.most_common(20),
    }


# ── Country code mapping ────────────────────────────────────────────────────

COUNTRY_NAMES = {
    'ALB': 'Albania', 'AND': 'Andorra', 'ARM': 'Armenia', 'AUT': 'Austria',
    'AZE': 'Azerbaijan', 'BEL': 'Belgium', 'BIH': 'Bosnia and Herzegovina',
    'BGR': 'Bulgaria', 'HRV': 'Croatia', 'CYP': 'Cyprus', 'CZE': 'Czech Republic',
    'DNK': 'Denmark', 'EST': 'Estonia', 'FIN': 'Finland', 'FRA': 'France',
    'GEO': 'Georgia', 'DEU': 'Germany', 'GRC': 'Greece', 'HUN': 'Hungary',
    'ISL': 'Iceland', 'IRL': 'Ireland', 'ITA': 'Italy', 'LVA': 'Latvia',
    'LIE': 'Liechtenstein', 'LTU': 'Lithuania', 'LUX': 'Luxembourg',
    'MLT': 'Malta', 'MDA': 'Moldova', 'MCO': 'Monaco', 'MNE': 'Montenegro',
    'NLD': 'Netherlands', 'MKD': 'North Macedonia', 'NOR': 'Norway',
    'POL': 'Poland', 'PRT': 'Portugal', 'ROU': 'Romania', 'RUS': 'Russia',
    'SMR': 'San Marino', 'SRB': 'Serbia', 'SVK': 'Slovakia', 'SVN': 'Slovenia',
    'ESP': 'Spain', 'SWE': 'Sweden', 'CHE': 'Switzerland', 'TUR': 'Turkey',
    'UKR': 'Ukraine', 'GBR': 'United Kingdom',
}


# ── Routes ───────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    stats = {
        'total_cases': len(CASES),
        'total_paragraphs': len(PARAGRAPH_INDEX),
        'countries': len(COUNTRIES_SET),
        'date_range': f"{CASES[-1]['judgment_date']} – {CASES[0]['judgment_date']}" if CASES else '',
    }
    return render_template('index.html',
                           stats=stats,
                           articles=ARTICLES_SET,
                           countries=[(c, COUNTRY_NAMES.get(c, c)) for c in COUNTRIES_SET],
                           sections=[(s, SECTION_LABELS[s]) for s in SECTIONS])


@app.route('/search')
def search():
    query = request.args.get('q', '').strip()
    sections_filter = request.args.getlist('sections')
    articles_filter = request.args.getlist('articles')
    countries_filter = request.args.getlist('countries')
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()
    case_type = request.args.getlist('case_type')

    t0 = time.time()
    results, terms, total_hits = search_paragraphs(
        query,
        sections_filter=set(sections_filter) if sections_filter else None,
        articles_filter=set(articles_filter) if articles_filter else None,
        countries_filter=set(countries_filter) if countries_filter else None,
        date_from=date_from or None,
        date_to=date_to or None,
        case_type_filter=case_type or None,
    )
    search_time = time.time() - t0
    analytics = compute_analytics(results) if results else None

    return render_template('results.html',
                           query=query,
                           results=results,
                           total_hits=total_hits,
                           total_cases=len(results),
                           search_time=search_time,
                           terms=terms,
                           analytics=analytics,
                           country_names=COUNTRY_NAMES,
                           section_labels=SECTION_LABELS,
                           sections_filter=sections_filter,
                           articles_filter=articles_filter,
                           countries_filter=countries_filter,
                           date_from=date_from,
                           date_to=date_to)


@app.route('/api/search')
def api_search():
    query = request.args.get('q', '').strip()
    sections_filter = request.args.getlist('sections')
    articles_filter = request.args.getlist('articles')
    countries_filter = request.args.getlist('countries')
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()
    case_type = request.args.getlist('case_type')

    t0 = time.time()
    results, terms, total_hits = search_paragraphs(
        query,
        sections_filter=set(sections_filter) if sections_filter else None,
        articles_filter=set(articles_filter) if articles_filter else None,
        countries_filter=set(countries_filter) if countries_filter else None,
        date_from=date_from or None,
        date_to=date_to or None,
        case_type_filter=case_type or None,
    )
    search_time = time.time() - t0

    json_results = []
    for case_id, data in results.items():
        case = data['case']
        json_results.append({
            'case_id': case_id,
            'case_no': case.get('case_no', ''),
            'title': case.get('title', ''),
            'judgment_date': case.get('judgment_date', ''),
            'defendants': case.get('defendants', []),
            'article_no': case.get('article_no', ''),
            'hit_count': data['hit_count'],
            'paragraphs': data['paragraphs'],
        })

    return jsonify({
        'total_hits': total_hits,
        'total_cases': len(results),
        'search_time': round(search_time, 3),
        'results': json_results,
    })


@app.route('/case/<case_id>')
def view_case(case_id):
    case = None
    for c in CASES:
        if c['case_id'] == case_id:
            case = c
            break
    if not case:
        return "Case not found", 404

    return render_template('case_view.html',
                           case=case,
                           section_labels=SECTION_LABELS,
                           section_colors=SECTION_COLORS,
                           sections=SECTIONS,
                           country_names=COUNTRY_NAMES)


@app.route('/export')
def export_csv():
    query = request.args.get('q', '').strip()
    sections_filter = request.args.getlist('sections')
    articles_filter = request.args.getlist('articles')
    countries_filter = request.args.getlist('countries')
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()

    results, terms, total_hits = search_paragraphs(
        query,
        sections_filter=set(sections_filter) if sections_filter else None,
        articles_filter=set(articles_filter) if articles_filter else None,
        countries_filter=set(countries_filter) if countries_filter else None,
        date_from=date_from or None,
        date_to=date_to or None,
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Case ID', 'Case No', 'Title', 'Judgment Date', 'Defendants',
                     'Articles', 'Section', 'Paragraph', 'Text'])

    for case_id, data in results.items():
        case = data['case']
        for p in data['paragraphs']:
            writer.writerow([
                case_id,
                case.get('case_no', ''),
                case.get('title', ''),
                case.get('judgment_date', ''),
                ', '.join(case.get('defendants', [])),
                case.get('article_no', ''),
                p['section_label'],
                p['para_idx'] + 1,
                p['raw_text'],
            ])

    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode('utf-8-sig')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'echr_search_{query[:30].replace(" ", "_")}.csv'
    )


@app.route('/stats')
def stats_page():
    date_counts = Counter()
    year_counts = Counter()
    paragraph_month_counts = Counter()
    country_counts = Counter()
    article_counts = Counter()
    chamber_counts = Counter()
    section_counts = Counter()
    unique_articles = set()
    case_paragraph_lengths = []
    parsed_dates = []
    violation_cases = 0
    non_violation_cases = 0

    for case in CASES:
        paragraphs = [
            p for p in case.get('paragraphs', [])
            if (p.get('section') != 'header') and str(p.get('text', '')).strip()
        ]
        case_paragraph_lengths.append(len(paragraphs))

        parsed_date = parse_judgment_date(case.get('judgment_date', ''))
        if parsed_date:
            month_key = parsed_date.strftime('%Y-%m')
            year_key = parsed_date.strftime('%Y')
            date_counts[month_key] += 1
            year_counts[year_key] += 1
            paragraph_month_counts[month_key] += len(paragraphs)
            parsed_dates.append(parsed_date)

        for d in case.get('defendants', []):
            country_counts[d] += 1

        for a in re.split(r'[;,]', case.get('article_no', '')):
            a = a.strip()
            if a and not a.startswith('P') and len(a) < 10:
                article_counts[a] += 1
                unique_articles.add(a)

        doc_types = case.get('document_type', [])
        if 'GRANDCHAMBER' in doc_types:
            chamber_counts['Grand Chamber'] += 1
        elif 'CHAMBER' in doc_types:
            chamber_counts['Chamber'] += 1
        else:
            chamber_counts['Other'] += 1

        if case.get('violation'):
            violation_cases += 1
        if case.get('non-violation'):
            non_violation_cases += 1

        # Count indexed (non-header) paragraphs per section.
        for p in paragraphs:
            section_counts[p.get('section', 'unknown')] += 1

    sorted_lengths = sorted(case_paragraph_lengths)
    total_cases = len(CASES)
    avg_length = (sum(sorted_lengths) / total_cases) if total_cases else 0
    med_length = percentile(sorted_lengths, 0.5)
    p90_length = percentile(sorted_lengths, 0.9)
    min_length = sorted_lengths[0] if sorted_lengths else 0
    max_length = sorted_lengths[-1] if sorted_lengths else 0

    earliest_date = min(parsed_dates).strftime('%d %b %Y') if parsed_dates else 'n/a'
    latest_date = max(parsed_dates).strftime('%d %b %Y') if parsed_dates else 'n/a'
    grand_count = chamber_counts.get('Grand Chamber', 0)
    chamber_count = chamber_counts.get('Chamber', 0)
    other_count = chamber_counts.get('Other', 0)
    grand_share = (grand_count / total_cases * 100) if total_cases else 0
    dated_cases = len(parsed_dates)
    undated_cases = max(0, total_cases - dated_cases)

    return render_template('stats.html',
                           total_cases=total_cases,
                           total_paragraphs=len(PARAGRAPH_INDEX),
                           date_counts=sorted(date_counts.items()),
                           year_counts=sorted(year_counts.items()),
                           paragraph_month_counts=sorted(paragraph_month_counts.items()),
                           date_range_label=f'{earliest_date} – {latest_date}',
                           dated_cases=dated_cases,
                           undated_cases=undated_cases,
                           unique_countries=len(country_counts),
                           unique_articles=len(unique_articles),
                           avg_paragraphs_per_case=avg_length,
                           median_paragraphs_per_case=med_length,
                           p90_paragraphs_per_case=p90_length,
                           min_paragraphs_per_case=min_length,
                           max_paragraphs_per_case=max_length,
                           violation_cases=violation_cases,
                           non_violation_cases=non_violation_cases,
                           grand_chamber_share=grand_share,
                           chamber_cases=chamber_count,
                           grand_chamber_cases=grand_count,
                           other_cases=other_count,
                           country_counts=country_counts.most_common(20),
                           article_counts=article_counts.most_common(20),
                           chamber_counts=dict(chamber_counts),
                           chamber_breakdown=[
                               ['Grand Chamber', grand_count],
                               ['Chamber', chamber_count],
                               ['Other', other_count],
                           ],
                           section_counts=section_counts.most_common(),
                           section_labels=SECTION_LABELS,
                           section_colors=SECTION_COLORS,
                           country_names=COUNTRY_NAMES)


# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    load_data()
    app.run(debug=True, host='127.0.0.1', port=5001)
