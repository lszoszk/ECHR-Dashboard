#!/usr/bin/env python3
"""P37 audit — compare JSONL paragraph text against HUDOC DOCX visible text.

The audit intentionally ignores section labels and numbering metadata.  It
checks the core source-exact promise: every visible HUDOC DOCX paragraph must
appear in the stored case text in the same order after light whitespace
normalisation.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
P34_PATH = ROOT / "scripts" / "p34_rebuild_from_hudoc.py"
WS_RE = re.compile(r"\s+")


def norm(text: str) -> str:
    return WS_RE.sub(" ", str(text or "").replace("\xa0", " ")).strip()


def load_p34():
    spec = importlib.util.spec_from_file_location("p34_rebuild_from_hudoc", P34_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {P34_PATH}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def iter_cases(path: Path, wanted: set[str]):
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            case = json.loads(line)
            if not wanted or case.get("case_id") in wanted:
                yield case


def audit_case(p34, case: dict) -> dict:
    cid = case.get("case_id") or ""
    blob = p34.fetch_docx(cid)
    source_rows, _lang = p34.parse_docx(blob)
    source = [norm(r.get("text", "")) for r in source_rows if norm(r.get("text", ""))]
    stored = [norm(p.get("text", "")) for p in case.get("paragraphs", []) if norm(p.get("text", ""))]

    missing = []
    pos = 0
    for text in source:
        try:
            idx = stored.index(text, pos)
        except ValueError:
            missing.append(text)
        else:
            pos = idx + 1

    return {
        "case_id": cid,
        "source_count": len(source),
        "stored_count": len(stored),
        "missing_count": len(missing),
        "missing": missing[:10],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--jsonl", default="docs/data/echr_cases.jsonl")
    ap.add_argument("--case-id", action="append", default=[])
    ap.add_argument("--case-list")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    jsonl_path = Path(args.jsonl)
    if not jsonl_path.is_absolute():
        jsonl_path = ROOT / jsonl_path
    wanted = set(args.case_id)
    if args.case_list:
        wanted |= {line.strip() for line in Path(args.case_list).read_text().splitlines() if line.strip()}

    p34 = load_p34()
    failures = []
    total = 0
    for case in iter_cases(jsonl_path, wanted):
        if args.limit and total >= args.limit:
            break
        total += 1
        try:
            result = audit_case(p34, case)
        except Exception as exc:  # noqa: BLE001
            failures.append({"case_id": case.get("case_id"), "error": str(exc)[:160]})
            continue
        if result["missing_count"]:
            failures.append(result)
        print(
            f"{result['case_id']} source={result['source_count']} "
            f"stored={result['stored_count']} missing={result['missing_count']}"
        )

    print(f"\naudited: {total:,}")
    print(f"failures: {len(failures):,}")
    if failures:
        print(json.dumps(failures[:20], ensure_ascii=False, indent=2))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
