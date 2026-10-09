#!/usr/bin/env python3
"""
Ask Jev (TypeSafe System One) whether each translated paragraph is a complete and faithful translation,
and list the chunks to send to a stronger model.

Jev only judges and returns a calibrated probability per question. One request per chunk: the French and
English rows are the state, one yes/no question per row. The client is the travaux project's
pipeline/jev.py (key in travaux/.env, never printed; token usage appended to travaux/data/jev_usage.jsonl
under the task name "echr_mt_check"). Answers are cached by the English text, so a repaired row is asked
again and an unchanged one is not.

A paragraph goes on the repair list ("case__chunk row_id" lines, for translate.py submit --rows) when Jev
puts it below --threshold, when Jev gave no answer, when it has no translation, or when the deterministic
checks flag it. Calibrated on one held-out judgment with deliberately damaged copies: at 0.8 Jev caught
43/43 omissions, changed numbers and reversed statements and flagged 8/84 good paragraphs; it does not
notice French left untranslated, which the deterministic check catches.

    python3 scripts/mt/judge.py --jobs mt/jobs_t1 --suffix t1a,t1b,t1c --cache mt/jev_t1.jsonl --jev \\
            --fix-list mt/fix_t1.txt
Without --jev nothing is sent; the counts of what would be asked are printed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import citations  # noqa: E402
from assemble import FRENCH, merged_translation  # noqa: E402

QUESTION = ("Consider only {k} in the state: one paragraph of a judgment of the European Court of Human Rights "
            "in French and its English translation. Is the English a complete and faithful translation of the "
            "French? It must keep the meaning, omit and add nothing, keep every number, date, name, application "
            "number and paragraph reference, and leave no French untranslated. Different wording or word order and "
            "the Court's standard English formulas are fine.")
TRUE = "Complete and faithful: same meaning, nothing missing or added, numbers, dates, names and references intact."
FALSE = ("Not faithful: the meaning differs, something is omitted or added, a number, date, name or reference "
         "differs, or French is left untranslated.")


def rule_flags(fr: str, en: str) -> list[str]:
    """The deterministic checks of assemble.py for one row."""
    flags = []
    en = citations.convert(en)
    if citations.check(fr, en):
        flags.append("citations")
    if len(fr) > 80 and not 0.6 <= len(en) / len(fr) <= 1.5:
        flags.append("length")
    if len(FRENCH.findall(en)) >= 3:
        flags.append("french")
    return flags


def sha(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def ask_chunk(jev, rows: list[dict]) -> dict[str, float | None]:
    state = {f"item_{i}": {"french": r["fr"], "english": r["en"]} for i, r in enumerate(rows)}
    questions = {k: jev.noul(QUESTION.format(k=k), TRUE, FALSE) for k in state}
    answers = jev.ask({"items": state}, questions, task="echr_mt_check")
    out = {}
    for i, r in enumerate(rows):
        p = (answers.get(f"item_{i}") or {}).get("noul")
        out[r["id"]] = float(p) if isinstance(p, (int, float)) else None
    return out


def load_cache(path: str) -> dict[str, float | None]:
    cache: dict[str, float | None] = {}
    if Path(path).exists():
        for line in Path(path).read_text().splitlines():
            rec = json.loads(line)
            cache[rec["key"]] = rec["p"]
    return cache


def collect_chunks(jobs: str, tags: list[str], wanted: set | None):
    """Chunks with their translated rows, plus the rows the rules already send to repair ("case__chunk row")."""
    chunks, fix = [], set()
    stats = {"chunks": 0, "rows": 0, "untranslated_chunks": 0, "rule_flagged_rows": 0, "missing_rows": 0}
    for jf in sorted(Path(jobs).glob("*/chunk_[0-9][0-9][0-9].json")):
        rid = f"{jf.parent.name}__{jf.stem[6:]}"
        if wanted is not None and rid not in wanted:
            continue
        stats["chunks"] += 1
        job, tr = json.loads(jf.read_text()), merged_translation(jf, tags)
        if not tr:
            stats["untranslated_chunks"] += 1
        rows = []
        for r in job["rows"]:
            en = tr.get(r["id"])
            stats["rows"] += 1
            if not en:
                stats["missing_rows"] += 1
                fix.add(f"{rid} {r['id']}")
                continue
            if rule_flags(r["fr"], en):
                stats["rule_flagged_rows"] += 1
                fix.add(f"{rid} {r['id']}")
            rows.append({"id": r["id"], "fr": r["fr"], "en": en, "key": f"{rid}__{r['id']}__{sha(en)}"})
        chunks.append((rid, rows))
    return chunks, fix, stats


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--jobs", required=True)
    ap.add_argument("--suffix", required=True, help="translation tags, first existing file wins (as assemble.py)")
    ap.add_argument("--cache", required=True, help="JSONL of Jev answers (appended)")
    ap.add_argument("--only", help="request ids (case__chunk), comma-separated or a file")
    ap.add_argument("--limit", type=int, help="ask at most N chunks")
    ap.add_argument("--threshold", type=float, default=0.8)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--fix-list", help="write the paragraphs to repair here")
    ap.add_argument("--travaux", default=str(Path.home() / "Desktop/AI/travaux"), help="travaux project (Jev client)")
    ap.add_argument("--jev", action="store_true", help="call TypeSafe (sends the paragraphs' text)")
    args = ap.parse_args()

    wanted = None
    if args.only:
        wanted = set(Path(args.only).read_text().split() if Path(args.only).is_file() else args.only.split(","))
    cache = load_cache(args.cache)
    chunks, fix, stats = collect_chunks(args.jobs, args.suffix.split(","), wanted)
    todo = [(rid, rows) for rid, rows in chunks if rows and any(r["key"] not in cache for r in rows)]
    if args.limit:
        todo = todo[: args.limit]
    print(json.dumps({**stats, "chunks_to_ask": len(todo), "answers_cached": len(cache)}), file=sys.stderr)

    if todo and args.jev:
        sys.path.insert(0, str(Path(args.travaux) / "pipeline"))
        import jev  # noqa: E402  travaux's client: reads TYPESAFE_API_KEY, retries, logs usage
        done = failed = 0
        with ThreadPoolExecutor(max_workers=args.workers) as pool, open(args.cache, "a") as out:
            futures = {pool.submit(ask_chunk, jev, rows): (rid, rows) for rid, rows in todo}
            for fut in as_completed(futures):
                rid, rows = futures[fut]
                try:
                    answers = fut.result()
                except Exception as exc:                                  # noqa: BLE001 - ask again next run
                    failed += 1
                    print(f"  {rid}: {str(exc)[:200]}", file=sys.stderr)
                    continue
                for r in rows:
                    cache[r["key"]] = answers.get(r["id"])
                    out.write(json.dumps({"key": r["key"], "p": answers.get(r["id"])}) + "\n")
                done += 1
                if done % 100 == 0:
                    out.flush()
                    print(f"  {done}/{len(todo)} chunks asked", file=sys.stderr)
        print(f"  asked {done} chunks, {failed} failed (asked again on the next run)", file=sys.stderr)
    elif todo:
        print("rerun with --jev to ask Jev (sends the paragraphs' text to TypeSafe)", file=sys.stderr)

    low = unanswered = judged = 0
    for rid, rows in chunks:
        for r in rows:
            if r["key"] not in cache:
                continue
            judged += 1
            p = cache[r["key"]]
            if p is None:
                unanswered += 1
                fix.add(f"{rid} {r['id']}")
            elif p < args.threshold:
                low += 1
                fix.add(f"{rid} {r['id']}")
    print(json.dumps({"rows_judged": judged, f"rows_below_{args.threshold}": low, "rows_unanswered": unanswered,
                      "rows_to_repair": len(fix), "chunks_to_repair": len({x.split()[0] for x in fix}),
                      "rows": stats["rows"]}))
    if args.fix_list:
        Path(args.fix_list).write_text("\n".join(sorted(fix)) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
