#!/usr/bin/env python3
"""Resolve free-text strasbourg_caselaw citations to structured appno links.

Builds a case-name → case_no lookup from the dataset itself, then parses
each strasbourg_caselaw citation string to extract the referenced case name
and resolve it to an application number (case_no).

This is a self-enrichment script: no external data is needed.  It fills the
citation gap for cases not covered by the ECTHR-PCR dataset (typically
post-2022 judgments).

New/updated fields:
  resolved_citations       – list of {appno, title, raw} dicts for each resolved cite
  resolved_citation_count  – number of successfully resolved citations
  resolution_rate          – fraction of strasbourg_caselaw entries that resolved
  pcr_citations            – extended with newly resolved appnos (deduped)
  pcr_citation_count       – updated count

The original strasbourg_caselaw field is never modified.
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path


# ---------------------------------------------------------------------------
# Text normalisation
# ---------------------------------------------------------------------------

def normalize_text(s: str) -> str:
    """Lowercase, strip accents, collapse whitespace."""
    s = str(s or "").strip().lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"\s+", " ", s)
    return s


def clean_title(title: str) -> str:
    """Strip common prefixes from case titles."""
    t = str(title or "").strip()
    # Remove "CASE OF", "AFFAIRE"
    t = re.sub(r"^(?:CASE OF|AFFAIRE)\s+", "", t, flags=re.IGNORECASE)
    # Remove trailing case-number-like suffixes: (No. 2), (no. 3), (APPLICATION NO. ...)
    t = re.sub(r"\s*\((?:No\.\s*\d+|APPLICATION NO\.?\s*[\d/]+|ARTICLE\s+50|PRELIMINARY\s+OBJECTION(?:S)?|MERITS|JUST\s+SATISFACTION|REVISION|INTERPRETATION|FORMER\s+.*?)\)\s*$",
               "", t, flags=re.IGNORECASE)
    return t.strip()


# ---------------------------------------------------------------------------
# Build lookup index from the dataset
# ---------------------------------------------------------------------------

def build_case_index(cases: list[dict]) -> dict:
    """Build multiple lookup tables: normalized_name → {appno, title}.

    Returns a dict mapping normalized name strings to case info.
    Multiple variants are indexed for each case to maximise hit rate.
    """
    index = {}  # normalized_key → {"appno": str, "title": str}
    collision_count = 0

    for case in cases:
        case_no = str(case.get("case_no") or "").strip()
        title = str(case.get("title") or "").strip()
        if not case_no or not title:
            continue

        # Skip press releases
        doc_type = str(case.get("document_type") or "").lower()
        if "press release" in doc_type:
            continue

        info = {"appno": case_no.split(";")[0].strip(), "title": title}
        cleaned = clean_title(title)

        # Index multiple variants
        variants = set()

        # Full cleaned title: "GOLDER v. THE UNITED KINGDOM"
        variants.add(normalize_text(cleaned))

        # Without "THE": "GOLDER v. UNITED KINGDOM"
        no_the = re.sub(r"\bthe\b", "", normalize_text(cleaned)).strip()
        no_the = re.sub(r"\s+", " ", no_the)
        variants.add(no_the)

        # Extract "v." parts
        v_match = re.match(r"^(.+?)\s+v\.?\s+(.+)$", cleaned, re.IGNORECASE)
        if v_match:
            applicant = v_match.group(1).strip()
            respondent = v_match.group(2).strip()

            # "golder v. united kingdom"
            variants.add(normalize_text(f"{applicant} v. {respondent}"))
            # Without "the" in respondent
            resp_no_the = re.sub(r"^the\s+", "", respondent, flags=re.IGNORECASE)
            variants.add(normalize_text(f"{applicant} v. {resp_no_the}"))

            # Applicant surname only (for "Golder judgment" style citations)
            # Take first word of applicant as surname key
            surname = applicant.split()[0] if applicant else ""
            if surname and len(surname) >= 3:
                variants.add(normalize_text(surname))

            # "and others" variants
            base_applicant = re.sub(
                r"\s+and\s+others?\s*$", "", applicant, flags=re.IGNORECASE
            )
            if base_applicant != applicant:
                variants.add(normalize_text(f"{base_applicant} v. {respondent}"))
                variants.add(normalize_text(f"{base_applicant} v. {resp_no_the}"))
                variants.add(normalize_text(f"{base_applicant} and others v. {respondent}"))
                variants.add(normalize_text(f"{base_applicant} and others v. {resp_no_the}"))

        for v in variants:
            if not v or len(v) < 3:
                continue
            if v in index and index[v]["appno"] != info["appno"]:
                # Collision — same normalised name, different cases.
                # Keep the first (older) one for stability but note it.
                collision_count += 1
                continue
            index[v] = info

    return index


# ---------------------------------------------------------------------------
# Citation parsing
# ---------------------------------------------------------------------------

def extract_case_name_from_citation(citation: str) -> list[str]:
    """Extract candidate case-name strings from a free-text citation.

    Returns a list of candidates (most specific first) for lookup.
    """
    cite = str(citation or "").strip()
    candidates = []

    # Pattern 1: "Name v. Country, judgment/decision of ..."
    m = re.match(
        r"^(?:No\.\s*[\d/]+\s*,\s*)?(.+?)\s+v\.?\s+(.+?)(?:\s*,\s*(?:judgment|decision|dec\.|comm\.|report))",
        cite,
        re.IGNORECASE,
    )
    if m:
        full = f"{m.group(1).strip()} v. {m.group(2).strip()}"
        candidates.append(full)
        # Without "the"
        resp_no_the = re.sub(r"^the\s+", "", m.group(2).strip(), flags=re.IGNORECASE)
        candidates.append(f"{m.group(1).strip()} v. {resp_no_the}")

    # Pattern 2: "Name v. Country judgment of ..." (no comma)
    if not candidates:
        m = re.match(
            r"^(?:No\.\s*[\d/]+\s*,\s*)?(.+?)\s+v\.?\s+(.+?)\s+(?:judgment|decision)\s+of",
            cite,
            re.IGNORECASE,
        )
        if m:
            full = f"{m.group(1).strip()} v. {m.group(2).strip()}"
            candidates.append(full)
            resp_no_the = re.sub(r"^the\s+", "", m.group(2).strip(), flags=re.IGNORECASE)
            candidates.append(f"{m.group(1).strip()} v. {resp_no_the}")

    # Pattern 3: "Name judgment of ..." (single name, no v.)
    if not candidates:
        m = re.match(
            r"^(.+?)\s+(?:judgment|decision)\s+of\s+",
            cite,
            re.IGNORECASE,
        )
        if m:
            name = m.group(1).strip()
            # Remove leading "No. 12345/67, "
            name = re.sub(r"^No\.\s*[\d/]+\s*,\s*", "", name)
            if name and len(name) >= 3:
                candidates.append(name)

    # Pattern 4: "No. XXXX/YY, Name v. Country, Dec. ..."
    if not candidates:
        m = re.match(
            r"^No\.\s*[\d/]+\s*,\s*(.+?)\s+v\.?\s+(.+?)\s*,\s*(?:Dec\.|Comm\.)",
            cite,
            re.IGNORECASE,
        )
        if m:
            full = f"{m.group(1).strip()} v. {m.group(2).strip()}"
            candidates.append(full)

    # Pattern 5: "Name v. Country, no. XXXXX/XX, ..." or "Name v. Country (dec.), ..."
    if not candidates and " v. " in cite:
        # Greedy: grab everything up to ", no." or ", §" or ", judgment" or year
        m = re.match(
            r"^(?:No\.\s*[\d/]+\s*,\s*)?(.+?\s+v\.\s+.+?)"
            r"(?:\s*(?:\(dec\.\))?\s*(?:,\s*no\.|\s*,\s*§|,\s+\d{1,2}\s+\w+\s+\d{4}|\s+judgment|\s+decision|\s*\[|\s*,\s*Reports))",
            cite,
            re.IGNORECASE,
        )
        if m:
            name = m.group(1).strip()
            # Strip trailing (dec.), [GC], etc.
            name = re.sub(r"\s*\(dec\.\)\s*$", "", name, flags=re.IGNORECASE)
            name = re.sub(r"\s*\[GC\]\s*$", "", name, flags=re.IGNORECASE)
            candidates.append(name)

    # Pattern 6: last resort — anything before first comma with "v."
    if not candidates and " v. " in cite:
        m = re.match(r"^(.+?\s+v\.\s+[^,]+)", cite)
        if m:
            name = m.group(1).strip()
            name = re.sub(r"\s*\(dec\.\)\s*$", "", name, flags=re.IGNORECASE)
            name = re.sub(r"\s*\[GC\]\s*$", "", name, flags=re.IGNORECASE)
            candidates.append(name)

    return candidates


def extract_appno_from_citation(citation: str) -> str | None:
    """Try to extract an application number directly from the citation."""
    # Match "No." or "no." followed by digits/slash
    m = re.search(r"no\.\s*(\d+/\d+)", citation, re.IGNORECASE)
    if m:
        return m.group(1)
    return None


def resolve_citation(citation: str, index: dict, appno_index: dict) -> dict | None:
    """Try to resolve a single citation string to a case in the index.

    Returns {"appno": str, "title": str, "raw": str} or None.
    """
    # First try direct appno extraction (O(1) lookup)
    direct_appno = extract_appno_from_citation(citation)
    if direct_appno and direct_appno in appno_index:
        info = appno_index[direct_appno]
        return {"appno": info["appno"], "title": info["title"], "raw": citation}

    # Try name-based matching
    candidates = extract_case_name_from_citation(citation)
    for candidate in candidates:
        key = normalize_text(candidate)
        if key in index:
            return {
                "appno": index[key]["appno"],
                "title": index[key]["title"],
                "raw": citation,
            }

    return None


# ---------------------------------------------------------------------------
# Main merge
# ---------------------------------------------------------------------------

def enrich(input_path: Path, output_path: Path):
    """Read enriched JSONL, resolve citations, write updated JSONL."""
    print(f"Reading cases from {input_path} ...")
    cases = []
    with input_path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                cases.append(json.loads(line))
    print(f"  Loaded {len(cases):,} records")

    print("Building case-name index ...")
    index = build_case_index(cases)
    print(f"  Indexed {len(index):,} name variants")

    # Build appno → info dict for direct O(1) lookups
    appno_index = {}
    for case in cases:
        case_no = str(case.get("case_no") or "").strip()
        title = str(case.get("title") or "").strip()
        doc_type = str(case.get("document_type") or "").lower()
        if "press release" in doc_type or not case_no:
            continue
        for part in case_no.split(";"):
            part = part.strip()
            if part and part not in appno_index:
                appno_index[part] = {"appno": part, "title": title}
    print(f"  Indexed {len(appno_index):,} direct appno lookups")

    total = 0
    already_matched = 0
    newly_enriched = 0
    total_resolved = 0
    total_citations_attempted = 0
    total_failed = 0
    cases_with_no_caselaw = 0

    failed_samples = Counter()

    with output_path.open("w", encoding="utf-8") as fout:
        for case in cases:
            total += 1
            caselaw = case.get("strasbourg_caselaw") or []
            was_matched = case.get("pcr_matched", False)
            existing_pcr = set(case.get("pcr_citations") or [])

            if was_matched:
                already_matched += 1

            if not caselaw:
                cases_with_no_caselaw += 1
                case.setdefault("resolved_citations", [])
                case.setdefault("resolved_citation_count", 0)
                case.setdefault("resolution_rate", 0.0)
                fout.write(json.dumps(case, ensure_ascii=False) + "\n")
                continue

            resolved = []
            for cite in caselaw:
                total_citations_attempted += 1
                result = resolve_citation(cite, index, appno_index)
                if result:
                    resolved.append(result)
                    total_resolved += 1
                else:
                    total_failed += 1
                    # Track failed patterns for diagnostics
                    short = cite[:80]
                    failed_samples[short] += 1

            # Extend pcr_citations with newly resolved appnos
            new_appnos = []
            for r in resolved:
                appno = r["appno"]
                if appno not in existing_pcr:
                    new_appnos.append(appno)
                    existing_pcr.add(appno)

            if new_appnos and not was_matched:
                newly_enriched += 1

            case["pcr_citations"] = (case.get("pcr_citations") or []) + new_appnos
            case["pcr_citation_count"] = len(case["pcr_citations"])
            case["resolved_citations"] = resolved
            case["resolved_citation_count"] = len(resolved)
            case["resolution_rate"] = round(len(resolved) / len(caselaw), 4) if caselaw else 0.0

            fout.write(json.dumps(case, ensure_ascii=False) + "\n")

    print()
    print("=" * 65)
    print(f"  Total records:                {total:>10,}")
    print(f"  Already had PCR match:        {already_matched:>10,}")
    print(f"  Newly enriched (was empty):   {newly_enriched:>10,}")
    print(f"  No strasbourg_caselaw at all: {cases_with_no_caselaw:>10,}")
    print(f"  ---")
    print(f"  Citations attempted:          {total_citations_attempted:>10,}")
    print(f"  Successfully resolved:        {total_resolved:>10,}  ({total_resolved/max(total_citations_attempted,1)*100:.1f}%)")
    print(f"  Failed to resolve:            {total_failed:>10,}  ({total_failed/max(total_citations_attempted,1)*100:.1f}%)")
    print("=" * 65)
    print(f"\n  Output: {output_path}")
    print(f"  Original UNTOUCHED: {input_path}")

    if failed_samples:
        print(f"\n  Top 10 unresolved citations:")
        for cite, count in failed_samples.most_common(10):
            print(f"    [{count:>3}x] {cite}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--input",
        default="docs/data/echr_cases_enriched.jsonl",
        help="Path to enriched JSONL (from merge_ecthr_pcr.py)",
    )
    parser.add_argument(
        "--output",
        default="docs/data/echr_cases_enriched.jsonl",
        help="Path to write updated JSONL (can be same as input to update in-place)",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    input_path = Path(args.input).expanduser()
    if not input_path.is_absolute():
        input_path = (repo_root / input_path).resolve()

    output_path = Path(args.output).expanduser()
    if not output_path.is_absolute():
        output_path = (repo_root / output_path).resolve()

    if not input_path.exists():
        print(f"ERROR: Input not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    enrich(input_path, output_path)


if __name__ == "__main__":
    main()
