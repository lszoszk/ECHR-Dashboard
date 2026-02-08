# ── Imports ──────────────────────────────────────────────────────────────────
from flask import (
    Flask,
    render_template,
    request,
    send_file,
    jsonify,
    send_from_directory,
)
from flask_session import Session
import pandas as pd
import io
import json
import os
import re
import datetime
from collections import Counter, defaultdict
import time
import pickle
from bs4 import BeautifulSoup
import nltk
from nltk.corpus import stopwords
from nltk.tokenize import word_tokenize, RegexpTokenizer
from nltk import bigrams
from nltk.util import ngrams as nltk_ngrams
import glob
import logging
from logging.handlers import RotatingFileHandler
from flask_caching import Cache
import markdown
from markupsafe import Markup # NEW ─ render .md → HTML

# ── Module-level utility functions ───────────────────────────────────────────

def matches_query(item_text, and_terms, or_term_groups):
    """Return True if item_text satisfies all AND terms and at least one term in each OR group."""
    for term in and_terms:
        if term not in item_text:
            return False
    for or_terms in or_term_groups:
        if not any(t.strip() in item_text for t in or_terms):
            return False
    return True

def highlight_terms(text, terms):
    """Wrap each search term in <span class="highlight">…</span>."""
    for term in sorted(terms, key=len, reverse=True):
        pattern = re.escape(term)
        text = re.sub(
            pattern,
            r'<span class="highlight">\g<0></span>',
            text,
            flags=re.IGNORECASE
        )
    return text

def clean_illegal_chars(value):
    """Remove control chars that Excel cannot handle."""
    if isinstance(value, str):
        return re.sub(r'[\x00-\x08\x0B-\x0C\x0E-\x1F]', '', value)
    return value

def matches_neurorights_filters(item, neurorights_filters):
    if not neurorights_filters:
        return True
    text = " ".join([
        item.get('Title', ''),
        item.get('Abstract', ''),
        item.get('Author Keywords', '')
    ]).lower()
    return any(nf.lower() in text for nf in neurorights_filters)

def matches_search_query(item, query_terms, fields):
    if not query_terms:
        return True
    if not fields or fields == ['default']:
        fields = ['Title', 'Abstract', 'Keywords', 'Authors']
    text = ""
    if 'Title' in fields:
        text += item.get('Title', '')
    if 'Abstract' in fields:
        text += " " + item.get('Abstract', '')
    if 'Keywords' in fields:
        text += " " + item.get('Author Keywords', '')
    if 'Authors' in fields:
        text += " " + item.get('Authors', '')
    text = text.lower()
    for term in query_terms:
        if term.startswith('"') and term.endswith('"'):
            if term[1:-1].lower() not in text:
                return False
        else:
            if term.lower() not in text:
                return False
    return True

# ── Application setup ────────────────────────────────────────────────────────
# Replace:
# nltk.download('stopwords')
# nltk.download('wordnet')
# nltk.download('punkt')

try:
    _ = stopwords.words('english')
except LookupError:
    app.logger.warning("NLTK 'stopwords' missing; install at build time")
try:
    nltk.data.find('tokenizers/punkt')
except LookupError:
    app.logger.warning("NLTK 'punkt' missing; install at build time")

# ---- Config class (put just above app = Flask(...) or in a separate config.py) ----
class BaseConfig:
    SESSION_TYPE = "filesystem"
    SECRET_KEY = os.environ.get("SECRET_KEY", os.urandom(32).hex())
    CACHE_TYPE = "SimpleCache"
    CACHE_DEFAULT_TIMEOUT = 300

    JSON_DIR = os.environ.get("JSON_DIR", "/home/lszoszk/mysite/json_data")
    JSON_SP_DIR = os.environ.get("JSON_SP_DIR", "/home/lszoszk/mysite/json_data_sp")
    MD_SP_DIR = os.environ.get("MD_SP_DIR", "/home/lszoszk/mysite/md_data_sp")

# ---- Create app and apply config ----
app = Flask(__name__)
app.config.from_object(BaseConfig)

# Flask-Session and Flask-Caching now read from app.config
Session(app)
cache = Cache(app)  # no dict needed, uses CACHE_* from app.config

# ---- Use config values instead of literals ----
JSON_DIR    = app.config["JSON_DIR"]
JSON_SP_DIR = app.config["JSON_SP_DIR"]
MD_SP_DIR   = app.config["MD_SP_DIR"]

# Create directory for survey responses if it doesn't exist
SURVEY_DIR = '/home/lszoszk/mysite/survey_responses'
os.makedirs(SURVEY_DIR, exist_ok=True)


# ── Load metadata ────────────────────────────────────────────────────────────
with open("/home/lszoszk/mysite/crc_gc_info.json", "r", encoding="utf-8") as f:
    gc_info = json.load(f)

with open("/home/lszoszk/mysite/specialprocedures_info.json", "r", encoding="utf-8") as f:
    sp_info = json.load(f)

def load_custom_stopwords(path):
    with open(path, 'r', encoding='utf-8') as file:
        return set(line.strip().lower() for line in file if line.strip())

custom_stopwords = load_custom_stopwords("/home/lszoszk/mysite/custom_stopwords.txt")
nltk_stopwords = set(stopwords.words('english'))
all_stopwords = nltk_stopwords.union(custom_stopwords)

def format_text_for_display(text):
    if text is None:
        return ''
    return re.sub(r'; \(([a-zA-Z])\)', r'<br>; (\1)', text)

committee_names = sorted({
    c.strip()
    for item in gc_info if 'Committee' in item
    for c in item['Committee'].split(',')
})

def get_info_by_filepath(json_file, info_list):
    return next((item for item in info_list if item["File PATH"].endswith(json_file)), None)

def get_all_committees():
    committees = set()
    for item in gc_info:
        if 'Committee' in item:
            for c in item['Committee'].split(','):
                committees.add(c.strip())
    return sorted(committees)

def get_documents_for_committee(committee):
    docs = []
    for item in gc_info:
        committees = [x.strip() for x in item.get('Committee', '').split(',')]
        if committee in committees:
            filename = os.path.basename(item.get('File PATH', ''))
            doc_id, _ = os.path.splitext(filename)
            docs.append({
                'name': item.get('Name', 'Unknown'),
                'id': doc_id,
                'committee': ', '.join(committees)
            })
    return docs

def get_document_content(document_id):
    info = next((i for i in gc_info if i["File PATH"].endswith(document_id + '.json')), None)
    title = info.get('Name', 'Unknown') if info else 'Unknown'
    signature = info.get('Signature', '') if info else ''
    adoption_year = info.get('Adoption Year', '') if info else ''
    adoption_date = info.get('Adoption Date', '') if info else ''
    path = os.path.join(JSON_DIR, f"{document_id}.json")
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        paras = [f"{i+1}. {p.get('Text', '')}" for i, p in enumerate(data)]
        return {
            'title': title,
            'signature': signature,
            'adoption_year': adoption_year,
            'adoption_date': adoption_date,
            'paragraphs': paras
        }
    return {'title': 'Not found', 'paragraphs': []}

# ── Basic routes ─────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return render_template('index2.html')

@app.route('/robots.txt')
def robots():
    return send_from_directory(app.static_folder, 'robots.txt')

@app.template_filter('get_info_by_filepath')
def jinja_get_info(json_file, gc_info_list):
    return next((item for item in gc_info_list if item["File PATH"].endswith(json_file)), None)

# ── UN Documents browser (Special Procedures) ────────────────────────────────
@app.route('/documents')
def documents_browser():
    """Return the HTML front-end that contains the grid/list view."""
    return render_template('sp_documents.html')  # place the HTML (your code) here

@cache.cached(timeout=300)
@app.route('/api/sp_documents')
def api_sp_documents():
    """Return the full list of Special-Procedures metadata used by the filters."""
    return jsonify(sp_info)

@app.route('/api/sp_documents/<path:doc_id>')
def api_sp_document_content(doc_id):
    """
    Return markdown *and* rendered HTML for one document.

    The front-end expects `doc_id` without extension, e.g. 'Academic freedom'
    """
    md_path = os.path.join(MD_SP_DIR, f"{doc_id}.md")
    if not os.path.exists(md_path):
        return jsonify({"error": "Document not found"}), 404

    with open(md_path, "r", encoding="utf-8") as f:
        md_text = f.read()

    html_text = markdown.markdown(
        md_text,
        extensions=["fenced_code", "tables", "toc", "sane_lists"]
    )

    return jsonify({"markdown": md_text, "html": html_text})

# ── Main UN Treaty Bodies search ─────────────────────────────────────────────
@app.route('/search', methods=['GET'])
@cache.cached(timeout=300, query_string=True)
def search():
    # Read parameters
    year_start = request.args.get('year_start', type=int)
    year_end   = request.args.get('year_end',   type=int)
    raw_query  = request.args.get('search_query', '').strip().lower()
    selected_labels        = [l.lower() for l in request.args.getlist('labels[]')]
    selected_treaty_bodies = request.args.getlist('treatyBodies[]')

    # Build query terms
    ngrams_list = re.findall(r'"([^"]+)"', raw_query)
    words       = re.findall(r'\b\w+\b', raw_query)
    query_terms = ngrams_list + [w for w in words if w not in ' '.join(ngrams_list)]
    and_terms   = [t for t in query_terms if ' or ' not in t]
    or_term_groups = [t.split(' or ') for t in query_terms if ' or ' in t]

    grouped = {}
    total_hits = 0
    label_counter = Counter()
    all_text = ""
    committee_counter = defaultdict(int)

    for fname in os.listdir(JSON_DIR):
        if not fname.endswith('.json'):
            continue
        info = get_info_by_filepath(fname, gc_info) or {}
        committees = [c.strip() for c in info.get('Committee', '').split(',')]

        # filters
        if selected_treaty_bodies and not any(tb in committees for tb in selected_treaty_bodies):
            continue
        adoption_year = None
        try:
            adoption_year = int(info.get('Adoption Year', ''))
        except ValueError:
            pass
        if year_start and adoption_year and adoption_year < year_start:
            continue
        if year_end and adoption_year and adoption_year > year_end:
            continue

        path = os.path.join(JSON_DIR, fname)
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        paras = []
        for item in data:
            text_orig = item.get('Text', '')
            text_low  = text_orig.lower()
            labels = [lbl.lower() for lbl in item.get('Labels', [])]
            if matches_query(text_low, and_terms, or_term_groups) and (
                not selected_labels or
                any(lbl in labels for lbl in selected_labels)
            ):
                total_hits += 1
                pid = item.get('ID', '')
                highlighted = highlight_terms(text_orig, query_terms)
                formatted = format_text_for_display(highlighted)
                paras.append((pid, {'Text': formatted, **item}, len(labels)))
                all_text += " " + text_low
                for lbl in labels:
                    label_counter[lbl] += 1

        if paras:
            doc_name = info.get('Name', 'Unknown')
            grouped[doc_name] = {
                'link':          info.get('Link', '#'),
                'total_count':   len(paras),
                'paragraphs':    paras,
                'committee':     info.get('Committee', ''),
                'adoption_date': info.get('Adoption Date', ''),
                'signature':     info.get('Signature', '')
            }
            for c in committees:
                committee_counter[c] += len(paras)

    sorted_results = sorted(grouped.items(), key=lambda x: x[1]['total_count'], reverse=True)
    total_docs = len(grouped)
    most_concerned = label_counter.most_common(10)

    export_key = str(time.time())
    with open(f'cache/{export_key}.pkl', 'wb') as cf:
        pickle.dump(grouped, cf)

    tokenizer = RegexpTokenizer(r'\w+')
    tokens = tokenizer.tokenize(all_text.lower())
    filtered_words = [w for w in tokens if w.isalpha() and w not in all_stopwords]
    most_common_words = Counter(filtered_words).most_common(20)
    bigrams_list = list(bigrams(filtered_words))
    most_common_bigrams = Counter(bigrams_list).most_common(20)
    committees_with_hits = sorted(committee_counter.items(), key=lambda x: x[1], reverse=True)

    return render_template(
        'search_results_enhanced.html',
        results=sorted_results,
        query=raw_query,
        total_hits=total_hits,
        total_docs=total_docs,
        search_key=export_key,
        selected_labels=selected_labels,
        most_concerned_groups=most_concerned,
        most_common_words=most_common_words,
        most_common_bigrams=most_common_bigrams,
        committees_with_hits=committees_with_hits,
        year_start=year_start,
        year_end=year_end
    )

# ── Export to Excel ──────────────────────────────────────────────────────────
@app.route('/export_to_excel', methods=['POST'])
def export_to_excel():
    key = request.form.get('search_key')
    if not key:
        app.logger.error("No search_key provided")
        return "No search key", 400
    try:
        with open(f'cache/{key}.pkl', 'rb') as cf:
            grouped = pickle.load(cf)
    except Exception as e:
        app.logger.error(f"Export load error: {e}")
        return "Error loading data", 400

    rows = []
    for doc, info in grouped.items():
        for tup in info.get('paragraphs', []):
            pid, pinfo = tup[0], tup[1]
            raw = BeautifulSoup(pinfo.get('Text', ''), 'html.parser').get_text()
            txt = clean_illegal_chars(raw)
            labels = pinfo.get('Labels', [])
            rows.append({
                'Document Name': doc,
                'Paragraph ID': pid,
                'Text': txt,
                'Labels': ', '.join(labels),
                'Committee': info.get('committee', ''),
                'Adoption Date': info.get('adoption_date', ''),
                'Signature': info.get('signature', '')
            })

    df = pd.DataFrame(rows)
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Results')
    out.seek(0)
    return send_file(
        out,
        as_attachment=True,
        download_name="search_results.xlsx",
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )

# ── Corpus viewer & document AJAX ────────────────────────────────────────────
@app.route('/corpus_viewer.html')
def corpus_viewer():
    return render_template('corpus_viewer.html', committees=get_all_committees())

@app.route('/get_documents/<committee>')
def get_documents(committee):
    return jsonify(get_documents_for_committee(committee))

@app.route('/get_document/<document_id>')
def get_document(document_id):
    return jsonify(get_document_content(document_id))

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/vibecoding')
def vibecoding():
    return render_template('vibecoding.html')

@app.route('/oneshot')
def oneshot():
    return render_template('un_app_oneshot.html')

@app.route('/cookie-policy')
def cookie_policy():
    return render_template('cookie_policy.html')

# ── Special Procedures search (existing) ─────────────────────────────────────
@app.route('/specialprocedures')
def specialprocedures():
    return render_template('specialprocedures.html')

@app.route('/specialprocedures/search', methods=['GET'])
@cache.cached(timeout=300, query_string=True)
def specialprocedures_search():
    year_start = request.args.get('year_start', type=int)
    year_end   = request.args.get('year_end',   type=int)
    raw_query  = request.args.get('search_query', '').strip().lower()
    selected_labels     = [l.lower() for l in request.args.getlist('labels[]')]
    selected_committees = request.args.getlist('treatyBodies[]')

    ngrams_list = re.findall(r'"([^"]+)"', raw_query)
    words       = re.findall(r'\b\w+\b', raw_query)
    query_terms = ngrams_list + [w for w in words if w not in ' '.join(ngrams_list)]
    and_terms   = [t for t in query_terms if ' or ' not in t]
    or_term_groups = [t.split(' or ') for t in query_terms if ' or ' in t]

    grouped = {}
    total_hits = 0
    label_counter = Counter()
    all_text = ""
    committee_counter = defaultdict(int)

    for fname in os.listdir(JSON_SP_DIR):
        if not fname.endswith('.json'):
            continue

        info = next((i for i in sp_info if i['File PATH'].endswith(fname)), {})
        committees = [c.strip() for c in info.get('Committee', '').split(',')]

        if selected_committees and not any(c in committees for c in selected_committees):
            continue

        year = int(info.get('Adoption Year', 0) or 0)
        if year_start and year < year_start:
            continue
        if year_end and year > year_end:
            continue

        with open(os.path.join(JSON_SP_DIR, fname), 'r', encoding='utf-8') as jf:
            data = json.load(jf)

        hits = []
        for item in data:
            text_orig = item.get('Text', '')
            text_low  = text_orig.lower()
            labels    = [lbl.lower() for lbl in item.get('Labels', [])]

            if matches_query(text_low, and_terms, or_term_groups) and (
                not selected_labels or
                any(lbl in labels for lbl in selected_labels)
            ):
                total_hits += 1
                pid         = item.get('ID', '')
                highlighted = highlight_terms(text_orig, query_terms)
                formatted   = format_text_for_display(highlighted)
                hit_dict    = {'Text': formatted, 'Labels': labels}
                hits.append((pid, hit_dict, len(labels)))
                all_text += " " + text_low
                for lbl in labels:
                    label_counter[lbl] += 1

        if hits:
            grouped[info.get('Name', fname)] = {
                'link':          info.get('Link', '#'),
                'total_count':   len(hits),
                'paragraphs':    hits,
                'committee':     info.get('Committee', ''),
                'adoption_date': info.get('Adoption Date', ''),
                'signature':     info.get('Signature', '')
            }
            for c in committees:
                committee_counter[c] += len(hits)

    sorted_results = sorted(grouped.items(), key=lambda x: x[1]['total_count'], reverse=True)
    total_docs = len(grouped)
    most_concerned = label_counter.most_common(10)

    export_key_sp = str(time.time())
    with open(f'cache/{export_key_sp}.pkl', 'wb') as cf:
        pickle.dump(grouped, cf)

    tokenizer = RegexpTokenizer(r'\w+')
    tokens = tokenizer.tokenize(all_text.lower())
    fw = [w for w in tokens if w.isalpha() and w not in all_stopwords]
    common_words = Counter(fw).most_common(20)
    bigrams_list = list(bigrams(fw))
    common_bigrams = Counter(bigrams_list).most_common(20)
    committees_with_hits = sorted(committee_counter.items(), key=lambda x: x[1], reverse=True)

    return render_template(
        'search_results_enhanced.html',
        results=sorted_results,
        query=raw_query,
        total_hits=total_hits,
        total_docs=total_docs,
        search_key=export_key_sp,
        selected_labels=selected_labels,
        most_concerned_groups=most_concerned,
        most_common_words=common_words,
        most_common_bigrams=common_bigrams,
        committees_with_hits=committees_with_hits,
        year_start=year_start,
        year_end=year_end
    )

# ── Load Neurorights corpus & search endpoint (unchanged) ────────────────────
with open("Neurorights.json", "r", encoding="utf-8") as file:
    neurorights_data = json.load(file)

print(f"Neurorights data loaded: {len(neurorights_data)} items")

for item in neurorights_data:
    item['Title_original']    = item['Title']
    item['Abstract_original'] = item['Abstract']

@app.route('/neurorights_search', methods=['GET'])
def neurorights_search():
    search_query       = request.args.get('search_query', '').strip().lower()
    neurorights_filters = request.args.getlist('neurorights_filters')
    year_start         = request.args.get('year_start', default=None, type=int)
    year_end           = request.args.get('year_end',   default=None, type=int)
    only_open_access   = 'only_open_access' in request.args
    search_fields      = request.args.getlist('search_fields') or ['default']
    page               = request.args.get('page', default=1, type=int)
    per_page           = 20

    ngrams = re.findall(r'"([^"]+)"', search_query)
    words  = re.findall(r'\b\w+\b', search_query)
    query_terms = ngrams + [word for word in words if word not in ' '.join(ngrams)]

    authors_counter  = Counter()
    keywords_counter = Counter()
    bigram_stopwords = {("springer", "nature"), ("rights", "reserved"), ("all", "rights")}
    bigrams_counter  = Counter()
    filtered_results = []

    for item in neurorights_data:
        item_year = int(item.get('Year', 0))
        if year_start and year_end and not (year_start <= item_year <= year_end):
            continue
        if not matches_neurorights_filters(item, neurorights_filters):
            continue
        if not matches_search_query(item, query_terms, search_fields):
            continue
        if only_open_access and 'All Open Access' not in item.get('Open Access', ''):
            continue
        filtered_results.append(item)

    for item in filtered_results:
        authors_counter.update([a.strip() for a in item.get('Authors', '').split(';')])

        kw_list = [k.strip() for k in item.get('Author Keywords', '').split(';') if len(k.strip()) >= 3]
        keywords_counter.update(kw_list)

        combined = ' '.join([item.get('Title', ''), item.get('Abstract', ''), ' '.join(kw_list)]).lower()
        tokens = word_tokenize(combined)
        filtered = [t for t in tokens if t not in all_stopwords and len(t) > 1]
        bigrams_counter.update([bg for bg in nltk_ngrams(filtered, 2) if bg not in bigram_stopwords])

    top_bigrams  = bigrams_counter.most_common(20)
    top_bigrams_str = ['{} ({})'.format(' '.join(bg), c) for bg, c in top_bigrams]
    top_authors  = [(a, c) for a, c in authors_counter.most_common(20)]
    top_keywords = [(k, c) for k, c in keywords_counter.most_common(20)]

    total_items  = len(filtered_results)
    total_pages  = (total_items + per_page - 1) // per_page
    start, end   = (page - 1) * per_page, (page - 1) * per_page + per_page

    paginated_items = filtered_results[start:end]
    search_results  = []

    for item in paginated_items:
        item_copy = item.copy()
        item_copy['Title']    = highlight_terms(item['Title_original'],    query_terms)
        item_copy['Abstract'] = highlight_terms(item['Abstract_original'], query_terms)

        if 'Author Keywords' in item and query_terms:
            highlighted_kw = [
                highlight_terms(k.strip(), query_terms)
                for k in item['Author Keywords'].split(';')
            ]
            item_copy['Author Keywords'] = '; '.join(highlighted_kw)

        search_results.append(item_copy)

    return render_template(
        'neurorights_search.html',
        search_results           = search_results,
        total_filtered_results   = total_items,
        search_query             = search_query,
        top_bigrams              = '; '.join(top_bigrams_str),
        top_authors              = '; '.join(['{} ({})'.format(a, c) for a, c in top_authors]),
        top_keywords             = '; '.join(['{} ({})'.format(k, c) for k, c in top_keywords]),
        total_pages              = total_pages,
        current_page             = page
    )

# Enhanced version under specific route
@app.route('/enhanced')
def index_enhanced():
    return render_template('index_enhanced.html')

# ── Enhanced search route ────────────────────────────────────────────────────
@app.route('/enhanced/search', methods=['GET'])
@cache.cached(timeout=300, query_string=True)
def search_enhanced():
    # Read parameters
    year_start = request.args.get('year_start', type=int)
    year_end   = request.args.get('year_end',   type=int)
    raw_query  = request.args.get('search_query', '').strip().lower()
    selected_labels        = [l.lower() for l in request.args.getlist('labels[]')]
    selected_treaty_bodies = request.args.getlist('treatyBodies[]')

    # Build query terms
    ngrams_list = re.findall(r'"([^"]+)"', raw_query)
    words       = re.findall(r'\b\w+\b', raw_query)
    query_terms = ngrams_list + [w for w in words if w not in ' '.join(ngrams_list)]
    and_terms   = [t for t in query_terms if ' or ' not in t]
    or_term_groups = [t.split(' or ') for t in query_terms if ' or ' in t]

    grouped = {}
    total_hits = 0
    label_counter = Counter()
    all_text = ""
    committee_counter = defaultdict(int)

    for fname in os.listdir(JSON_DIR):
        if not fname.endswith('.json'):
            continue
        info = get_info_by_filepath(fname, gc_info) or {}
        committees = [c.strip() for c in info.get('Committee', '').split(',')]

        # filters
        if selected_treaty_bodies and not any(tb in committees for tb in selected_treaty_bodies):
            continue
        adoption_year = None
        try:
            adoption_year = int(info.get('Adoption year', ''))
        except ValueError:
            pass
        if year_start and adoption_year and adoption_year < year_start:
            continue
        if year_end and adoption_year and adoption_year > year_end:
            continue

        path = os.path.join(JSON_DIR, fname)
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        paras = []
        for item in data:
            text_orig = item.get('Text', '')
            text_low  = text_orig.lower()
            labels = [lbl.lower() for lbl in item.get('Labels', [])]
            if matches_query(text_low, and_terms, or_term_groups) and (
                not selected_labels or
                any(lbl in labels for lbl in selected_labels)
            ):
                total_hits += 1
                pid = item.get('ID', '')
                highlighted = highlight_terms(text_orig, query_terms)
                formatted = format_text_for_display(highlighted)
                paras.append((pid, {'Text': formatted, **item}, len(labels)))
                all_text += " " + text_low
                for lbl in labels:
                    label_counter[lbl] += 1

        if paras:
            doc_name = info.get('Name', 'Unknown')
            grouped[doc_name] = {
                'link':          info.get('Link', '#'),
                'total_count':   len(paras),
                'paragraphs':    paras,
                'committee':     info.get('Committee', ''),
                'adoption_date': info.get('Adoption Date', ''),
                'signature':     info.get('Signature', '')
            }
            for c in committees:
                committee_counter[c] += len(paras)

    sorted_results = sorted(grouped.items(), key=lambda x: x[1]['total_count'], reverse=True)
    total_docs = len(grouped)
    most_concerned = label_counter.most_common(10)

    export_key = str(time.time())
    with open(f'cache/{export_key}.pkl', 'wb') as cf:
        pickle.dump(grouped, cf)

    tokenizer = RegexpTokenizer(r'\w+')
    tokens = tokenizer.tokenize(all_text.lower())
    filtered_words = [w for w in tokens if w.isalpha() and w not in all_stopwords]
    most_common_words = Counter(filtered_words).most_common(20)
    bigrams_list = list(bigrams(filtered_words))
    most_common_bigrams = Counter(bigrams_list).most_common(20)
    committees_with_hits = sorted(committee_counter.items(), key=lambda x: x[1], reverse=True)

    return render_template(
        'search_results_enhanced.html',
        results=sorted_results,
        query=raw_query,
        total_hits=total_hits,
        total_docs=total_docs,
        search_key=export_key,
        selected_labels=selected_labels,
        most_concerned_groups=most_concerned,
        most_common_words=most_common_words,
        most_common_bigrams=most_common_bigrams,
        committees_with_hits=committees_with_hits,
        year_start=year_start,
        year_end=year_end
    )

@app.route('/enhanced_home')
def enhanced_homey():
    return render_template('enhanced_home.html')

@app.route('/enhanced_about')
def enhanced_about():
    return render_template('enhanced_about.html')

@app.route('/enhanced_browse')
def enhanced_browsey():
    return render_template('enhanced_browse.html')

@app.route('/enhanced_procedures')
def enhanced_procedures():
    return render_template('enhanced_procedures.html')

@app.route('/enhanced_procedures_browse')
def enhanced_procedures_browse():
    # Get list of available special procedures documents for browsing
    sp_committees = sorted(set(
        item.get('Committee', 'Unknown').strip()
        for item in sp_info
        if item.get('Committee')
    ))
    return render_template('enhanced_procedures_browse.html', committees=sp_committees)

@app.route('/enhanced_get_documents/<committee>')
def enhanced_get_documents(committee):
    return jsonify(get_documents_for_committee(committee))

@app.route('/enhanced_get_document/<document_id>')
def enhanced_get_document(document_id):
    return jsonify(get_document_content(document_id))

@app.route('/survey')
def survey():
    """Display the feedback survey"""
    return render_template('survey.html')

@app.route('/api/submit_survey', methods=['POST'])
def submit_survey():
    """Save survey response as JSON file"""
    try:
        data = request.get_json()

        # Add server-side timestamp
        data['server_timestamp'] = datetime.datetime.now().isoformat()

        # Generate unique filename
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'survey_response_{timestamp}.json'
        filepath = os.path.join(SURVEY_DIR, filename)

        # Save to file
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, indent=2, fp=f)

        app.logger.info(f"Survey response saved: {filename}")
        return jsonify({"success": True, "message": "Survey submitted successfully!"})

    except Exception as e:
        app.logger.error(f"Error saving survey: {e}")
        return jsonify({"success": False, "message": "Error submitting survey"}), 500

# ── Run (only locally; PythonAnywhere uses WSGI) ─────────────────────────────
if __name__ == '__main__':
    app.run(debug=True)
