"""Re-extract paragraph heading data from local DOCX cache.  Emits a TSV
with (case_id, text_hash, match_key, hudoc_para_no, heading_level,
heading_prefix) per row, joined on the VM by ``apply_extract.py`` to
augment ``paragraphs.row_role`` and text with proper heading levels.

Two HUDOC template families are supported:

  NEW (Ju_*) — prefix is GENERATED from per-case counters that mirror
  Word's auto-numbering, because the DOCX text doesn't carry "I." /
  "A." / "1." for these styles:
    - Ju_H_Head             → h0, no prefix (PROCEDURE / THE LAW)
    - Ju_H_1, Ju_H_I_Roman  → h1 Roman uppercase  (I., II.)
    - Ju_H_A                → h2 Letter uppercase  (A., B.)
    - Ju_H_1., Ju_H_a0      → h3 Arabic           (1., 2.)
    - Ju_H_a, Ju_H_alpha    → h4 paren letter     ((a), (b))
    - Ju_H_i                → h4 lowercase Roman  (i., ii.)
  Counters reset whenever a higher-level heading is encountered.

  OLD (ECHR_*) — used in ~thousands of pre-2022 Court / Section
  judgments (e.g. GAUGHRAN v. UK, 001-200817).  The prefix is ALREADY
  in the DOCX text ("A.  The background facts"), so we extract it
  from the text rather than generate it.  Style name encodes the
  level directly:
    - ECHR_Title_1..3    → h0
    - ECHR_Heading_1     → h1
    - ECHR_Heading_2     → h2
    - ECHR_Heading_3     → h3
    - ECHR_Heading_4..7  → h4 (deeper nesting collapsed to h4 since
                                 the modal CSS only renders h0..h4)
"""
import hashlib
import re
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))
from p34_rebuild_from_hudoc import parse_docx  # uses fixed para_text_full

DOCX_DIR = Path.home() / "Desktop" / "HUDOC-Docx"
WHITESPACE_RE = re.compile(r"\s+")


def hash_text(text):
    norm = WHITESPACE_RE.sub(" ", (text or "").strip()).lower()
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:16]


def normalize_for_match(text):
    """First-60-chars match key — case_id + this should uniquely
    identify a paragraph within a case."""
    norm = WHITESPACE_RE.sub(" ", (text or "").strip()).lower()
    return norm[:60]


# Heading style → (level, prefix-formatter)
# parse_docx flattens all Ju_H_* into row_role='heading', so we need
# to re-parse with style retention.  We'll do that below in a custom
# extractor that uses the public helpers.


from docx import Document
from p34_rebuild_from_hudoc import (
    iter_visible_paragraphs, para_text_full, classify_style,
    PARA_NUM_RE, TOC_LINE_RE, CONVERTED_PAGE_ARTIFACT_RE,
    section_for_header, is_legacy_word_doc, convert_legacy_word_to_docx,
    is_docx_zip,
)
import io


def to_letter(n):
    """1 → 'A', 2 → 'B', ..., 26 → 'Z'."""
    if n <= 0 or n > 26:
        return str(n)
    return chr(ord("A") + n - 1)


def to_roman(n):
    """1 → 'I', 2 → 'II', ..., uppercase."""
    if n <= 0:
        return str(n)
    table = [(1000, "M"), (900, "CM"), (500, "D"), (400, "CD"),
             (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
             (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]
    out = []
    for v, sym in table:
        while n >= v:
            out.append(sym)
            n -= v
    return "".join(out)


def make_prefix(style, counters):
    """Given a heading style and counters dict, format the prefix.
    Returns (level, prefix) where level is 'h0'..'h4'.

    Two HUDOC heading style families:

    NEW template (Ju_H_*) — prefix is GENERATED from counters because
    the DOCX text does not carry "I." / "A." / "1." (Word auto-numbers
    via list paragraphs):

      Ju_H_Head              → h0 (section header, no prefix)
                                   resets ALL child counters
      Ju_H_I_Roman, Ju_H_1   → h1 Roman uppercase (I., II.)
                                   resets h2/h3/h4
      Ju_H_A                 → h2 Letter (A., B., C.)
                                   resets h3/h4
      Ju_H_1.                → h3 Arabic numeric (1., 2., 3.)
                                   resets h4
      Ju_H_a, Ju_H_alpha     → h4 Letter in parens ((a), (b), (c))
      Ju_H_i                 → h4 lowercase Roman fallback

    OLD template (ECHR_*) — the prefix is already in the DOCX text
    (e.g. "A.  The background facts"), so we return prefix="" and let
    apply_extract.py be an idempotent no-op on the text column. Level
    is read straight from the style name suffix:

      ECHR_Title_1..3        → h0 (PROCEDURE, THE FACTS, etc.)
      ECHR_Heading_1         → h1 (I., II., …)
      ECHR_Heading_2         → h2 (A., B., …)
      ECHR_Heading_3         → h3 (1., 2., …)
      ECHR_Heading_4..7      → h4 (deeper nesting collapsed to h4
                                   since the modal CSS only renders
                                   h0..h4)
    """
    # ─── OLD ECHR_ template ─────────────────────────────────────────
    if style.startswith("ECHR_Title_"):
        # Top-level section header — reset counters like Ju_H_Head.
        counters["h1"] = 0
        counters["h2"] = 0
        counters["h3"] = 0
        counters["h4"] = 0
        return ("h0", "")
    m_echr = re.match(r"ECHR_Heading_(\d+)", style)
    if m_echr:
        lvl = int(m_echr.group(1))
        # Reset deeper counters so subsequent fix passes see the right
        # state, even though we don't emit a prefix.
        if lvl <= 1:
            counters["h2"] = counters["h3"] = counters["h4"] = 0
        elif lvl == 2:
            counters["h3"] = counters["h4"] = 0
        elif lvl == 3:
            counters["h4"] = 0
        # Map style level → CSS level, capped at h4.
        css_level = f"h{min(lvl, 4)}"
        return (css_level, "")

    # ─── NEW Ju_H_ template ────────────────────────────────────────
    if style == "Ju_H_Head":
        # Top section reset
        counters["h1"] = 0
        counters["h2"] = 0
        counters["h3"] = 0
        counters["h4"] = 0
        return ("h0", "")
    if style in ("Ju_H_I_Roman", "Ju_H_1"):
        counters["h1"] += 1
        counters["h2"] = 0
        counters["h3"] = 0
        counters["h4"] = 0
        return ("h1", f"{to_roman(counters['h1'])}.")
    if style == "Ju_H_A":
        counters["h2"] += 1
        counters["h3"] = 0
        counters["h4"] = 0
        return ("h2", f"{to_letter(counters['h2'])}.")
    if style in ("Ju_H_1.", "Ju_H_1_dot", "Ju_H_a0"):
        # Arabic numeric, with trailing dot in some templates
        counters["h3"] += 1
        counters["h4"] = 0
        return ("h3", f"{counters['h3']}.")
    if style in ("Ju_H_a", "Ju_H_alpha"):
        counters["h4"] += 1
        return ("h4", f"({chr(ord('a') + counters['h4'] - 1)})")
    if style == "Ju_H_i":
        counters["h4"] += 1
        return ("h4", f"{to_roman(counters['h4']).lower()}.")
    return ("h2", "")  # fallback for unknown styles


def extract_case(cid):
    """Return list of dicts: case_id, position_idx, text_first_60_hash,
    hudoc_para_no, heading_level, heading_prefix.  Mirrors parse_docx
    but keeps style info."""
    docx_path = DOCX_DIR / f"{cid}.docx"
    if not docx_path.exists():
        return []
    blob = docx_path.read_bytes()
    if is_legacy_word_doc(blob):
        try:
            blob = convert_legacy_word_to_docx(blob)
        except Exception:
            return []

    try:
        doc = Document(io.BytesIO(blob))
    except Exception:
        return []

    rows = []
    counters = {"h1": 0, "h2": 0, "h3": 0, "h4": 0}
    max_para_seen = 0
    para_accept_count = 0

    for p, in_table in iter_visible_paragraphs(doc):
        text = (para_text_full(p) or "").strip()
        if not text:
            continue
        if CONVERTED_PAGE_ARTIFACT_RE.match(text):
            continue
        style = p.style.name if p.style else ""
        if TOC_LINE_RE.search(text):
            continue
        role = classify_style(style)
        if role == "toc":
            continue
        if style == "ECHR_Placeholder":
            continue

        # Heading: capture level + prefix
        if role == "heading":
            level, prefix = make_prefix(style, counters)
            # OLD ECHR_ template stores the prefix IN the text already
            # ("A.  The background facts").  apply_extract.py's flow is:
            #   strip leading prefix → optionally prepend heading_prefix
            # so unless we feed it the same prefix back, the visible
            # "A." would disappear from the rendered heading.  Pull the
            # prefix out of the raw text so apply_extract can re-stamp
            # exactly what HUDOC ships.
            if not prefix and style.startswith(("ECHR_Heading_", "ECHR_Title_")):
                m_pfx = re.match(
                    r"^("                       # prefix group:
                    r"\([a-z]\)|"               #   (a), (b)
                    r"\([ivx]+\)|"              #   (i), (ii)
                    r"\([α-ω]\)|"     #   (α), (β) — Greek
                    r"[IVX]+\.|"                #   I., II.
                    r"[A-Z]\.|"                 #   A., B.
                    r"\d+\.|"                   #   1., 2.
                    r"[a-z]\."                  #   a., b.
                    r")\s",
                    text,
                )
                if m_pfx:
                    prefix = m_pfx.group(1)
            rows.append({
                "cid": cid,
                "text": text,
                "hash": hash_text(text),
                "match_key": normalize_for_match(text),
                "hpno": None,
                "heading_level": level,
                "heading_prefix": prefix,
            })
            continue

        # Body: try to extract paragraph number from leading digit
        if role == "judgment":
            m = PARA_NUM_RE.match(text)
            if m:
                n = int(m.group(1))
                if para_accept_count > 0 and n <= max_para_seen:
                    if not (para_accept_count == 1 and n <= 3 and max_para_seen <= 3):
                        rows.append({
                            "cid": cid, "text": text, "hash": hash_text(text),
                            "match_key": normalize_for_match(text),
                            "hpno": None, "heading_level": "", "heading_prefix": "",
                        })
                        continue
                rows.append({
                    "cid": cid, "text": text, "hash": hash_text(text),
                    "match_key": normalize_for_match(text),
                    "hpno": n, "heading_level": "", "heading_prefix": "",
                })
                max_para_seen = max(max_para_seen, n)
                para_accept_count += 1
                continue

        rows.append({
            "cid": cid, "text": text, "hash": hash_text(text),
            "match_key": normalize_for_match(text),
            "hpno": None, "heading_level": "", "heading_prefix": "",
        })
    return rows


def main():
    # Read list of affected case_ids from stdin (one per line)
    cids = [l.strip() for l in sys.stdin if l.strip()]
    print(f"# processing {len(cids)} cases", file=sys.stderr)
    out_path = Path("/tmp/case_extract.tsv")
    n_ok = n_err = 0
    with out_path.open("w") as f:
        f.write("case_id\thash\tmatch_key\thpno\theading_level\theading_prefix\n")
        for i, cid in enumerate(cids, 1):
            try:
                rows = extract_case(cid)
                for r in rows:
                    f.write(
                        f"{r['cid']}\t{r['hash']}\t{r['match_key']}\t"
                        f"{r['hpno'] if r['hpno'] is not None else ''}\t"
                        f"{r['heading_level']}\t{r['heading_prefix']}\n"
                    )
                n_ok += 1
            except Exception as e:
                n_err += 1
                print(f"# ERR {cid}: {e}", file=sys.stderr)
            if i % 200 == 0:
                print(f"  {i}/{len(cids)}  ok={n_ok}  err={n_err}", file=sys.stderr, flush=True)
    print(f"\nwrote {out_path}  ok={n_ok} err={n_err}", file=sys.stderr)


if __name__ == "__main__":
    main()
