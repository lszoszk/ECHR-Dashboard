#!/usr/bin/env python3
"""
P29 — extract paragraph-level citations from text and build case_citations.

Background
----------
~16,800 cases — most importantly the 6,240 post-2021 committee judgments —
never went through the JSONL ingest path that carried a `strasbourg_caselaw`
field, so they showed "0 cites / 0 cited by" in the dashboard even when their
text is full of HUDOC-style citations.  This pass walks the paragraphs of every
case, resolves each citation to a `case_id`, and writes a `case_citations`
table:

    case_citations(
      citing_case_id TEXT NOT NULL,
      cited_case_id  TEXT NOT NULL,
      citing_paragraph_rowid INTEGER,
      raw_text TEXT,
      extraction_method TEXT,
      PRIMARY KEY (citing_case_id, cited_case_id, citing_paragraph_rowid)
    )

Detection strategy
------------------
1. `appno_with_cue` / `appno_no_cue` — an application number (`19376/23`,
   `80982/12`) found in the paragraph and present in the *cases* index.  A number
   that is not in the index is ignored, which removes year-codes such as
   ``2026/01``.  Judgments cite modern cases this way.

2. `name_date` — a reference carrying NO application number, as pre-1999
   judgments are cited: ``Handyside v. the United Kingdom, 7 December 1976,
   Series A no. 24``.  The pair is accepted only when exactly one judgment in the
   corpus has that date, the applicant's name tokens are contained in its title,
   and the respondent State named in the reference occurs in its respondent
   part.  A date alone, or a name alone, is never enough.

Rules shared by both passes
---------------------------
* One application number can belong to several documents of the same case
  (merits, just satisfaction, revision, struck out, ...).  A date written next to
  the reference picks the right one; otherwise the principal merits judgment
  wins, then the earliest.
* Unofficial translations (titles containing "[... translation]") are neither
  cited nor citing: they would split or double every count.
* A reference marked ``(dec.)`` resolves only to a Decision document.  If the
  corpus does not hold that decision the reference is dropped rather than
  credited to the later judgment that happens to share the number.
* A judgment cannot cite a judgment delivered after it (`name_date` only).
* Self-citations are dropped.

The script is idempotent: running it twice rebuilds the table from scratch
(DROP + CREATE).  The table is fully derived from `paragraphs` + `cases`.

Usage
-----
    python3 scripts/p29_extract_citations.py [--db PATH] [--apply] \\
            [--audit-out FILE.jsonl] [--limit-cases N] [--report-cues]

`--audit-out` writes one JSON line per `name_date` row and per application
number that needed disambiguation, for a blind precision check.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import NamedTuple, Optional

# ECHR application-number pattern.  Two forms in the wild:
#   - 4-5 digit application + 2-digit year:    19376/23
#   - 4-5 digit application + 4-digit year:    19376/2023  (rare, recent)
APPNO_RE = re.compile(r"\b(\d{4,5})/(\d{2}|\d{4})\b")

# Heuristic: appno is more credible if context within ±60 chars contains
# any of these citation cue words.  We DON'T strictly require this — the
# case_no resolution already filters most false positives — but we use
# it for the `extraction_method` audit trail.
CITATION_CUE_RE = re.compile(
    r"\b(no\.?|nos?\.?|application|judgment|decision|v\.|cited above|see\s|compare)",
    re.IGNORECASE,
)

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]
MONTH_NO = {m: i + 1 for i, m in enumerate(MONTHS)}
DATE_RE = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)? (" + "|".join(MONTHS) + r") (\d{4})\b")

# "Handyside v. the United Kingdom": group 1 = applicant(s), group 2 = first word
# of the respondent State.
NAME_RE = re.compile(
    r"([A-ZÀ-Ž][\w'’\-\.À-ž]*(?:[ ,]+(?:and|and Others|[A-ZÀ-Ž][\w'’\-\.À-ž]*))*?)"
    r"\s+v\.\s+(?:the\s+)?([A-ZÀ-Ž][\w'’\-À-ž]+)"
)
DEC_MARK_RE = re.compile(r"\(dec\.\)")
# "Nadtoka v. Russia (no. 2) (request for revision of the judgment of 8 October 2019":
# the date belongs to the judgment under revision, not to the document being cited.
REVISION_RE = re.compile(r"\b(?:revision|interpretation)\b", re.IGNORECASE)
TRANSLATION_RE = re.compile(r"\[[^\]]*translation[^\]]*\]", re.IGNORECASE)

# Longest stretch allowed between the end of "X v. State" and the date that
# belongs to it ("... Kingdom, judgment of 7 December 1976").
NAME_DATE_MAX_GAP = 90
# Where to look for a date next to an application number.
APPNO_DATE_WINDOW = 80

# Document types that are the principal judgment of a case.  Everything else
# (just satisfaction, revision, interpretation, struck out, preliminary
# objection, ...) ranks lower when one application number has several documents.
PRINCIPAL_TYPES = {
    "Judgment (Merits and Just Satisfaction)", "Judgment (Merits)",
    "Judgment (Grand Chamber)", "Judgment (Chamber)", "Judgment (Committee)",
    "Judgment (Lack of Jurisdiction)", "Judgment (Questions of Procedure)",
}

_CHAR_MAP = str.maketrans({"ł": "l", "ø": "o", "đ": "d", "ð": "d", "æ": "ae",
                           "œ": "oe", "ß": "ss", "ı": "i"})
# A reference in an older judgment may spell the State differently from the title.
_STATE_ALIASES = {"turkey": {"turkey", "turkiye"}, "turkiye": {"turkey", "turkiye"}}


_ODD_SPACES = re.compile(r"[\u00a0\u2000-\u200b\u202f\u205f\u3000]")


def plain(text: str) -> str:
    """Replace no-break and other Unicode spaces one-for-one so offsets stay valid."""
    return _ODD_SPACES.sub(" ", text or "")


def fold(s: str) -> str:
    """Lower-case, strip accents and map letters NFKD leaves alone (ł, ø, ı, ...)."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return s.lower().translate(_CHAR_MAP)


def tokens(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", fold(s)))


def parse_date(s: str) -> Optional[tuple[int, int, int]]:
    m = re.fullmatch(r"\s*(\d{1,2})/(\d{1,2})/(\d{4})\s*", s or "")
    return (int(m.group(3)), int(m.group(2)), int(m.group(1))) if m else None


class Doc(NamedTuple):
    case_id: str
    date_str: str                       # DD/MM/YYYY as stored
    date: Optional[tuple[int, int, int]]
    is_decision: bool
    rank: int                           # 0 = principal judgment, 1 = ancillary
    appnos: frozenset                   # every application number of the document
    is_gc: bool                         # Grand Chamber judgment or decision
    applicant: frozenset                # name tokens before " v. " in the title
    lead: frozenset                     # name tokens of the first applicant only
    respondent: frozenset               # name tokens after " v. "


class Indexes(NamedTuple):
    by_appno: dict[str, list[Doc]]
    by_date_judgment: dict[str, list[Doc]]
    by_date_decision: dict[str, list[Doc]]
    docs: dict[str, Doc]
    excluded: set[str]                  # translations: neither cited nor citing
    not_citing: set[str]                # machine translations: cited, never citing (their own
                                        # citations come from HUDOC's metadata, french_only_citations)


def build_indexes(cur: sqlite3.Cursor) -> Indexes:
    cols = [r[1] for r in cur.execute("PRAGMA table_info(cases)")]
    has_body = "originating_body" in cols
    cur.execute("SELECT case_id, case_no, title, judgment_date, document_type, "
                + ("originating_body" if has_body else "'' AS originating_body")
                + (", COALESCE(text_origin, '') AS text_origin" if "text_origin" in cols else ", '' AS text_origin")
                + " FROM cases")
    by_appno: dict[str, list[Doc]] = defaultdict(list)
    by_date_j: dict[str, list[Doc]] = defaultdict(list)
    by_date_d: dict[str, list[Doc]] = defaultdict(list)
    docs: dict[str, Doc] = {}
    excluded: set[str] = set()
    not_citing: set[str] = set()
    for r in cur.fetchall():
        title = r["title"] or ""
        if TRANSLATION_RE.search(title):
            excluded.add(r["case_id"])
            continue
        if r["text_origin"] == "machine_translation":
            not_citing.add(r["case_id"])
        dtype = r["document_type"] or ""
        is_dec = dtype.startswith("Decision")
        left, _, right = fold(title.replace("CASE OF ", "")).partition(" v. ")
        own = frozenset(p.strip() for p in re.split(r"[;,]\s*", (r["case_no"] or "").strip())
                        if APPNO_RE.fullmatch(p.strip()))
        doc = Doc(
            case_id=r["case_id"],
            date_str=(r["judgment_date"] or "").strip(),
            date=parse_date(r["judgment_date"]),
            is_decision=is_dec,
            rank=0 if (is_dec or dtype in PRINCIPAL_TYPES) else 1,
            appnos=own,
            is_gc=("Grand Chamber" in (r["originating_body"] or "")
                   or dtype == "Judgment (Grand Chamber)"),
            applicant=frozenset(tokens(left)),
            lead=frozenset(tokens(re.split(r",| and ", left)[0])),
            respondent=frozenset(tokens(right)),
        )
        docs[doc.case_id] = doc
        if doc.date_str:
            (by_date_d if is_dec else by_date_j)[doc.date_str].append(doc)
        # case_no often holds several appnos for joined cases ("32310/08; 33191/08").
        for part in own:
            by_appno[part].append(doc)
    return Indexes(by_appno, by_date_j, by_date_d, docs, excluded, not_citing)


def extract_appnos(text: str) -> list[tuple[str, int, int]]:
    """Return [(canonical_appno, start, end), …] of distinct appnos in text."""
    seen: set[str] = set()
    out: list[tuple[str, int, int]] = []
    for m in APPNO_RE.finditer(text):
        canon = f"{m.group(1)}/{m.group(2)}"
        if canon in seen:
            continue
        seen.add(canon)
        out.append((canon, m.start(), m.end()))
    return out


def has_citation_cue(text: str, offset: int, window: int = 60) -> bool:
    lo = max(0, offset - window)
    hi = min(len(text), offset + window)
    return bool(CITATION_CUE_RE.search(text[lo:hi]))


_DEC_AFTER_RE = re.compile(r"\s{0,2},?\s{0,2}\(dec\.\)")


def is_decision_reference(text: str, start: int, end: int) -> bool:
    """True when the number at text[start:end] belongs to a "(dec.)" reference.

    The marker normally precedes the number ("X v. Y (dec.), no. 1/01") but some
    judgments write "(no. 1/01 (dec.), …)".
    """
    if _DEC_AFTER_RE.match(text, end):
        return True
    window = text[max(0, start - 70):start]
    for sep in (";", " v. "):
        window = window.rpartition(sep)[2]
    return bool(DEC_MARK_RE.search(window))


def dates_after(text: str, end: int) -> set[str]:
    out = set()
    for m in DATE_RE.finditer(text[end:end + APPNO_DATE_WINDOW]):
        out.add(f"{int(m.group(1)):02d}/{MONTH_NO[m.group(2)]:02d}/{m.group(3)}")
    return out


_REPORT_YEAR_RE = re.compile(r"\b(?:ECHR|Reports(?: of Judgments and Decisions)?)\s+(\d{4})")
_GC_MARK_RE = re.compile(r"\[GC\]")


def pick_for_appno(cands: list[Doc], text: str, start: int, end: int,
                   want_decision: bool) -> tuple[Optional[Doc], str]:
    """Choose the document an application-number reference points at.

    When one number has several documents (Chamber and Grand Chamber judgments,
    merits and just satisfaction, ...) the evidence is used in this order: a date
    written after the number, the "ECHR 2005" year, the "[GC]" marker (its absence
    prefers the non-Grand-Chamber document), then the principal judgment, then the
    earliest.
    """
    pool = [d for d in cands if d.is_decision == want_decision]
    if not pool:
        if want_decision:
            return None, "dec_not_in_corpus"
        pool = [d for d in cands if d.is_decision]      # only a decision holds this number
        if not pool:
            return None, "unresolved"
    if len(pool) == 1:
        return pool[0], "single"
    near = dates_after(text, end)
    by_date = [d for d in pool if d.date_str in near]
    if len(by_date) == 1:
        return by_date[0], "multi_by_date"
    ranked = by_date or pool
    year = _REPORT_YEAR_RE.search(text, end, end + 70)
    if year:
        same_year = [d for d in ranked if d.date and str(d.date[0]) == year.group(1)]
        if same_year:
            ranked = same_year
    if len({d.is_gc for d in ranked}) > 1:
        gc_marked = bool(_GC_MARK_RE.search(text[max(0, start - 45):end + 25]))
        ranked = [d for d in ranked if d.is_gc == gc_marked]
    best = min(d.rank for d in ranked)
    top = sorted((d for d in ranked if d.rank == best),
                 key=lambda d: (d.date or (9999, 0, 0), d.case_id))
    return top[0], "multi_by_rank"


def appno_citations(text: str, citing_id: str, idx: Indexes, stats: Counter):
    """Yield (cited_id, excerpt, method, how) for every application number in `text`."""
    if "/" not in text:
        return
    text = plain(text)
    own = idx.docs[citing_id].appnos if citing_id in idx.docs else frozenset()
    for appno, start, end in extract_appnos(text):
        if appno in own:                     # the judgment's own "Application no. …" header
            stats["self_cite"] += 1
            continue
        cands = idx.by_appno.get(appno)
        if not cands:
            stats["appno_not_in_index"] += 1
            continue
        doc, how = pick_for_appno(cands, text, start, end, is_decision_reference(text, start, end))
        if doc is None:
            stats[f"appno_{how}"] += 1
            continue
        if doc.case_id == citing_id:
            stats["self_cite"] += 1
            continue
        cued = has_citation_cue(text, start)
        method = "appno_with_cue" if cued else "appno_no_cue"
        excerpt = text[max(0, start - 50):min(len(text), end + 50)].replace("\n", " ")
        yield doc.case_id, excerpt, method, how


def name_date_citations(text: str, citing: Optional[Doc], citing_id: str,
                        idx: Indexes, stats: Counter):
    """Yield (cited_id, excerpt, 'name_date', '') for references without an appno."""
    text = plain(text)
    if " v. " not in text:
        return
    for m in DATE_RE.finditer(text):
        key = f"{int(m.group(1)):02d}/{MONTH_NO[m.group(2)]:02d}/{m.group(3)}"
        in_j, in_d = key in idx.by_date_judgment, key in idx.by_date_decision
        if not (in_j or in_d):
            continue
        look_from = max(0, m.start() - 160)
        look = text[look_from:m.start()]
        name = None
        for name in NAME_RE.finditer(look):
            pass
        if name is None:
            continue
        gap = look[name.end():]
        if len(gap) > NAME_DATE_MAX_GAP:
            continue
        want_decision = bool(DEC_MARK_RE.search(gap))
        pool = (idx.by_date_decision if want_decision else idx.by_date_judgment).get(key, [])
        if not pool:
            continue
        resp = fold(name.group(2))
        resp_ok = _STATE_ALIASES.get(resp, {resp})
        # "In Handyside v. …" captures "In Handyside": retry without leading words.
        words = re.split(r",| and ", name.group(1))[0].split()
        cands: list[Doc] = []
        for drop in range(min(3, len(words))):
            key_tokens = tokens(" ".join(words[drop:]))
            if not key_tokens:
                continue
            # Initials alone ("H v. Austria") must equal the first applicant exactly,
            # otherwise "H" would also match "R. H. v. Austria" decided the same day.
            initials = not any(len(t) >= 3 for t in key_tokens)
            cands = [d for d in pool
                     if (key_tokens == d.lead if initials else key_tokens <= d.applicant)]
            if cands:
                break
        if not cands:
            stats["name_date_no_name_match"] += 1
            continue
        cands = [d for d in cands if d.respondent & resp_ok]
        if not cands:
            stats["name_date_state_mismatch"] += 1
            continue
        cands = [d for d in cands if d.case_id != citing_id]
        if REVISION_RE.search(gap):
            stats["name_date_revision_reference"] += 1
            continue
        # A number written in the reference must belong to the candidate: if it
        # names another application, the same-day namesake is the wrong case.
        written = {f"{a.group(1)}/{a.group(2)}" for a in APPNO_RE.finditer(gap)}
        if written:
            cands = [d for d in cands if written & d.appnos]
            if not cands:
                stats["name_date_appno_conflict"] += 1
                continue
        if citing is not None and citing.date is not None:
            before = len(cands)
            cands = [d for d in cands if d.date is None or d.date <= citing.date]
            if before and not cands:
                stats["name_date_cited_is_later"] += 1
                continue
        if len(cands) != 1:
            if cands:
                stats["name_date_ambiguous"] += 1
            continue
        excerpt = text[look_from + name.start():m.end()].replace("\n", " ")
        yield cands[0].case_id, excerpt, "name_date", ""


def hudoc_additions(cur, idx: Indexes, citations: list, text_appnos: dict, stats: Counter) -> list:
    """Citations that HUDOC records for a judgment and our text pass did not find.

    Two HUDOC fields, read from the hudoc_metadata table (scripts/p69_sync_hudoc_metadata.py):
      * scl — the "Strasbourg case-law" list the Court's documentalists compile. Each item is a
        citation string, resolved with the same rules as the text (so a "(dec.)" item still needs the
        decision to be in the corpus);
      * extractedappno — application numbers HUDOC extracted from the full document. Only numbers
        that do not occur in our text are used: those are mostly in footnotes, which our text lacks.
        Where the number is in our text, the text pass has already decided (for instance it dropped
        a "(dec.)" reference whose decision is not in the corpus).
    A case already cited by the judgment (any document sharing an application number) is not added
    again, and a judgment never cites a later one. Rows have no paragraph (citing_paragraph_rowid NULL).
    """
    try:
        rows = cur.execute("SELECT case_id, scl, extractedappno FROM hudoc_metadata").fetchall()
    except sqlite3.OperationalError:
        print("  (no hudoc_metadata table: HUDOC additions skipped)")
        return []
    covered: dict[str, set] = defaultdict(set)              # citing -> application numbers cited
    for citing_id, cited_id, *_ in citations:
        d = idx.docs.get(cited_id)
        if d:
            covered[citing_id] |= d.appnos
    added = []
    for r in rows:
        citing_id = r["case_id"]
        citing = idx.docs.get(citing_id)
        if citing is None or citing_id in idx.excluded or citing_id in idx.not_citing:
            continue
        have = covered[citing_id]

        def take(doc, raw, method):
            if doc is None or doc.case_id == citing_id or doc.appnos & citing.appnos:
                return
            if doc.appnos & have:
                stats[f"{method}_already_cited"] += 1
                return
            if citing.date and doc.date and doc.date > citing.date:
                stats[f"{method}_later_case"] += 1
                return
            have.update(doc.appnos)
            added.append((citing_id, doc.case_id, None, raw[:300], method))
            stats[method] += 1

        for item in (x.strip() for x in (r["scl"] or "").split(";")):
            if not item:
                continue
            found = [c for c, *_ in appno_citations(item, citing_id, idx, Counter())]
            found += [c for c, *_ in name_date_citations(item, citing, citing_id, idx, Counter())]
            if not found:
                stats["hudoc_caselaw_not_in_corpus"] += 1
            for c in found:
                take(idx.docs.get(c), item, "hudoc_caselaw")
        for appno in (x.strip() for x in (r["extractedappno"] or "").split(";")):
            if not appno or appno in text_appnos.get(citing_id, ()) or appno in citing.appnos:
                continue
            cands = idx.by_appno.get(appno)
            if not cands:
                continue
            doc, _ = pick_for_appno(cands, "", 0, 0, False)
            take(doc, f"HUDOC extracted application no. {appno}", "hudoc_extracted")
    return added


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--db", default="data/echr_search.db")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit-cases", type=int, default=0,
                    help="Cap the number of citing cases scanned (debug).")
    ap.add_argument("--report-cues", action="store_true",
                    help="Audit-only: report on appnos found WITHOUT a "
                    "citation cue word in context (potential false "
                    "positives).  No DB writes.")
    ap.add_argument("--no-hudoc", action="store_true",
                    help="text only: do not add citations from HUDOC's metadata (hudoc_metadata table)")
    ap.add_argument("--audit-out", default="",
                    help="Write a JSONL file with every name_date row and every "
                    "disambiguated appno row (for a blind precision check).")
    args = ap.parse_args()

    db_path = Path(args.db).resolve()
    if not db_path.exists():
        print(f"ERROR: DB not found at {db_path}", file=sys.stderr)
        return 2

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    print("building case indexes…")
    idx = build_indexes(cur)
    print(f"  {len(idx.docs):,} documents, {len(idx.by_appno):,} unique application numbers, "
          f"{len(idx.excluded):,} translations excluded, "
          f"{len(idx.not_citing):,} machine translations cited only")

    print("\nscanning paragraphs for citations…")
    cur.execute("SELECT DISTINCT case_id FROM paragraphs ORDER BY case_id")
    case_ids = [r["case_id"] for r in cur.fetchall()
                if r["case_id"] not in idx.excluded and r["case_id"] not in idx.not_citing]
    if args.limit_cases:
        case_ids = case_ids[: args.limit_cases]

    citations: list[tuple[str, str, int, str, str]] = []
    # (citing_case_id, cited_case_id, paragraph_rowid, raw_text_excerpt, method)
    seen_pair_para: set[tuple[str, str, int]] = set()
    text_appnos: dict[str, set] = defaultdict(set)          # numbers that occur in our text, per case
    stats: Counter = Counter()
    audit = open(args.audit_out, "w", encoding="utf-8") if args.audit_out else None
    t0 = time.perf_counter()

    for i, citing_id in enumerate(case_ids, 1):
        citing = idx.docs.get(citing_id)
        cur.execute("SELECT rowid, text FROM paragraphs WHERE case_id = ?", [citing_id])
        for prow in cur.fetchall():
            text = prow["text"] or ""
            if "/" in text:
                text_appnos[citing_id].update(a for a, _, _ in extract_appnos(plain(text)))
            found = list(appno_citations(text, citing_id, idx, stats))
            found += [(c, e, m, h) for c, e, m, h in
                      name_date_citations(text, citing, citing_id, idx, stats)]
            for cited_id, excerpt, method, how in found:
                key = (citing_id, cited_id, prow["rowid"])
                if key in seen_pair_para:
                    continue
                seen_pair_para.add(key)
                stats[method] += 1
                if how.startswith("multi"):
                    stats[f"appno_{how}"] += 1
                citations.append((citing_id, cited_id, prow["rowid"], excerpt, method))
                if audit and (method == "name_date" or how.startswith("multi")):
                    audit.write(json.dumps({
                        "citing": citing_id, "cited": cited_id, "method": method,
                        "how": how, "paragraph_rowid": prow["rowid"], "excerpt": excerpt,
                    }, ensure_ascii=False) + "\n")
        if i % 1000 == 0 or i == len(case_ids):
            elapsed = time.perf_counter() - t0
            rate = i / elapsed if elapsed > 0 else 0
            print(f"  scanned {i:,}/{len(case_ids):,} cases  "
                  f"citations queued={len(citations):,}  ({rate:.0f} cases/s)")
    if audit:
        audit.close()

    if not args.no_hudoc and not args.limit_cases:
        print("\nadding citations recorded by HUDOC and missing from the text pass…")
        citations += hudoc_additions(cur, idx, citations, text_appnos, stats)

    print()
    print(f"total citations extracted:    {len(citations):,}")
    for k in ("appno_with_cue", "appno_no_cue", "name_date", "hudoc_caselaw", "hudoc_extracted"):
        print(f"  {k:<26}  {stats[k]:,}")
    if stats["hudoc_caselaw"] or stats["hudoc_extracted"] or stats["hudoc_caselaw_already_cited"]:
        print("HUDOC items already found in the text (not added):")
        for k in ("hudoc_caselaw_already_cited", "hudoc_extracted_already_cited",
                  "hudoc_caselaw_not_in_corpus", "hudoc_caselaw_later_case", "hudoc_extracted_later_case"):
            print(f"  {k:<30}  {stats[k]:,}")
    print("application numbers needing a choice between documents:")
    for k in ("appno_multi_by_date", "appno_multi_by_rank"):
        print(f"  {k:<26}  {stats[k]:,}")
    print("dropped:")
    for k in ("self_cite", "appno_dec_not_in_corpus", "appno_unresolved",
              "name_date_no_name_match", "name_date_state_mismatch",
              "name_date_appno_conflict", "name_date_revision_reference",
              "name_date_cited_is_later", "name_date_ambiguous"):
        print(f"  {k:<26}  {stats[k]:,}")

    cited_by = Counter(c[1] for c in citations)
    cites = Counter(c[0] for c in citations)
    print(f"\ncases with at least one cite:    {len(cites):,}")
    print(f"cases that are cited by something: {len(cited_by):,}")
    if cited_by:
        print("most-cited cases (top 5):")
        for cid, n in cited_by.most_common(5):
            cur.execute("SELECT title FROM cases WHERE case_id = ?", [cid])
            tr = cur.fetchone()
            print(f"    {cid}  {n:>4}× cited  {tr['title'] if tr else '(unknown)'}")

    if args.report_cues:
        return 0
    if not args.apply:
        print("\n(dry run — pass --apply to write case_citations table)")
        return 0

    print("\napplying — building case_citations table…")
    try:
        cur.execute("BEGIN")
        cur.execute("DROP TABLE IF EXISTS case_citations")
        cur.execute(
            "CREATE TABLE case_citations ("
            "  citing_case_id TEXT NOT NULL, "
            "  cited_case_id TEXT NOT NULL, "
            "  citing_paragraph_rowid INTEGER, "
            "  raw_text TEXT, "
            "  extraction_method TEXT, "
            "  PRIMARY KEY (citing_case_id, cited_case_id, citing_paragraph_rowid)"
            ")"
        )
        cur.execute("CREATE INDEX idx_cc_citing ON case_citations(citing_case_id)")
        cur.execute("CREATE INDEX idx_cc_cited  ON case_citations(cited_case_id)")
        cur.executemany(
            "INSERT INTO case_citations "
            "  (citing_case_id, cited_case_id, citing_paragraph_rowid, "
            "   raw_text, extraction_method) "
            "VALUES (?, ?, ?, ?, ?)",
            citations,
        )
        con.commit()
    except Exception as exc:
        con.rollback()
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"done.  case_citations table contains {len(citations):,} rows.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
