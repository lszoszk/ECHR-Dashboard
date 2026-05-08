#!/usr/bin/env python3
"""P34 full rebuild — replace each case's main-judgment paragraphs with what
HUDOC's source DOCX actually contains.

Rationale: rather than chasing fragment-vs-canonical heuristics (P26b, P32,
P33), trust HUDOC as the single source of truth.  python-docx returns one
string per `<w:p>` element with all styled runs concatenated, so styled
case-name spans / hyperlinked numbers no longer fragment paragraphs.

Scope:
  REPLACES rows where  numbering_block IS NULL OR numbering_block = 'main_judgment'
  KEEPS    rows where  numbering_block = 'operative_dispositif'
                   OR  numbering_block LIKE 'separate_opinion_%'
                   OR  numbering_block = 'pop_c_*'  (any other custom tag)

Output:
  /tmp/p34_rebuild.sql           — forward (DELETE + INSERTs)
  /tmp/p34_rebuild_rollback.sql  — pre-state snapshot of replaced rows
                                    (full INSERT statements to restore)
"""
import json, re, ssl, sys, urllib.request, io, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from docx import Document

DOCX_URL = "https://hudoc.echr.coe.int/app/conversion/docx/?library=ECHR&id={cid}&filename={cid}.docx"
API_BASE = "https://150.254.115.204/echr-api/api"
PARA_NUM_RE = re.compile(r"^\s*(\d+)\.\s+")
ctx = ssl._create_unverified_context()

# Section assignment from major all-caps headers.  Order = priority (longer
# match first when needles overlap).
HEADING_RULES = [
    ("FOR THESE REASONS",            "Operative part"),
    ("APPLICATION OF ARTICLE 41",    "Just Satisfaction"),
    ("JUST SATISFACTION",            "Just Satisfaction"),
    ("OTHER ALLEGED VIOLATIONS",     "Merits"),
    ("OTHER COMPLAINTS",             "Merits"),
    ("ALLEGED VIOLATION OF",         "Merits"),
    ("THE COURT'S ASSESSMENT",       "Merits"),
    ("THE COURT’S ASSESSMENT",  "Merits"),
    ("SUBJECT MATTER OF THE CASE",   "Facts"),
    ("THE FACTS",                    "Facts"),
    ("THE CIRCUMSTANCES OF THE CASE","Facts"),
    ("PROCEDURE",                    "Facts"),
    ("RELEVANT LEGAL FRAMEWORK",     "Legal Framework"),
    ("RELEVANT DOMESTIC LAW",        "Legal Framework"),
    ("RELEVANT INTERNATIONAL",       "Legal Framework"),
    ("THE LAW",                      "Merits"),
]

# Stop processing main judgment when we hit one of these — separate
# opinions and document footer are out of scope.
STOP_PATTERNS = [
    re.compile(r"^Done in (English|French)", re.I),
    re.compile(r"^Fait en (anglais|fran[cç]ais)", re.I),
    re.compile(r"^(SEPARATE|DISSENTING|CONCURRING|JOINT)\s+(PARTLY\s+)?(CONCURRING|DISSENTING|JOINT|OPINION|OPINIONS|DECLARATION)", re.I),
    re.compile(r"^OPINION (CONCORDANT|DISSIDENT|S[EÉ]PAR[EÉ]E)", re.I),
]


def fetch_docx(cid):
    """Fetch DOCX with exponential backoff on 403/429 (rate-limit) errors."""
    backoff = [3, 10, 30]
    for attempt, wait in enumerate([0] + backoff):
        if wait:
            time.sleep(wait)
        try:
            req = urllib.request.Request(DOCX_URL.format(cid=cid),
                headers={"User-Agent": "Mozilla/5.0", "Accept": "*/*"})
            return urllib.request.urlopen(req, context=ctx, timeout=25).read()
        except urllib.error.HTTPError as e:
            if e.code in (403, 429) and attempt < len(backoff):
                continue
            raise
        except Exception:
            if attempt < len(backoff):
                continue
            raise
    raise RuntimeError("fetch_docx exhausted retries")


def is_likely_heading(text):
    """A line that *looks like* a heading: short and dominantly uppercase.
    Real numbered paragraphs are long and have plenty of lowercase, so they
    fail this gate even when their text mentions heading keywords like
    'the law' inside 'the lawfulness'.  Cap length to 220 (existing rule)."""
    if not text or len(text) > 220:
        return False
    upper = sum(1 for c in text if c.isalpha() and c.isupper())
    lower = sum(1 for c in text if c.isalpha() and c.islower())
    if upper == 0:
        return False
    # Mostly uppercase, OR very short title-case ("THE LAW", "PROCEDURE").
    return upper >= lower * 2 or (len(text) <= 50 and upper >= 4)


def section_for_header(text):
    if not is_likely_heading(text):
        return None
    upper = text.upper()
    for needle, sec in HEADING_RULES:
        # word-boundary match — avoids "THE LAW" hitting "THE LAWFULNESS"
        if re.search(r"\b" + re.escape(needle.upper()) + r"\b", upper):
            return sec
    return None


def parse_docx(blob):
    """Return ordered list of paragraph dicts for the main-judgment portion.

    Each dict: {section, hudoc_para_no, numbering_block, text}

    Section is inherited from the most recent recognised heading.  Big
    headers themselves are emitted as Header rows (numbering_block=NULL).
    Numbered paragraphs (¶ N) become main_judgment rows with hudoc_para_no=N.
    Everything else (sub-section titles like "A. Damage", "(a) The
    applicant") becomes a NULL-numbered main_judgment row — the frontend's
    isStructuralHeading regex picks them up as headings at render time.
    Monotonic-only ¶ N filter to avoid Legal-Framework numbered list items
    polluting paragraph numbering.
    """
    doc = Document(io.BytesIO(blob))
    out = []
    section = "Facts"
    in_legal_framework = False
    max_para_seen = 0
    para_accept_count = 0
    # Skip the cover page / pre-PROCEDURE preamble (case caption, dateline,
    # composition, "Having regard to…").  Start emitting only after we hit
    # the first big section heading.
    started = False

    for p in doc.paragraphs:
        text = (p.text or "").strip()
        if not text:
            continue

        # Stop at separate-opinion / footer
        if any(pat.match(text) for pat in STOP_PATTERNS):
            break

        # Big section header?
        new_section = section_for_header(text)
        if new_section:
            if not started:
                started = True
            # Operative part marks the end of main judgment
            if new_section == "Operative part":
                # Emit nothing — existing operative_dispositif rows stay
                break
            section = new_section
            in_legal_framework = (section == "Legal Framework")
            out.append({
                "section": "Header",
                "hudoc_para_no": None,
                "numbering_block": None,
                "text": text,
            })
            continue

        if not started:
            # Skip cover page / pre-PROCEDURE preamble entirely
            continue

        # Numbered paragraph?
        m = PARA_NUM_RE.match(text)
        if m:
            n = int(m.group(1))
            if in_legal_framework:
                # Don't number Legal Framework list items — they reset
                out.append({
                    "section": section,
                    "hudoc_para_no": None,
                    "numbering_block": "main_judgment",
                    "text": text,
                })
                continue
            if para_accept_count > 0 and n <= max_para_seen:
                # Allow exactly one small early reset
                if not (para_accept_count == 1 and n <= 3 and max_para_seen <= 3):
                    # Treat as non-paragraph content (probably a numbered
                    # list item embedded in text we shouldn't renumber)
                    out.append({
                        "section": section,
                        "hudoc_para_no": None,
                        "numbering_block": "main_judgment",
                        "text": text,
                    })
                    continue
            out.append({
                "section": section,
                "hudoc_para_no": n,
                "numbering_block": "main_judgment",
                "text": text,
            })
            max_para_seen = max(max_para_seen, n)
            para_accept_count += 1
            continue

        # Sub-section heading or unmarked content — keep as
        # main_judgment NULL-numbered.  Frontend isStructuralHeading
        # picks up real headings (A. Damage, (a) The applicant, etc.).
        out.append({
            "section": section,
            "hudoc_para_no": None,
            "numbering_block": "main_judgment",
            "text": text,
        })

    return out


def get_existing_rows(cid):
    """Return rows from API; we use this to capture pre-state for rollback."""
    url = f"{API_BASE}/cases/{cid}"
    req = urllib.request.Request(url, headers={"User-Agent": "p34/1.0"})
    return json.loads(urllib.request.urlopen(req, context=ctx, timeout=15).read()).get("paragraphs", [])


def sql_escape(s):
    if s is None:
        return "NULL"
    return "'" + s.replace("'", "''").replace("\n", " ") + "'"


def sql_value(v):
    if v is None:
        return "NULL"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, str):
        return sql_escape(v)
    return sql_escape(str(v))


def process_case(cid):
    """Returns dict with status, sql, rollback, stats."""
    try:
        existing = get_existing_rows(cid)
        blob = fetch_docx(cid)
        new_rows = parse_docx(blob)
    except Exception as e:
        return {"cid": cid, "status": "FAIL", "err": str(e)[:80]}

    # Capture pre-state of rows we'll replace (numbering_block IS NULL or 'main_judgment')
    replaced_rows = [
        r for r in existing
        if r.get("numbering_block") in (None, "main_judgment")
    ]

    if not new_rows:
        return {"cid": cid, "status": "NOCAN", "old_count": len(replaced_rows)}

    forward = []
    forward.append(
        f"DELETE FROM paragraphs WHERE case_id = '{cid}' "
        f"AND (numbering_block IS NULL OR numbering_block = 'main_judgment');"
    )
    for r in new_rows:
        forward.append(
            f"INSERT INTO paragraphs (case_id, section, para_idx, hudoc_para_no, numbering_block, text) "
            f"VALUES ('{cid}', {sql_value(r['section'])}, NULL, {sql_value(r['hudoc_para_no'])}, "
            f"{sql_value(r['numbering_block'])}, {sql_value(r['text'])});"
        )

    # Rollback: restore pre-state via INSERTs (and DELETE everything we'll write).
    rollback = []
    rollback.append(
        f"DELETE FROM paragraphs WHERE case_id = '{cid}' "
        f"AND (numbering_block IS NULL OR numbering_block = 'main_judgment');"
    )
    for r in replaced_rows:
        rollback.append(
            f"INSERT INTO paragraphs (case_id, section, para_idx, hudoc_para_no, numbering_block, text) "
            f"VALUES ('{cid}', {sql_value(r.get('section'))}, NULL, "
            f"{sql_value(r.get('hudoc_para_no'))}, {sql_value(r.get('numbering_block'))}, "
            f"{sql_value(r.get('text'))});"
        )

    return {
        "cid": cid, "status": "OK",
        "sql": forward, "rollback": rollback,
        "old_count": len(replaced_rows), "new_count": len(new_rows),
    }


def main():
    if len(sys.argv) < 2:
        print("usage: p34_rebuild_from_hudoc.py CASE_LIST [sweep|diff]")
        sys.exit(1)
    cases = [l.strip() for l in Path(sys.argv[1]).open() if l.strip()]
    mode = sys.argv[2] if len(sys.argv) > 2 else "sweep"
    print(f"P34 rebuild — {len(cases)} cases, mode={mode}")

    results = []
    fail_count = nocan_count = done_count = 0
    total_old = total_new = 0
    start = time.time()
    lock = Lock()

    # Lower concurrency on retry passes — HUDOC tightens rate-limit when it
    # sees parallel fetches.  Default 6, but env var can override.
    import os
    workers = 2 if mode == "diff" else int(os.environ.get("P34_WORKERS", "6"))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(process_case, cid): cid for cid in cases}
        for fut in as_completed(futures):
            r = fut.result()
            with lock:
                done_count += 1
                results.append(r)
                if r["status"] == "FAIL":
                    fail_count += 1
                elif r["status"] == "NOCAN":
                    nocan_count += 1
                else:
                    total_old += r.get("old_count", 0)
                    total_new += r.get("new_count", 0)
                if mode == "sweep" and (done_count % 200 == 0 or done_count == len(cases)):
                    elapsed = time.time() - start
                    rate = done_count / elapsed if elapsed > 0 else 0
                    eta = (len(cases) - done_count) / rate if rate > 0 else 0
                    print(f"  {done_count:,}/{len(cases):,}  old_rows={total_old:,}  new_rows={total_new:,}  fails={fail_count}  nocan={nocan_count}  rate={rate:.1f}/s  eta={eta:.0f}s")

    print(f"\nold rows replaced: {total_old:,}")
    print(f"new rows inserted: {total_new:,}")
    print(f"fetch failures:   {fail_count}")
    print(f"no-canonical:     {nocan_count}")

    if mode == "diff":
        print("\n" + "=" * 100)
        for r in sorted(results, key=lambda x: x.get("cid", "")):
            cid = r["cid"]
            if r["status"] == "FAIL":
                print(f"\n❌ {cid}  FAIL  {r.get('err','')}")
                continue
            if r["status"] == "NOCAN":
                print(f"\n➖ {cid}  no parsable content (no main-judgment paragraphs)")
                continue
            print(f"\n=== {cid}  old={r['old_count']}  new={r['new_count']} ===")

    out_name = os.environ.get("P34_OUT", "/tmp/p34_rebuild.sql")
    rb_name = os.environ.get("P34_ROLLBACK", "/tmp/p34_rebuild_rollback.sql")
    append = os.environ.get("P34_APPEND") == "1"
    out = Path(out_name)
    rb = Path(rb_name)
    all_fwd, all_rb = [], []
    for r in results:
        all_fwd.extend(r.get("sql", []))
        all_rb.extend(r.get("rollback", []))
    fwd_text = "\n".join(all_fwd) + "\n"
    rb_text = "\n".join(all_rb) + "\n"
    if append and out.exists():
        with out.open("a") as f: f.write(fwd_text)
        with rb.open("a") as f: f.write(rb_text)
    else:
        out.write_text(fwd_text)
        rb.write_text(rb_text)
    print(f"\nForward  SQL: {out}  ({out.stat().st_size:,} bytes, +{len(all_fwd)} stmts {'APPENDED' if append else 'WRITTEN'})")
    print(f"Rollback SQL: {rb}  ({rb.stat().st_size:,} bytes, +{len(all_rb)} stmts {'APPENDED' if append else 'WRITTEN'})")


if __name__ == "__main__":
    main()
