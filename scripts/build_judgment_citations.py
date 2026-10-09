#!/usr/bin/env python3
"""Resolve bilingual HUDOC citation metadata without changing production data."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import unicodedata

from hudoc_catalog import eligible, fingerprint, validate_catalog, write_json

VERSION = "judgment-citations-v1"
APPNO = re.compile(r"(?<![\d/])(\d{1,7})/(\d{4}|\d{2})(?![\d/])")
HUDOC_ID = re.compile(r"\b(?:001|002|003)-\d+\b")
ECLI = re.compile(r"\bECLI:CE:ECHR:\d{4}:[A-Z0-9]+\b", re.I)
MONTHS = {
    "january": 1, "janvier": 1, "february": 2, "fevrier": 2,
    "march": 3, "mars": 3, "april": 4, "avril": 4, "may": 5, "mai": 5,
    "june": 6, "juin": 6, "july": 7, "juillet": 7, "august": 8, "aout": 8,
    "september": 9, "septembre": 9, "october": 10, "octobre": 10,
    "november": 11, "novembre": 11, "december": 12, "decembre": 12,
}


def ascii_text(value):
    value = str(value or "").lower().replace("\u0142", "l")
    return "".join(c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c))


def applications(value):
    return {f"{int(n)}/{int(y) % 100:02d}" for n, y in APPNO.findall(str(value or ""))}


def stage(value):
    text = ascii_text(value)
    if re.search(r"just satisfaction|satisfaction equitable|article\s*41", text):
        return "just_satisfaction"
    if re.search(r"\brevision\b", text):
        return "revision"
    if re.search(r"\binterpretation\b", text):
        return "interpretation"
    return None


def title_key(value):
    text = ascii_text(value)
    text = re.sub(r"^(?:case of|affaire|arrets?|judgment in the case of)\s+", "", text)
    text = re.sub(r"\([^)]*(?:just satisfaction|satisfaction equitable|article\s*41|revision|interpretation)[^)]*\)", "", text)
    text = re.sub(r"\[[^]]*\]", "", text)
    text = re.sub(r"\s+(?:v\.|c\.)\s+", " versus ", text)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def reference_title(value):
    text = ascii_text(value)
    text = re.split(r"\s*\[GC\]|,\s*(?:nos?\.?\s*\d|n[\u00b0\u00ba]|\u00a7|ECHR\b|CEDH\b|Series A\b|serie A\b|Reports\b|Recueil\b|(?:judgment|decision) of\b|\d{1,2}\s+[a-z]|\d{1,2}[./]\d{1,2}[./]\d{4})|,?\s+(?:judgment|decision|arret)\s+(?:of|du)\b|\s+du\s+\d{1,2}(?:er)?\s+[a-z]+\s+\d{4}", text, maxsplit=1, flags=re.I)[0]
    return title_key(text)


def reference_dates(value):
    text = ascii_text(value)
    result = set()
    for day, month, year in re.findall(r"\b(\d{1,2})(?:er)?\s+([a-z]+)\s+(\d{4})\b", text):
        if month in MONTHS:
            try:
                result.add(date(int(year), MONTHS[month], int(day)).isoformat())
            except ValueError:
                pass
    for year, month, day in re.findall(r"\b(\d{4})-(\d{2})-(\d{2})\b", text):
        try:
            result.add(date(int(year), int(month), int(day)).isoformat())
        except ValueError:
            pass
    for day, month, year in re.findall(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b", text):
        try:
            result.add(date(int(year), int(month), int(day)).isoformat())
        except ValueError:
            pass
    return result


def excluded_type(value):
    text = ascii_text(value)
    return bool(re.search(r"\((?:dec\.?|decision|decisions)\)|\b(?:commission decision|commission report|advisory opinion|avis consultatif|decision du|decision de la commission)\b|ECLI:CE:ECHR:\d{4}:\d{4}DEC", text, re.I))


class JudgmentIndex:
    def __init__(self, rows):
        self.nodes = {}
        self.aliases = {}
        self.eclis = defaultdict(set)
        self.appnos = defaultdict(set)
        self.agreed = {}
        self.names = defaultdict(set)
        self.issues = []
        self.outside_ids = {r["itemid"] for r in rows if not eligible(r)}
        self.review_ids = set()
        groups = defaultdict(list)
        for row in rows:
            if eligible(row):
                groups[(row.get("ecli") or "").upper() or "HUDOC:" + row["itemid"]].append(row)
        for key, members in sorted(groups.items()):
            eng = [r for r in members if r["languageisocode"] == "ENG"]
            language_counts = Counter(r["languageisocode"] for r in members)
            compatible = len({(r["kpdate"][:10], r["doctypebranch"]) for r in members}) == 1
            if len(eng) != 1 or not compatible or any(n > 1 for n in language_counts.values()):
                reason = "unpaired_french_identity" if not eng else "conflicting_identity"
                self.issues.append({"reason": reason, "key": key, "ids": sorted(r["itemid"] for r in members)})
                self.review_ids.update(r["itemid"] for r in members)
                continue
            preferred = eng[0]
            when = date.fromisoformat(preferred["kpdate"][:10]).isoformat()
            node = {
                "judgment_id": key, "case_id": preferred["itemid"], "ecli": preferred.get("ecli") or None,
                "title": re.sub(r"^CASE OF\s+", "", str(preferred.get("docname") or preferred["itemid"]), flags=re.I).strip(),
                "date": when, "collection": preferred["doctypebranch"],
                "hudoc_url": "https://hudoc.echr.coe.int/eng?i=" + preferred["itemid"],
                "languages": sorted(language_counts), "versions": members,
            }
            self.nodes[key] = node
            if not preferred.get("ecli"):
                self.issues.append({"reason": "missing_ecli_unpaired", "key": key, "ids": [preferred["itemid"]]})
            app_sets = {tuple(sorted(applications(r.get("appno")))) for r in members}
            if len(app_sets) > 1:
                self.issues.append({"reason": "application_metadata_difference", "key": key,
                                    "ids": sorted(r["itemid"] for r in members)})
            # Disagreeing metadata is retained for audit, but extra application
            # numbers from only one translation must not resolve a citation.
            agreed_appnos = set.intersection(*(applications(r.get("appno")) for r in members))
            self.agreed[key] = agreed_appnos
            for appno in agreed_appnos:
                self.appnos[appno].add(key)
            for row in members:
                self.aliases[row["itemid"]] = key
                if row.get("ecli"):
                    self.eclis[row["ecli"].upper()].add(key)
                self.names[title_key(row["docname"])].add(key)

    def resolve(self, raw, citing_id):
        if excluded_type(raw):
            return {"status": "excluded_document_type", "method": "explicit_non_judgment", "candidates": []}
        ids, eclis = set(HUDOC_ID.findall(raw)), {e.upper() for e in ECLI.findall(raw)}
        evidence_sets = []
        for value in sorted(ids):
            if value in self.review_ids:
                return {"status": "identity_review", "method": "hudoc_id", "candidates": []}
            if value in self.outside_ids:
                return {"status": "excluded_document_type", "method": "hudoc_id", "candidates": []}
            evidence_sets.append({self.aliases[value]} if value in self.aliases else set())
        for value in sorted(eclis):
            evidence_sets.append(set(self.eclis.get(value, set())))
        dates = reference_dates(raw)
        hint = stage(raw)
        name_candidates = set(self.names.get(reference_title(raw), set()))
        if evidence_sets:
            candidates = set.intersection(*evidence_sets)
            method = "direct_identifier"
            if not candidates:
                return {"status": "unresolved", "method": "unknown_or_conflicting_identifier", "candidates": []}
        else:
            appnos = applications(raw)
            if appnos:
                candidates = set.intersection(*(set(self.appnos.get(a, set())) for a in appnos))
                method = "application_date" if dates else "application_title"
                if not dates:
                    candidates &= name_candidates
            else:
                candidates = name_candidates if dates else set()
                method = "title_date" if dates else "insufficient_identifiers"
        if len(dates) > 1:
            return {"status": "ambiguous", "method": "multiple_reference_dates", "candidates": sorted(candidates)}
        if dates:
            candidates = {k for k in candidates if self.nodes[k]["date"] in dates}
        if candidates and name_candidates and not (candidates & name_candidates):
            return {"status": "identifier_conflict", "method": method, "candidates": sorted(candidates | name_candidates)}
        if hint:
            candidates = {k for k in candidates if any(stage(r["docname"]) == hint for r in self.nodes[k]["versions"])
                          or (dates and all(stage(r["docname"]) is None for r in self.nodes[k]["versions"]))}
        if len(candidates) != 1:
            return {"status": "ambiguous" if candidates else "unresolved", "method": method, "candidates": sorted(candidates)}
        target = next(iter(candidates))
        if self.nodes[target]["date"] > self.nodes[citing_id]["date"]:
            return {"status": "chronology_conflict", "method": method, "candidates": [target]}
        if target == citing_id:
            return {"status": "self_reference", "method": method, "candidates": [target]}
        return {"status": "resolved", "method": method, "candidates": [target], "target_id": target}


    def resolve_extracted(self, appno, citing_id):
        """An application number HUDOC extracted from the text of a judgment.

        The number carries no date, name or document stage, so it only resolves when exactly one other
        judgment in the catalog has that application and is not later than the citing judgment. Several
        judgments of one application (Chamber and Grand Chamber, merits and just satisfaction) stay
        ambiguous, and the citing judgment's own application numbers are not citations.
        """
        method = "extracted_application"
        if appno in self.agreed.get(citing_id, set()):
            return {"status": "self_reference", "method": method, "candidates": []}
        candidates = set(self.appnos.get(appno, set())) - {citing_id}
        if not candidates:
            return {"status": "unresolved", "method": method, "candidates": []}
        when = self.nodes[citing_id]["date"]
        earlier = {k for k in candidates if self.nodes[k]["date"] <= when}
        if not earlier:
            return {"status": "chronology_conflict", "method": method, "candidates": sorted(candidates)}
        if len(earlier) > 1:
            return {"status": "ambiguous", "method": method, "candidates": sorted(earlier)}
        target = next(iter(earlier))
        return {"status": "resolved", "method": method, "candidates": [target], "target_id": target}


def public_node(node):
    return {k: v for k, v in node.items() if k != "versions"}


def rank(index, edges):
    """Top 20 judgments by distinct citing judgments, with the citing lists the page shows."""
    cited_by = defaultdict(set)
    for citing, cited in edges:
        cited_by[cited].add(citing)
    top = sorted(cited_by, key=lambda k: (-len(cited_by[k]), index.nodes[k]["date"], k))[:20]
    ranking = [{**public_node(index.nodes[k]), "cited_by_count": len(cited_by[k])} for k in top]
    citing_lists = {index.nodes[k]["case_id"]: [index.nodes[c]["case_id"] for c in sorted(cited_by[k],
                    key=lambda c: (index.nodes[c]["date"], c), reverse=True)] for k in top}
    listed_sources = set().union(*(cited_by[k] for k in top)) if top else set()
    citing_nodes = {index.nodes[k]["case_id"]: {field: index.nodes[k][field] for field in ("title", "date", "ecli")}
                   for k in sorted(listed_sources)}
    return ranking, citing_lists, citing_nodes, cited_by, top


def edge_hash(edges):
    return hashlib.sha256("\n".join(a + "\t" + b for a, b in sorted(edges)).encode()).hexdigest()


def extracted_appnos(index, extracted):
    """identity -> {application number -> (HUDOC id, language) of a record that carries it}."""
    found = {}
    for key, node in index.nodes.items():
        numbers = {}
        for row in node["versions"]:
            raw = extracted.get(row["itemid"], row.get("extractedappno")) if extracted is not None else row.get("extractedappno")
            for appno in sorted(applications(raw)):
                numbers.setdefault(appno, (row["itemid"], row["languageisocode"]))
        if numbers:
            found[key] = numbers
    return found


def build_graph(catalog, extracted=None):
    """`extracted` maps HUDOC item id -> the record's extractedappno (application numbers HUDOC found in the
    full text). Without it, or when no catalog row has the field, the snapshot is the curated-list one."""
    validate_catalog(catalog, ("ENG", "FRE"), complete_history=True)
    index = JudgmentIndex(catalog["documents"])
    observations, edges = [], set()
    metadata_sources, metadata_languages = set(), Counter()
    outcomes, methods = Counter(), Counter()
    for key, node in sorted(index.nodes.items()):
        for row in node["versions"]:
            refs = sorted({ref.strip() for ref in (row.get("scl") or "").split(";") if ref.strip()})
            if refs:
                metadata_sources.add(key)
                metadata_languages[row["languageisocode"]] += 1
            for raw in refs:
                result = index.resolve(raw, key)
                outcomes[result["status"]] += 1
                methods[result["method"]] += 1
                observations.append({"citing_id": key, "source_hudoc_id": row["itemid"],
                    "language": row["languageisocode"], "origin": "hudoc_scl", "raw_reference": raw, **result})
                if result["status"] == "resolved":
                    edges.add((key, result["target_id"]))
    ranking, citing_lists, citing_nodes, _, _ = rank(index, edges)
    snapshot = {
        "schema_version": VERSION, "generated_at": datetime.now(timezone.utc).isoformat(),
        "cutoff": catalog["manifest"]["to"], "catalog_sha256": catalog["manifest"]["sha256"],
        "catalog_content_sha256": catalog["manifest"].get("content_sha256"), "edges_sha256": edge_hash(edges),
        "statistics_scope_sha256": fingerprint(r["itemid"] for r in catalog["documents"] if eligible(r) and r["languageisocode"] == "ENG"),
        "scope": "Judgments only, English-flagged catalog identities with verified French ECLI aliases. "
                 "Counts use bilingual HUDOC citation metadata, not full-text extraction.",
        "coverage": {
            "judgments": len(index.nodes), "judgments_with_metadata": len(metadata_sources),
            "metadata_versions_by_language": dict(metadata_languages), "reference_observations": len(observations),
            "by_status": dict(sorted(outcomes.items())), "by_method": dict(sorted(methods.items())),
            "unique_edges": len(edges), "judgments_with_resolved_citations": len({a for a, _ in edges}),
            "identity_issues": index.issues, "full_text_analyzed": False,
        },
        "ranking": ranking, "citing_by_target": citing_lists, "citing_judgments": citing_nodes,
    }
    found = extracted_appnos(index, extracted)
    if found:
        extracted_edges, statuses = set(), Counter()
        for key, numbers in sorted(found.items()):
            for appno, (source_id, language) in sorted(numbers.items()):
                result = index.resolve_extracted(appno, key)
                statuses[result["status"]] += 1
                observations.append({"citing_id": key, "source_hudoc_id": source_id, "language": language,
                    "origin": "hudoc_extractedappno", "raw_reference": appno, **result})
                if result["status"] == "resolved":
                    extracted_edges.add((key, result["target_id"]))
        combined = edges | extracted_edges
        c_rank, c_lists, c_nodes, c_cited_by, c_top = rank(index, combined)
        curated_by, extracted_by = defaultdict(set), defaultdict(set)
        for a, b in edges:
            curated_by[b].add(a)
        for a, b in extracted_edges:
            extracted_by[b].add(a)
        for row, key in zip(c_rank, c_top):
            row["cited_by_curated_list"] = len(curated_by[key])
            row["cited_by_extracted_application"] = len(extracted_by[key])
        snapshot["with_extracted_appno"] = {
            "scope": "As above, plus application numbers HUDOC extracted from the full text of each judgment. "
                     "A number resolves only when one earlier judgment in the catalog has that application; "
                     "the citing judgment's own numbers are skipped and several judgments of one application "
                     "stay ambiguous. Counts are lower bounds and the numbers carry no citation context.",
            "edges_sha256": edge_hash(combined),
            "coverage": {
                "judgments": len(index.nodes),
                "judgments_with_metadata": len(metadata_sources | set(found)),
                "judgments_with_extracted_application_numbers": len(found),
                "reference_observations": sum(statuses.values()),
                "by_status": dict(sorted(statuses.items())),
                "unique_edges": len(combined), "edges_from_curated_list": len(edges),
                "edges_from_extracted_application": len(extracted_edges),
                "edges_in_both": len(edges & extracted_edges),
                "judgments_with_resolved_citations": len({a for a, _ in combined}),
                "full_text_analyzed": False,
            },
            "ranking": c_rank, "citing_by_target": c_lists, "citing_judgments": c_nodes,
        }
        edges = combined
    return snapshot, index, observations, edges


def write_audit(path, index, observations, edges):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="citation-audit-", suffix=".sqlite", dir=path.parent)
    os.close(fd)
    with sqlite3.connect(temporary) as conn:
        conn.executescript("""
            CREATE TABLE judgments (judgment_id TEXT PRIMARY KEY, metadata TEXT NOT NULL);
            CREATE TABLE aliases (hudoc_id TEXT PRIMARY KEY, judgment_id TEXT NOT NULL);
            CREATE TABLE observations (id INTEGER PRIMARY KEY, citing_id TEXT NOT NULL,
                source_hudoc_id TEXT NOT NULL, language TEXT NOT NULL, origin TEXT NOT NULL,
                raw_reference TEXT NOT NULL, status TEXT NOT NULL, method TEXT NOT NULL,
                candidates TEXT NOT NULL, target_id TEXT);
            CREATE TABLE edges (citing_id TEXT NOT NULL, cited_id TEXT NOT NULL,
                PRIMARY KEY(citing_id,cited_id), CHECK(citing_id != cited_id));
            CREATE INDEX observation_status ON observations(status);
            CREATE INDEX observation_target ON observations(target_id);
        """)
        conn.executemany("INSERT INTO judgments VALUES (?,?)", [(k, json.dumps(public_node(n), ensure_ascii=False)) for k, n in index.nodes.items()])
        conn.executemany("INSERT INTO aliases VALUES (?,?)", index.aliases.items())
        conn.executemany("INSERT INTO edges VALUES (?,?)", sorted(edges))
        conn.executemany("INSERT INTO observations(citing_id,source_hudoc_id,language,origin,raw_reference,status,method,candidates,target_id) VALUES (?,?,?,?,?,?,?,?,?)",
            [(o["citing_id"], o["source_hudoc_id"], o["language"], o["origin"], o["raw_reference"], o["status"], o["method"], json.dumps(o["candidates"]), o.get("target_id")) for o in observations])
    os.replace(temporary, path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--extracted-appno", type=Path,
                        help="JSON of HUDOC records ({item id: {extractedappno: ...}}, e.g. p69_sync_hudoc_metadata.py fetch)")
    args = parser.parse_args()
    catalog = json.loads(args.catalog.read_text())
    extracted = None
    if args.extracted_appno:
        extracted = {k: v.get("extractedappno") for k, v in json.loads(args.extracted_appno.read_text()).items()}
    snapshot, index, observations, edges = build_graph(catalog, extracted)
    write_audit(args.audit, index, observations, edges)
    write_json(args.output, snapshot)
    print(json.dumps({"coverage": snapshot["coverage"], "top": snapshot["ranking"][:5]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
