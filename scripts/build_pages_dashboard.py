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
    "legal_context": "Legal Context",
    "admissibility": "Admissibility",
    "merits": "Merits",
    "just_satisfaction": "Just Satisfaction",
    "article_46": "Article 46 (Execution)",
    "operative_part": "Operative Part",
    "separate_opinion": "Separate Opinion",
    "appendix": "Appendix",
}

OUTCOME_LABELS = {
    "violation_only": "Violation only",
    "non_violation_only": "Non-violation only",
    "both": "Both",
    "neither": "Neither",
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


def is_present(value) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict, tuple, set)):
        return len(value) > 0
    return True


def normalize_list(value, split_text: bool = False):
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]

    text = str(value or "").strip()
    if not text:
        return []

    if split_text:
        return [x.strip() for x in re.split(r"[;,]", text) if x.strip()]
    return [text]


def normalize_section_key(raw_section: str) -> str:
    key = str(raw_section or "").strip().lower().replace("-", " ")
    aliases = {
        "header": "header",
        "introduction": "introduction",
        "facts background": "facts_background",
        "facts_background": "facts_background",
        "facts proceedings": "facts_proceedings",
        "facts_proceedings": "facts_proceedings",
        "legal framework": "legal_framework",
        "legal_framework": "legal_framework",
        "legal context": "legal_context",
        "legal_context": "legal_context",
        "admissibility": "admissibility",
        "merits": "merits",
        "just satisfaction": "just_satisfaction",
        "just_satisfaction": "just_satisfaction",
        "article 46": "article_46",
        "article_46": "article_46",
        "operative part": "operative_part",
        "operative_part": "operative_part",
        "separate opinion": "separate_opinion",
        "separate_opinion": "separate_opinion",
        "appendix": "appendix",
    }
    if key in aliases:
        return aliases[key]
    return re.sub(r"\s+", "_", key or "unknown")


def normalize_doc_types(case):
    return normalize_list(case.get("document_type"), split_text=False)


def normalize_states(case):
    respondent = str(case.get("respondent_state") or "").strip()
    if respondent:
        return [respondent]

    defendants = normalize_list(case.get("defendants"), split_text=True)
    if not defendants:
        return []
    return [COUNTRY_NAMES.get(code, code) for code in defendants]


def infer_chamber_category(doc_types, originating_body: str) -> str:
    doc_text = " ".join(doc_types).upper()
    body_text = str(originating_body or "").upper()

    if "GRANDCHAMBER" in doc_text or "GRAND CHAMBER" in doc_text or "GRAND CHAMBER" in body_text:
        return "GRANDCHAMBER"
    if "CHAMBER" in doc_text or "SECTION" in body_text or "CHAMBER" in body_text:
        return "CHAMBER"
    return "OTHER"


def normalize_bool(value) -> bool:
    if value is True or value is False:
        return value
    text = str(value or "").strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    return False


def normalize_articles(case):
    articles = []
    for token in re.split(r"[;,]", str(case.get("article_no", ""))):
        token = token.strip()
        if token:
            articles.append(token)
    return articles


def derive_outcome_bucket(violation, non_violation):
    has_v = len(violation) > 0
    has_nv = len(non_violation) > 0
    if has_v and has_nv:
        return "both"
    if has_v:
        return "violation_only"
    if has_nv:
        return "non_violation_only"
    return "neither"


def normalize_case(case):
    doc_types = normalize_doc_types(case)
    originating_body = str(case.get("originating_body") or "").strip()
    states = normalize_states(case)
    keywords = normalize_list(case.get("keywords"), split_text=False)
    violation = normalize_list(case.get("violation"), split_text=True)
    non_violation = normalize_list(case.get("non-violation"), split_text=True)
    citations = normalize_list(case.get("strasbourg_caselaw"), split_text=False)
    judges = normalize_list(case.get("chamber_composed_of"), split_text=False)
    paragraphs = []

    for para in case.get("paragraphs", []):
        text = str((para or {}).get("text", "")).strip()
        section = normalize_section_key((para or {}).get("section", "unknown"))
        if not text or section == "header":
            continue
        paragraphs.append({"section": section, "text": text})

    return {
        "date": parse_date(str(case.get("judgment_date", "")).strip()),
        "states": states,
        "articles": normalize_articles(case),
        "doc_types": doc_types,
        "chamber_category": infer_chamber_category(doc_types, originating_body),
        "originating_body": originating_body or "Unknown",
        "importance": str(case.get("importance") or "").strip() or "Unspecified",
        "separate_opinion": normalize_bool(case.get("separate_opinion")),
        "paragraphs": paragraphs,
        "paragraph_len": len(paragraphs),
        "violation": violation,
        "non_violation": non_violation,
        "outcome_bucket": derive_outcome_bucket(violation, non_violation),
        "keywords": keywords,
        "citations": citations,
        "judges": judges,
        "has_strasbourg_caselaw": len(citations) > 0,
        "has_domestic_law": is_present(case.get("domestic_law")),
        "has_international_law": is_present(case.get("international_law")),
        "has_rules_of_court": is_present(case.get("rules_of_court")),
        "is_key_case": str(case.get("importance") or "").strip().lower() == "key cases",
    }


def select_input_file(root: Path):
    preferred = root / "echr_cases_20260213_081310.jsonl"
    sample = root / "data" / "echr_decisions_sample.jsonl"
    option_b = root / "echr_cases_optionB.jsonl"
    fallback = root / "echr_cases_20260207_121847.jsonl"

    for candidate in (preferred, sample, option_b, fallback):
        if candidate.exists():
            return candidate

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
    body_counts = Counter()
    importance_counts = Counter()
    outcome_counts = Counter()
    keyword_counts = Counter()
    judge_counts = Counter()
    citation_counts = Counter()
    separate_opinion_by_body_total = Counter()
    separate_opinion_by_body_cases = Counter()
    article_violation_counts = Counter()
    article_non_violation_counts = Counter()

    case_lengths = []
    parsed_dates = []
    unique_articles = set()

    total_paragraphs = 0
    violation_cases = 0
    non_violation_cases = 0
    key_cases = 0
    separate_opinion_cases = 0
    cases_with_strasbourg_caselaw = 0
    cases_with_domestic_law = 0
    cases_with_international_law = 0
    cases_with_rules_of_court = 0
    total_strasbourg_citations = 0

    quality_fields = [
        "respondent_state",
        "defendants",
        "originating_body",
        "importance",
        "keywords",
        "separate_opinion",
        "ecli",
        "hudoc_url",
        "represented_by",
        "strasbourg_caselaw",
        "domestic_law",
        "international_law",
        "rules_of_court",
        "violation",
        "non-violation",
        "applicability",
        "conclusion",
        "chamber_composed_of",
    ]
    nonempty_field_counts = Counter()

    for case in cases:
        normalized = normalize_case(case)
        paragraph_len = normalized["paragraph_len"]

        total_paragraphs += paragraph_len
        case_lengths.append(paragraph_len)

        date_obj = normalized["date"]
        if date_obj:
            month_key = date_obj.strftime("%Y-%m")
            year_key = date_obj.strftime("%Y")
            case_count_by_month[month_key] += 1
            case_count_by_year[year_key] += 1
            paragraph_count_by_month[month_key] += paragraph_len
            parsed_dates.append(date_obj)

        for state in normalized["states"]:
            country_counts[state] += 1

        for article in normalized["articles"]:
            if article and not article.startswith("P") and len(article) < 10:
                article_counts[article] += 1
                unique_articles.add(article)

        for article in normalized["violation"]:
            article_violation_counts[article] += 1
        for article in normalized["non_violation"]:
            article_non_violation_counts[article] += 1

        if normalized["chamber_category"] == "GRANDCHAMBER":
            chamber_counts["Grand Chamber"] += 1
        elif normalized["chamber_category"] == "CHAMBER":
            chamber_counts["Chamber"] += 1
        else:
            chamber_counts["Other"] += 1

        if normalized["violation"]:
            violation_cases += 1
        if normalized["non_violation"]:
            non_violation_cases += 1

        if normalized["is_key_case"]:
            key_cases += 1

        if normalized["separate_opinion"]:
            separate_opinion_cases += 1

        if normalized["has_strasbourg_caselaw"]:
            cases_with_strasbourg_caselaw += 1

        if normalized["has_domestic_law"]:
            cases_with_domestic_law += 1

        if normalized["has_international_law"]:
            cases_with_international_law += 1

        if normalized["has_rules_of_court"]:
            cases_with_rules_of_court += 1

        total_strasbourg_citations += len(normalized["citations"])

        body = normalized["originating_body"]
        importance = normalized["importance"]
        outcome = normalized["outcome_bucket"]
        body_counts[body] += 1
        importance_counts[importance] += 1
        outcome_counts[outcome] += 1
        separate_opinion_by_body_total[body] += 1
        if normalized["separate_opinion"]:
            separate_opinion_by_body_cases[body] += 1

        for para in normalized["paragraphs"]:
            section_counts[para["section"]] += 1

        for keyword in normalized["keywords"]:
            keyword_counts[keyword] += 1

        for citation in normalized["citations"]:
            citation_counts[citation] += 1

        for judge in normalized["judges"]:
            judge_counts[judge] += 1

        for field in quality_fields:
            if is_present(case.get(field)):
                nonempty_field_counts[field] += 1

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

    avg_strasbourg_citations_per_case = (
        total_strasbourg_citations / total_cases if total_cases else 0
    )

    article_outcomes = []
    for article in set(article_violation_counts) | set(article_non_violation_counts):
        v_count = article_violation_counts.get(article, 0)
        nv_count = article_non_violation_counts.get(article, 0)
        article_outcomes.append([article, v_count, nv_count, v_count + nv_count])
    article_outcomes.sort(key=lambda row: row[3], reverse=True)

    field_completeness = {
        field: round((nonempty_field_counts[field] / total_cases), 4) if total_cases else 0
        for field in quality_fields
    }

    separate_opinion_share_by_body = []
    for body, total in separate_opinion_by_body_total.most_common(20):
        separate_cases = separate_opinion_by_body_cases.get(body, 0)
        share_pct = (separate_cases / total * 100) if total else 0
        separate_opinion_share_by_body.append([body, round(share_pct, 2), total, separate_cases])

    importance_breakdown = [[level, count] for level, count in importance_counts.most_common()]
    outcome_breakdown = [
        [OUTCOME_LABELS.get(key, key), outcome_counts.get(key, 0)]
        for key in ("violation_only", "non_violation_only", "both", "neither")
    ]

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
            "key_cases": key_cases,
            "separate_opinion_cases": separate_opinion_cases,
            "cases_with_strasbourg_caselaw": cases_with_strasbourg_caselaw,
            "avg_strasbourg_citations_per_case": avg_strasbourg_citations_per_case,
            "cases_with_domestic_law": cases_with_domestic_law,
            "cases_with_international_law": cases_with_international_law,
            "cases_with_rules_of_court": cases_with_rules_of_court,
            "outcome_violation_only": outcome_counts.get("violation_only", 0),
            "outcome_non_violation_only": outcome_counts.get("non_violation_only", 0),
            "outcome_both": outcome_counts.get("both", 0),
            "outcome_neither": outcome_counts.get("neither", 0),
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
            "importance_breakdown": importance_breakdown,
            "outcome_breakdown": outcome_breakdown,
            "separate_opinion_share_by_body": separate_opinion_share_by_body,
        },
        "rankings": {
            "countries_top": country_counts.most_common(20),
            "articles_top": article_counts.most_common(20),
            "sections": [
                [SECTION_LABELS.get(sec, sec), count]
                for sec, count in section_counts.most_common()
            ],
            "originating_bodies_top": body_counts.most_common(20),
            "importance_distribution": importance_breakdown,
            "keywords_top": keyword_counts.most_common(30),
            "judges_top": judge_counts.most_common(30),
            "strasbourg_caselaw_top": citation_counts.most_common(20),
            "article_outcomes_top": article_outcomes[:20],
            "outcomes": outcome_breakdown,
        },
        "quality": {
            "field_completeness": field_completeness,
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
    parser.add_argument(
        "--sample-output",
        default="docs/data/echr_cases_sample50.jsonl",
        help="Path to write sample JSONL for static web app",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=50,
        help="Number of decisions in generated sample JSONL",
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

    sample_output_path = None
    if args.sample_output:
        sample_output_path = Path(args.sample_output).expanduser()
        if not sample_output_path.is_absolute():
            sample_output_path = (repo_root / sample_output_path).resolve()

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

    if sample_output_path:
        sample_output_path.parent.mkdir(parents=True, exist_ok=True)
        sample_size = max(0, int(args.sample_size))
        with sample_output_path.open("w", encoding="utf-8") as f:
            for case in cases[:sample_size]:
                f.write(json.dumps(case, ensure_ascii=False) + "\n")
        print(
            "Wrote sample JSONL for web app: "
            f"{sample_output_path} ({min(sample_size, len(cases))} cases)"
        )


if __name__ == "__main__":
    main()
