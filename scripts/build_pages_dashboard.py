#!/usr/bin/env python3
"""Generate a static stats payload for the GitHub Pages dashboard."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


# Load KP thesaurus labels
_KPT_LABELS_PATH = Path(__file__).resolve().parent / "kpthesaurus_labels.json"
KPT_LABELS: dict[str, str] = {}
if _KPT_LABELS_PATH.exists():
    KPT_LABELS = json.loads(_KPT_LABELS_PATH.read_text(encoding="utf-8"))


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
    "summary": "Summary",
    "introduction": "Introduction",
    # P63/P64 split the Facts family. The two legacy labels below survive only
    # in the handful of cases that still carry an unsegmented `Facts` label.
    "procedure": "Procedure",
    "circumstances": "Circumstances of the Case",
    "subject_matter": "Subject Matter of the Case",
    "facts": "Facts (unsegmented)",
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

OUTCOME_KEYS = ("violation_only", "non_violation_only", "both", "neither")
SCHEMA_VERSION = "echr-dashboard-v2"
PARSER_VERSION = "2.0.0"


def parse_date(value: str):
    if not value:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def normalize_search_text(value: str) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text)


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


def canonicalize_citation(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_citations(value):
    items = normalize_list(value, split_text=False)
    out = []
    seen = set()
    for item in items:
        clean = canonicalize_citation(item)
        if not clean:
            continue
        key = normalize_search_text(clean)
        if key in seen:
            continue
        seen.add(key)
        out.append(clean)
    return out


def parse_conclusion_flags(conclusion: str):
    text = normalize_search_text(conclusion)
    return {
        "has_inadmissibility": "inadmissible" in text,
        "is_struck_out": "struck out" in text,
        "has_procedural_aspect": "procedural aspect" in text,
        "has_substantive_aspect": "substantive aspect" in text,
    }


def extract_inadmissibility_grounds(conclusion: str):
    text = normalize_search_text(conclusion)
    grounds = []
    mapping = [
        ("manifestly ill-founded", "Manifestly ill-founded"),
        ("ratione materiae", "Ratione materiae"),
        ("ratione personae", "Ratione personae"),
        ("ratione temporis", "Ratione temporis"),
        ("ratione loci", "Ratione loci"),
        ("non-exhaustion", "Non-exhaustion of domestic remedies"),
        ("exhaustion of domestic remedies", "Exhaustion of domestic remedies"),
        ("six-month", "Six-month rule"),
        ("four-month", "Four-month rule"),
        ("no significant disadvantage", "No significant disadvantage"),
    ]
    for needle, label in mapping:
        if needle in text:
            grounds.append(label)
    if "inadmissible" in text and not grounds:
        grounds.append("Other / unspecified")
    return grounds


def _award_stats(amounts: list[float]) -> dict:
    """Compute summary stats for a list of award amounts."""
    if not amounts:
        return {"count": 0, "min": 0, "max": 0, "median": 0, "mean": 0, "total": 0}
    sorted_a = sorted(amounts)
    n = len(sorted_a)
    return {
        "count": n,
        "min": round(sorted_a[0], 2),
        "max": round(sorted_a[-1], 2),
        "median": round(sorted_a[n // 2], 2),
        "mean": round(sum(sorted_a) / n, 2),
        "total": round(sum(sorted_a), 2),
    }


def parse_conclusion_clauses(conclusion: str) -> dict:
    """Parse conclusion string into structured outcome categories.

    Returns a dict with:
      clause_types: Counter of clause categories
      just_satisfaction: dict with award stats (pecuniary, non_pecuniary, costs)
      preliminary_objections: dict with accepted/rejected counts
    """
    clause_types = Counter()
    awards = {"pecuniary": [], "non_pecuniary": [], "costs": []}
    prelim = {"rejected": 0, "accepted": 0, "joined_to_merits": 0}

    if not conclusion or not conclusion.strip():
        return {"clause_types": clause_types, "awards": awards, "preliminary_objections": prelim}

    for clause in conclusion.split(";"):
        clause = clause.strip()
        if not clause:
            continue
        cl = clause.lower()

        if re.match(r"violation of art", cl):
            clause_types["Violation finding"] += 1
        elif re.match(r"no violation of art", cl):
            clause_types["No violation finding"] += 1
        elif "not necessary to examine" in cl:
            clause_types["Not necessary to examine"] += 1
        elif re.match(r"preliminary objection", cl):
            if "rejected" in cl or "dismissed" in cl:
                clause_types["Preliminary objection rejected"] += 1
                prelim["rejected"] += 1
            elif "allowed" in cl or "accepted" in cl or "upheld" in cl:
                clause_types["Preliminary objection accepted"] += 1
                prelim["accepted"] += 1
            elif "joined to merits" in cl:
                clause_types["Preliminary objection joined to merits"] += 1
                prelim["joined_to_merits"] += 1
            else:
                clause_types["Preliminary objection other"] += 1
        elif "just satisfaction" in cl:
            clause_types["Just satisfaction reserved"] += 1
        elif "pecuniary damage" in cl and "non-pecuniary" not in cl:
            if "financial award" in cl or ("award" in cl and "dismiss" not in cl):
                clause_types["Pecuniary damage awarded"] += 1
                m = re.search(r"EUR\s+([\d,]+(?:\.\d+)?)", clause)
                if m:
                    try:
                        awards["pecuniary"].append(float(m.group(1).replace(",", "")))
                    except ValueError:
                        pass
            elif "dismissed" in cl or "claim dismissed" in cl:
                clause_types["Pecuniary damage dismissed"] += 1
            else:
                clause_types["Pecuniary damage other"] += 1
        elif "non-pecuniary damage" in cl:
            if "financial award" in cl:
                clause_types["Non-pecuniary damage awarded"] += 1
                m = re.search(r"EUR\s+([\d,]+(?:\.\d+)?)", clause)
                if m:
                    try:
                        awards["non_pecuniary"].append(float(m.group(1).replace(",", "")))
                    except ValueError:
                        pass
            elif "finding of violation sufficient" in cl:
                clause_types["Non-pecuniary: violation sufficient"] += 1
            elif "dismissed" in cl:
                clause_types["Non-pecuniary damage dismissed"] += 1
            else:
                clause_types["Non-pecuniary damage other"] += 1
        elif "costs and expenses" in cl:
            if "award" in cl and "dismiss" not in cl:
                clause_types["Costs & expenses awarded"] += 1
                m = re.search(r"EUR\s+([\d,]+(?:\.\d+)?)", clause)
                if m:
                    try:
                        awards["costs"].append(float(m.group(1).replace(",", "")))
                    except ValueError:
                        pass
            elif "dismissed" in cl:
                clause_types["Costs & expenses dismissed"] += 1
            else:
                clause_types["Costs & expenses other"] += 1
        elif "struck out" in cl:
            clause_types["Struck out"] += 1
        elif "friendly settlement" in cl:
            clause_types["Friendly settlement"] += 1
        elif "inadmissible" in cl:
            clause_types["Inadmissible"] += 1

    return {
        "clause_types": clause_types,
        "awards": awards,
        "preliminary_objections": prelim,
    }


def normalize_section_key(raw_section: str) -> str:
    key = str(raw_section or "").strip().lower().replace("-", " ")
    aliases = {
        "header": "header",
        "introduction": "introduction",
        "procedure": "procedure",
        "circumstances": "circumstances",
        "subject matter": "subject_matter",
        "subject_matter": "subject_matter",
        "facts": "facts",
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


def is_press_release(case) -> bool:
    """Return True if this record is a press release, not a judgment.

    Press releases are a distinct document type that should be excluded from
    all judgment-related statistics (case counts, violation rates, article
    breakdowns, country rankings, etc.).  The check mirrors the logic used in
    search-app.js: document_type contains "press release" (case-insensitive).
    """
    doc_type = str(case.get("document_type") or "").lower()
    return "press release" in doc_type


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
    citations = normalize_citations(case.get("strasbourg_caselaw"))
    judges = normalize_list(case.get("chamber_composed_of"), split_text=False)
    conclusion = str(case.get("conclusion") or "").strip()
    conclusion_flags = parse_conclusion_flags(conclusion)
    outcome_primary = derive_outcome_bucket(violation, non_violation)
    paragraphs = []

    for para in case.get("paragraphs", []):
        text = str((para or {}).get("text", "")).strip()
        section = normalize_section_key((para or {}).get("section", "unknown"))
        if not text:
            continue
        paragraphs.append({
            "section": section,
            "text": text,
            "row_role": (para or {}).get("row_role"),
        })

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
        "outcome_bucket": outcome_primary,
        "outcome_primary": outcome_primary,
        "has_inadmissibility": conclusion_flags["has_inadmissibility"],
        "is_struck_out": conclusion_flags["is_struck_out"],
        "has_procedural_aspect": conclusion_flags["has_procedural_aspect"],
        "has_substantive_aspect": conclusion_flags["has_substantive_aspect"],
        "inadmissibility_grounds": extract_inadmissibility_grounds(conclusion),
        "keywords": keywords,
        "citations": citations,
        "judges": judges,
        "conclusion": conclusion,
        "has_strasbourg_caselaw": len(citations) > 0,
        "has_domestic_law": is_present(case.get("domestic_law")),
        "has_international_law": is_present(case.get("international_law")),
        "has_rules_of_court": is_present(case.get("rules_of_court")),
        "is_key_case": str(case.get("importance") or "").strip().lower() == "key cases",
    }


def select_input_file(root: Path):
    preferred = root / "echr_cases_20260217_103005.jsonl"
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
    article_case_counts = Counter()
    article_violation_case_counts = Counter()
    inadmissibility_ground_counts = Counter()
    state_case_counts = Counter()
    state_outcome_counts = defaultdict(Counter)
    state_violation_counts = Counter()
    article_state_counts = defaultdict(Counter)
    article_state_violation_counts = defaultdict(Counter)
    state_article_violation_counts = defaultdict(Counter)
    state_cases_by_year = defaultdict(Counter)
    outcomes_by_year = defaultdict(Counter)
    procedural_vs_substantive_by_year = defaultdict(Counter)
    precedent_to_cases = defaultdict(set)

    # KP Thesaurus analytics
    kpt_term_counts = Counter()
    kpt_cases_count = 0
    kpt_by_country = defaultdict(Counter)  # state -> kpt Counter
    kpt_by_year = defaultdict(Counter)  # year -> kpt Counter
    kpt_cooccurrence = Counter()  # (kpt_a, kpt_b) pairs

    # Conclusion/Outcome analytics
    conclusion_clause_counts = Counter()
    all_pecuniary_awards = []
    all_non_pecuniary_awards = []
    all_costs_awards = []
    prelim_obj_rejected = 0
    prelim_obj_accepted = 0
    prelim_obj_joined = 0
    cases_with_pecuniary_award = 0
    cases_with_non_pecuniary_award = 0
    cases_with_costs_award = 0
    just_satisfaction_by_year = defaultdict(lambda: {"count": 0, "total_eur": 0.0})
    conclusion_outcome_by_year = defaultdict(Counter)

    case_lengths = []
    parsed_dates = []
    unique_articles = set()

    total_paragraphs = 0
    press_release_count = 0
    violation_cases = 0
    non_violation_cases = 0
    key_cases = 0
    separate_opinion_cases = 0
    cases_with_strasbourg_caselaw = 0
    cases_with_domestic_law = 0
    cases_with_international_law = 0
    cases_with_rules_of_court = 0
    total_strasbourg_citations = 0
    inadmissible_cases = 0
    struck_out_cases = 0
    procedural_aspect_cases = 0
    substantive_aspect_cases = 0

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
        # Exclude press releases from all judgment-related statistics.
        # They are a different document type and should not inflate case counts,
        # violation rates, article breakdowns, country stats, or any other
        # metric that describes judicial outcomes.
        if is_press_release(case):
            press_release_count += 1
            continue

        normalized = normalize_case(case)
        case_id = str(case.get("case_id") or "").strip()
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
            outcomes_by_year[year_key][normalized["outcome_primary"]] += 1
            if normalized["has_procedural_aspect"]:
                procedural_vs_substantive_by_year[year_key]["procedural"] += 1
            if normalized["has_substantive_aspect"]:
                procedural_vs_substantive_by_year[year_key]["substantive"] += 1

        for state in normalized["states"]:
            country_counts[state] += 1
            state_case_counts[state] += 1
            state_outcome_counts[state][normalized["outcome_primary"]] += 1
            if normalized["violation"]:
                state_violation_counts[state] += 1
            if date_obj:
                state_cases_by_year[state][date_obj.strftime("%Y")] += 1

        case_articles = set()
        for article in normalized["articles"]:
            if article and not article.startswith("P") and len(article) < 10:
                article_counts[article] += 1
                unique_articles.add(article)
                case_articles.add(article)
        for article in case_articles:
            article_case_counts[article] += 1
            for state in normalized["states"]:
                article_state_counts[article][state] += 1

        for article in set(normalized["violation"]):
            for state in normalized["states"]:
                article_state_violation_counts[article][state] += 1
                state_article_violation_counts[state][article] += 1

        for article in set(normalized["violation"]):
            article_violation_counts[article] += 1
            article_violation_case_counts[article] += 1
        for article in set(normalized["non_violation"]):
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

        if normalized["has_inadmissibility"]:
            inadmissible_cases += 1
            for ground in normalized["inadmissibility_grounds"]:
                inadmissibility_ground_counts[ground] += 1

        if normalized["is_struck_out"]:
            struck_out_cases += 1

        if normalized["has_procedural_aspect"]:
            procedural_aspect_cases += 1

        if normalized["has_substantive_aspect"]:
            substantive_aspect_cases += 1

        total_strasbourg_citations += len(normalized["citations"])

        body = normalized["originating_body"]
        importance = normalized["importance"]
        outcome = normalized["outcome_primary"]
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
            if case_id:
                precedent_to_cases[citation].add(case_id)

        for judge in normalized["judges"]:
            judge_counts[judge] += 1

        for field in quality_fields:
            if is_present(case.get(field)):
                nonempty_field_counts[field] += 1

        # Parse conclusion clauses for outcome analytics
        parsed_conc = parse_conclusion_clauses(normalized["conclusion"])
        for ct, cnt in parsed_conc["clause_types"].items():
            conclusion_clause_counts[ct] += cnt
        conc_awards = parsed_conc["awards"]
        if conc_awards["pecuniary"]:
            cases_with_pecuniary_award += 1
            all_pecuniary_awards.extend(conc_awards["pecuniary"])
        if conc_awards["non_pecuniary"]:
            cases_with_non_pecuniary_award += 1
            all_non_pecuniary_awards.extend(conc_awards["non_pecuniary"])
        if conc_awards["costs"]:
            cases_with_costs_award += 1
            all_costs_awards.extend(conc_awards["costs"])
        pobj = parsed_conc["preliminary_objections"]
        prelim_obj_rejected += pobj["rejected"]
        prelim_obj_accepted += pobj["accepted"]
        prelim_obj_joined += pobj["joined_to_merits"]

        # Just satisfaction awards by year
        if date_obj:
            yr = date_obj.strftime("%Y")
            total_award_eur = sum(conc_awards["pecuniary"]) + sum(conc_awards["non_pecuniary"]) + sum(conc_awards["costs"])
            if total_award_eur > 0:
                just_satisfaction_by_year[yr]["count"] += 1
                just_satisfaction_by_year[yr]["total_eur"] += total_award_eur
            # Conclusion outcome categories by year
            has_v_clause = parsed_conc["clause_types"].get("Violation finding", 0) > 0
            has_nv_clause = parsed_conc["clause_types"].get("No violation finding", 0) > 0
            has_award = any(conc_awards[k] for k in conc_awards)
            has_inadm = parsed_conc["clause_types"].get("Inadmissible", 0) > 0
            if has_v_clause:
                conclusion_outcome_by_year[yr]["violation"] += 1
            if has_nv_clause:
                conclusion_outcome_by_year[yr]["no_violation"] += 1
            if has_award:
                conclusion_outcome_by_year[yr]["award_granted"] += 1
            if has_inadm:
                conclusion_outcome_by_year[yr]["inadmissible"] += 1

        # KP Thesaurus processing
        kpt_raw = str(case.get("hudoc_kpthesaurus") or "").strip()
        if kpt_raw:
            kpt_cases_count += 1
            kpt_ids = [k.strip() for k in kpt_raw.split(";") if k.strip()]
            for kid in kpt_ids:
                label = KPT_LABELS.get(kid, f"#{kid}")
                kpt_term_counts[label] += 1
                for state in normalized["states"]:
                    kpt_by_country[state][label] += 1
                if date_obj:
                    kpt_by_year[date_obj.strftime("%Y")][label] += 1
            # Co-occurrence pairs (top-level only, limit to first 8 terms)
            labels_list = [KPT_LABELS.get(k.strip(), f"#{k.strip()}") for k in kpt_ids[:8]]
            for i in range(len(labels_list)):
                for j in range(i + 1, len(labels_list)):
                    pair = tuple(sorted([labels_list[i], labels_list[j]]))
                    kpt_cooccurrence[pair] += 1

    sorted_lengths = sorted(case_lengths)
    # total_cases counts only judgments — press releases are excluded
    total_cases = len(cases) - press_release_count

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

    article_violation_rates = []
    for article, denominator in article_case_counts.items():
        if denominator <= 0:
            continue
        numerator = article_violation_case_counts.get(article, 0)
        rate = numerator / denominator
        article_violation_rates.append([article, round(rate, 4), numerator, denominator])
    article_violation_rates.sort(key=lambda row: (row[1], row[3], row[2]), reverse=True)

    state_outcomes = []
    for state, total in state_case_counts.items():
        if total < 5:
            continue
        counters = state_outcome_counts[state]
        v_only = counters.get("violation_only", 0)
        nv_only = counters.get("non_violation_only", 0)
        both = counters.get("both", 0)
        neither = counters.get("neither", 0)
        v_rate = (state_violation_counts.get(state, 0) / total * 100) if total else 0
        state_outcomes.append([state, total, v_only, nv_only, both, neither, round(v_rate, 2)])
    state_outcomes.sort(key=lambda row: (row[1], row[6]), reverse=True)

    precedent_to_citing_cases = [
        [citation, len(case_ids)]
        for citation, case_ids in precedent_to_cases.items()
        if case_ids
    ]
    precedent_to_citing_cases.sort(key=lambda row: (row[1], citation_counts.get(row[0], 0)), reverse=True)

    precedent_concentration = []
    cumulative_share = 0.0
    for citation, count in citation_counts.most_common(10):
        share = (count / total_strasbourg_citations * 100) if total_strasbourg_citations else 0
        cumulative_share += share
        precedent_concentration.append([citation, count, round(share, 2), round(cumulative_share, 2)])

    # Article × State cross-tabulation (top 15 articles, top 15 states each)
    top_articles_for_crosstab = [a for a, _ in article_counts.most_common(20)]
    article_by_state = {}
    for article in top_articles_for_crosstab:
        state_rows = []
        for state, count in article_state_counts[article].most_common(15):
            v_count = article_state_violation_counts.get(article, {}).get(state, 0)
            state_rows.append([state, count, v_count])
        if state_rows:
            article_by_state[article] = state_rows

    # Per-state comparison data (states with >= 3 cases)
    all_years = sorted(set(y for counts in state_cases_by_year.values() for y in counts))
    state_profiles = {}
    for state, total in state_case_counts.items():
        if total < 3:
            continue
        yearly = [state_cases_by_year[state].get(y, 0) for y in all_years]
        top_articles = state_article_violation_counts[state].most_common(10)
        counters = state_outcome_counts[state]
        state_profiles[state] = {
            "total": total,
            "violation_rate": round(state_violation_counts.get(state, 0) / total * 100, 1),
            "outcomes": {
                "violation_only": counters.get("violation_only", 0),
                "non_violation_only": counters.get("non_violation_only", 0),
                "both": counters.get("both", 0),
                "neither": counters.get("neither", 0),
            },
            "top_violated_articles": top_articles,
            "cases_by_year": yearly,
        }
    compare_data = {
        "years": all_years,
        "states": state_profiles,
    }

    field_completeness = {
        field: round((nonempty_field_counts[field] / total_cases), 4) if total_cases else 0
        for field in quality_fields
    }

    separate_opinion_share_by_body = []
    for body, total in separate_opinion_by_body_total.most_common(20):
        separate_cases = separate_opinion_by_body_cases.get(body, 0)
        share_pct = (separate_cases / total * 100) if total else 0
        separate_opinion_share_by_body.append([body, round(share_pct, 2), total, separate_cases])

    outcomes_by_year_series = []
    for year in sorted(outcomes_by_year.keys()):
        counts = outcomes_by_year[year]
        outcomes_by_year_series.append(
            [
                year,
                counts.get("violation_only", 0),
                counts.get("non_violation_only", 0),
                counts.get("both", 0),
                counts.get("neither", 0),
            ]
        )

    procedural_vs_substantive_series = []
    for year in sorted(procedural_vs_substantive_by_year.keys()):
        counts = procedural_vs_substantive_by_year[year]
        procedural_vs_substantive_series.append(
            [year, counts.get("procedural", 0), counts.get("substantive", 0)]
        )

    importance_breakdown = [[level, count] for level, count in importance_counts.most_common()]
    outcome_breakdown = [
        [OUTCOME_LABELS.get(key, key), outcome_counts.get(key, 0)]
        for key in OUTCOME_KEYS
    ]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_file": source_file,
        "schema_version": SCHEMA_VERSION,
        "parser_version": PARSER_VERSION,
        "summary": {
            "total_cases": total_cases,
            "total_press_releases": press_release_count,
            "input_record_count": total_cases + press_release_count,
            "schema_version": SCHEMA_VERSION,
            "parser_version": PARSER_VERSION,
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
            "inadmissible_cases": inadmissible_cases,
            "struck_out_cases": struck_out_cases,
            "procedural_aspect_cases": procedural_aspect_cases,
            "substantive_aspect_cases": substantive_aspect_cases,
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
            "outcomes_by_year": outcomes_by_year_series,
            "procedural_vs_substantive_by_year": procedural_vs_substantive_series,
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
            "article_violation_rates_top": article_violation_rates[:20],
            "state_outcomes_top": state_outcomes[:30],
            "inadmissibility_grounds_top": inadmissibility_ground_counts.most_common(20),
            "precedent_concentration_top": precedent_concentration,
            "precedent_to_citing_cases_top": precedent_to_citing_cases[:20],
            "outcomes": outcome_breakdown,
        },
        "cross_tabs": {
            "article_by_state": article_by_state,
            "compare": compare_data,
        },
        "quality": {
            "field_completeness": field_completeness,
        },
        "thesaurus_analytics": {
            "cases_with_thesaurus": kpt_cases_count,
            "unique_terms": len(kpt_term_counts),
            "top_terms": kpt_term_counts.most_common(30),
            "top_cooccurrences": [
                [list(pair), count]
                for pair, count in kpt_cooccurrence.most_common(15)
            ],
            "top_terms_by_country": {
                state: kpt_by_country[state].most_common(10)
                for state in sorted(
                    kpt_by_country.keys(),
                    key=lambda s: state_case_counts.get(s, 0),
                    reverse=True,
                )[:15]
            },
            "terms_by_year": [
                [yr] + [kpt_by_year[yr].get(t, 0) for t in [
                    KPT_LABELS.get("445", "#445"),
                    KPT_LABELS.get("350", "#350"),
                    KPT_LABELS.get("451", "#451"),
                    KPT_LABELS.get("369", "#369"),
                    KPT_LABELS.get("449", "#449"),
                ]]
                for yr in sorted(kpt_by_year.keys())
            ],
            "terms_by_year_labels": [
                KPT_LABELS.get("445", "#445"),
                KPT_LABELS.get("350", "#350"),
                KPT_LABELS.get("451", "#451"),
                KPT_LABELS.get("369", "#369"),
                KPT_LABELS.get("449", "#449"),
            ],
        },
        "conclusion_analytics": {
            "clause_breakdown": conclusion_clause_counts.most_common(20),
            "preliminary_objections": {
                "rejected": prelim_obj_rejected,
                "accepted": prelim_obj_accepted,
                "joined_to_merits": prelim_obj_joined,
            },
            "just_satisfaction": {
                "cases_with_pecuniary_award": cases_with_pecuniary_award,
                "cases_with_non_pecuniary_award": cases_with_non_pecuniary_award,
                "cases_with_costs_award": cases_with_costs_award,
                "pecuniary_stats": _award_stats(all_pecuniary_awards),
                "non_pecuniary_stats": _award_stats(all_non_pecuniary_awards),
                "costs_stats": _award_stats(all_costs_awards),
                "by_year": [
                    [yr, just_satisfaction_by_year[yr]["count"],
                     round(just_satisfaction_by_year[yr]["total_eur"], 2)]
                    for yr in sorted(just_satisfaction_by_year.keys())
                ],
            },
            "conclusion_outcomes_by_year": [
                [yr,
                 conclusion_outcome_by_year[yr].get("violation", 0),
                 conclusion_outcome_by_year[yr].get("no_violation", 0),
                 conclusion_outcome_by_year[yr].get("award_granted", 0),
                 conclusion_outcome_by_year[yr].get("inadmissible", 0)]
                for yr in sorted(conclusion_outcome_by_year.keys())
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

    # Skip rebuild if existing stats.json was built from a larger dataset
    if output_path.exists():
        try:
            existing = json.loads(output_path.read_text(encoding="utf-8"))
            existing_count = existing.get("summary", {}).get("total_cases", 0)
            if existing_count > len(cases):
                print(f"Existing {output_path.name} has {existing_count} cases (input has {len(cases)}); keeping pre-built version.")
                return
        except (json.JSONDecodeError, KeyError):
            pass

    payload = build_payload(cases, input_path.name)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Wrote dashboard data: {output_path}")
    print(f"Judgments: {payload['summary']['total_cases']}, press releases excluded: {payload['summary']['total_press_releases']}, paragraphs: {payload['summary']['total_paragraphs']}")

    if export_data_path:
        export_data_path.parent.mkdir(parents=True, exist_ok=True)
        if input_path.resolve() == export_data_path.resolve():
            print(f"Input dataset already in web app location: {export_data_path}")
        else:
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
