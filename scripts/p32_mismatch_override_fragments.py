#!/usr/bin/env python3
"""P32 mismatch override — for cases still sub-100% after rounds 1 and 2,
demote rows whose text doesn't match HUDOC ¶ N's first-60-char prefix,
then insert HUDOC's canonical text.

This fixes the L.P.-style failure where the segmenter mistagged a
mid-text reference like "1. (a) of Protocol No. 7" as paragraph 1."""
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
    """Parse DOCX paragraphs.  Only accept ¶ N when N strictly exceeds the
    max ¶ seen so far — this filters out the in-Legal-Framework numbered
    lists ("1. Civil Code, 2. Law of …") that reset numbering and would
    otherwise pollute main-body paragraph extraction.

    Tolerance: allow ONE small "reset" of ≤2 if the very first numbered
    paragraph in the doc is ¶ 1 — sometimes a procedural-history block
    starts at ¶ 1 then re-resets when entering Subject Matter.  We
    detect this by allowing the second-ever ¶ to be ≤ the first.
    Beyond that, monotonic-only."""
    doc = Document(io.BytesIO(blob))
    cur_section = None
    out = []
    max_seen = 0
    accept_count = 0
    for p in doc.paragraphs:
        text = (p.text or "").strip()
        if not text: continue
        if is_heading(text):
            s = section_for(text)
            if s: cur_section = s
            continue
        m = PARA_NUM_RE.match(text)
        if not m: continue
        n = int(m.group(1))
        # Monotonic guard
        if accept_count > 0 and n <= max_seen:
            # Allow second-ever paragraph to be a small reset
            if not (accept_count == 1 and n <= 3 and max_seen <= 3):
                continue
        out.append({"n": n, "text": text, "section": cur_section or "Facts"})
        max_seen = max(max_seen, n)
        accept_count += 1
    return out

def get_existing(cid):
    """Returns dict of n -> [(rowid, text), ...]"""
    url = f"{API_BASE}/cases/{cid}"
    req = urllib.request.Request(url, headers={"User-Agent":"sweep/1.0"})
    d = json.loads(urllib.request.urlopen(req, context=ctx, timeout=15).read())
    out = {}
    # API doesn't expose rowid directly — match by hudoc_para_no + text
    for p in d.get("paragraphs", []):
        n = p.get("hudoc_para_no")
        if not n or p.get("numbering_block") == "operative_dispositif":
            continue
        out.setdefault(n, []).append({"text": p.get("text", ""), "section": p.get("section", "")})
    return out

def first60_norm(t):
    """Normalised first-60 for fuzzy comparison: strip leading 'N. ' and
    extra whitespace, lower, take 60 chars."""
    if not t: return ""
    s = re.sub(r"^\s*\d+\.\s+", "", t)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:60].lower()

def process_case(cid):
    """Returns (cid, status, sql_lines)
    sql_lines: SQL statements to execute on VM"""
    try:
        existing = get_existing(cid)
        blob = fetch_docx(cid)
        parsed = parse(blob)
    except Exception as e:
        return (cid, "FAIL", str(e)[:80], [])

    sql = []
    for p in parsed:
        n = p["n"]
        hudoc_text = p["text"]
        hudoc_norm = first60_norm(hudoc_text)
        if not hudoc_norm: continue

        existing_rows = existing.get(n, [])
        if existing_rows:
            # Conservative override: only demote when our existing row is
            # CLEARLY wrong / fragment-like.  python-docx drops styled
            # spans (italic case names, redacted entities), so HUDOC's
            # parsed text often reads "the approved" while ours has "the
            # Commercial Court approved" — a naive prefix mismatch sees
            # difference where there isn't one.
            #
            # Decision rule: keep our row when ANY of these holds:
            #   * substantial word overlap with HUDOC (>50% of HUDOC's
            #     first-12 content words appear in ours);
            #   * our text is LONGER than HUDOC's (we have content the
            #     extractor dropped);
            #   * exact prefix match on first 30 chars.
            # Otherwise treat ours as fragment-like and override.
            def words_of(s):
                return [w.lower() for w in re.findall(r"\w{3,}", s) if w.isalpha()]
            hudoc_words = words_of(hudoc_text)[:12]
            keep_existing = False
            for r in existing_rows:
                ours_text = r["text"] or ""
                if not ours_text:
                    continue
                ours_words = set(words_of(ours_text)[:50])
                # 50%+ word overlap?
                if hudoc_words and sum(1 for w in hudoc_words if w in ours_words) >= len(hudoc_words) * 0.5:
                    keep_existing = True
                    break
                # Our text noticeably longer (we have richer content)?
                if len(ours_text) >= len(hudoc_text) * 0.95:
                    keep_existing = True
                    break
                # Exact 30-char prefix
                if first60_norm(ours_text)[:30] and first60_norm(ours_text)[:30] == hudoc_norm[:30]:
                    keep_existing = True
                    break
            if keep_existing:
                continue
            # Mismatch + fragment-like: override
            t = hudoc_text.replace("'", "''").replace("\n", " ")
            sql.append(
                f"UPDATE paragraphs SET hudoc_para_no = NULL "
                f"WHERE case_id = '{cid}' AND hudoc_para_no = {n} "
                f"AND (numbering_block IS NULL OR numbering_block != 'operative_dispositif');"
            )
            sql.append(
                f"INSERT INTO paragraphs (case_id, section, para_idx, hudoc_para_no, numbering_block, text) "
                f"VALUES ('{cid}', '{p['section']}', NULL, {n}, 'main_judgment', '{t}');"
            )
        else:
            # Number absent — straight insert
            t = hudoc_text.replace("'", "''").replace("\n", " ")
            sql.append(
                f"INSERT INTO paragraphs (case_id, section, para_idx, hudoc_para_no, numbering_block, text) "
                f"VALUES ('{cid}', '{p['section']}', NULL, {n}, 'main_judgment', '{t}');"
            )
    return (cid, "OK", "", sql)

cases = [l.strip() for l in Path(sys.argv[1]).open() if l.strip()]
print(f"P32 override sweep — {len(cases)} cases")

all_sql = []
fail_count = 0
done_count = 0
demoted = 0
inserted = 0
start = time.time()
lock = Lock()

with ThreadPoolExecutor(max_workers=8) as ex:
    futures = {ex.submit(process_case, cid): cid for cid in cases}
    for fut in as_completed(futures):
        cid, status, err, sql = fut.result()
        with lock:
            done_count += 1
            if status == "FAIL":
                fail_count += 1
            else:
                all_sql.extend(sql)
                for s in sql:
                    if s.startswith("UPDATE"): demoted += 1
                    elif s.startswith("INSERT"): inserted += 1
            if done_count % 200 == 0 or done_count == len(cases):
                elapsed = time.time() - start
                rate = done_count / elapsed if elapsed > 0 else 0
                print(f"  {done_count:,}/{len(cases):,}  demoted={demoted:,} inserted={inserted:,} fails={fail_count} rate={rate:.1f}/s")

print(f"\ntotal demotions: {demoted}, inserts: {inserted}, fetch failures: {fail_count}")

out_path = Path("/tmp/p32_override.sql")
out_path.write_text("\n".join(all_sql) + "\n")
print(f"SQL written to: {out_path} ({out_path.stat().st_size:,} bytes)")
