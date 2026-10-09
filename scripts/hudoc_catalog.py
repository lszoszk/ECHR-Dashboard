#!/usr/bin/env python3
"""Harvest a count-checked official judgment catalog and reconcile production IDs.

No production writes. Each date partition must contain exactly resultcount
distinct IDs before it can be accepted. The raw catalog retains language versions;
canonical judgments prefer English, then French, using ECLI only for grouping.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import ssl
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

URL = "https://hudoc.echr.coe.int/app/query/results"
FIELDS = (
    "itemid,docname,appno,kpdate,judgementdate,ecli,respondent,importance,"
    "conclusion,article,violation,nonviolation,kpthesaurus,scl,rulesofcourt,"
    "originatingbody,doctypebranch,documentcollectionid2,languageisocode,doctype"
)
BODIES = {"CHAMBER", "GRANDCHAMBER", "COMMITTEE"}


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def http_get(params, attempts=4):
    request = urllib.request.Request(URL + "?" + urllib.parse.urlencode(params), headers={
        "User-Agent": "Mozilla/5.0 HUDOC-Researcher-Catalog/1.0",
        "Referer": "https://hudoc.echr.coe.int/",
    })
    try:
        import certifi
        context = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        context = ssl.create_default_context()
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=60, context=context) as response:
                result = json.load(response)
            if not isinstance(result.get("resultcount"), int) or not isinstance(result.get("results"), list):
                raise ValueError("HUDOC returned an invalid catalog response")
            return result
        except Exception:
            if attempt == attempts - 1:
                raise
            time.sleep(2 ** attempt)


def query_for(start, end, language):
    return (
        'contentsitename:ECHR AND (NOT (doctype=PR OR doctype=HFCOMOLD OR doctype=HECOMOLD)) '
        'AND ((documentcollectionid="GRANDCHAMBER") OR '
        '(documentcollectionid="CHAMBER") OR (documentcollectionid="COMMITTEE")) '
        f'AND languageisocode:"{language}" '
        f'AND kpdate>="{start}T00:00:00.0Z" '
        f'AND kpdate<="{end}T23:59:59.0Z"'
    )


def fetch_partition(start, end, language, fetch=http_get, delay=0.15):
    query = query_for(start, end, language)
    params = {"query": query, "select": FIELDS, "sort": "itemid Ascending", "start": 0, "length": 500}
    first = fetch(params)
    total = first["resultcount"]
    # HUDOC limits a single search to 10,000 results. Split before approaching it.
    if total >= 9000:
        lo, hi = date.fromisoformat(start), date.fromisoformat(end)
        if lo == hi:
            raise ValueError(f"Too many records on {start}; cannot certify completeness")
        mid = lo + (hi - lo) // 2
        left = fetch_partition(start, mid.isoformat(), language, fetch, delay)
        right = fetch_partition((mid + timedelta(days=1)).isoformat(), end, language, fetch, delay)
        if len(left) + len(right) != total:
            raise ValueError("HUDOC count changed while splitting a partition; retry")
        return left + right
    rows = {}
    page = first
    offset = 0
    while True:
        if page["resultcount"] != total:
            raise ValueError(f"HUDOC changed during pagination of {language} {start}..{end}; retry")
        batch = page["results"]
        expected = min(500, total - offset)
        if len(batch) != expected:
            raise ValueError(f"Truncated HUDOC page at offset {offset}: {len(batch)} != {expected}")
        for result in batch:
            cols = result["columns"]
            itemid = cols.get("itemid")
            if not itemid or itemid in rows:
                raise ValueError(f"Missing/duplicate HUDOC ID at offset {offset}: {itemid}")
            if cols.get("languageisocode") != language:
                raise ValueError(f"HUDOC language filter failed for {itemid}")
            if not start <= cols.get("kpdate", "")[:10] <= end:
                raise ValueError(f"HUDOC date filter failed for {itemid}")
            rows[itemid] = cols
        offset += len(batch)
        if offset >= total:
            break
        if delay:
            time.sleep(delay)
        page = fetch(dict(params, start=offset))
    verification = fetch(dict(params, length=1))
    if verification["resultcount"] != len(rows):
        raise ValueError("HUDOC count changed after pagination; retry partition")
    return list(rows.values())


def eligible(row):
    return (
        row.get("itemid", "").startswith("001-")
        and row.get("doctypebranch") in BODIES
        and row.get("doctype") in {"HEJUD", "HFJUD"}
        and "JUDGMENTS" in row.get("documentcollectionid2", "").split(";")
        and row.get("languageisocode") in {"ENG", "FRE"}
    )


def canonical_rows(rows):
    groups = defaultdict(list)
    for row in rows:
        if eligible(row):
            groups[row.get("ecli") or row["itemid"]].append(row)
    chosen, ambiguous = [], []
    for key, members in sorted(groups.items()):
        languages = Counter(r["languageisocode"] for r in members)
        if any(n > 1 for n in languages.values()):
            ambiguous.append({"key": key, "ids": sorted(r["itemid"] for r in members)})
            # Do not silently collapse ambiguous records, even if totals look better.
            chosen.extend(members)
        else:
            chosen.append(min(members, key=lambda r: (
                "translation]" in r.get("docname", "").lower(),
                r["languageisocode"] != "ENG", r["itemid"],
            )))
    return chosen, ambiguous


def fingerprint(ids):
    return hashlib.sha256("\n".join(sorted(ids)).encode()).hexdigest()


def content_fingerprint(rows):
    payload = json.dumps(sorted(rows, key=lambda r: r["itemid"]), ensure_ascii=False,
                         sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def validate_catalog(catalog, required_languages=(), complete_history=False):
    manifest, rows = catalog["manifest"], catalog["documents"]
    ids = [r["itemid"] for r in rows]
    if (not manifest.get("count_checked") or manifest.get("resumed")
            or len(ids) != len(set(ids)) or manifest["sha256"] != fingerprint(ids)
            or manifest["raw_count"] != len(rows)):
        raise ValueError("A fresh, complete, checksum-verified catalog is required")
    if manifest.get("content_sha256") and manifest["content_sha256"] != content_fingerprint(rows):
        raise ValueError("Catalog metadata checksum does not match")
    start, end = date.fromisoformat(manifest["since"]), date.fromisoformat(manifest["to"])
    if start > end or (complete_history and start != date(1959, 1, 1)):
        raise ValueError("A partial date window cannot replace the production catalog")
    languages = manifest["languages"]
    if len(languages) != len(set(languages)) or not set(required_languages).issubset(languages):
        raise ValueError("Catalog does not contain the requested languages")
    expected_parts = {(lang, max(start, date(y, 1, 1)).isoformat(),
                       min(end, date(y, 12, 31)).isoformat())
                      for lang in languages for y in range(start.year, end.year + 1)}
    parts = manifest["partitions"]
    keys = [(p["language"], p["since"], p["to"]) for p in parts]
    if len(keys) != len(set(keys)) or set(keys) != expected_parts:
        raise ValueError("Catalog partitions do not cover the declared history")
    counts = Counter((r["languageisocode"], r["kpdate"][:4]) for r in rows)
    for row in rows:
        if row["languageisocode"] not in languages or not manifest["since"] <= row["kpdate"][:10] <= manifest["to"]:
            raise ValueError("Catalog contains records outside its declared scope")
    for part in parts:
        if counts[part["language"], part["since"][:4]] != part["count"]:
            raise ValueError("Catalog partition count does not match its documents")
    if "final_language_counts" in manifest:
        observed = Counter(r["languageisocode"] for r in rows if eligible(r))
        if any(observed[lang] != manifest["final_language_counts"].get(lang) for lang in languages):
            raise ValueError("Catalog does not match the final official judgment count")


def reconcile(catalog, production, scope="ENG"):
    raw = catalog["documents"]
    canonical, ambiguous = canonical_rows(raw)
    expected_rows = [r for r in raw if eligible(r) and r["languageisocode"] == "ENG"] if scope == "ENG" else canonical
    expected = {r["itemid"]: r for r in expected_rows}
    actual = {r["case_id"]: r for r in production}
    if len(actual) != len(production):
        raise ValueError("Production export has duplicate IDs")
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    lookup = {r["itemid"]: r for r in raw}
    metadata_mismatches = []
    for cid in set(expected) & set(actual):
        if not actual[cid].get("document_type", "").startswith("Judgment"):
            metadata_mismatches.append({"case_id": cid, "stored_type": actual[cid].get("document_type"), "official_type": expected[cid]["doctype"]})
    counts = lambda rows: dict(sorted(Counter(r.get("kpdate", "")[:4] for r in rows).items()))
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": scope,
        "catalog_manifest": catalog["manifest"],
        "official_documents_by_language": dict(Counter(r.get("languageisocode") for r in raw if eligible(r))),
        "translation_title_warnings": [r["itemid"] for r in raw if eligible(r) and "translation]" in r.get("docname", "").lower()],
        "missing_ecli": [r["itemid"] for r in raw if eligible(r) and not r.get("ecli")],
        "official_canonical_judgments": len(canonical),
        "ambiguous_ecli_groups": ambiguous,
        "expected_count": len(expected),
        "production_count": len(actual),
        "matching_ids": len(set(expected) & set(actual)),
        "missing_count": len(missing),
        "extra_count": len(extra),
        "identity_resolved": scope == "ENG" or (not ambiguous and all(r.get("ecli") for r in canonical)),
        "id_sets_equal": not missing and not extra and (scope == "ENG" or (not ambiguous and all(r.get("ecli") for r in canonical))),
        "expected_sha256": fingerprint(expected),
        "production_sha256": fingerprint(actual),
        "expected_by_year": counts(expected.values()),
        "missing_by_year": counts(expected[cid] for cid in missing),
        "metadata_mismatches": metadata_mismatches,
        "missing": [expected[cid] for cid in missing],
        "extra": [{"production": actual[cid], "official": lookup.get(cid)} for cid in extra],
    }


def harvest(args):
    end = date.fromisoformat(args.to)
    start = date.fromisoformat(args.since)
    documents = []
    partitions = []
    for language in args.languages:
        for year in range(start.year, end.year + 1):
            lo = max(start, date(year, 1, 1)).isoformat()
            hi = min(end, date(year, 12, 31)).isoformat()
            cache = Path(args.work) / f"{language}-{lo}-{hi}.json"
            if args.resume and cache.exists():
                part = json.loads(cache.read_text())
                rows = part["documents"]
                if part.get("query") != query_for(lo, hi, language) or part["sha256"] != fingerprint(r["itemid"] for r in rows) or len(rows) != part["count"]:
                    raise ValueError(f"Invalid partition cache: {cache}")
            else:
                rows = fetch_partition(lo, hi, language)
                write_json(cache, {"query": query_for(lo, hi, language), "count": len(rows), "sha256": fingerprint(r["itemid"] for r in rows), "documents": rows})
            documents.extend(rows)
            partitions.append({"language": language, "since": lo, "to": hi, "count": len(rows)})
            print(f"{language} {year}: {len(rows):,} records", flush=True)
    ids = [r["itemid"] for r in documents]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate IDs across date/language partitions")
    final_counts = {}
    observed = Counter(r["languageisocode"] for r in documents if eligible(r))
    for language in args.languages:
        final_counts[language] = http_get({"query": query_for(args.since, args.to, language),
                                           "select": "itemid", "sort": "itemid Ascending",
                                           "start": 0, "length": 1})["resultcount"]
        if observed[language] != final_counts[language]:
            raise ValueError("Final official count differs from harvested judgments; rerun without --resume")
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "since": args.since, "to": args.to, "languages": args.languages,
        "count_checked": True, "resumed": args.resume, "partitions": partitions,
        "raw_count": len(documents), "sha256": fingerprint(ids),
        "content_sha256": content_fingerprint(documents), "final_language_counts": final_counts,
    }
    write_json(args.out, {"manifest": manifest, "documents": sorted(documents, key=lambda r: r["itemid"])})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    h = commands.add_parser("harvest")
    h.add_argument("--since", default="1959-01-01")
    h.add_argument("--to", default=date.today().isoformat())
    h.add_argument("--languages", nargs="+", choices=["ENG", "FRE"], default=["ENG", "FRE"])
    h.add_argument("--work", default="output/hudoc-reconciliation/partitions")
    h.add_argument("--out", default="output/hudoc-reconciliation/catalog.json")
    h.add_argument("--resume", action="store_true")
    r = commands.add_parser("compare")
    r.add_argument("--catalog", required=True)
    r.add_argument("--production", required=True)
    r.add_argument("--scope", choices=["ENG", "ENG-FRE"], default="ENG")
    r.add_argument("--out", required=True)
    args = parser.parse_args()
    if args.command == "harvest":
        harvest(args)
    else:
        catalog = json.loads(Path(args.catalog).read_text())
        validate_catalog(catalog)
        production = [json.loads(line) for line in Path(args.production).read_text().splitlines() if line.strip()]
        report = reconcile(catalog, production, args.scope)
        write_json(args.out, report)
        print(json.dumps({k: report[k] for k in ("scope", "expected_count", "production_count", "matching_ids", "missing_count", "extra_count", "id_sets_equal")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
