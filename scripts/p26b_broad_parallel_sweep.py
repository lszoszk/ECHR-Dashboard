#!/usr/bin/env python3
"""Parallel P26 sweep — fill missing-paragraph gaps from HUDOC source DOCX
across all sub-100% cases.  Uses ThreadPoolExecutor since the work is
network-bound."""
import json, re, ssl, sys, urllib.request, io, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from docx import Document

DOCX_URL = "https://hudoc.echr.coe.int/app/conversion/docx/?library=ECHR&id={cid}&filename={cid}.docx"
API_BASE = "https://150.254.115.204/echr-api/api"
PARA_NUM_RE = re.compile(r"^\s*(\d+)\.\s+")
HEADING_RULES = [
    ("FOR THESE REASONS", "Operative part"),
    ("APPLICATION OF ARTICLE 41", "Just Satisfaction"),
    ("JUST SATISFACTION", "Just Satisfaction"),
    ("OTHER COMPLAINTS", "Merits"),
    ("ALLEGED VIOLATION OF ARTICLE", "Merits"),
    ("THE COURT'S ASSESSMENT", "Merits"),
    ("THE COURT’S ASSESSMENT", "Merits"),
    ("SUBJECT MATTER OF THE CASE", "Facts"),
    ("THE FACTS", "Facts"),
    ("PROCEDURE", "Facts"),
    ("THE LAW", "Merits"),
    ("RELEVANT LEGAL FRAMEWORK", "Legal Framework"),
    ("RELEVANT DOMESTIC LAW", "Legal Framework"),
]
ctx = ssl._create_unverified_context()

def fetch_docx(cid):
    req = urllib.request.Request(DOCX_URL.format(cid=cid),
        headers={"User-Agent": "Mozilla/5.0", "Accept": "*/*"})
    return urllib.request.urlopen(req, context=ctx, timeout=25).read()

def is_heading(t):
    if not t or len(t) > 100: return False
    if PARA_NUM_RE.match(t): return False
    upper = sum(1 for c in t if c.isalpha() and c.isupper())
    lower = sum(1 for c in t if c.isalpha() and c.islower())
    return upper >= 4 and upper > lower * 3

def section_for(h):
    H = h.upper()
    for needle, sec in HEADING_RULES:
        if needle in H: return sec
    return None

def parse(blob):
    doc = Document(io.BytesIO(blob))
    cur_section = None
    out = []
    for p in doc.paragraphs:
        text = (p.text or "").strip()
        if not text: continue
        if is_heading(text):
            s = section_for(text)
            if s: cur_section = s
            continue
        m = PARA_NUM_RE.match(text)
        if not m: continue
        out.append({"n": int(m.group(1)), "text": text, "section": cur_section or "Facts"})
    return out

def get_existing(cid):
    url = f"{API_BASE}/cases/{cid}"
    req = urllib.request.Request(url, headers={"User-Agent":"sweep/1.0"})
    d = json.loads(urllib.request.urlopen(req, context=ctx, timeout=15).read())
    return {p["hudoc_para_no"] for p in d.get("paragraphs", [])
            if p.get("hudoc_para_no") and p.get("numbering_block") != "operative_dispositif"}

def process_case(cid):
    """Returns list of (cid, section, n, text) tuples for missing paragraphs."""
    try:
        existing = get_existing(cid)
        blob = fetch_docx(cid)
        parsed = parse(blob)
    except Exception as e:
        return ("FAIL", cid, str(e)[:80])
    inserts = [(cid, p["section"], p["n"], p["text"])
               for p in parsed if p["n"] not in existing]
    return ("OK", cid, inserts)

# Read case list
cases = [l.strip() for l in Path("/tmp/sub100_cases.txt").open() if l.strip()]
print(f"sweep target: {len(cases):,} cases")

# Run with 8 threads
all_inserts = []
fail_count = 0
done_count = 0
start = time.time()
lock = Lock()

with ThreadPoolExecutor(max_workers=8) as ex:
    futures = {ex.submit(process_case, cid): cid for cid in cases}
    for fut in as_completed(futures):
        result = fut.result()
        with lock:
            done_count += 1
            if result[0] == "FAIL":
                fail_count += 1
            else:
                all_inserts.extend(result[2])
            if done_count % 200 == 0 or done_count == len(cases):
                elapsed = time.time() - start
                rate = done_count / elapsed if elapsed > 0 else 0
                eta = (len(cases) - done_count) / rate if rate > 0 else 0
                print(f"  {done_count:,}/{len(cases):,}  inserts={len(all_inserts):,}  "
                      f"fails={fail_count}  rate={rate:.1f}/s  eta={eta:.0f}s")

print(f"\ntotal: {len(all_inserts):,} inserts, {fail_count} failures")

# Write SQL
out_path = Path("/tmp/p26_broad_sweep.sql")
with out_path.open("w") as f:
    for cid, sec, n, text in all_inserts:
        t = text.replace("'", "''").replace("\n", " ")
        f.write(f"INSERT INTO paragraphs (case_id, section, para_idx, hudoc_para_no, numbering_block, text) "
                f"VALUES ('{cid}', '{sec}', NULL, {n}, 'main_judgment', '{t}');\n")
print(f"SQL written to: {out_path} ({out_path.stat().st_size:,} bytes)")
