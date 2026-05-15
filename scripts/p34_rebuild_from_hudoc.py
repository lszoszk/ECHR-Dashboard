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

# P58 logical-paragraph backfill — shared with p58_logical_para_heal.py so a
# rebuild reproduces the same logical_para_idx / display_para_no a heal would.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from p58_logical_para_heal import compute_logical_para
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
    # Pre-Protocol-11 (pre-1998) judgments used Article 50 as the
    # just-satisfaction clause; renamed to Article 41 in 1998.
    ("APPLICATION OF ARTICLE 50",    "Just Satisfaction", "en"),
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
    # Pre-1995 ECHR/Commission templates used these mid-Facts headings.
    # Treated as Facts so the section label doesn't flip, but emitting
    # them as headings resets the ¶-numbering watermark so the new
    # sub-sequence (¶ 10, ¶ 11, …) is accepted instead of suppressed.
    ("PROCEEDINGS BEFORE THE COMMISSION", "Facts",         "en"),
    ("FINAL SUBMISSIONS TO THE COURT",    "Facts",         "en"),
    ("AS TO THE LAW",                "Merits",            "en"),
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

# Authoritative opinion-heading text patterns.  These are the ONLY way
# we will flip section to "Separate Opinion" — a misapplied DOCX
# `Opi_H_*` style alone is not enough (S. and Marper v. UK proved a
# single tag can poison 80 paragraphs of Court text).  Patterns are
# anchored to require "OF JUDGE(S)" / "DE … JUGE" so they cannot match
# body prose like "in his concurring opinion".
OPI_HEAD_RE = re.compile(
    r"^\s*("
    # English: (JOINT) (PARTLY) {CONCURRING|DISSENTING} (, PARTLY {CONCURRING|DISSENTING}) OPINION OF JUDGES?
    r"(JOINT\s+)?(PARTLY\s+)?(CONCURRING|DISSENTING)"
    r"(\s*,\s*PARTLY\s+(CONCURRING|DISSENTING))?\s+OPINION\s+(OF|BY)\s+JUDGES?\b"
    r"|SEPARATE\s+OPINION\s+OF\s+JUDGES?\b"
    r"|DECLARATION\s+OF\s+JUDGE\b"
    # French: OPINION {CONCORDANTE|DISSIDENTE|SÉPARÉE|COMMUNE|CONJOINTE}
    r"|OPINION\s+(CONCORDANTE|DISSIDENTE|S[EÉ]PAR[EÉ]E|COMMUNE|CONJOINTE)"
    r"|OPINION\s+(EN\s+PARTIE|PARTIELLEMENT)\s+(CONCORDANTE|DISSIDENTE)"
    r"|D[EÉ]CLARATION\s+(DU|DE\s+LA)\s+JUGE\b"
    r")",
    re.I,
)

# "Done in English/French" / "Fait en anglais/français" — the formal
# notification line that closes the Court's judgment text and (often)
# precedes the appended separate opinions.  Used as a forward-only
# ratchet to gate trust in `Opi_*` style tags.
DONE_LINE_RE = re.compile(
    r"^\s*(Done in (English|French)|Fait en (anglais|fran[cç]ais))",
    re.I,
)

# Appendix / annex section start — terminates the sticky "Separate
# Opinion" state when applicants' tables come after the opinions.
APPENDIX_HEAD_RE = re.compile(
    r"^\s*(APPENDIX|ANNEX|ANNEXE|LIST OF (APPLICANTS|CASES))\b",
    re.I,
)

# Article 41 / Article 46 boundary markers — used to flip section to
# "Just Satisfaction" when the parser is still inside Merits but the
# text is plainly Article 41 content.  See LLM-judge findings (13 N
# cases with `boundary-off-by-N`).
ART41_QUOTE_RE = re.compile(
    r"\bArticle\s*4[16]\s+of the Convention\s+(provides|reads)",
    re.I,
)
ART41_HEADING_RE = re.compile(
    r"^\s*([IVX]+\.\s+)?APPLICATION\s+OF\s+ARTICLE\s*4[16]\b",
    re.I,
)
DEFAULT_INTEREST_RE = re.compile(
    r"default\s+interest.{0,80}marginal\s+lending\s+rate\s+of\s+the\s+European\s+Central\s+Bank",
    re.I,
)

# P55 — Long-tail JS-boundary triggers (pre-Protocol-11 Article 50 cases +
# modern committee judgments that quote Article 41 body directly without
# a preface).
ART50_QUOTE_RE = re.compile(
    r"\bArticle\s*50\s+of the Convention\s+(provides|reads)",
    re.I,
)
ART50_HEADING_RE = re.compile(
    r"^\s*([IVX]+\.\s+)?APPLICATION\s+OF\s+ARTICLE\s*50\b",
    re.I,
)
ART50_BODY_RE = re.compile(
    r"^\s*[\"“]?\s*If the Court finds that a decision or a measure taken by a legal authority",
    re.I,
)
ART41_BODY_RE = re.compile(
    r"^\s*[\"“]?\s*If the Court finds that there has been a violation of the Convention",
    re.I,
)
JS_AMOUNTS_TABLE_RE = re.compile(
    r"\bamounts\s+claimed\s+by\s+the\s+applicants?\s+under\s+the\s+head\s+of",
    re.I,
)
JS_APPENDED_TABLE_RE = re.compile(
    r"\b(amounts?\s+(detailed|indicated|listed)\s+in\s+the\s+appended\s+table"
    r"|appended\s+table\s+(detailing|listing|setting\s+out))",
    re.I,
)
JS_GOV_ART41_RE = re.compile(
    r"\bArticle\s*4[16]\s+of\s+the\s+Convention\s+should\s+be\s+applied\b",
    re.I,
)

# P55 — Old-template initials signatures + pre-1998 annex notice patterns
PRE98_ANNEX_NOTICE_RE = re.compile(
    r"(The following separate opinions are annexed to the present judgment"
    r"|Article\s*51\s*(?:par|para|§)\.?\s*2.*Rule\s*50\s*(?:par|para|§)\.?\s*2"
    r"|Rule\s*50\s*(?:par|para|§)\.?\s*2.*Article\s*51\s*(?:par|para|§)\.?\s*2)",
    re.I,
)
OPINION_BULLET_RE = re.compile(
    r"^\s*(\([a-z]\)\s*)?[\-–—•]?\s*(joint\s+)?(partly\s+)?"
    r"(concurring|dissenting|separate)(?:\s*,\s*partly\s+(?:concurring|dissenting))?"
    r"\s+opinion\s+of\s+",
    re.I,
)

# P57 — opinion-voice guard: paragraphs the operative-tail heal must
# NOT sweep into Appendix (stray separate-opinion content that lacks
# an OPI_HEAD anchor and is still sitting in the Operative part).
OPINION_VOICE_RE = re.compile(
    r"\b(I\s+(respectfully\s+)?(dissent|disagree|am unable to agree|"
    r"am of the opinion|share|voted)|we\s+(share|do not|cannot|are unable|"
    r"voted|had no)|in my (view|opinion)|in our (view|opinion)|"
    r"my (general remarks|view|opinion))\b",
    re.I,
)


def looks_like_initials_signature(text):
    """Detect old-template judge initials like 'G.W.' or 'M.-A.E.'"""
    if not text:
        return False
    t = text.strip()
    if not t or len(t) > 30:
        return False
    if t.count(".") < 2:
        return False
    non_space = [c for c in t if not c.isspace()]
    if len(non_space) < 3:
        return False
    initialy = sum(1 for c in non_space if c.isupper() or c in ".-")
    return initialy / len(non_space) >= 0.85

# Operative-part role-tightening (P54 corollary).  Annex-notice
# boilerplate that sits between the dispositif and the appended
# separate opinions, plus registrar/president signature blocks that
# old templates style as Normal/Ju_Para instead of Ju_Signed.  Both
# should NOT render as operative dispositif paragraphs in the modal
# or appear in body-text search results.
ANNEX_NOTICE_RE = re.compile(
    r"(In accordance with\s+Article\s*45\s*§\s*2\b"
    r"|Conform[ée]ment\s+(?:à\s+)?l['’]article\s*45\s*§\s*2\b)",
    re.I,
)
SIG_REGISTRAR_RE = re.compile(
    r"\b(Deputy\s+)?(Section\s+|Grand\s+Chamber\s+)?(Registrar|Greffier)(?:\s+adjoint)?\b",
    re.I,
)
SIG_PRESIDENT_RE = re.compile(
    r"\b(Vice-?\s*)?(President|Pr[ée]sident)\b",
    re.I,
)


def looks_like_signature_block(text):
    """Tab/whitespace-separated registrar/president signature block."""
    if not text:
        return False
    t = text.strip()
    if not t or len(t) > 220:
        return False
    if not SIG_REGISTRAR_RE.search(t):
        return False
    if not SIG_PRESIDENT_RE.search(t):
        return False
    # Substantive sentence guard
    if re.search(r"[.?!]\s+[A-Z]", t):
        return False
    return True

FETCH_DELAY_S = float(__import__("os").environ.get("P34_FETCH_DELAY", "0"))
_last_fetch = [0.0]
_fetch_lock = __import__("threading").Lock()


_DOCX_CACHE_DIR = __import__("os").environ.get(
    "P34_DOCX_CACHE_DIR",
    str(Path.home() / "Desktop" / "HUDOC-Docx"),
)
_DOCX_CACHE_MIN_BYTES = 1024


def fetch_docx(cid):
    """Fetch DOCX with throttle + exponential backoff on rate-limit errors.

    Local cache lookup happens first: if ``$P34_DOCX_CACHE_DIR/{cid}.docx``
    exists and is at least ``_DOCX_CACHE_MIN_BYTES``, read it from disk
    instead of contacting HUDOC.  Cache misses fall through to the network
    fetch and are persisted to the cache on success so subsequent runs are
    fast.  Set ``P34_DOCX_CACHE_DIR=""`` to disable.

    Distinguish failure modes:
      - 403/429: rate-limit → retry with backoff
      - 500/502/503: HUDOC server bug for this case → fail immediately
        (these are persistent, retrying wastes time)
      - Other transient errors (timeout, network): retry once
      - 204: empty content → fail immediately (rare, but means nothing
        to parse)
    Per-request throttle via FETCH_DELAY_S (env var P34_FETCH_DELAY).
    """
    cache_path = None
    if _DOCX_CACHE_DIR:
        cache_path = Path(_DOCX_CACHE_DIR) / f"{cid}.docx"
        if cache_path.exists() and cache_path.stat().st_size >= _DOCX_CACHE_MIN_BYTES:
            return cache_path.read_bytes()
        cache_path.parent.mkdir(parents=True, exist_ok=True)

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
            # Persist to local cache atomically (.tmp → rename) so partial
            # writes can never poison subsequent runs.
            if cache_path is not None and len(data) >= _DOCX_CACHE_MIN_BYTES:
                tmp = cache_path.with_suffix(".tmp")
                try:
                    tmp.write_bytes(data)
                    tmp.replace(cache_path)
                except OSError:
                    # Cache write is best-effort; never block the rebuild.
                    pass
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


# Stricter heading detector — also matches mixed-case structural labels
# ("A. Pecuniary damage", "(b) The Government", "1. Admissibility")
# without confusing them with body paragraphs.  Mirrors P52 multi-heal's
# is_heading_only().  Used at parse time to demote paragraph rows whose
# text is plainly a heading.  See LLM-judge findings: 41/60 HEADING-rows
# were originally tagged 'paragraph'.
_HEADING_BODY_RE = re.compile(r"[.?!;]\s+(?=[a-z])")
_H_CHAR_P34 = r"[A-Za-zÀ-ſ \-–—'‘’/&:(),]"
_STRUCTURAL_HEADING_PATTERNS = [
    re.compile(r"^\s*(THE LAW|THE FACTS|PROCEDURE|THE COURT|JUDGMENT)\s*$", re.I),
    re.compile(r"^\s*(PROCÉDURE|EN FAIT|EN DROIT)\s*$", re.I),
    re.compile(r"^\s*[IVX]+\.\s+[A-Z][A-Z " + _H_CHAR_P34 + r"]{2,180}\s*$"),
    re.compile(r"^\s*[A-Z]\.\s+[A-Z]" + _H_CHAR_P34 + r"{2,180}\s*$"),
    re.compile(r"^\s*\d+\.\s+[A-Z]" + _H_CHAR_P34 + r"{2,160}\s*$"),
    re.compile(r"^\s*\([a-z]+\)\s+[A-Z]" + _H_CHAR_P34 + r"{2,160}\s*$"),
    re.compile(r"^\s*\([ivx]+\)\s+[A-Z]" + _H_CHAR_P34 + r"{2,160}\s*$"),
    re.compile(r"^\s*FOR THESE REASONS\b.*$", re.I),
    re.compile(r"^\s*PAR CES MOTIFS\b.*$", re.I),
    re.compile(r"^\s*APPLICATION OF ARTICLE 4[16]\s*", re.I),
    re.compile(r"^\s*ALLEGED VIOLATION OF\b", re.I),
    re.compile(r"^\s*RELEVANT (DOMESTIC|INTERNATIONAL)\b", re.I),
]


def is_structural_heading(text):
    """True iff text is a structural heading with no paragraph body."""
    if not text:
        return False
    t = text.strip()
    if not t or len(t) > 220:
        return False
    for pat in _STRUCTURAL_HEADING_PATTERNS:
        if pat.match(t):
            return True
    # Body-like detection: if it has a sentence terminator followed by
    # lowercase AND is dominantly lowercase, it's body.
    if _HEADING_BODY_RE.search(t) or len(t) >= 120:
        lower = sum(1 for c in t if c.isalpha() and c.islower())
        upper = sum(1 for c in t if c.isalpha() and c.isupper())
        if lower > upper * 2:
            return False
    # Fallback: short and dominantly uppercase
    if len(t) <= 90:
        upper = sum(1 for c in t if c.isalpha() and c.isupper())
        lower = sum(1 for c in t if c.isalpha() and c.islower())
        if upper >= 4 and upper >= lower * 2:
            return True
    return False


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
       'judgment'  — main numbered paragraph (Ju_Para / ECHR_Para)
       'quote'     — indented blockquote (Ju_Quot / ECHR_Para_Quote
                      — their own \\d+. numbers are quoting an external
                      source, NOT main ¶ numbering)
       'heading'   — section / sub-section title (Ju_H_* OR ECHR_Title_*
                      / ECHR_Heading_1..7 from old template family)
       'opinion'   — separate / dissenting / concurring opinion text
       'list'      — operative-part list item (Ju_List)
       'signature' — signature block
       'metadata'  — visible cover / case caption / judges list
       'normal'    — unstyled / catch-all (often the Convention quote
                      blockquotes that aren't tagged Ju_Quot)

    Two HUDOC template families are recognised:
      - NEW (~2022+):  Ju_Para / Ju_Quot / Ju_H_* / Ju_List / Opi_*
      - OLD (~pre-2022): ECHR_Para / ECHR_Para_Quote / ECHR_Heading_N /
                          ECHR_Title_N — GAUGHRAN v. UK (001-200817),
                          and ~thousands of other Court / Section
                          judgments before the template refresh.
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
    # OLD ECHR_ template family ────────────────────────────────────
    # ECHR_Title_1..3       = top-level section title (PROCEDURE,
    #                          THE FACTS, THE LAW, FOR THESE REASONS)
    # ECHR_Heading_1..7     = nested headings (I., A., 1., (a), (i),
    #                          (α), free text) — level N is encoded
    #                          in the style name, mapped to h1..h4
    #                          by extract_correct_data.py.
    # ECHR_Para             = main numbered judgment paragraph
    # ECHR_Para_Quote       = quoted blockquote (external source
    #                          numbering, never main ¶)
    if s.startswith("ECHR_Title_"):
        return "heading"
    if s.startswith("ECHR_Heading_"):
        return "heading"
    if s == "ECHR_Para_Quote":
        return "quote"
    if s == "ECHR_Para":
        return "judgment"
    if s == "ECHR_Decision_Body":
        return "metadata"
    return "normal"


def para_text_full(p):
    """Concatenate every visible `<w:t>`, `<w:tab/>`, `<w:br/>` descendant
    of a `<w:p>` — *including* text inside `<w:fldSimple>` (Word's
    auto-numbered SEQ fields, which carry HUDOC's "48.", "49.", … list
    markers) and `<w:hyperlink>` wrappers.

    python-docx's `Paragraph.text` only walks top-level `<w:r>` children,
    so it silently drops paragraph numbers wrapped in `<w:fldSimple>`.
    For ŻUREK v. POLAND (001-217705) this turned every numbered body
    paragraph into the bug-pattern ".\\xa0\\xa0Word…" with no leading digit
    and no `hudoc_para_no` — until we walk the full XML tree.

    Excludes `<w:instrText>` (field instruction codes like
    "SEQ level0 \\*arabic \\* MERGEFORMAT") which are non-visible.
    """
    parts = []
    # python-docx XML elements are lxml — iter() walks all descendants.
    for el in p._element.iter():
        tag = el.tag
        # Tag is in clark notation "{ns}local" — strip namespace once.
        local = tag.rsplit("}", 1)[-1] if "}" in tag else tag
        if local == "t":
            if el.text:
                parts.append(el.text)
        elif local == "tab":
            parts.append("\t")
        elif local == "br":
            parts.append("\n")
        # instrText / fldChar / etc. are skipped (non-visible)
    return "".join(parts)


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
    # Forward-only ratchets that gate trust in `Opi_*` DOCX styles.
    # Once we've seen the dispositif ("FOR THESE REASONS, THE COURT")
    # OR the "Done in English/French" notification line, the document
    # has formally closed the Court's voice and we may believe later
    # `Opi_*` styles.  Before either landmark, an `Opi_*` style is
    # treated as a HUDOC authoring error (mis-applied to Court text)
    # and demoted to its judgment-equivalent role.  Cf. S. AND MARPER
    # v. UK (001-90051) where DOCX style `Opi_H_a` on "(b) The
    # Government" poisoned 80 Court paragraphs.
    operative_part_seen = False
    done_line_seen = False
    # Article 41 ratchet: once we've seen an explicit "APPLICATION OF
    # ARTICLE 41" heading or the Convention's Article 41 quote, every
    # subsequent paragraph (until OPI_HEAD or DONE_LINE) belongs to
    # Just Satisfaction.  Closes the merits→JS boundary gap (LLM-judge
    # found 13 of these mislabelled in our 1000-row sample).
    art41_seen = False

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
        # Use full-tree text extraction (includes <w:fldSimple> auto-number
        # SEQ fields).  python-docx's `.text` drops them, which breaks
        # numbered-paragraph parsing for ŻUREK-class judgments where HUDOC
        # uses Word's auto-numbering instead of literal "48." in a run.
        text = (para_text_full(p) or "").strip()
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
            # Post-dispositif table cells are part of an annex/appendix
            # (compensation schedules, applicant lists).  Promote
            # section to 'Appendix' so search and downstream filters
            # don't treat them as Operative-part or Separate-Opinion
            # body text.  Closes the 'annex-confusion' gap surfaced by
            # the LLM-judge (54 of 124 false labels in 1000-row sample).
            if (operative_part_seen or done_line_seen) and section in (
                "Operative part", "Separate Opinion"
            ):
                section = "Appendix"
            append_row(text, section, None, "table", "table_cell")
            continue

        # Bookkeeping for the opinion-gating ratchets BEFORE we decide
        # how to classify this row.  Section transition into "Operative
        # part" is detected later when section_for_header matches FOR
        # THESE REASONS / PAR CES MOTIFS; for now we treat any prior
        # operative_part section state as the landmark.
        if section == "Operative part":
            operative_part_seen = True
        if DONE_LINE_RE.match(text):
            done_line_seen = True
        # Article 41/50 ratchet — flip once.  Only valid before the
        # dispositif (the operative part itself is not Just Satisfaction).
        # P55 extends the trigger set:
        #   - Article 50 (pre-Protocol 11) heading / quote / body
        #   - Article 41 body text (committee-judgment opening without
        #     "Article 41 of the Convention provides")
        #   - Committee-style JS-content phrases (amounts table,
        #     appended table, "Article 41 should be applied")
        if not art41_seen and not operative_part_seen:
            if (
                ART41_HEADING_RE.match(text)
                or ART41_QUOTE_RE.search(text)
                or DEFAULT_INTEREST_RE.search(text)
                or ART50_HEADING_RE.match(text)
                or ART50_QUOTE_RE.search(text)
                or ART50_BODY_RE.match(text)
                or ART41_BODY_RE.match(text)
                or JS_AMOUNTS_TABLE_RE.search(text)
                or JS_APPENDED_TABLE_RE.search(text)
                or JS_GOV_ART41_RE.search(text)
                or section in ("Just Satisfaction", "Article 46")
            ):
                art41_seen = True
                # Don't retro-rewrite earlier rows; just flip section
                # forward.  If we're inside Merits / Final Submissions,
                # move to Just Satisfaction.
                if section in ("Merits", "Admissibility", "Final Submissions"):
                    section = "Just Satisfaction"
        # P56 — Sticky propagation: once art41_seen, every subsequent
        # Merits/Admissibility/Final-Submissions row also belongs to
        # Just Satisfaction (until OPI_HEAD or operative).  Closes the
        # quote-block reset bug in modern Ju_* committee judgments
        # (001-214668..670 cluster): the parser correctly assigned the
        # Art41 heading + intro to JS, but then quote-block rows fell
        # back to their structural parent ("Merits"), stranding all
        # following body rows in the wrong section.
        elif art41_seen and not operative_part_seen and section in (
            "Merits", "Admissibility", "Final Submissions"
        ):
            section = "Just Satisfaction"

        # ─────────────────────────────────────────────────────────────
        # RULE A — Hard text anchor.  An explicit opinion heading
        # ("CONCURRING OPINION OF JUDGE X", "OPINION SÉPARÉE DE …",
        # "DECLARATION OF JUDGE …") unambiguously opens the Separate
        # Opinion stream regardless of DOCX style.  Anchored with
        # "OF JUDGE(S)" / "DE … JUGE" so body prose can't false-match.
        # ─────────────────────────────────────────────────────────────
        if OPI_HEAD_RE.match(text) and is_likely_heading(text):
            section = "Separate Opinion"
            append_row(text, section, None, "separate_opinion", "heading")
            continue

        # ─────────────────────────────────────────────────────────────
        # RULE B — Style signal is honoured ONLY behind a forward-only
        # gate (operative_part_seen OR done_line_seen).  Pre-gate
        # `Opi_*` is treated as a HUDOC authoring error and demoted to
        # the judgment-style equivalent.  This is the S. AND MARPER
        # fix: an Opi_H_a accidentally applied to a Court sub-heading
        # no longer poisons section state.
        # ─────────────────────────────────────────────────────────────
        if role == "opinion":
            if section == "Separate Opinion":
                # We're already in opinion territory — keep classifying
                # this row as an opinion paragraph or heading.
                row_role = "heading" if style.startswith("Opi_H_") else "paragraph"
                append_row(text, section, None, "separate_opinion", row_role)
                continue
            if operative_part_seen or done_line_seen:
                # Post-gate Opi_* — trust the style; we're past the
                # Court's formal closure of the judgment text.
                section = "Separate Opinion"
                row_role = "heading" if style.startswith("Opi_H_") else "paragraph"
                append_row(text, section, None, "separate_opinion", row_role)
                continue
            # Pre-gate Opi_* — demote to Ju_* equivalent and fall through
            # to the normal classification branches below.  Heading-like
            # opinion rows become headings; body rows become judgment.
            role = "heading" if style.startswith("Opi_H_") else "judgment"

        # ─────────────────────────────────────────────────────────────
        # RULE C — Recovery: APPENDIX/ANNEX heading terminates the
        # sticky "Separate Opinion" state so applicant tables aren't
        # mis-attributed to opinions (BURMYCH / SANDU class).
        # ─────────────────────────────────────────────────────────────
        if (
            section == "Separate Opinion"
            and APPENDIX_HEAD_RE.match(text)
            and is_likely_heading(text)
        ):
            section = "Appendix"
            append_row(text, section, None, None, "heading")
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
                # Pre-1995 ECHR/Commission judgments restart ¶ numbering
                # whenever a major heading is encountered — PROCEDURE,
                # THE FACTS, PROCEEDINGS BEFORE THE COMMISSION, AS TO
                # THE LAW and APPLICATION OF ARTICLE 50 each open with a
                # fresh ¶ 1.  We reset the running-max guard on EVERY
                # recognised heading rather than only on section-name
                # changes, because mid-Facts sub-headings (PROCEEDINGS
                # BEFORE THE COMMISSION → still "Facts") need the reset
                # too.  Modern Ju_* judgments keep monotone numbering
                # across sections, but their paragraph numbers also keep
                # climbing, so the reset is a no-op for them
                # (n > max_para_seen will still hold).
                max_para_seen = 0
                para_accept_count = 0
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
            if new_section != section:
                # Same rationale as above — reset running-max on
                # top-level section boundary.
                max_para_seen = 0
                para_accept_count = 0
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

    # Pre-1995 HUDOC DOCX files use hard line-breaks (one <w:p> per
    # rendered line, ~60–80 chars), so a logical paragraph spans many
    # rows.  Reflow them into single rows now so the modal renders
    # coherent ¶ 1 ... ¶ N units instead of an exploded line list.
    out = _reflow_line_wrapped(out)

    # Promote structural-heading rows mis-tagged as paragraph.  The
    # earlier branches treat anything that didn't match a section
    # keyword (PROCEDURE / THE LAW / etc.) as paragraph by default,
    # which buries "A. Pecuniary damage", "(b) The Government" etc.
    # inside the body.  LLM-judge confirmed 41/60 HEADING-bucket rows
    # were originally paragraph-typed.  Conservative: only flip when
    # text matches `is_structural_heading` AND row has no hudoc_para_no
    # AND text is short enough (<=220 chars).
    for r in out:
        if r.get("row_role") != "paragraph":
            continue
        if r.get("hudoc_para_no") is not None:
            continue
        if is_structural_heading(r.get("text") or ""):
            r["row_role"] = "heading"

    # P54 + P55 role-tightening: demote annex-notice / signature /
    # done-line / initials / pre-1998 annex-list rows in Operative-part
    # section out of `paragraph` role so they don't surface in body-text
    # search results and don't render as dispositif paragraphs in the
    # modal.  LLM-judge identified ~2.2 K + ~1.4 K such rows on post-P52
    # / post-P54 DBs respectively.  Conservative: only acts inside
    # Operative part (no risk of touching real merits paragraphs).
    for r in out:
        if r.get("section") not in ("Operative part", "Operative Part"):
            continue
        role = r.get("row_role")
        if role not in ("paragraph", "footer"):
            continue
        text = r.get("text") or ""
        if ANNEX_NOTICE_RE.search(text) or PRE98_ANNEX_NOTICE_RE.search(text):
            r["row_role"] = "metadata"
        elif OPINION_BULLET_RE.match(text):
            # "- dissenting opinion of Mr. X;" annex list items
            r["row_role"] = "metadata"
        elif looks_like_signature_block(text):
            r["row_role"] = "signature"
        elif looks_like_initials_signature(text):
            # Pre-1995 templates close with judge initials only
            r["row_role"] = "signature"
        elif role == "paragraph" and DONE_LINE_RE.match(text):
            # Done-in-English landed in the body — surface it as footer
            # so the modal still shows it visually distinct without
            # confusing it with the dispositif.
            r["row_role"] = "footer"

    # P57 — Operative-tail heal: move the post-dispositif tail of the
    # Operative part section into Appendix.  Everything after the LAST
    # operative_list row (signatures, footers, annex notices, ANNEX
    # headings, annex tables) belongs to Appendix, not OPERATIVE.
    # Selective: only unambiguous tail material; never numbered
    # judgment ¶, opinion-voiced prose, or quote rows (those may be
    # stray separate-opinion content).  Stops at Separate Opinion.
    last_op_idx = None
    for i, r in enumerate(out):
        if (
            r.get("row_role") == "operative_list"
            and r.get("section") in ("Operative part", "Operative Part")
        ):
            last_op_idx = i
    if last_op_idx is not None:
        annex_sticky = False
        for i in range(last_op_idx + 1, len(out)):
            r = out[i]
            sec = r.get("section")
            if sec == "Separate Opinion":
                break
            if sec not in ("Operative part", "Operative Part"):
                continue
            role = r.get("row_role") or ""
            text = r.get("text") or ""
            move = False
            if role in ("signature", "footer", "metadata", "table_cell"):
                move = True
            elif role.startswith("heading"):
                if APPENDIX_HEAD_RE.match(text):
                    move = True
                    annex_sticky = True
                elif looks_like_initials_signature(text):
                    move = True
            elif role == "operative_list":
                continue
            elif role == "paragraph":
                if r.get("hudoc_para_no") is not None:
                    continue
                if OPINION_VOICE_RE.search(text):
                    continue
                if (
                    ANNEX_NOTICE_RE.search(text)
                    or PRE98_ANNEX_NOTICE_RE.search(text)
                    or OPINION_BULLET_RE.match(text)
                    or DONE_LINE_RE.match(text)
                ):
                    move = True
                elif annex_sticky and len(text.strip()) <= 90 \
                        and not re.search(r"[.?!]\s", text):
                    move = True
            if move:
                r["section"] = "Appendix"

    # P58 — reconstruct the logical paragraph each physical row belongs to
    # (logical_para_idx + display_para_no) once the row set is final.
    compute_logical_para(out)

    # Determine language: majority vote from matched headers; default "en".
    if language_votes["fr"] > language_votes["en"]:
        lang = "fr"
    else:
        lang = "en"
    return (out, lang)


# Sentence-terminating punctuation we treat as a hard break for the
# line-wrap detector.  Trailing close-quote/paren/comma are tolerated.
_SENTENCE_END = (".", "?", "!", ":", ";", "”", "”", "\"", "”")
_LINE_WRAP_NUM_RE = re.compile(r"^\s*\d+\.\s")
_LINE_WRAP_FOOTNOTE_RE = re.compile(r"^\s*\*+\s")


def _reflow_line_wrapped(rows):
    """If ``rows`` was produced from a line-wrapped pre-1995 DOCX,
    merge body-paragraph continuation lines into their preceding
    numbered ¶ row.  Conservative: only merges into rows that already
    have a ``hudoc_para_no`` (i.e. confirmed start-of-paragraph), so
    Header / cover-metadata fragments stay untouched.

    Detection heuristic
    -------------------
    A case is "line-wrapped" when many of its body paragraphs are
    SHORT (under ~90 chars after strip) AND do NOT end with a
    sentence-terminating punctuation mark.  Modern flowed DOCX has
    long paragraphs ending in ".", "?", ";" etc., so the ratio drops
    below the threshold and reflow is skipped entirely.

    Merge boundaries
    ----------------
    Stop appending continuation lines when the next row:
      * has its own ``hudoc_para_no`` (= next paragraph),
      * is a heading / list / metadata / signature row,
      * sits in a different ``section``,
      * starts with the leading-number prefix ``"\\d+\\.\\s"``
        (defensive — should also be picked up by hudoc_para_no but the
        old fallback branch sometimes leaves it null),
      * starts with a footnote marker ``"*"`` / ``"**"`` / ``"***"``,
      * looks like a section heading (``is_likely_heading``).
    """
    if len(rows) < 30:
        return rows
    body = [r for r in rows if r.get("row_role") == "paragraph"]
    if not body:
        return rows

    def is_unterminated(text):
        s = (text or "").rstrip().rstrip(")\"'`")
        if not s:
            return False
        return s[-1] not in _SENTENCE_END

    short_unterm = sum(
        1 for r in body
        if len(r["text"]) < 90 and is_unterminated(r["text"])
    )
    if short_unterm / max(len(body), 1) < 0.30:
        return rows

    out_rows = []
    for r in rows:
        if (
            out_rows
            and out_rows[-1].get("row_role") == "paragraph"
            and out_rows[-1].get("hudoc_para_no") is not None
            and r.get("row_role") == "paragraph"
            and r.get("hudoc_para_no") is None
            and r.get("section") == out_rows[-1].get("section")
            and not _LINE_WRAP_NUM_RE.match(r["text"])
            and not _LINE_WRAP_FOOTNOTE_RE.match(r["text"])
            and not is_likely_heading(r["text"])
        ):
            # Continuation of the previous numbered paragraph.
            merged = dict(out_rows[-1])
            merged["text"] = (
                merged["text"].rstrip() + " " + r["text"].lstrip()
            )
            out_rows[-1] = merged
            continue
        out_rows.append(r)
    return out_rows


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
            f"INSERT INTO paragraphs (case_id, section, para_idx, hudoc_para_no, numbering_block, row_role, logical_para_idx, display_para_no, text) "
            f"VALUES ('{cid}', {sql_value(r['section'])}, {sql_value(r['para_idx'])}, "
            f"{sql_value(r['hudoc_para_no'])}, {sql_value(r['numbering_block'])}, "
            f"{sql_value(r['row_role'])}, {sql_value(r.get('logical_para_idx'))}, "
            f"{sql_value(r.get('display_para_no'))}, {sql_value(r['text'])});"
        )

    # Rollback: restore pre-state via INSERTs (and DELETE everything we'll write).
    rollback = []
    rollback.append(
        f"DELETE FROM paragraphs WHERE case_id = '{cid}';"
    )
    for r in replaced_rows:
        rollback.append(
            f"INSERT INTO paragraphs (case_id, section, para_idx, hudoc_para_no, numbering_block, row_role, logical_para_idx, display_para_no, text) "
            f"VALUES ('{cid}', {sql_value(r.get('section'))}, {sql_value(r.get('para_idx'))}, "
            f"{sql_value(r.get('hudoc_para_no'))}, {sql_value(r.get('numbering_block'))}, "
            f"{sql_value(r.get('row_role'))}, {sql_value(r.get('logical_para_idx'))}, "
            f"{sql_value(r.get('display_para_no'))}, {sql_value(r.get('text'))});"
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
