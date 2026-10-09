#!/usr/bin/env python3
"""
Collect translated chunks, apply the citation conventions, run the QA checks and (for the held-out
test set) score the translation against the Court's official English.

For every judgment folder under --jobs: chunk_NNN.json (job) + chunk_NNN.en.json (translation,
{"row id": "English text"}). Writes <id>/translation.json (rows with French and English and QA flags)
and a summary report.

QA per row:
  * missing   – the translation has no entry for the row;
  * citations – application numbers, § pinpoints or dates lost, or French citation forms left
                (scripts/mt/citations.py check);
  * length    – English/French length ratio outside 0.6–1.5 for rows over 80 characters;
  * french    – at least three French function words left in the English text.
With reference.json present it also reports chrF (character 6-grams, beta 2) per judgment and overall,
and glossary-term accuracy against the reference.

    python3 scripts/mt/assemble.py --jobs mt/jobs --report mt/report.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import citations  # noqa: E402

FRENCH = re.compile(r"\b(le|la|les|des|du|une|est|sont|dans|pour|avec|qui|que|aux|cette|été)\b", re.IGNORECASE)


def chrf(hyp: str, ref: str, n: int = 6, beta: float = 2.0) -> float:
    def grams(s, k):
        s = re.sub(r"\s+", "", s)
        return Counter(s[i:i + k] for i in range(len(s) - k + 1))
    ps, rs = [], []
    for k in range(1, n + 1):
        h, r = grams(hyp, k), grams(ref, k)
        overlap = sum((h & r).values())
        if sum(h.values()):
            ps.append(overlap / sum(h.values()))
        if sum(r.values()):
            rs.append(overlap / sum(r.values()))
    p = sum(ps) / len(ps) if ps else 0.0
    r = sum(rs) / len(rs) if rs else 0.0
    return 0.0 if p + r == 0 else 100 * (1 + beta ** 2) * p * r / (beta ** 2 * p + r)


def merged_translation(chunk: Path, tags: list[str]) -> dict:
    """Row id -> English, taking each row from the first tag whose file has it (a repair file holds only the
    rows it repaired, so it goes first)."""
    merged: dict = {}
    for t in reversed(tags):
        f = chunk.with_name(f"{chunk.stem}.{t}.json")
        if f.exists():
            merged.update(json.loads(f.read_text()))
    return merged


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--jobs", required=True)
    ap.add_argument("--report", required=True)
    ap.add_argument("--suffix", default="en", help="translation files chunk_NNN.<suffix>.json (translate.py --tag); "
                    "several tags comma-separated: the first file that exists is used, so a retry tag can go first")
    ap.add_argument("--fix-list", help="write the request ids (case__chunk) of chunks with a flagged or missing row, "
                    "for translate.py submit --only")
    ap.add_argument("--out-name", default=None, help="name of the per-judgment output file (default translation.json "
                    "or translation.<suffix>.json)")
    args = ap.parse_args()
    to_fix = []
    summary = {"judgments": 0, "complete": 0, "rows": 0, "flags": Counter(), "chrf": [], "terms": [0, 0]}
    per_case = []
    for case_dir in sorted(p for p in Path(args.jobs).iterdir() if p.is_dir()):
        jobs = sorted(case_dir.glob("chunk_[0-9][0-9][0-9].json"))
        if not jobs:
            continue
        summary["judgments"] += 1
        rows, complete, glossary = [], True, {}
        for jf in jobs:
            job = json.loads(jf.read_text())
            glossary.update(job.get("glossary", {}))
            tr = merged_translation(jf, args.suffix.split(","))
            tf = tr or None
            complete &= all(r["id"] in tr for r in job["rows"])
            chunk_flagged = False
            for r in job["rows"]:
                en = tr.get(r["id"])
                flags = []
                if en is None:
                    flags.append("missing")
                    en = ""
                else:
                    en = citations.convert(en)
                    if citations.check(r["fr"], en):
                        flags.append("citations")
                    if len(r["fr"]) > 80 and not 0.6 <= len(en) / len(r["fr"]) <= 1.5:
                        flags.append("length")
                    if len(FRENCH.findall(en)) >= 3:
                        flags.append("french")
                rows.append({**r, "en": en, "flags": flags})
                chunk_flagged |= bool(flags)
                summary["flags"].update(flags)
            if chunk_flagged:
                to_fix.append(f"{case_dir.name}__{jf.stem[6:]}")
        summary["rows"] += len(rows)
        summary["complete"] += complete
        info = {"id": case_dir.name, "rows": len(rows), "complete": complete,
                "flagged": sum(1 for r in rows if r["flags"])}
        ref_file = case_dir / "reference.json"
        if ref_file.exists() and complete:
            ref = json.loads(ref_file.read_text())
            hyp_all = " ".join(r["en"] for r in rows if r["id"] in ref)
            ref_all = " ".join(ref[r["id"]] for r in rows if r["id"] in ref)
            info["chrf"] = round(chrf(hyp_all, ref_all), 1)
            summary["chrf"].append(info["chrf"])
            for r in rows:
                if r["id"] not in ref:
                    continue
                for fr, en in glossary.items():
                    if fr.lower() in r["fr"].lower() and en.lower() in ref[r["id"]].lower():
                        summary["terms"][1] += 1
                        summary["terms"][0] += en.lower() in r["en"].lower()
        name = args.out_name or ("translation.json" if args.suffix == "en" else f"translation.{args.suffix.split(',')[0]}.json")
        (case_dir / name).write_text(json.dumps(rows, ensure_ascii=False, indent=1))
        per_case.append(info)
    report = {
        "judgments": summary["judgments"], "complete": summary["complete"], "rows": summary["rows"],
        "flags": dict(summary["flags"]),
        "rows_flagged_share": round(sum(1 for c in per_case for _ in range(c["flagged"])) / max(1, summary["rows"]), 4),
        "chrf_mean": round(sum(summary["chrf"]) / len(summary["chrf"]), 1) if summary["chrf"] else None,
        "glossary_term_accuracy": round(summary["terms"][0] / summary["terms"][1], 4) if summary["terms"][1] else None,
        "per_judgment": per_case,
    }
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=1))
    if args.fix_list:
        Path(args.fix_list).write_text("\n".join(to_fix) + "\n")
        print(f"{len(to_fix)} chunks to repair -> {args.fix_list}")
    print(json.dumps({k: v for k, v in report.items() if k != "per_judgment"}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
