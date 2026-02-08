from flask import Flask, render_template, request, send_file
import json
import os
from elasticsearch import Elasticsearch, exceptions
from collections import defaultdict
import re
import pandas as pd
from collections import Counter
import sys

# Load the crc_gc_info.json file
with open("crc_gc_info.json", "r", encoding="utf-8") as file:
    crc_gc_info = json.load(file)

app = Flask(__name__, static_folder='static')

# Fetch Elasticsearch credentials from environment variables
es_api_key = "MXJlYVM0d0JoOHd4WHJoOG5sdE46RnlnX2hEZzBRbjIySm5Jc2pzMm5BQQ=="
es_url = "https://56d3919933e04f5c92332a6a6ba76985.europe-west3.gcp.cloud.es.io:443"

# Check if API key and URL are not None
if es_api_key is None or es_url is None:
    print("Elasticsearch API key or URL are not set in environment variables.")
    sys.exit(1)

# Initialize the Elasticsearch client
try:
    es = Elasticsearch(
        [es_url],
        api_key=es_api_key,
        verify_certs=True
    )
    print("Connected to Elasticsearch.")
except exceptions.ConnectionError as e:
    print(f"Failed to connect to Elasticsearch: {e}")
    sys.exit(1)

# Check if Elasticsearch is running
#if not es.ping():
#    print("Elasticsearch is not running!")
#    sys.exit(1)

# Create an index
index_name = 'my_paragraphs'
if not es.indices.exists(index=index_name):
    es.indices.create(index=index_name)
    print(f"Created index {index_name}.")

# Directory containing JSON files
json_dir = os.path.join(os.getcwd(), 'json_data')

# Read and index each JSON file
json_files = [f for f in os.listdir(json_dir) if f.endswith('.json')]
for json_file in json_files:
    with open(os.path.join(json_dir, json_file), "r", encoding='utf-8-sig') as f:
        paragraphs = json.load(f)
    for idx, paragraph in enumerate(paragraphs):
        es.index(index=index_name, id=f"{json_file}_{idx}", document=paragraph)
    print(f"Indexed paragraphs from {json_file}.")

# Text formatting function
def format_text(text):
    return re.sub(r'(\([a-zA-Z0-9]\))', r'\n\1', text)

# Global variable to store the search results temporarily
grouped_results_global = None

@app.route('/')
def index():
    return render_template('index2.html')

@app.template_filter('get_info_by_filepath')
def get_info_by_filepath(json_file, crc_gc_info):
    return next((item for item in crc_gc_info if item["File PATH"].endswith(json_file)), None)

@app.route('/search', methods=['POST'])
def search():
    global grouped_results_global
    query = request.form['search_query'].strip()
    selected_labels = request.form.getlist('labels')
    selected_labels = [label for label in selected_labels if label != "None"]

    if not query and not selected_labels:
        return "Enter search query or select at least one concerned group to run the database."

    must_clauses = []
    filter_clauses = []

    if query:
        must_clauses.append({
            "query_string": {
                "default_field": "Text",
                "query": query
            }
        })

    if selected_labels:
        filter_clauses.append({"terms": {"Labels.keyword": selected_labels}})

    search_body = {
        "query": {
            "bool": {
                "must": must_clauses,
                "filter": filter_clauses
            }
        },
        "highlight": {
            "pre_tags": ['<span style="background-color: yellow;">'],
            "post_tags": ['</span>'],
            "fields": {
                "Text": {"number_of_fragments": 0}
            }
        }
    }

    response = es.search(index=index_name, body=search_body, size=1000)
    results = response['hits']['hits']
    num_hits = response['hits']['total']['value']
    num_docs = es.count(index=index_name)['count']

    grouped_results = defaultdict(list)
    for hit in results:
        json_file, paragraph_num = hit['_id'].rsplit('_', 1)
        highlighted_text = hit.get('highlight', {}).get('Text', [hit['_source']['Text']])[0]
        labels = ', '.join(hit['_source'].get('Labels', [])) or 'None'
        grouped_results[json_file].append({
            'id': hit['_id'],
            'score': hit['_score'],
            'text': f"Paragraph {paragraph_num}: {hit['_source']['Text']}",
            'highlight': highlighted_text,
            'labels': labels
        })

    concerned_groups_counter = Counter()
    for hit in results:
        labels = hit['_source'].get('Labels', [])
        for label in labels:
            concerned_groups_counter[label] += 1

    concerned_groups_distribution = dict(sorted(concerned_groups_counter.items(), key=lambda item: item[1], reverse=True))

    grouped_results_global = grouped_results

    return render_template('search_results.html', grouped_results=grouped_results, num_hits=num_hits,
                           num_docs=num_docs, concerned_groups_distribution=concerned_groups_distribution,
                           crc_gc_info=crc_gc_info)

@app.route('/export_to_excel', methods=['GET'])
def export_to_excel():
    global grouped_results_global
    if grouped_results_global is None:
        return "No data to export", 400

    rows = []
    for json_file, paragraphs in grouped_results_global.items():
        for paragraph in paragraphs:
            row = {
                'Text': format_text(paragraph['text']),
                'Concerned Persons/Groups': paragraph.get('labels', '-'),
                'Source File': json_file
            }
            rows.append(row)

    df = pd.DataFrame(rows)

    # Define the path to the folder where the Excel file will be saved
    save_folder = os.path.join(os.getcwd(), 'SavedXLS')

    # Create the folder if it doesn't exist
    os.makedirs(save_folder, exist_ok=True)

    # Define the full path for the Excel file
    excel_path = os.path.join(save_folder, 'search_results.xlsx')

    # Save the DataFrame to an Excel file
    df.to_excel(excel_path, index=False)

    return send_file(excel_path, as_attachment=True, download_name='search_results.xlsx')

# Load the Neurorights.json file
with open("Neurorights.json", "r", encoding="utf-8") as file:
    neurorights_data = json.load(file)

print(f"Neurorights data loaded: {len(neurorights_data)} items")
print(neurorights_data[0])  # Print the first item in the data

@app.route('/neurorights_search', methods=['GET'])
def neurorights_search():
    search_query = request.args.get('search_query', '').strip().lower()
    neurorights_filters = request.args.getlist('neurorights_filters')
    search_fields = request.args.getlist('search_fields')
    year_start = request.args.get('year_start', default=None, type=int)
    year_end = request.args.get('year_end', default=None, type=int)
    only_open_access = 'only_open_access' in request.args

    search_results = []

    for item in neurorights_data:
        item_year = int(item.get('Year', 0))  # Assuming each item has a 'Year' key

        # Check if the item's year falls within the specified range
        if year_start and year_end and not (year_start <= item_year <= year_end):
            continue  # Skip this document if it doesn't fall within the year range

        # Now checking if the item matches the neurorights filters
        if not matches_neurorights_filters(item, neurorights_filters):
            continue

        # Check if the search query matches within the selected search fields
        if not matches_search_query(item, search_query, search_fields):
            continue

        # Check if Only Open Access filter is applied and document has "All Open Access"
        if only_open_access and 'All Open Access' not in item.get('Open Access', ''):
            continue

        search_results.append(item)

    # Sort the search results by year, newest first
    search_results.sort(key=lambda x: x.get('Year', 0), reverse=True)

    return render_template('neurorights_search.html', search_results=search_results, search_query=search_query)

def matches_neurorights_filters(item, neurorights_filters):
    if not neurorights_filters:
        return True  # No filter selected, so everything matches
    text_to_search = item.get('Title', '') + " " + item.get('Abstract', '') + " " + " ".join(item.get('Author Keywords', []))
    text_to_search = text_to_search.lower()
    return any(nf.lower() in text_to_search for nf in neurorights_filters)

def matches_search_query(item, query, fields):
    if not query:
        return True  # No query means match everything
    if not fields:  # If no fields are selected, search across all
        fields = ['Title', 'Abstract', 'Keywords']
    text_to_search = ""
    if 'Title' in fields:
        text_to_search += item.get('Title', '')
    if 'Abstract' in fields:
        text_to_search += " " + item.get('Abstract', '')
    if 'Keywords' in fields:
        text_to_search += " " + " ".join(item.get('Author Keywords', []))
    text_to_search = text_to_search.lower()
    return query in text_to_search

@app.route('/diagram')
def index():
    return render_template('diagram.html')

if __name__ == '__main__': # This is for running the app locally and allowing external users to visit your localhost
    app.run(host='0.0.0.0', debug=True)

#if __name__ == '__main__': # This is for running the app locally
#    app.run(debug=True)