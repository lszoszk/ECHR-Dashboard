#!/usr/bin/env python3
"""Generate a static stats payload for the GitHub Pages dashboard."""

from __future__ import annotations

import argparse
import json
import re
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


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
    "UKR": "Ukraine",
    "GBR": "United Kingdom",
}

SECTION_LABELS = {
    "header": "Header",
    "introduction": "Introduction",
    "facts_background": "Facts (Background)",
    "facts_proceedings": "Facts (Proceedings)",
    "legal_framework": "Legal Framework",
    "admissibility": "Admissibility",
    "merits": "Merits",
    "just_satisfaction": "Just Satisfaction",
    "article_46": "Article 46 (Execution)",
    "operative_part": "Operative Part",
    "separate_opinion": "Separate Opinion",
}


def parse_date(value: str):
    if not value:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def percentile(sorted_values, q):
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    pos = (len(sorted_values) - 1) * q
    low = int(pos)
    high = min(low + 1, len(sorted_values) - 1)
    weight = pos - low
    return sorted_values[low] * (1 - weight) + sorted_values[high] * weight


def select_input_file(root: Path):
    sample = root / "data" / "echr_decisions_sample.jsonl"
    option_b = root / "echr_cases_optionB.jsonl"
    fallback = root / "echr_cases_20260207_121847.jsonl"
    if sample.exists():
        return sample
    if option_b.exists():
        return option_b
    if fallback.exists():
        return fallback
    raise FileNotFoundError("No JSONL input found in expected locations.")


def load_cases(path: Path):
    cases = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                cases.append(json.loads(line))
    return cases


def build_payload(cases, source_file: str):
    case_count_by_month = Counter()
    case_count_by_year = Counter()
    paragraph_count_by_month = Counter()
    country_counts = Counter()
    article_counts = Counter()
    chamber_counts = Counter()
    section_counts = Counter()
    case_lengths = []
    parsed_dates = []
    violation_cases = 0
    non_violation_cases = 0
    unique_articles = set()

    total_paragraphs = 0

    for case in cases:
        paragraphs = [
            p
            for p in case.get("paragraphs", [])
            if p.get("section") != "header" and str(p.get("text", "")).strip()
        ]
        paragraph_len = len(paragraphs)
        total_paragraphs += paragraph_len
        case_lengths.append(paragraph_len)

        date_obj = parse_date(str(case.get("judgment_date", "")).strip())
        if date_obj:
            month_key = date_obj.strftime("%Y-%m")
            year_key = date_obj.strftime("%Y")
            case_count_by_month[month_key] += 1
            case_count_by_year[year_key] += 1
            paragraph_count_by_month[month_key] += paragraph_len
            parsed_dates.append(date_obj)

        for country in case.get("defendants", []):
            country_counts[country] += 1

        for article in re.split(r"[;,]", case.get("article_no", "")):
            article = article.strip()
            if article and not article.startswith("P") and len(article) < 10:
                article_counts[article] += 1
                unique_articles.add(article)

        doc_types = case.get("document_type", [])
        if "GRANDCHAMBER" in doc_types:
            chamber_counts["Grand Chamber"] += 1
        elif "CHAMBER" in doc_types:
            chamber_counts["Chamber"] += 1
        else:
            chamber_counts["Other"] += 1

        if case.get("violation"):
            violation_cases += 1
        if case.get("non-violation"):
            non_violation_cases += 1

        for para in paragraphs:
            section_counts[para.get("section", "unknown")] += 1

    sorted_lengths = sorted(case_lengths)
    total_cases = len(cases)

    avg_len = (sum(sorted_lengths) / total_cases) if total_cases else 0
    med_len = percentile(sorted_lengths, 0.5)
    p90_len = percentile(sorted_lengths, 0.9)
    min_len = sorted_lengths[0] if sorted_lengths else 0
    max_len = sorted_lengths[-1] if sorted_lengths else 0

    dated_cases = len(parsed_dates)
    undated_cases = max(0, total_cases - dated_cases)
    earliest = min(parsed_dates).strftime("%d %b %Y") if parsed_dates else "n/a"
    latest = max(parsed_dates).strftime("%d %b %Y") if parsed_dates else "n/a"

    grand_count = chamber_counts.get("Grand Chamber", 0)
    chamber_count = chamber_counts.get("Chamber", 0)
    other_count = chamber_counts.get("Other", 0)
    grand_share = (grand_count / total_cases * 100) if total_cases else 0

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_file": source_file,
        "summary": {
            "total_cases": total_cases,
            "total_paragraphs": total_paragraphs,
            "dated_cases": dated_cases,
            "undated_cases": undated_cases,
            "date_range_label": f"{earliest} – {latest}",
            "unique_countries": len(country_counts),
            "unique_articles": len(unique_articles),
            "avg_paragraphs_per_case": avg_len,
            "median_paragraphs_per_case": med_len,
            "p90_paragraphs_per_case": p90_len,
            "min_paragraphs_per_case": min_len,
            "max_paragraphs_per_case": max_len,
            "violation_cases": violation_cases,
            "non_violation_cases": non_violation_cases,
            "grand_chamber_share": grand_share,
            "grand_chamber_cases": grand_count,
            "chamber_cases": chamber_count,
            "other_cases": other_count,
        },
        "series": {
            "cases_by_month": sorted(case_count_by_month.items()),
            "cases_by_year": sorted(case_count_by_year.items()),
            "paragraphs_by_month": sorted(paragraph_count_by_month.items()),
            "chamber_breakdown": [
                ["Grand Chamber", grand_count],
                ["Chamber", chamber_count],
                ["Other", other_count],
            ],
            "case_length_snapshot": [
                ["Min", min_len],
                ["Median", med_len],
                ["P90", p90_len],
                ["Max", max_len],
            ],
        },
        "rankings": {
            "countries_top": [
                [COUNTRY_NAMES.get(code, code), count]
                for code, count in country_counts.most_common(20)
            ],
            "articles_top": article_counts.most_common(20),
            "sections": [
                [SECTION_LABELS.get(sec, sec), count]
                for sec, count in section_counts.most_common()
            ],
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", help="Path to input JSONL file")
    parser.add_argument(
        "--output",
        default="docs/data/stats.json",
        help="Path to output stats JSON",
    )
    parser.add_argument(
        "--export-data",
        default="docs/data/echr_cases.jsonl",
        help="Path to copy selected input JSONL for static web app",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    input_path = Path(args.input).expanduser().resolve() if args.input else select_input_file(repo_root)
    output_path = Path(args.output).expanduser()
    if not output_path.is_absolute():
        output_path = (repo_root / output_path).resolve()

    export_data_path = None
    if args.export_data:
        export_data_path = Path(args.export_data).expanduser()
        if not export_data_path.is_absolute():
            export_data_path = (repo_root / export_data_path).resolve()

    cases = load_cases(input_path)
    payload = build_payload(cases, input_path.name)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Wrote dashboard data: {output_path}")
    print(f"Cases: {payload['summary']['total_cases']}, paragraphs: {payload['summary']['total_paragraphs']}")

    if export_data_path:
        export_data_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(input_path, export_data_path)
        print(f"Copied JSONL dataset for web app: {export_data_path}")


if __name__ == "__main__":
    main()
