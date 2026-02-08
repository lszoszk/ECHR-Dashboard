# ── Enhanced Flask Application for Human Rights Research ───────────────────
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
from markupsafe import Markup
from datetime import datetime, timedelta
import threading
from functools import wraps

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

def log_research_usage(search_type, query, total_hits, user_ip):
    """Log research usage for analytics."""
    timestamp = datetime.now().isoformat()
    log_entry = {
        'timestamp': timestamp,
        'search_type': search_type,
        'query': query,
        'total_hits': total_hits,
        'user_ip': user_ip
    }
    
    # Log to file for persistent analytics
    log_file = 'research_analytics.jsonl'
    with open(log_file, 'a', encoding='utf-8') as f:
        f.write(json.dumps(log_entry) + '\n')

def calculate_search_performance(search_results):
    """Calculate performance metrics for search results."""
    if not search_results:
        return {}
    
    # Calculate relevance scores, diversity metrics, etc.
    total_docs = len(search_results)
    total_hits = sum(doc['total_count'] for doc in search_results.values())
    
    # Committee diversity
    committees = set()
    for doc in search_results.values():
        if doc.get('committee'):
            committees.update([c.strip() for c in doc['committee'].split(',')])
    
    return {
        'total_documents': total_docs,
        'total_hits': total_hits,
        'committee_diversity': len(committees),
        'avg_hits_per_doc': total_hits / total_docs if total_docs > 0 else 0
    }

# ── Enhanced caching decorator ───────────────────────────────────────────────
def enhanced_cache(timeout=300):
    """Enhanced caching with analytics tracking."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            cache_key = f"{func.__name__}_{hash(str(request.args))}"
            cached_result = cache.get(cache_key)
            
            if cached_result:
                # Log cache hit for analytics
                app.logger.info(f"Cache hit for {func.__name__}")
                return cached_result
            
            # Execute function and cache result
            result = func(*args, **kwargs)
            cache.set(cache_key, result, timeout=timeout)
            app.logger.info(f"Cache miss for {func.__name__} - result cached")
            return result
        return wrapper
    return decorator

# ── Application setup ────────────────────────────────────────────────────────
nltk.download('stopwords', quiet=True)
nltk.download('wordnet', quiet=True)
nltk.download('punkt', quiet=True)

app = Flask(__name__)
app.config["SESSION_TYPE"] = "filesystem"
app.secret_key = 'I2N}=V|7PWCjyMt4>`7"a#yG=hycpAOq%):u0#?i%RBg0w`Ha)~Tf@iH3.")9mI'

def setup_enhanced_logger():
    """Enhanced logging setup with multiple handlers."""
    # Main application log
    handler = RotatingFileHandler('enhanced_app.log', maxBytes=1_000_000, backupCount=5)
    handler.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    app.logger.addHandler(handler)
    
    # Analytics log
    analytics_handler = RotatingFileHandler('analytics.log', maxBytes=1_000_000, backupCount=10)
    analytics_handler.setLevel(logging.INFO)
    analytics_handler.setFormatter(formatter)
    
    analytics_logger = logging.getLogger('analytics')
    analytics_logger.addHandler(analytics_handler)
    analytics_logger.setLevel(logging.INFO)

setup_enhanced_logger()
Session(app)

# Enhanced caching configuration
cache = Cache(app, config={
    'CACHE_TYPE': 'SimpleCache',
    'CACHE_DEFAULT_TIMEOUT': 300,
    'CACHE_THRESHOLD': 1000
})

cache_dir = 'cache'
if not os.path.exists(cache_dir):
    os.makedirs(cache_dir)

# Analytics storage
analytics_dir = 'analytics'
if not os.path.exists(analytics_dir):
    os.makedirs(analytics_dir)

# ── Data paths ───────────────────────────────────────────────────────────────
JSON_DIR     = "/home/lszoszk/mysite/json_data"         # treaty bodies
JSON_SP_DIR  = "/home/lszoszk/mysite/json_data_sp"      # special procedures
MD_SP_DIR    = "/home/lszoszk/mysite/md_data_sp"        # markdown directory

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
    adoption_year = info.get('Adoption year', '') if info else ''
    path = os.path.join(JSON_DIR, f"{document_id}.json")
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        paras = [f"{i+1}. {p.get('Text', '')}" for i, p in enumerate(data)]
        return {
            'title': title,
            'signature': signature,
            'adoption_year': adoption_year,
            'paragraphs': paras
        }
    return {'title': 'Not found', 'paragraphs': []}

# ── Analytics functions ──────────────────────────────────────────────────────
def get_analytics_data(days=30):
    """Get analytics data for the last N days."""
    try:
        analytics_file = 'research_analytics.jsonl'
        if not os.path.exists(analytics_file):
            return {}
            
        cutoff_date = datetime.now() - timedelta(days=days)
        analytics = []
        
        with open(analytics_file, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    entry = json.loads(line.strip())
                    entry_date = datetime.fromisoformat(entry['timestamp'])
                    if entry_date >= cutoff_date:
                        analytics.append(entry)
                except (json.JSONDecodeError, KeyError, ValueError):
                    continue
        
        # Calculate metrics
        total_searches = len(analytics)
        search_types = Counter(entry['search_type'] for entry in analytics)
        popular_terms = Counter()
        total_hits_sum = sum(entry.get('total_hits', 0) for entry in analytics)
        
        for entry in analytics:
            query = entry.get('query', '').lower()
            if query:
                # Extract meaningful terms
                terms = re.findall(r'\b\w+\b', query)
                terms = [t for t in terms if len(t) > 2 and t not in all_stopwords]
                popular_terms.update(terms)
        
        # Daily search volume
        daily_searches = defaultdict(int)
        for entry in analytics:
            date_str = entry['timestamp'][:10]  # YYYY-MM-DD
            daily_searches[date_str] += 1
        
        return {
            'total_searches': total_searches,
            'search_types': dict(search_types.most_common()),
            'popular_terms': dict(popular_terms.most_common(20)),
            'total_hits': total_hits_sum,
            'avg_hits_per_search': total_hits_sum / max(total_searches, 1),
            'daily_searches': dict(daily_searches),
            'days_analyzed': days
        }
    except Exception as e:
        app.logger.error(f"Error getting analytics data: {e}")
        return {}

def get_real_time_stats():
    """Get real-time statistics."""
    try:
        # Cache size
        cache_stats = {
            'cache_hits': getattr(cache, '_hits', 0),
            'cache_misses': getattr(cache, '_misses', 0)
        }
        
        # Document counts
        treaty_docs = len([f for f in os.listdir(JSON_DIR) if f.endswith('.json')]) if os.path.exists(JSON_DIR) else 0
        sp_docs = len([f for f in os.listdir(JSON_SP_DIR) if f.endswith('.json')]) if os.path.exists(JSON_SP_DIR) else 0
        
        # Recent search activity (last 24 hours)
        recent_analytics = get_analytics_data(days=1)
        
        return {
            'cache_stats': cache_stats,
            'document_counts': {
                'treaty_bodies': treaty_docs,
                'special_procedures': sp_docs,
                'total': treaty_docs + sp_docs
            },
            'recent_activity': {
                'searches_24h': recent_analytics.get('total_searches', 0),
                'hits_24h': recent_analytics.get('total_hits', 0)
            },
            'timestamp': datetime.now().isoformat()
        }
    except Exception as e:
        app.logger.error(f"Error getting real-time stats: {e}")
        return {}

# ── Basic routes (original + enhanced) ───────────────────────────────────────
@app.route('/')
def index():
    return render_template('index2.html')

@app.route('/enhanced')
def enhanced_index():
    """Enhanced route using new templates with analytics."""
    analytics = get_analytics_data(days=7)  # Last 7 days
    real_time_stats = get_real_time_stats()
    
    return render_template('enhanced_index.html', 
                         analytics=analytics,
                         real_time_stats=real_time_stats)

@app.route('/robots.txt')
def robots():
    return send_from_directory(app.static_folder, 'robots.txt')

@app.template_filter('get_info_by_filepath')
def jinja_get_info(json_file, gc_info_list):
    return next((item for item in gc_info_list if item["File PATH"].endswith(json_file)), None)

# ── Enhanced API endpoints ───────────────────────────────────────────────────
@app.route('/api/analytics/dashboard')
@enhanced_cache(timeout=600)  # Cache for 10 minutes
def api_analytics_dashboard():
    """API endpoint for analytics dashboard data."""
    try:
        days = request.args.get('days', default=30, type=int)
        analytics = get_analytics_data(days=days)
        return jsonify({
            'success': True,
            'data': analytics
        })
    except Exception as e:
        app.logger.error(f"Error in analytics dashboard API: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/stats/realtime')
def api_realtime_stats():
    """API endpoint for real-time statistics."""
    try:
        stats = get_real_time_stats()
        return jsonify({
            'success': True,
            'data': stats
        })
    except Exception as e:
        app.logger.error(f"Error in real-time stats API: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/search/suggestions')
@enhanced_cache(timeout=1800)  # Cache for 30 minutes
def api_search_suggestions():
    """API endpoint for search term suggestions."""
    try:
        query = request.args.get('q', '').lower()
        if len(query) < 2:
            return jsonify({'suggestions': []})
        
        # Get popular terms from analytics
        analytics = get_analytics_data(days=90)
        popular_terms = analytics.get('popular_terms', {})
        
        # Filter suggestions based on query
        suggestions = [
            term for term in popular_terms.keys()
            if query in term.lower() and len(term) > 2
        ][:10]
        
        return jsonify({
            'success': True,
            'suggestions': suggestions
        })
    except Exception as e:
        app.logger.error(f"Error in search suggestions API: {e}")
        return jsonify({
            'success': False,
            'suggestions': []
        })

# ── Enhanced search endpoints ────────────────────────────────────────────────
@app.route('/enhanced/search', methods=['GET'])
@enhanced_cache(timeout=300)
def enhanced_search():
    """Enhanced search with improved analytics and performance."""
    start_time = time.time()
    
    # Read parameters (same as original)
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

    # Enhanced search processing
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

    # Enhanced analytics calculation
    sorted_results = sorted(grouped.items(), key=lambda x: x[1]['total_count'], reverse=True)
    total_docs = len(grouped)
    most_concerned = label_counter.most_common(10)
    
    # Performance metrics
    search_time = time.time() - start_time
    performance_metrics = calculate_search_performance(grouped)
    performance_metrics['search_time'] = search_time

    export_key = str(time.time())
    with open(f'cache/{export_key}.pkl', 'wb') as cf:
        pickle.dump(grouped, cf)

    # Enhanced text analysis
    tokenizer = RegexpTokenizer(r'\w+')
    tokens = tokenizer.tokenize(all_text.lower())
    filtered_words = [w for w in tokens if w.isalpha() and w not in all_stopwords]
    most_common_words = Counter(filtered_words).most_common(20)
    bigrams_list = list(bigrams(filtered_words))
    most_common_bigrams = Counter(bigrams_list).most_common(20)
    committees_with_hits = sorted(committee_counter.items(), key=lambda x: x[1], reverse=True)

    # Log search for analytics
    user_ip = request.environ.get('HTTP_X_FORWARDED_FOR', request.environ.get('REMOTE_ADDR', 'unknown'))
    log_research_usage('treaty_bodies_enhanced', raw_query, total_hits, user_ip)

    return render_template(
        'enhanced_search_results.html',
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
        year_end=year_end,
        performance_metrics=performance_metrics
    )

# ── UN Documents browser (Special Procedures) ────────────────────────────────
@app.route('/documents')
def documents_browser():
    """Return the HTML front-end that contains the grid/list view."""
    return render_template('sp_documents.html')

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

# ── Main UN Treaty Bodies search (original) ──────────────────────────────────
@app.route('/search', methods=['GET'])
@cache.cached(timeout=300, query_string=True)
def search():
    """Original search functionality - maintained for compatibility."""
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

    # Log for analytics
    user_ip = request.environ.get('HTTP_X_FORWARDED_FOR', request.environ.get('REMOTE_ADDR', 'unknown'))
    log_research_usage('treaty_bodies', raw_query, total_hits, user_ip)

    return render_template(
        'search_results.html',
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

@app.route('/cookie-policy')
def cookie_policy():
    return render_template('cookie_policy.html')

# ── Special Procedures search (enhanced) ─────────────────────────────────────
@app.route('/specialprocedures')
def specialprocedures():
    return render_template('specialprocedures.html')

@app.route('/enhanced/specialprocedures')
def enhanced_specialprocedures():
    """Enhanced special procedures search with analytics."""
    analytics = get_analytics_data(days=7)
    return render_template('enhanced_specialprocedures.html', analytics=analytics)

@app.route('/specialprocedures/search', methods=['GET'])
@cache.cached(timeout=300, query_string=True)
def specialprocedures_search():
    """Original special procedures search - maintained for compatibility."""
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

        year = int(info.get('Adoption year', 0) or 0)
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

    # Log for analytics
    user_ip = request.environ.get('HTTP_X_FORWARDED_FOR', request.environ.get('REMOTE_ADDR', 'unknown'))
    log_research_usage('special_procedures', raw_query, total_hits, user_ip)

    return render_template(
        'search_results.html',
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

@app.route('/enhanced/specialprocedures/search', methods=['GET'])
@enhanced_cache(timeout=300)
def enhanced_specialprocedures_search():
    """Enhanced special procedures search with improved performance and analytics."""
    start_time = time.time()
    
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

        year = int(info.get('Adoption year', 0) or 0)
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

    # Enhanced analytics
    sorted_results = sorted(grouped.items(), key=lambda x: x[1]['total_count'], reverse=True)
    total_docs = len(grouped)
    most_concerned = label_counter.most_common(10)
    
    search_time = time.time() - start_time
    performance_metrics = calculate_search_performance(grouped)
    performance_metrics['search_time'] = search_time

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

    # Log for analytics
    user_ip = request.environ.get('HTTP_X_FORWARDED_FOR', request.environ.get('REMOTE_ADDR', 'unknown'))
    log_research_usage('special_procedures_enhanced', raw_query, total_hits, user_ip)

    return render_template(
        'enhanced_search_results.html',
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
        year_end=year_end,
        performance_metrics=performance_metrics
    )

# ── Load Neurorights corpus & search endpoint (enhanced) ─────────────────────
with open("Neurorights.json", "r", encoding="utf-8") as file:
    neurorights_data = json.load(file)

print(f"Neurorights data loaded: {len(neurorights_data)} items")

for item in neurorights_data:
    item['Title_original']    = item['Title']
    item['Abstract_original'] = item['Abstract']

@app.route('/neurorights_search', methods=['GET'])
def neurorights_search():
    """Original neurorights search - maintained for compatibility."""
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

    # Log for analytics
    user_ip = request.environ.get('HTTP_X_FORWARDED_FOR', request.environ.get('REMOTE_ADDR', 'unknown'))
    log_research_usage('neurorights', search_query, total_items, user_ip)

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

@app.route('/enhanced/neurorights_search', methods=['GET'])
@enhanced_cache(timeout=300)
def enhanced_neurorights_search():
    """Enhanced neurorights search with improved analytics and performance."""
    start_time = time.time()
    
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

    # Enhanced analytics processing
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

    # Performance metrics
    search_time = time.time() - start_time
    performance_metrics = {
        'search_time': search_time,
        'total_items': total_items,
        'items_per_page': per_page,
        'total_pages': total_pages
    }

    # Log for analytics
    user_ip = request.environ.get('HTTP_X_FORWARDED_FOR', request.environ.get('REMOTE_ADDR', 'unknown'))
    log_research_usage('neurorights_enhanced', search_query, total_items, user_ip)

    return render_template(
        'enhanced_neurorights_search.html',
        search_results           = search_results,
        total_filtered_results   = total_items,
        search_query             = search_query,
        top_bigrams              = '; '.join(top_bigrams_str),
        top_authors              = '; '.join(['{} ({})'.format(a, c) for a, c in top_authors]),
        top_keywords             = '; '.join(['{} ({})'.format(k, c) for k, c in top_keywords]),
        total_pages              = total_pages,
        current_page             = page,
        performance_metrics      = performance_metrics
    )

# ── Error handlers ───────────────────────────────────────────────────────────
@app.errorhandler(404)
def not_found_error(error):
    app.logger.warning(f"404 error: {request.url}")
    return render_template('errors/404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    app.logger.error(f"500 error: {error}")
    return render_template('errors/500.html'), 500

@app.errorhandler(Exception)
def handle_exception(e):
    app.logger.error(f"Unhandled exception: {e}", exc_info=True)
    return render_template('errors/500.html'), 500

# ── Run (only locally; PythonAnywhere uses WSGI) ─────────────────────────────
if __name__ == '__main__':
    app.run(debug=True, port=5001)  # Different port to run alongside original