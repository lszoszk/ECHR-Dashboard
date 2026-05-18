#!/usr/bin/env python3
"""P60 — monthly incremental corpus update (fetch + build).

Discovers ECHR judgments published on HUDOC since the corpus's newest
case, fetches their metadata and source-exact paragraph text, and emits
SQL that inserts them into the production database.

This is the *fetch+build* half of the monthly update.  It runs LOCALLY
because paragraph parsing reuses ``p34_rebuild_from_hudoc.parse_docx``,
which needs python-docx.  The emitted SQL is then applied to the VM
database and P29 rebuilds the citation graph — see
``scripts/run_monthly_update.sh`` for the full orchestration.

Design notes
------------
* New cases are INSERTed, never UPDATEd.  Cases already in the corpus
  (matched by ``case_id``) are skipped, so the script is safe to re-run.
* Paragraph rows come from p34's source-exact parser, so the P52–P58
  segmentation / heal logic is already baked in — no heal passes need
  replaying for new cases.
* The FTS5 index syncs automatically: ``paragraphs`` INSERTs fire the
  ``paragraphs_ai`` trigger.  An ``optimize`` is appended for tidiness.
* Metadata mapping mirrors ``backend/build_db.py`` (same JSON-text
  columns, same violation inference) so new rows match the existing
  19,720 cases.

Existing-corpus input: a TSV whose first two columns are
``case_id<TAB>judgment_date`` (``run_monthly_update.sh`` dumps exactly
this from the VM database).

Usage
-----
    # driven by run_monthly_update.sh
    python3 scripts/p60_monthly_update.py \\
        --existing /tmp/echr_existing.tsv --out /tmp/p60_update.sql

    # local smoke test against a throwaway DB
    python3 scripts/p60_monthly_update.py \\
        --existing data/p30_scl_compare/cases.tsv --limit 3 \\
        --out /tmp/p60_update.sql --apply-to /tmp/p60_test.db
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import ssl
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent          # scripts/
REPO = ROOT.parent
P34_PATH = ROOT / "p34_rebuild_from_hudoc.py"
BUILD_DB_PATH = REPO / "backend" / "build_db.py"
KPTHESAURUS_PATH = ROOT / "kpthesaurus_labels.json"

HUDOC_QUERY_URL = "https://hudoc.echr.coe.int/app/query/results"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
_SSL = ssl._create_unverified_context()

# HUDOC metadata fields requested per case (confirmed against the live
# API — see scripts/hudoc_rescrape.py for the field vocabulary).
META_SELECT = (
    "itemid,docname,appno,kpdate,judgementdate,ecli,respondent,importance,"
    "conclusion,article,violation,nonviolation,kpthesaurus,scl,rulesofcourt,"
    "originatingbody,doctypebranch,documentcollectionid2"
)

# ISO-3 → display name.  Mirrors COUNTRY_NAMES in docs/assets/search-app.js
# so a new case's respondent_state reverse-maps cleanly in the country
# filter.
COUNTRY_NAMES = {
    "ALB": "Albania", "AND": "Andorra", "ARM": "Armenia", "AUT": "Austria",
    "AZE": "Azerbaijan", "BEL": "Belgium", "BIH": "Bosnia and Herzegovina",
    "BGR": "Bulgaria", "HRV": "Croatia", "CYP": "Cyprus",
    "CZE": "Czech Republic", "DNK": "Denmark", "EST": "Estonia",
    "FIN": "Finland", "FRA": "France", "GEO": "Georgia", "DEU": "Germany",
    "GRC": "Greece", "HUN": "Hungary", "ISL": "Iceland", "IRL": "Ireland",
    "ITA": "Italy", "LVA": "Latvia", "LIE": "Liechtenstein",
    "LTU": "Lithuania", "LUX": "Luxembourg", "MLT": "Malta", "MDA": "Moldova",
    "MCO": "Monaco", "MNE": "Montenegro", "NLD": "Netherlands",
    "MKD": "North Macedonia", "NOR": "Norway", "POL": "Poland",
    "PRT": "Portugal", "ROU": "Romania", "RUS": "Russia", "SMR": "San Marino",
    "SRB": "Serbia", "SVK": "Slovakia", "SVN": "Slovenia", "ESP": "Spain",
    "SWE": "Sweden", "CHE": "Switzerland", "TUR": "Turkey", "UKR": "Ukraine",
    "GBR": "United Kingdom",
}

DOCTYPE_BY_BRANCH = {
    "GRANDCHAMBER": "Judgment (Grand Chamber)",
    "COMMITTEE": "Judgment (Committee)",
    "CHAMBER": "Judgment (Chamber)",
}
VALID_BRANCHES = set(DOCTYPE_BY_BRANCH)


# ── reuse the existing pipeline ──────────────────────────────────────
def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── HUDOC API ────────────────────────────────────────────────────────
def hudoc_get(params: dict, attempts: int = 4) -> dict:
    """GET the HUDOC query API.  Returns parsed JSON or raises."""
    url = HUDOC_QUERY_URL + "?" + urllib.parse.urlencode(params)
    last = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA,
                "Referer": "https://hudoc.echr.coe.int/",
            })
            with urllib.request.urlopen(req, context=_SSL, timeout=60) as r:
                return json.loads(r.read().decode())
        except Exception as exc:                       # noqa: BLE001
            last = exc
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"HUDOC query failed after {attempts} tries: {last}")


def discover(since: str, to: str) -> list[dict]:
    """Return HUDOC judgment metadata rows (column dicts) in the window.

    ``since`` / ``to`` are ``YYYY-MM-DD``.  Filtered to real judgments:
    ``001-`` itemids whose ``doctypebranch`` is Chamber/GC/Committee
    (drops ``003-`` press releases and legal summaries).
    """
    query = (
        'contentsitename:ECHR AND documentcollectionid2:"JUDGMENTS" '
        f'AND (kpdate>="{since}T00:00:00.0Z" '
        f'AND kpdate<="{to}T23:59:59.0Z")'
    )
    rows: list[dict] = []
    start, page = 0, 500
    while True:
        data = hudoc_get({
            "query": query, "select": META_SELECT,
            "sort": "itemid Ascending", "start": str(start),
            "length": str(page),
        })
        batch = data.get("results", [])
        for res in batch:
            cols = res.get("columns", {})
            iid = cols.get("itemid", "")
            branch = (cols.get("doctypebranch") or "").upper()
            if iid.startswith("001-") and branch in VALID_BRANCHES:
                rows.append(cols)
        total = data.get("resultcount", 0)
        start += page
        if not batch or start >= total:
            break
        time.sleep(0.4)
    return rows


# ── metadata mapping (HUDOC columns → cases-table fields) ────────────
def _semicolon_list(value) -> list[str]:
    if not value or not str(value).strip():
        return []
    return [x.strip() for x in str(value).split(";") if x.strip()]


def _hudoc_date(cols: dict) -> str:
    """Return judgment_date as dd/mm/yyyy."""
    jd = (cols.get("judgementdate") or "").strip()
    if len(jd) >= 10 and jd[2] == "/" and jd[5] == "/":
        return jd[:10]
    kp = (cols.get("kpdate") or "").strip()        # 2026-05-12T00:00:00
    if len(kp) >= 10 and kp[4] == "-":
        y, m, d = kp[:10].split("-")
        return f"{d}/{m}/{y}"
    return ""


def _importance(value) -> str:
    v = (str(value or "")).strip()
    if not v:
        return "Unspecified"
    if "key" in v.lower():
        return "Key cases"
    return v if v in ("1", "2", "3") else "Unspecified"


def _originating_body(cols: dict) -> str:
    branch = (cols.get("doctypebranch") or "").upper()
    ob = (cols.get("originatingbody") or "").strip()
    if branch == "GRANDCHAMBER":
        return "Court (Grand Chamber)"
    if branch == "COMMITTEE":
        # HUDOC supplies the section-committee code (25-29); the frontend
        # BODY_CODE_LABELS map renders it.  Keep it if it looks like one.
        return ob if ob in ("25", "26", "27", "28", "29") else "Court (Committee)"
    if branch == "CHAMBER":
        return "Court (Chamber)"
    return ob


def map_metadata(cols: dict, kpthes: dict, build_db) -> dict:
    """Map a HUDOC column dict to the 20 cases-table fields + article_no."""
    iid = cols["itemid"]
    branch = (cols.get("doctypebranch") or "").upper()

    respondents = [COUNTRY_NAMES.get(c, c)
                   for c in _semicolon_list(cols.get("respondent"))]
    keywords = [kpthes[c] for c in _semicolon_list(cols.get("kpthesaurus"))
                if c in kpthes]

    conclusion = (cols.get("conclusion") or "").strip()
    hudoc_v = _semicolon_list(cols.get("violation"))
    hudoc_nv = _semicolon_list(cols.get("nonviolation"))
    inf_v, inf_nv = build_db._infer_violations_from_conclusion(conclusion)
    new_v = [a for a in inf_v if a not in set(hudoc_v)]
    new_nv = [a for a in inf_nv if a not in set(hudoc_nv)]

    return {
        "case_id": iid,
        "case_no": (cols.get("appno") or "").strip(),
        "title": (cols.get("docname") or "").strip(),
        "hudoc_url": f"https://hudoc.echr.coe.int/?i={iid}",
        "judgment_date": _hudoc_date(cols),
        "ecli": (cols.get("ecli") or "").strip(),
        "respondent_state": "; ".join(respondents),
        "importance": _importance(cols.get("importance")),
        "conclusion": conclusion,
        "violation": hudoc_v + new_v,
        "non_violation": hudoc_nv + new_nv,
        "violation_inferred": new_v,
        "non_violation_inferred": new_nv,
        "keywords": keywords,
        "originating_body": _originating_body(cols),
        "document_type": DOCTYPE_BY_BRANCH.get(branch, "Judgment"),
        "strasbourg_caselaw": _semicolon_list(cols.get("scl")),
        "domestic_law": [],
        "international_law": [],
        "rules_of_court": (cols.get("rulesofcourt") or "").strip(),
        "article_no": (cols.get("article") or "").strip(),
    }


# ── SQL emission ─────────────────────────────────────────────────────
CASES_COLS = (
    "case_id, case_no, title, hudoc_url, judgment_date, ecli, "
    "respondent_state, importance, conclusion, violation, non_violation, "
    "violation_inferred, non_violation_inferred, keywords, originating_body, "
    "document_type, strasbourg_caselaw, domestic_law, international_law, "
    "rules_of_court"
)
PARA_COLS = (
    "case_id, section, para_idx, hudoc_para_no, numbering_block, row_role, "
    "logical_para_idx, display_para_no, title, keywords_text, text"
)


def emit_case(meta: dict, paras: list[dict], build_db, p34) -> list[str]:
    """Forward SQL for one new case: INSERT cases + paragraphs + articles."""
    v = p34.sql_value
    out: list[str] = []

    # cases row — JSON-text columns mirror build_db._json_field()
    cells = [
        v(meta["case_id"]), v(meta["case_no"]), v(meta["title"]),
        v(meta["hudoc_url"]), v(meta["judgment_date"]), v(meta["ecli"]),
        v(meta["respondent_state"]), v(meta["importance"]),
        v(build_db._json_field(meta["conclusion"])),
        v(build_db._json_field(meta["violation"])),
        v(build_db._json_field(meta["non_violation"])),
        v(build_db._json_field(meta["violation_inferred"] or [])),
        v(build_db._json_field(meta["non_violation_inferred"] or [])),
        v(build_db._json_field(meta["keywords"])),
        v(build_db._json_field(meta["originating_body"])),
        v(meta["document_type"]),
        v(build_db._json_field(meta["strasbourg_caselaw"])),
        v(build_db._json_field(meta["domestic_law"])),
        v(build_db._json_field(meta["international_law"])),
        v(build_db._json_field(meta["rules_of_court"])),
    ]
    out.append(f"INSERT OR IGNORE INTO cases ({CASES_COLS}) "
               f"VALUES ({', '.join(cells)});")

    # paragraphs — title + keywords_text land on the first body row only
    # (the BM25F "metadata row" layout from build_db.py).
    kw_text = " ; ".join(str(k) for k in meta["keywords"] if k)
    first = True
    for r in paras:
        text = r.get("text") or ""
        if not text:
            continue
        row_title = v(meta["title"]) if first else v("")
        row_kw = v(kw_text) if first else v("")
        first = False
        out.append(
            f"INSERT INTO paragraphs ({PARA_COLS}) VALUES ("
            f"{v(meta['case_id'])}, {v(r.get('section'))}, "
            f"{v(r.get('para_idx'))}, {v(r.get('hudoc_para_no'))}, "
            f"{v(r.get('numbering_block'))}, {v(r.get('row_role'))}, "
            f"{v(r.get('logical_para_idx'))}, {v(r.get('display_para_no'))}, "
            f"{row_title}, {row_kw}, {v(text)});"
        )

    # exploded articles
    for art in build_db._normalize_articles(meta["article_no"]):
        out.append(f"INSERT OR IGNORE INTO case_articles (case_id, article) "
                   f"VALUES ({v(meta['case_id'])}, {v(art)});")
    return out


def emit_rollback(case_ids: list[str], p34) -> list[str]:
    v = p34.sql_value
    out = []
    for cid in case_ids:
        out.append(f"DELETE FROM paragraphs WHERE case_id = {v(cid)};")
        out.append(f"DELETE FROM case_articles WHERE case_id = {v(cid)};")
        out.append(f"DELETE FROM cases WHERE case_id = {v(cid)};")
    return out


# ── existing-corpus input ────────────────────────────────────────────
def load_existing(path: Path) -> tuple[set[str], str | None]:
    """Return ({case_id}, latest_judgment_date as YYYY-MM-DD or None).

    Accepts any TSV whose first column is ``case_id``.  The latest
    judgment date is found by scanning every other column for a
    dd/mm/yyyy value, so a 2-column ``case_id<TAB>date`` dump and a
    3-column ``case_id<TAB>case_no<TAB>date`` dump both work.
    """
    ids: set[str] = set()
    latest: date | None = None
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        ids.add(parts[0].strip())
        for cell in parts[1:]:
            try:
                d = datetime.strptime(cell.strip(), "%d/%m/%Y").date()
            except ValueError:
                continue
            if latest is None or d > latest:
                latest = d
            break
    return ids, (latest.isoformat() if latest else None)


# ── main ─────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--existing", required=True,
                    help="TSV of case_id<TAB>judgment_date already in corpus")
    ap.add_argument("--since",
                    help="YYYY-MM-DD lower bound (default: latest corpus "
                         "date minus 7-day safety overlap)")
    ap.add_argument("--to", default=date.today().isoformat(),
                    help="YYYY-MM-DD upper bound (default: today)")
    ap.add_argument("--out", default="/tmp/p60_update.sql",
                    help="forward SQL output path")
    ap.add_argument("--rollback-out",
                    help="rollback SQL output path (default: <out>.rollback)")
    ap.add_argument("--limit", type=int, default=0,
                    help="cap new cases processed (debug)")
    ap.add_argument("--workers", type=int, default=2,
                    help="parallel HUDOC DOCX fetches (keep low — HUDOC "
                         "rate-limits aggressive parallelism)")
    ap.add_argument("--fetch-delay", type=float, default=0.5,
                    help="seconds between HUDOC DOCX fetches (politeness)")
    ap.add_argument("--apply-to",
                    help="also executescript the forward SQL into this "
                         "SQLite DB (local testing / direct apply)")
    args = ap.parse_args()

    existing_path = Path(args.existing)
    if not existing_path.exists():
        print(f"ERROR: --existing not found: {existing_path}", file=sys.stderr)
        return 2

    # p34.fetch_docx reads P34_FETCH_DELAY at import time — set it first.
    os.environ["P34_FETCH_DELAY"] = str(args.fetch_delay)
    p34 = _load_module(P34_PATH, "p34_rebuild_from_hudoc")
    build_db = _load_module(BUILD_DB_PATH, "build_db")
    kpthes = json.loads(KPTHESAURUS_PATH.read_text())

    existing_ids, latest = load_existing(existing_path)
    print(f"corpus: {len(existing_ids):,} cases   latest judgment: {latest}")

    if args.since:
        since = args.since
    elif latest:
        since = (datetime.fromisoformat(latest).date()
                 - timedelta(days=7)).isoformat()
    else:
        print("ERROR: no --since and no dated corpus rows", file=sys.stderr)
        return 2
    print(f"discovery window: {since} … {args.to}")

    discovered = discover(since, args.to)
    new_cols = [c for c in discovered if c["itemid"] not in existing_ids]
    print(f"HUDOC judgments in window: {len(discovered):,}")
    print(f"already in corpus:         {len(discovered) - len(new_cols):,}")
    print(f"NEW cases to ingest:       {len(new_cols):,}")
    if args.limit:
        new_cols = new_cols[:args.limit]
        print(f"  (--limit: processing first {len(new_cols)})")
    if not new_cols:
        print("nothing to do.")
        return 0

    from concurrent.futures import ThreadPoolExecutor

    def fetch_one(cols):
        cid = cols["itemid"]
        try:
            blob = p34.fetch_docx(cid)
            rows, _lang = p34.parse_docx(blob)
            if not rows:
                return cid, cols, None, "no parsable paragraphs"
            return cid, cols, rows, None
        except Exception as exc:                       # noqa: BLE001
            return cid, cols, None, str(exc)[:140]

    forward: list[str] = []
    ok_ids: list[str] = []
    failures: list[tuple[str, str]] = []
    n_paras = 0
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        for i, (cid, cols, rows, err) in enumerate(
                ex.map(fetch_one, new_cols), 1):
            if err:
                failures.append((cid, err))
            else:
                meta = map_metadata(cols, kpthes, build_db)
                forward += emit_case(meta, rows, build_db, p34)
                ok_ids.append(cid)
                n_paras += sum(1 for r in rows if r.get("text"))
            if i % 25 == 0 or i == len(new_cols):
                print(f"  fetched {i}/{len(new_cols)}  "
                      f"ok={len(ok_ids)} failed={len(failures)}")

    # Wrap the inserts in one transaction so application is atomic
    # (all new cases land, or none).  FTS triggers sync each INSERT;
    # the optimise runs once, after COMMIT.
    forward_sql = ("BEGIN;\n" + "\n".join(forward) + "\nCOMMIT;\n"
                   "INSERT INTO paragraphs_fts(paragraphs_fts) "
                   "VALUES('optimize');\n")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(forward_sql)
    rb_path = Path(args.rollback_out or (str(out_path) + ".rollback"))
    rb_path.write_text("BEGIN;\n" + "\n".join(emit_rollback(ok_ids, p34))
                       + "\nCOMMIT;\n")

    print()
    print("=" * 60)
    print(f"new cases built:   {len(ok_ids):,}")
    print(f"paragraphs:        {n_paras:,}")
    print(f"fetch failures:    {len(failures):,}")
    # HTTP 500 = HUDOC has not finished rendering the DOCX for a very
    # recent judgment.  Not an error in our pipeline; the case stays
    # out of the corpus and is re-attempted automatically on the next
    # monthly run (it is still "new" until it succeeds).
    not_ready = [(c, e) for c, e in failures if "500" in e]
    other = [(c, e) for c, e in failures if "500" not in e]
    if not_ready:
        print(f"  {len(not_ready)} — HUDOC DOCX not yet rendered (HTTP 500); "
              f"auto-retried next run")
    for cid, err in other[:15]:
        print(f"  ! {cid}: {err}")
    print(f"forward SQL  → {out_path}  ({out_path.stat().st_size:,} bytes)")
    print(f"rollback SQL → {rb_path}")

    if args.apply_to:
        db = Path(args.apply_to)
        print(f"\napplying forward SQL to {db} …")
        con = sqlite3.connect(db)
        try:
            con.executescript(out_path.read_text())
            con.commit()
            n = con.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
            print(f"  done — cases table now holds {n:,} rows")
        finally:
            con.close()

    print("\nnext: apply forward SQL to the VM database, then re-run P29:")
    print("  docker exec echr-api python3 .../p29_extract_citations.py "
          "--db /data/echr_search.db --apply")
    return 0


if __name__ == "__main__":
    sys.exit(main())
