#!/usr/bin/env python3
"""Build judgment-only statistics from a verified catalog and text inventories.

Export mode uses only stdlib and a read-only transaction, so it can be piped
into the production container without installing or writing anything there.
Build mode never updates a database, downloads sources, or deploys the result.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys


def export_inventory(db):
    with sqlite3.connect(f"file:{Path(db).resolve()}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN")
        cases = {r["case_id"]: dict(r) for r in conn.execute("SELECT * FROM cases")}
        sections = defaultdict(Counter)
        roles = defaultdict(Counter)
        for row in conn.execute("""SELECT case_id, section, row_role, count(*) AS n
            FROM paragraphs WHERE length(trim(COALESCE(text,''))) > 0
            GROUP BY case_id, section, row_role"""):
            sections[row["case_id"]][row["section"] or "Unknown"] += row["n"]
            roles[row["case_id"]][row["row_role"] or "unknown"] += row["n"]
        for cid, case in cases.items():
            case["paragraph_section_counts"] = dict(sections[cid])
            case["paragraph_role_counts"] = dict(roles[cid])
        return {"exported_at": datetime.now(timezone.utc).isoformat(),
                "source": "production SQLite read-only transaction", "cases": cases}


def catalog_case(row):
    from build_pages_dashboard import COUNTRY_NAMES
    branches = {"GRANDCHAMBER": "Grand Chamber", "CHAMBER": "Chamber", "COMMITTEE": "Committee"}
    states = [COUNTRY_NAMES.get(code, code) for code in row["respondent"].split(";") if code]
    return {"case_id": row["itemid"], "title": row["docname"], "case_no": row["appno"],
            "judgment_date": row.get("judgementdate", "")[:10] or row["kpdate"][:10], "respondent_state": "; ".join(states),
            "document_type": f"Judgment ({branches[row['doctypebranch']]})",
            "originating_body": branches[row["doctypebranch"]],
            "importance": {"1": "Key cases", "2": "1", "3": "2", "4": "3"}.get(row["importance"], "Unspecified"),
            "ecli": row.get("ecli"), "hudoc_url": "https://hudoc.echr.coe.int/eng?i=" + row["itemid"],
            "article_no": row.get("article", ""), "violation": row.get("violation", ""),
            "non-violation": row.get("nonviolation", ""), "conclusion": row.get("conclusion", ""),
            "hudoc_kpthesaurus": row.get("kpthesaurus", ""),
            "strasbourg_caselaw": [s.strip() for s in row.get("scl", "").split(";") if s.strip()],
            "rules_of_court": row.get("rulesofcourt", ""),
            "paragraph_section_counts": {}, "paragraph_role_counts": {}}


def attach_bundle(case, job, directory):
    relative = Path(job["parsed_file"])
    path = (directory / relative).resolve()
    if not path.is_relative_to(directory.resolve()):
        raise ValueError("Parsed bundle is outside the download directory")
    bundle = json.loads(path.read_text())
    if bundle["case_id"] != case["case_id"] or bundle.get("needs_manual_review"):
        raise ValueError("Bundle identity/review check failed")
    meta, source = bundle["official_metadata"], bundle["source_metadata"]
    if meta["itemid"] != case["case_id"] or source["itemid"] != job["source_case_id"]:
        raise ValueError("Bundle source identity does not match the queue")
    if meta.get("ecli") != case.get("ecli") or bundle.get("source_sha256") != job.get("source_sha256"):
        raise ValueError("Bundle provenance does not match the catalog and queue")
    if source.get("languageisocode") != job["source_language"] or bundle.get("source_language") != job["source_language"]:
        raise ValueError("Bundle source-language provenance does not match")
    if job["source_language"] == "FRE" and (
        not meta.get("ecli") or meta["ecli"] != source.get("ecli")
        or meta["kpdate"] != source["kpdate"]
        or meta["doctypebranch"] != source["doctypebranch"]
    ):
        raise ValueError("French fallback is not the same verified judgment")
    sections, roles = Counter(), Counter()
    for para in bundle["paragraphs"]:
        if str(para.get("text") or "").strip():
            sections[para.get("section") or "Unknown"] += 1
            roles[para.get("row_role") or "unknown"] += 1
    if not sections or sum(sections.values()) != job["paragraph_count"]:
        raise ValueError("Parsed paragraph count differs from the queue")
    case.update(paragraph_section_counts=dict(sections), paragraph_role_counts=dict(roles))


def build_statistics(catalog, inventory, directory):
    from build_pages_dashboard import build_payload, parse_date, percentile
    from hudoc_catalog import eligible, fingerprint, validate_catalog
    validate_catalog(catalog, ("ENG", "FRE"), complete_history=True)
    rows = [r for r in catalog["documents"] if eligible(r) and r["languageisocode"] == "ENG"]
    if not rows:
        raise ValueError("Cannot build statistics for an empty catalog")
    with sqlite3.connect(f"file:{directory.resolve() / 'downloads.sqlite'}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        jobs = {r["case_id"]: dict(r) for r in conn.execute("SELECT * FROM jobs WHERE active=1")}
    cases, language_counts, origin_counts = [], Counter(), Counter()
    chamber_year, language_year = defaultdict(Counter), defaultdict(Counter)
    roles = Counter()
    for row in rows:
        case = catalog_case(row)
        cid, language, origin = row["itemid"], "Unknown", "Unavailable"
        stored = inventory["cases"].get(cid)
        # Use the curated deployed text when present; never sum two versions.
        if stored and sum(stored["paragraph_section_counts"].values()):
            case["paragraph_section_counts"] = stored["paragraph_section_counts"]
            case["paragraph_role_counts"] = stored["paragraph_role_counts"]
            language = stored.get("source_language") or "Unknown"
            origin = "Production inventory"
        elif cid in jobs and jobs[cid]["status"] == "ready":
            attach_bundle(case, jobs[cid], directory)
            language = jobs[cid]["source_language"]
            origin = "Local source bundle"
        if language not in {"ENG", "FRE"}:
            language = "Unknown"
        if origin != "Unavailable":
            language_counts[language] += 1
            roles.update(case["paragraph_role_counts"])
        origin_counts[origin] += 1
        parsed_date = parse_date(case["judgment_date"])
        if not parsed_date:
            raise ValueError(f"Invalid judgment date: {cid}")
        year = str(parsed_date.year)
        chamber_year[year][row["doctypebranch"]] += 1
        language_year[year][language if origin != "Unavailable" else "Unavailable"] += 1
        cases.append(case)
    payload = build_payload(cases, "Verified HUDOC catalog + production text inventory + local ENG/FRE bundles")
    lengths = sorted(sum(c["paragraph_section_counts"].values()) for c in cases if c["paragraph_section_counts"])
    payload["summary"].update(
        cases_with_text=len(lengths),
        avg_paragraphs_per_case=sum(lengths) / len(lengths) if lengths else 0,
        median_paragraphs_per_case=percentile(lengths, .5),
        p90_paragraphs_per_case=percentile(lengths, .9),
        min_paragraphs_per_case=min(lengths, default=0), max_paragraphs_per_case=max(lengths, default=0))
    payload["scope"] = {
        "document_type": "Judgments only", "judicial_collections": ["Grand Chamber", "Chamber", "Committee"],
        "catalog_language": "ENG", "text_languages": ["ENG", "FRE"],
        "unit": "HUDOC judgment record, not an application or applicant",
        "since": catalog["manifest"]["since"], "cutoff": catalog["manifest"]["to"],
        "catalog_verified_at": catalog["manifest"]["generated_at"],
        "catalog_sha256": fingerprint(r["itemid"] for r in rows),
        "catalog_content_sha256": catalog["manifest"].get("content_sha256"),
        "translation_title_warnings": [r["itemid"] for r in rows if "translation]" in r["docname"].lower()],
        "note": "English-flagged metadata; English text where available and verified French fallback. Language versions are not counted twice. Not a certified bilingual ECLI union.",
        "deployment": "Staged snapshot: local source bundles are not yet available in live Search.",
    }
    payload["text_coverage"] = {
        "by_language": dict(language_counts), "by_origin": dict(origin_counts),
        "inventory_exported_at": inventory["exported_at"], "paragraph_roles": dict(roles),
        "note": "Production text language is unknown unless explicitly recorded. Counts include nonempty parser/index rows, not only numbered paragraphs. Local French section labels still require source-exact QA."
    }
    payload["series"]["chambers_by_year"] = [[y] + [chamber_year[y][k] for k in ["GRANDCHAMBER", "CHAMBER", "COMMITTEE"]] for y in sorted(chamber_year)]
    payload["series"]["text_languages_by_year"] = [[y] + [language_year[y][k] for k in ["ENG", "FRE", "Unknown", "Unavailable"]] for y in sorted(language_year)]
    payload["quality"]["field_completeness"].update(
        article_no=sum(bool(c["article_no"]) for c in cases) / len(cases),
        hudoc_kpthesaurus=sum(bool(c["hudoc_kpthesaurus"]) for c in cases) / len(cases))
    fields = ["respondent_state", "ecli", "article_no", "conclusion", "originating_body",
              "importance", "hudoc_kpthesaurus", "strasbourg_caselaw", "rules_of_court"]
    payload["quality"]["field_counts"] = {key: sum(bool(c.get(key)) for c in cases) for key in fields}
    payload["quality"]["field_completeness"].update(
        {key: count / len(cases) for key, count in payload["quality"]["field_counts"].items()})
    if payload["summary"]["total_cases"] != len(rows) or sum(n for _, n in payload["series"]["cases_by_year"]) != len(rows):
        raise ValueError("Statistics do not match the audited catalog")
    return payload


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--export-inventory", metavar="DB")
    ap.add_argument("--catalog", type=Path)
    ap.add_argument("--inventory", type=Path)
    ap.add_argument("--downloads", type=Path)
    ap.add_argument("--output", type=Path)
    ap.add_argument("--citations-output", type=Path)
    ap.add_argument("--citations-audit", type=Path)
    args = ap.parse_args()
    if args.export_inventory:
        json.dump(export_inventory(args.export_inventory), sys.stdout, ensure_ascii=True)
        return
    if not all([args.catalog, args.inventory, args.downloads, args.output]):
        ap.error("build requires --catalog --inventory --downloads --output")
    if bool(args.citations_output) != bool(args.citations_audit):
        ap.error("--citations-output and --citations-audit must be supplied together")
    catalog = json.loads(args.catalog.read_text())
    payload = build_statistics(catalog, json.loads(args.inventory.read_text()), args.downloads)
    if args.citations_output:
        from build_judgment_citations import build_graph, write_audit
        from hudoc_catalog import write_json
        snapshot, index, observations, edges = build_graph(catalog)
        write_audit(args.citations_audit, index, observations, edges)
        write_json(args.citations_output, snapshot)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n")
    temporary.replace(args.output)
    print(json.dumps(payload["summary"], indent=2))


if __name__ == "__main__":
    main()
