#!/usr/bin/env python3
"""
convert_committee_cases.py -- Transform committee-format JSONL into the
schema expected by build_db.py and build_pages_dashboard.py, then append
to the main dataset.

Usage:
    python scripts/convert_committee_cases.py \
        --input ~/Downloads/echr_committee_cases_20260414_102928.jsonl \
        --output docs/data/echr_cases.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# ISO-3 → country name mapping (mirrors build_pages_dashboard.py)
COUNTRY_NAMES = {
    "ALB": "Albania",
    "AND": "Andorra",
    "ARM": "Armenia",
    "AUT": "Austria",
    "AZE": "Azerbaijan",
    "BEL": "Belgium",
    "BIH": "Bosnia and Herzegovina",
    "BGR": "Bulgaria",
    "HRV": "Croatia",
    "CYP": "Cyprus",
    "CZE": "Czech Republic",
    "DNK": "Denmark",
    "EST": "Estonia",
    "FIN": "Finland",
    "FRA": "France",
    "GEO": "Georgia",
    "DEU": "Germany",
    "GRC": "Greece",
    "HUN": "Hungary",
    "ISL": "Iceland",
    "IRL": "Ireland",
    "ITA": "Italy",
    "LVA": "Latvia",
    "LIE": "Liechtenstein",
    "LTU": "Lithuania",
    "LUX": "Luxembourg",
    "MLT": "Malta",
    "MDA": "Moldova",
    "MCO": "Monaco",
    "MNE": "Montenegro",
    "NLD": "Netherlands",
    "MKD": "North Macedonia",
    "NOR": "Norway",
    "POL": "Poland",
    "PRT": "Portugal",
    "ROU": "Romania",
    "RUS": "Russia",
    "SMR": "San Marino",
    "SRB": "Serbia",
    "SVK": "Slovakia",
    "SVN": "Slovenia",
    "ESP": "Spain",
    "SWE": "Sweden",
    "CHE": "Switzerland",
    "TUR": "Turkey",
    "TUR/": "Turkey",
    "UKR": "Ukraine",
    "GBR": "United Kingdom",
}

# Map new-format section field names → paragraph section labels used by
# build_db.py / build_pages_dashboard.py.
SECTION_MAP = [
    ("introduction", "Introduction"),
    ("legal_context", "Relevant legal framework"),
    ("relevant_legal_framework_practice", "Relevant legal framework"),
    ("facts", "Facts"),
    ("law", "Merits"),
    ("reasons_the_court_unanimously", "Operative part"),
]


def convert_date(iso_date: str) -> str:
    """YYYY-MM-DD → DD/MM/YYYY to match existing dataset format."""
    if not iso_date:
        return ""
    try:
        dt = datetime.strptime(iso_date, "%Y-%m-%d")
        return dt.strftime("%d/%m/%Y")
    except ValueError:
        return iso_date


def defendants_to_state(defendants: list) -> str:
    """Convert ['HUN'] or ['UKR', 'RUS'] → 'Hungary' or 'Ukraine; Russia'."""
    if not defendants:
        return ""
    names = [COUNTRY_NAMES.get(code, code) for code in defendants]
    return "; ".join(names)


def build_paragraphs(record: dict) -> list[dict]:
    """Assemble the paragraphs list from the section fields."""
    paragraphs = []
    for field, section_label in SECTION_MAP:
        texts = record.get(field) or []
        if isinstance(texts, str):
            texts = [texts]
        for text in texts:
            text = str(text).strip()
            if not text:
                continue
            paragraphs.append({"section": section_label, "text": text})
    return paragraphs


def doc_type_to_string(doc_type) -> str:
    """['CASELAW', 'JUDGMENTS', 'COMMITTEE', 'ENG'] → 'Judgment (Committee)'."""
    if isinstance(doc_type, list):
        upper = [x.upper() for x in doc_type]
        if "COMMITTEE" in upper:
            return "Judgment (Committee)"
        if "GRANDCHAMBER" in upper:
            return "Judgment (Grand Chamber)"
        if "CHAMBER" in upper:
            return "Judgment (Chamber)"
        return "Judgment (Merits and Just Satisfaction)"
    return str(doc_type or "")


def derive_conclusion(record: dict) -> str:
    """Best-effort conclusion from violation/non-violation lists."""
    parts = []
    for art in record.get("violation") or []:
        art = str(art).strip()
        if art:
            parts.append(f"Violation of {art}")
    for art in record.get("non-violation") or []:
        art = str(art).strip()
        if art:
            parts.append(f"No violation of {art}")
    return "; ".join(parts)


def originating_body_to_string(record: dict) -> str:
    """Normalize originating_body to a readable string."""
    ob = record.get("originating_body")
    if isinstance(ob, list):
        return "; ".join(str(x) for x in ob)
    return str(ob or "")


def convert_record(record: dict) -> dict:
    """Transform a single committee-format record to the existing schema."""
    case_id = record.get("case_id", "")
    defendants = record.get("defendants") or []

    return {
        "case_id": case_id,
        "case_no": record.get("case_no", ""),
        "title": record.get("title", ""),
        "hudoc_url": f"https://hudoc.echr.coe.int/?i={case_id}" if case_id else "",
        "judgment_date": convert_date(record.get("judgment_date", "")),
        "ecli": "",
        "respondent_state": defendants_to_state(defendants),
        "importance": "Unspecified",
        "conclusion": derive_conclusion(record),
        "violation": record.get("violation") or [],
        "non-violation": record.get("non-violation") or [],
        "keywords": [],
        "originating_body": originating_body_to_string(record),
        "document_type": doc_type_to_string(record.get("document_type")),
        "paragraphs": build_paragraphs(record),
        "separate_opinion": False,
        "represented_by": "",
        "domestic_law": "",
        "international_law": "",
        "rules_of_court": "",
        "strasbourg_caselaw": [],
        "applicability": [],
        "article_no": record.get("article_no", ""),
        "chamber_composed_of": record.get("chamber_composed_of") or [],
    }


def main():
    parser = argparse.ArgumentParser(
        description="Convert committee-format JSONL and append to main dataset.",
    )
    parser.add_argument(
        "--input", required=True, type=Path,
        help="Path to the committee cases JSONL file.",
    )
    parser.add_argument(
        "--output", required=True, type=Path,
        help="Path to the main echr_cases.jsonl to append to.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print stats without writing.",
    )
    args = parser.parse_args()

    if not args.input.is_file():
        print(f"Error: input file not found: {args.input}", file=sys.stderr)
        sys.exit(1)
    if not args.output.is_file():
        print(f"Error: output file not found: {args.output}", file=sys.stderr)
        sys.exit(1)

    # Collect existing case_ids to avoid duplicates
    existing_ids = set()
    with args.output.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                existing_ids.add(json.loads(line).get("case_id"))
            except json.JSONDecodeError:
                pass
    print(f"Existing dataset: {len(existing_ids)} case_ids")

    # Read and convert new records, deduplicating
    converted = []
    seen = set()
    skipped_dup_internal = 0
    skipped_dup_existing = 0
    total_input = 0

    with args.input.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            total_input += 1
            record = json.loads(line)
            cid = record.get("case_id")
            if cid in existing_ids:
                skipped_dup_existing += 1
                continue
            if cid in seen:
                skipped_dup_internal += 1
                continue
            seen.add(cid)
            converted.append(convert_record(record))

    total_paragraphs = sum(len(r["paragraphs"]) for r in converted)

    print(f"Input records:         {total_input}")
    print(f"Skipped (in existing): {skipped_dup_existing}")
    print(f"Skipped (internal dup):{skipped_dup_internal}")
    print(f"New cases to append:   {len(converted)}")
    print(f"Total new paragraphs:  {total_paragraphs}")

    if args.dry_run:
        print("\n[DRY RUN] No files modified.")
        # Print a sample
        if converted:
            print("\nSample converted record:")
            sample = converted[0]
            for k, v in sample.items():
                if k == "paragraphs":
                    print(f"  {k}: [{len(v)} paragraphs]")
                else:
                    print(f"  {k}: {str(v)[:100]}")
        return

    # Append to output
    with args.output.open("a", encoding="utf-8") as f:
        for record in converted:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"\nAppended {len(converted)} cases to {args.output}")
    print(f"New total: {len(existing_ids) + len(converted)} cases")


if __name__ == "__main__":
    main()
