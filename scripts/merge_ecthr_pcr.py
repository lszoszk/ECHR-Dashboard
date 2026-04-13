#!/usr/bin/env python3
"""Merge RashidHaddad/ECTHR-PCR citation network into the ECHR dataset.

Reads the original JSONL (untouched) and writes a *new* enriched JSONL
with additional citation-graph fields from the ECTHR-PCR dataset.

New fields added to each record:
  pcr_citations        – list of appnos this case cites (structured links)
  pcr_cited_by         – list of appnos that cite this case (reverse links)
  pcr_citation_count   – number of precedents this case cites
  pcr_cited_by_count   – number of cases that cite this case (influence score)
  pcr_matched          – True if this case was found in the PCR dataset

The original strasbourg_caselaw field (free-text citations) is preserved as-is.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from collections import defaultdict
from pathlib import Path


def load_pcr_dataset():
    """Download and parse the ECTHR-PCR dataset from HuggingFace."""
    print("Downloading ECTHR-PCR dataset from HuggingFace...")
    from datasets import load_dataset

    ds = load_dataset("RashidHaddad/ECTHR-PCR", split="train")
    print(f"  Loaded {len(ds)} records from ECTHR-PCR")
    return ds


def parse_citations(citations_str: str) -> list[str]:
    """Parse the Python-list-as-string citations field."""
    if not citations_str or citations_str.strip() in ("[]", ""):
        return []
    try:
        result = ast.literal_eval(citations_str)
        if isinstance(result, list):
            return [str(x).strip() for x in result if str(x).strip()]
    except (ValueError, SyntaxError):
        pass
    return []


def strip_gc_suffix(appno: str) -> str:
    """Strip Grand Chamber letter suffix: '332/57B' → '332/57'."""
    return re.sub(r"[A-Za-z]+$", "", appno.strip())


def build_pcr_index(ds):
    """Build forward and reverse citation indexes from PCR data.

    Returns:
        forward:  { appno_clean → [list of cited appnos (clean)] }
        reverse:  { appno_clean → [list of citing appnos (clean)] }
        raw_map:  { appno_clean → original appno (with suffix) }
    """
    forward = {}
    reverse = defaultdict(list)
    raw_map = {}

    for row in ds:
        raw_appno = str(row["appno"]).strip()
        clean = strip_gc_suffix(raw_appno)
        raw_map[clean] = raw_appno

        cited = parse_citations(row.get("citations", "[]"))
        cited_clean = [strip_gc_suffix(c) for c in cited]
        # deduplicate while preserving order
        seen = set()
        deduped = []
        for c in cited_clean:
            if c not in seen:
                seen.add(c)
                deduped.append(c)
        forward[clean] = deduped

        for c in deduped:
            reverse[c].append(clean)

    return forward, dict(reverse), raw_map


def extract_appnos_from_case(case: dict) -> list[str]:
    """Extract all application numbers from a case record.

    Handles semicolon-separated case_no values like '1474/62;1677/62;...'
    """
    case_no = str(case.get("case_no") or "").strip()
    if not case_no:
        return []

    parts = re.split(r"[;,]", case_no)
    return [p.strip() for p in parts if p.strip()]


def merge(input_path: Path, output_path: Path):
    """Merge PCR citation data into ECHR cases, writing a new JSONL."""
    ds = load_pcr_dataset()
    forward, reverse, raw_map = build_pcr_index(ds)
    pcr_appnos = set(forward.keys())

    print(f"  PCR index: {len(forward)} cases with forward citations")
    print(f"  PCR index: {len(reverse)} cases appear as cited precedents")
    print(f"  Reading input: {input_path}")

    matched = 0
    unmatched = 0
    enriched_citations = 0
    enriched_cited_by = 0
    total = 0

    with input_path.open("r", encoding="utf-8") as fin, \
         output_path.open("w", encoding="utf-8") as fout:

        for line in fin:
            line = line.strip()
            if not line:
                continue
            total += 1
            case = json.loads(line)

            appnos = extract_appnos_from_case(case)
            # Try to match any of the case's application numbers
            pcr_citations = []
            pcr_cited_by = []
            found = False

            for appno in appnos:
                if appno in pcr_appnos:
                    found = True
                    # Forward: what does this case cite?
                    for c in forward.get(appno, []):
                        if c not in pcr_citations:
                            pcr_citations.append(c)
                    # Reverse: who cites this case?
                    for c in reverse.get(appno, []):
                        if c not in pcr_cited_by:
                            pcr_cited_by.append(c)

            case["pcr_citations"] = pcr_citations
            case["pcr_cited_by"] = pcr_cited_by
            case["pcr_citation_count"] = len(pcr_citations)
            case["pcr_cited_by_count"] = len(pcr_cited_by)
            case["pcr_matched"] = found

            if found:
                matched += 1
                if pcr_citations:
                    enriched_citations += 1
                if pcr_cited_by:
                    enriched_cited_by += 1
            else:
                unmatched += 1

            fout.write(json.dumps(case, ensure_ascii=False) + "\n")

    print()
    print("=" * 60)
    print(f"  Total records processed:    {total:>8,}")
    print(f"  Matched to PCR:             {matched:>8,}  ({matched/total*100:.1f}%)")
    print(f"  Unmatched:                  {unmatched:>8,}")
    print(f"  With forward citations:     {enriched_citations:>8,}")
    print(f"  With cited-by (influence):  {enriched_cited_by:>8,}")
    print("=" * 60)
    print(f"\n  Output: {output_path}")
    print(f"  Original file UNTOUCHED: {input_path}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        default="docs/data/echr_cases.jsonl",
        help="Path to original JSONL (will NOT be modified)",
    )
    parser.add_argument(
        "--output",
        default="docs/data/echr_cases_enriched.jsonl",
        help="Path to write enriched JSONL",
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
        print(f"ERROR: Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    if input_path.resolve() == output_path.resolve():
        print("ERROR: Input and output paths must differ (original must stay untouched).",
              file=sys.stderr)
        sys.exit(1)

    merge(input_path, output_path)


if __name__ == "__main__":
    main()
