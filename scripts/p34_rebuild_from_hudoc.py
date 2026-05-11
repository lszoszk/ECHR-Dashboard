#!/usr/bin/env python3
"""P34/P37 full rebuild — replace each case's paragraphs with the visible
text from HUDOC's source DOCX.

Rationale: rather than chasing fragment-vs-canonical heuristics (P26b, P32,
P33), trust HUDOC as the single source of truth.  python-docx returns one
string per `<w:p>` element with all styled runs concatenated, so styled
case-name spans / hyperlinked numbers no longer fragment paragraphs.

Scope:
  REPLACES all paragraph rows for each rebuilt case.  Earlier versions kept
  pre-existing operative_dispositif rows and stopped parsing at
  "FOR THESE REASONS"; that silently cut visible HUDOC text such as operative
  headings, list continuations, final notification lines, and signatures.
  The current contract is source-exact visible DOCX text in source order.

Output:
  /tmp/p34_rebuild.sql           — forward (DELETE + INSERTs)
  /tmp/p34_rebuild_rollback.sql  — pre-state snapshot of replaced rows
                                    (full INSERT statements to restore)
"""
import json, re, ssl, sys, urllib.request, io, time, subprocess, tempfile, zipfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from docx import Document
from docx.document import Document as DocxDocument
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table, _Cell
from docx.text.paragraph import Paragraph

DOCX_URL = "https://hudoc.echr.coe.int/app/conversion/docx/?library=ECHR&id={cid}&filename={cid}.docx"
API_BASE = "https://150.254.115.204/echr-api/api"
PARA_NUM_RE = re.compile(r"^\s*(\d+)\.\s+")
# Table-of-contents entry: ends with "<TAB><page-number>" (1–4 digits).
# Recent Grand Chamber judgments (e.g. DANILEŢ v ROMANIA, 2025) prefix the
# main body with a TOC.  Each TOC line repeats a heading or sub-heading
# followed by a tab and a page number.  Without filtering, the parser
# captures TOC subsection numbers as if they were main paragraph numbers,
# then the monotonic guard rejects the real ¶ 1+ when it finally appears.
TOC_LINE_RE = re.compile(r"\t\d{1,4}\s*$")
OLE_WORD_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
CONVERTED_PAGE_ARTIFACT_RE = re.compile(
    r"^(?:PAGE\s+\d+\s*\t.+|.+\t\s*PAGE\s+\d+)$",
    re.I,
)
ctx = ssl._create_unverified_context()

# Section assignment from major all-caps headers.  Order = priority (longer
# match first when needles overlap).  Tagged with language so we can mark
# the case as French at output time.
HEADING_RULES = [
    # ── English ───────────────────────────────────────────────────────
    ("FOR THESE REASONS",            "Operative part",    "en"),
    ("APPLICATION OF ARTICLE 41",    "Just Satisfaction", "en"),
    ("JUST SATISFACTION",            "Just Satisfaction", "en"),
    ("OTHER ALLEGED VIOLATIONS",     "Merits",            "en"),
    ("OTHER COMPLAINTS",             "Merits",            "en"),
    ("ALLEGED VIOLATION OF",         "Merits",            "en"),
    ("THE COURT'S ASSESSMENT",       "Merits",            "en"),
    ("THE COURT’S ASSESSMENT",  "Merits",            "en"),
    ("SUBJECT MATTER OF THE CASE",   "Facts",             "en"),
    ("THE FACTS",                    "Facts",             "en"),
    ("THE CIRCUMSTANCES OF THE CASE","Facts",             "en"),
    ("PROCEDURE",                    "Facts",             "en"),
    ("RELEVANT LEGAL FRAMEWORK",     "Legal Framework",   "en"),
    ("RELEVANT DOMESTIC LAW",        "Legal Framework",   "en"),
    ("RELEVANT INTERNATIONAL",       "Legal Framework",   "en"),
    ("THE LAW",                      "Merits",            "en"),
    # ── French ────────────────────────────────────────────────────────
    ("PAR CES MOTIFS",               "Operative part",    "fr"),
    ("APPLICATION DE L'ARTICLE 41",  "Just Satisfaction", "fr"),
    ("APPLICATION DE L’ARTICLE 41",  "Just Satisfaction", "fr"),
    ("SATISFACTION ÉQUITABLE",       "Just Satisfaction", "fr"),
    ("DOMMAGE",                      "Just Satisfaction", "fr"),
    ("AUTRES VIOLATIONS ALLÉGUÉES",  "Merits",            "fr"),
    ("AUTRES GRIEFS",                "Merits",            "fr"),
    ("VIOLATION ALLÉGUÉE DE",        "Merits",            "fr"),
    ("VIOLATION ALLEGUEE DE",        "Merits",            "fr"),
    ("APPRÉCIATION DE LA COUR",      "Merits",            "fr"),
    ("APPRECIATION DE LA COUR",      "Merits",            "fr"),
    ("OBJET DE L'AFFAIRE",           "Facts",             "fr"),
    ("OBJET DE L’AFFAIRE",           "Facts",             "fr"),
    ("EN FAIT",                      "Facts",             "fr"),
    ("LES CIRCONSTANCES DE L'ESPÈCE","Facts",             "fr"),
    ("LES CIRCONSTANCES DE L’ESPÈCE","Facts",             "fr"),
    ("PROCÉDURE",                    "Facts",             "fr"),
    ("PROCEDURE DEVANT LA COUR",     "Facts",             "fr"),
    ("CADRE JURIDIQUE INTERNE",      "Legal Framework",   "fr"),
    ("DROIT ET PRATIQUE INTERNES",   "Legal Framework",   "fr"),
    ("DROIT INTERNE PERTINENT",      "Legal Framework",   "fr"),
    ("TEXTES INTERNATIONAUX",        "Legal Framework",   "fr"),
    ("EN DROIT",                     "Merits",            "fr"),
]

# Stop processing main judgment when we hit one of these — separate
# opinions and document footer are out of scope.
STOP_PATTERNS = [
    re.compile(r"^Done in (English|French)", re.I),
    re.compile(r"^Fait en (anglais|fran[cç]ais)", re.I),
    re.compile(r"^(SEPARATE|DISSENTING|CONCURRING|JOINT)\s+(PARTLY\s+)?(CONCURRING|DISSENTING|JOINT|OPINION|OPINIONS|DECLARATION)", re.I),
    re.compile(r"^OPINION (CONCORDANT|DISSIDENT|S[EÉ]PAR[EÉ]E)", re.I),
]


FETCH_DELAY_S = float(__import__("os").environ.get("P34_FETCH_DELAY", "0"))
_last_fetch = [0.0]
_fetch_lock = __import__("threading").Lock()


def fetch_docx(cid):
    """Fetch DOCX with throttle + exponential backoff on rate-limit errors.

    Distinguish failure modes:
      - 403/429: rate-limit → retry with backoff
      - 500/502/503: HUDOC server bug for this case → fail immediately
        (these are persistent, retrying wastes time)
      - Other transient errors (timeout, network): retry once
      - 204: empty content → fail immediately (rare, but means nothing
        to parse)
    Per-request throttle via FETCH_DELAY_S (env var P34_FETCH_DELAY).
    """
    if FETCH_DELAY_S > 0:
        with _fetch_lock:
            now = time.time()
            sleep_for = (_last_fetch[0] + FETCH_DELAY_S) - now
            if sleep_for > 0:
                time.sleep(sleep_for)
            _last_fetch[0] = time.time()

    backoff = [5, 20, 60]
    for attempt, wait in enumerate([0] + backoff):
        if wait:
            time.sleep(wait)
        try:
            req = urllib.request.Request(DOCX_URL.format(cid=cid),
                headers={"User-Agent": "Mozilla/5.0", "Accept": "*/*"})
            resp = urllib.request.urlopen(req, context=ctx, timeout=25)
            data = resp.read()
            if len(data) < 100:
                raise RuntimeError(f"empty response ({len(data)} bytes)")
            return data
        except urllib.error.HTTPError as e:
            if e.code in (403, 429) and attempt < len(backoff):
                continue  # rate-limit, retry
            raise  # 500 etc — give up
        except (urllib.error.URLError, TimeoutError):
            if attempt < 1:  # only retry transient errors once
                continue
            raise
    raise RuntimeError("fetch_docx exhausted retries")


def is_docx_zip(blob):
    return zipfile.is_zipfile(io.BytesIO(blob))


def is_legacy_word_doc(blob):
    return blob.startswith(OLE_WORD_MAGIC)


def convert_legacy_word_to_docx(blob):
    """Convert HUDOC's occasional old binary Word payload into OOXML.

    Some legacy HUDOC records are served from the ``/conversion/docx`` URL
    with a DOCX content type but the bytes are actually pre-OOXML ``.doc``.
    python-docx cannot read that container, so local corpus rebuilds use
    macOS ``textutil`` as a narrow compatibility bridge for those cases.
    """
    with tempfile.TemporaryDirectory(prefix="hudoc_legacy_doc_") as tmp:
        tmp_dir = Path(tmp)
        src = tmp_dir / "source.doc"
        dst = tmp_dir / "source.docx"
        src.write_bytes(blob)
        try:
            subprocess.run(
                ["textutil", "-convert", "docx", "-output", str(dst), str(src)],
                check=True,
                capture_output=True,
                text=True,
                timeout=90,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                "legacy Word document requires macOS textutil for conversion"
            ) from exc
        except subprocess.CalledProcessError as exc:
            msg = (exc.stderr or exc.stdout or "").strip()
            raise RuntimeError(f"textutil legacy Word conversion failed: {msg}") from exc
        if not dst.exists():
            raise RuntimeError("textutil did not create converted DOCX")
        return dst.read_bytes()


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
    """Return (section, language) or (None, None) if not a recognised header."""
    if not is_likely_heading(text):
        return (None, None)
    upper = text.upper()
    for needle, sec, lang in HEADING_RULES:
        # word-boundary match — avoids "THE LAW" hitting "THE LAWFULNESS"
        if re.search(r"\b" + re.escape(needle.upper()) + r"\b", upper):
            return (sec, lang)
    return (None, None)


# Style-name → semantic role mapping (HUDOC's Word template scheme,
# consistent across 1986 Plenary, 2010s Chamber, 2020s GC).  Discovered
# by paragraph-style frequency tally on stratified samples.
def classify_style(s):
    """Return one of:
       'toc'       — table of contents entry
       'judgment'  — main numbered paragraph (Ju_Para)
       'quote'     — indented blockquote (Ju_Quot — its own \\d+. numbers
                      are quoting an external source, NOT main ¶ numbering)
       'heading'   — section / sub-section title
       'opinion'   — separate / dissenting / concurring opinion text
       'list'      — operative-part list item (Ju_List)
       'signature' — signature block
       'metadata'  — visible cover / case caption / judges list
       'normal'    — unstyled / catch-all (often the Convention quote
                      blockquotes that aren't tagged Ju_Quot)
    """
    s = (s or "").strip()
    if not s:
        return "normal"
    sl = s.lower()
    if sl.startswith("toc"):
        return "toc"
    if s in ("Ju_Para", "Ju_Para_Last"):
        return "judgment"
    if s == "Ju_Quot":
        return "quote"
    if s.startswith("Opi_"):
        return "opinion"
    if s.startswith("Ju_H_") or s == "Ju_H_Head":
        return "heading"
    if s.startswith("Ju_List"):
        return "list"
    if s == "Ju_Signed":
        return "signature"
    if s.startswith("Dec_") or s in (
        "Ju_Title", "Ju_Case", "Ju_Judges", "Ju_Court",
        "ECHR_Cover_Title_4", "ECHR_Placeholder",
    ):
        return "metadata"
    return "normal"


def iter_visible_paragraphs(parent, in_table=False):
    """Yield Word paragraphs in body order, including table-cell paragraphs.

    ``python-docx`` exposes ``document.paragraphs`` for top-level body
    paragraphs only.  HUDOC judgments frequently store appendices and
    applicant lists as Word tables, so the source-exact rebuild must descend
    into table cells instead of silently dropping visible text.
    """
    if isinstance(parent, DocxDocument):
        parent_elm = parent.element.body
    elif isinstance(parent, _Cell):
        parent_elm = parent._tc
    else:
        parent_elm = parent._element

    for child in parent_elm.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, parent), in_table
        elif isinstance(child, CT_Tbl):
            table = Table(child, parent)
            for tr in table._tbl.tr_lst:
                for tc in tr.tc_lst:
                    cell = _Cell(tc, table)
                    yield from iter_visible_paragraphs(cell, True)


def parse_docx(blob, *, skip_converted_page_artifacts=False):
    """Return ordered visible HUDOC DOCX paragraphs.

    P37 source-exact contract: keep every non-empty visible DOCX paragraph
    in source order.  Classify by paragraph STYLE first, then use heading
    text to update section labels.  This lets us tell apart:
      - HUDOC's main numbered ¶s (style "Ju_Para") — these get hudoc_para_no
      - Indented quote blocks (style "Ju_Quot") whose internal "57.", "67."
        numbering is the quoted source's own numbering, NOT the ECHR's
      - TOC entries (style "toc 1..4") — completely ignored
      - Section / sub-section headings (Ju_H_*) — retained as visible rows
      - Operative list items (Ju_List*) — retained exactly, not merged/deleted
      - Notification/footer/signature lines — retained exactly
    """
    if is_legacy_word_doc(blob):
        converted = convert_legacy_word_to_docx(blob)
        return parse_docx(converted, skip_converted_page_artifacts=True)
    if not is_docx_zip(blob):
        # Fall through to python-docx so callers still get its precise
        # package-level error for unexpected payloads.
        pass
    doc = Document(io.BytesIO(blob))
    out = []
    section = "Header"
    max_para_seen = 0
    para_accept_count = 0
    language_votes = {"en": 0, "fr": 0}

    def append_row(text, section, hudoc_para_no=None, numbering_block=None, row_role="paragraph"):
        out.append({
            "section": section,
            "para_idx": len(out),
            "hudoc_para_no": hudoc_para_no,
            "numbering_block": numbering_block,
            "row_role": row_role,
            "text": text,
        })

    for p, in_table in iter_visible_paragraphs(doc):
        text = (p.text or "").strip()
        if not text:
            continue
        if skip_converted_page_artifacts and CONVERTED_PAGE_ARTIFACT_RE.match(text):
            continue
        style = p.style.name if p.style else ""
        role = classify_style(style)

        # TOC filter first — DANILEŢ's TOC contains lines like
        # "CONCURRING OPINION OF JUDGE KRENC\t71" which would otherwise
        # match STOP_PATTERNS and cut the parse short.
        if TOC_LINE_RE.search(text):
            continue
        if role == "toc":
            continue

        # Skip only non-visible placeholders.  Visible cover metadata,
        # judges, signatures and final notification lines are part of the
        # source text and must be preserved.
        if style == "ECHR_Placeholder":
            continue

        if in_table:
            append_row(text, section, None, "table", "table_cell")
            continue

        if role == "opinion":
            section = "Separate Opinion"
            row_role = "heading" if style.startswith("Opi_H_") else "paragraph"
            append_row(text, section, None, "separate_opinion", row_role)
            continue

        # Universal section-header detection by TEXT (works for both
        # styled Ju_H_* paragraphs and old-template "Normal" docs that
        # don't carry the modern style names — without this, cases that
        # have no Ju_H_* style at all still get useful section labels).
        if role != "judgment" and role != "quote":
            text_section, text_lang = section_for_header(text)
            if text_section:
                if text_lang:
                    language_votes[text_lang] = language_votes.get(text_lang, 0) + 1
                section = text_section
                append_row(text, section, None, None, "heading")
                continue

        # Heading?
        if role == "heading":
            new_section, lang = section_for_header(text)
            if not new_section:
                # Sub-section heading without a section keyword (e.g. "A.
                # Damage", "(a) The applicant") — keep as a visible row in
                # the current section.
                append_row(text, section, None, None, "heading")
                continue
            if lang:
                language_votes[lang] = language_votes.get(lang, 0) + 1
            section = new_section
            append_row(text, section, None, None, "heading")
            continue

        # Operative-part list ("Holds…", "Decides…") — visible source text.
        if role == "list":
            if section != "Operative part":
                section = "Operative part"
            append_row(text, section, None, "operative_dispositif", "operative_list")
            continue

        # Visible cover / court-composition metadata and signatures.
        if role == "metadata":
            append_row(text, section, None, "metadata", "metadata")
            continue
        if role == "signature":
            append_row(text, section, None, "signature", "signature")
            continue

        # Auto-start when we see the first Ju_Para with a leading number
        # — covers cases that lack Ju_H_* headings entirely (some
        # 1990s-era templates just use Normal + Ju_Para).
        if role == "judgment":
            m_check = PARA_NUM_RE.match(text)
            if section == "Header" and m_check and int(m_check.group(1)) <= 3:
                section = "Facts"
            m = PARA_NUM_RE.match(text)
            if not m:
                # Ju_Para without a leading number — preamble, footer, or
                # continuation.  Keep it exactly.
                footer = any(pat.match(text) for pat in STOP_PATTERNS)
                append_row(
                    text,
                    section,
                    None,
                    "judgment_footer" if footer else None,
                    "footer" if footer else "paragraph",
                )
                continue
            n = int(m.group(1))
            if para_accept_count > 0 and n <= max_para_seen:
                if not (para_accept_count == 1 and n <= 3 and max_para_seen <= 3):
                    append_row(text, section, None, "main_judgment", "paragraph")
                    continue
            append_row(text, section, n, "main_judgment", "paragraph")
            max_para_seen = max(max_para_seen, n)
            para_accept_count += 1
            continue

        # Quoted blockquote — never gets a ¶ number, even if its text
        # starts with "57. ...".  Numbering inside quotes belongs to the
        # quoted source (e.g. Romanian High Court).
        if role == "quote":
            append_row(text, section, None, "main_judgment", "quote")
            continue

        # Normal / fallback — text-pattern numbered ¶ for unstyled cases
        # (older Plenary judgments occasionally fall here).
        m = PARA_NUM_RE.match(text)
        if m:
            n = int(m.group(1))
            if para_accept_count == 0 or n > max_para_seen or (
                para_accept_count == 1 and n <= 3 and max_para_seen <= 3
            ):
                append_row(text, section, n, "main_judgment", "paragraph")
                max_para_seen = max(max_para_seen, n)
                para_accept_count += 1
                continue
        append_row(text, section, None, "main_judgment", "paragraph")

    # Determine language: majority vote from matched headers; default "en".
    if language_votes["fr"] > language_votes["en"]:
        lang = "fr"
    else:
        lang = "en"
    return (out, lang)


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
        new_rows, lang = parse_docx(blob)
    except Exception as e:
        return {"cid": cid, "status": "FAIL", "err": str(e)[:80]}

    # Capture the full pre-state.  Source-exact rebuilds replace every
    # visible text row for the case; preserving stale operative_dispositif
    # rows is exactly what caused truncated judgments such as 001-249785.
    replaced_rows = list(existing)

    if not new_rows:
        return {"cid": cid, "status": "NOCAN", "old_count": len(replaced_rows)}

    forward = []
    forward.append(
        f"DELETE FROM paragraphs WHERE case_id = '{cid}';"
    )
    for r in new_rows:
        forward.append(
            f"INSERT INTO paragraphs (case_id, section, para_idx, hudoc_para_no, numbering_block, row_role, text) "
            f"VALUES ('{cid}', {sql_value(r['section'])}, {sql_value(r['para_idx'])}, "
            f"{sql_value(r['hudoc_para_no'])}, {sql_value(r['numbering_block'])}, "
            f"{sql_value(r['row_role'])}, {sql_value(r['text'])});"
        )

    # Rollback: restore pre-state via INSERTs (and DELETE everything we'll write).
    rollback = []
    rollback.append(
        f"DELETE FROM paragraphs WHERE case_id = '{cid}';"
    )
    for r in replaced_rows:
        rollback.append(
            f"INSERT INTO paragraphs (case_id, section, para_idx, hudoc_para_no, numbering_block, row_role, text) "
            f"VALUES ('{cid}', {sql_value(r.get('section'))}, {sql_value(r.get('para_idx'))}, "
            f"{sql_value(r.get('hudoc_para_no'))}, {sql_value(r.get('numbering_block'))}, "
            f"{sql_value(r.get('row_role'))}, {sql_value(r.get('text'))});"
        )

    return {
        "cid": cid, "status": "OK", "language": lang,
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
    fr_name = os.environ.get("P34_OUT_FR", out_name.replace(".sql", "_fr.sql"))
    fr_rb_name = os.environ.get("P34_ROLLBACK_FR", rb_name.replace(".sql", "_fr.sql"))
    fr_list_name = os.environ.get("P34_FR_LIST", "/tmp/p34_fr_cases.txt")
    append = os.environ.get("P34_APPEND") == "1"

    en_fwd, en_rb, fr_fwd, fr_rb, fr_cases = [], [], [], [], []
    for r in results:
        if r.get("status") != "OK":
            continue
        if r.get("language") == "fr":
            fr_fwd.extend(r.get("sql", []))
            fr_rb.extend(r.get("rollback", []))
            fr_cases.append(r["cid"])
        else:
            en_fwd.extend(r.get("sql", []))
            en_rb.extend(r.get("rollback", []))

    def _write(path, text, append):
        p = Path(path)
        if append and p.exists():
            with p.open("a") as f: f.write(text)
        else:
            p.write_text(text)
        return p

    en_out_p = _write(out_name,    "\n".join(en_fwd) + "\n", append)
    en_rb_p  = _write(rb_name,     "\n".join(en_rb)  + "\n", append)
    fr_out_p = _write(fr_name,     "\n".join(fr_fwd) + "\n", append)
    fr_rb_p  = _write(fr_rb_name,  "\n".join(fr_rb)  + "\n", append)
    # FR case list
    fr_list_path = Path(fr_list_name)
    if append and fr_list_path.exists():
        existing_fr = set(fr_list_path.read_text().split())
        for c in fr_cases: existing_fr.add(c)
        fr_list_path.write_text("\n".join(sorted(existing_fr)) + "\n")
    else:
        fr_list_path.write_text("\n".join(sorted(fr_cases)) + "\n")

    print(f"\nEN Forward  SQL: {en_out_p}  ({en_out_p.stat().st_size:,} bytes, +{len(en_fwd)} stmts {'APPENDED' if append else 'WRITTEN'})")
    print(f"EN Rollback SQL: {en_rb_p}  ({en_rb_p.stat().st_size:,} bytes, +{len(en_rb)} stmts)")
    print(f"FR Forward  SQL: {fr_out_p}  ({fr_out_p.stat().st_size:,} bytes, +{len(fr_fwd)} stmts)")
    print(f"FR Rollback SQL: {fr_rb_p}  ({fr_rb_p.stat().st_size:,} bytes, +{len(fr_rb)} stmts)")
    print(f"FR case list:    {fr_list_path}  ({len(fr_cases)} new cases)")


if __name__ == "__main__":
    main()
