#!/usr/bin/env python3
"""P37 — rebuild JSONL paragraph text from source-exact HUDOC DOCX.

This is the JSONL companion to ``p34_rebuild_from_hudoc.py``.  It preserves
case metadata but replaces ``paragraphs`` for selected non-press-release cases
with the visible DOCX paragraphs returned by the source-exact parser.

Examples
--------
    # Golden-case rebuild to a temp file
    python3 scripts/p37_rebuild_jsonl_from_hudoc.py \\
        --case-id 001-249785 --output /tmp/echr_cases_p37.jsonl

    # Full corpus rebuild in place (long network job)
    python3 scripts/p37_rebuild_jsonl_from_hudoc.py --in-place --workers 4
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
P34_PATH = ROOT / "scripts" / "p34_rebuild_from_hudoc.py"


def load_p34():
    spec = importlib.util.spec_from_file_location("p34_rebuild_from_hudoc", P34_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {P34_PATH}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def read_case_list(path: str | None) -> set[str]:
    if not path:
        return set()
    return {line.strip() for line in Path(path).read_text().splitlines() if line.strip()}


def is_press_release(case: dict) -> bool:
    return "press release" in str(case.get("document_type") or "").lower()


def rebuild_case(p34, case: dict) -> tuple[str, list[dict] | None, str | None]:
    cid = case.get("case_id") or ""
    try:
        blob = p34.fetch_docx(cid)
        rows, _lang = p34.parse_docx(blob)
        return cid, rows, None
    except Exception as exc:  # noqa: BLE001 - report and keep original row
        return cid, None, str(exc)[:160]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", default="docs/data/echr_cases.jsonl")
    ap.add_argument("--output")
    ap.add_argument("--in-place", action="store_true")
    ap.add_argument("--case-id", action="append", default=[])
    ap.add_argument("--case-list")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    input_path = Path(args.input)
    if not input_path.is_absolute():
        input_path = ROOT / input_path
    if not input_path.exists():
        print(f"ERROR: input not found: {input_path}", file=sys.stderr)
        return 2
    if args.in_place and args.output:
        print("ERROR: choose either --in-place or --output, not both", file=sys.stderr)
        return 2
    if not args.in_place and not args.output:
        print("ERROR: provide --output or --in-place", file=sys.stderr)
        return 2

    target_ids = set(args.case_id) | read_case_list(args.case_list)
    p34 = load_p34()

    raw_lines: list[str] = []
    records: list[dict] = []
    targets: list[dict] = []
    with input_path.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            raw_lines.append(line)
            case = json.loads(line)
            records.append(case)
            if is_press_release(case):
                continue
            if target_ids and case.get("case_id") not in target_ids:
                continue
            if args.limit and len(targets) >= args.limit:
                continue
            targets.append(case)

    if not target_ids and args.limit:
        target_ids = {c.get("case_id") for c in targets}
    if not target_ids and not args.limit:
        target_ids = {c.get("case_id") for c in targets}

    print(f"loaded records: {len(records):,}")
    print(f"target cases:   {len(targets):,}")

    rebuilt: dict[str, list[dict]] = {}
    failures: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        futures = {ex.submit(rebuild_case, p34, case): case.get("case_id") for case in targets}
        for i, fut in enumerate(as_completed(futures), 1):
            cid, rows, err = fut.result()
            if rows:
                rebuilt[cid] = rows
            else:
                failures[cid] = err or "no rows"
            if i % 100 == 0 or i == len(futures):
                print(f"  {i:,}/{len(futures):,} rebuilt={len(rebuilt):,} failures={len(failures):,}")

    output_path: Path
    if args.in_place:
        tmp = tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False,
                                         dir=str(input_path.parent),
                                         prefix=input_path.name + ".p37.",
                                         suffix=".tmp")
        output_path = Path(tmp.name)
        out_fh = tmp
    else:
        output_path = Path(args.output)
        if not output_path.is_absolute():
            output_path = ROOT / output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        out_fh = output_path.open("w", encoding="utf-8")

    with out_fh:
        for raw, case in zip(raw_lines, records):
            cid = case.get("case_id")
            if cid in rebuilt:
                case = dict(case)
                case["paragraphs"] = rebuilt[cid]
                out_fh.write(json.dumps(case, ensure_ascii=False, separators=(",", ":")) + "\n")
            else:
                out_fh.write(raw if raw.endswith("\n") else raw + "\n")

    if args.in_place:
        output_path.replace(input_path)
        output_path = input_path

    print(f"wrote: {output_path}")
    print(f"rebuilt: {len(rebuilt):,}")
    if failures:
        print(f"failures: {len(failures):,}")
        for cid, err in list(failures.items())[:20]:
            print(f"  {cid}: {err}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
