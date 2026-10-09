#!/usr/bin/env python3
"""
Translate job files (prepare.py) through the Claude Message Batches API (half the price of single
requests, results within 24 hours, usually minutes).

    export ANTHROPIC_API_KEY=...      # never in the repo
    python3 scripts/mt/translate.py submit  --jobs mt_pilot/jobs --model claude-haiku-5-5 --tag haiku
    python3 scripts/mt/translate.py collect --jobs mt_pilot/jobs --tag haiku     # repeat until done

`submit` sends one request per chunk_NNN.json (system prompt = TRANSLATOR.md, user message = the job)
and records the batch in <jobs>/batch_<tag>.json. `collect` checks the batch; once it has ended it
writes chunk_NNN.<tag>.json ({"row id": "English"}) beside each job and prints the token usage.
Different tags keep the output of different models apart; assemble.py --suffix <tag> scores one.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import anthropic

HERE = Path(__file__).resolve().parent
INSTRUCTIONS = (HERE / "TRANSLATOR.md").read_text()
MAX_TOKENS = 8192


def user_message(job: dict) -> str:
    payload = {k: job[k] for k in ("case", "context_before", "glossary", "examples")}
    payload["rows"] = [{k: r.get(k) for k in ("id", "section", "role", "para_no", "fr")} for r in job["rows"]]
    return ("Translate the rows of this job. Answer with the JSON object only.\n\n"
            + json.dumps(payload, ensure_ascii=False))


def parse_answer(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    return json.loads(text[text.find("{"): text.rfind("}") + 1])


def submit(args) -> None:
    jobs = sorted(Path(args.jobs).glob("*/chunk_[0-9][0-9][0-9].json"))
    if args.only:
        wanted = set(Path(args.only).read_text().split() if Path(args.only).is_file() else args.only.split(","))
        jobs = [jf for jf in jobs if f"{jf.parent.name}__{jf.stem[6:]}" in wanted]
    jobs = jobs[args.offset:]
    if args.limit:
        jobs = jobs[: args.limit]
    requests = []
    for jf in jobs:
        job = json.loads(jf.read_text())
        requests.append({
            "custom_id": f"{jf.parent.name}__{jf.stem[6:]}",
            "params": {"model": args.model, "max_tokens": MAX_TOKENS, "thinking": {"type": args.thinking},
                       "system": INSTRUCTIONS,
                       "messages": [{"role": "user", "content": user_message(job)}]},
        })
    batch = anthropic.Anthropic().messages.batches.create(requests=requests)
    record = {"batch_id": batch.id, "model": args.model, "thinking": args.thinking, "requests": len(requests)}
    Path(args.jobs, f"batch_{args.tag}.json").write_text(json.dumps(record, indent=1))
    print(f"submitted {len(requests)} requests as {batch.id} ({args.model}); run collect --tag {args.tag}")


def collect(args) -> None:
    record = json.loads(Path(args.jobs, f"batch_{args.tag}.json").read_text())
    client = anthropic.Anthropic()
    batch = client.messages.batches.retrieve(record["batch_id"])
    if batch.processing_status != "ended":
        print(f"{batch.processing_status}: {batch.request_counts}")
        return
    usage = {"input_tokens": 0, "output_tokens": 0}
    ok, failed = 0, []
    for entry in client.messages.batches.results(record["batch_id"]):
        case, chunk = entry.custom_id.split("__")
        if entry.result.type != "succeeded":
            detail = getattr(getattr(entry.result, "error", None), "error", None)
            failed.append((entry.custom_id, entry.result.type, str(detail or "")))
            continue
        msg = entry.result.message
        usage["input_tokens"] += msg.usage.input_tokens
        usage["output_tokens"] += msg.usage.output_tokens
        try:
            answer = parse_answer("".join(b.text for b in msg.content if b.type == "text"))
        except ValueError as e:
            failed.append((entry.custom_id, f"unparsable answer ({e}; stop_reason {msg.stop_reason})"))
            continue
        Path(args.jobs, case, f"chunk_{chunk}.{args.tag}.json").write_text(json.dumps(answer, ensure_ascii=False))
        ok += 1
    record.update({"collected": ok, "failed": failed, "usage": usage})
    Path(args.jobs, f"batch_{args.tag}.json").write_text(json.dumps(record, indent=1))
    print(json.dumps({k: record.get(k) for k in ("model", "thinking", "requests", "collected", "usage")}))
    for f in failed:
        print("  failed", *f)


def cancel(args) -> None:
    record = json.loads(Path(args.jobs, f"batch_{args.tag}.json").read_text())
    batch = anthropic.Anthropic().messages.batches.cancel(record["batch_id"])
    print(f"{batch.processing_status}: {batch.request_counts} (finished requests stay collectable)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("submit")
    s.add_argument("--jobs", required=True)
    s.add_argument("--model", required=True)
    s.add_argument("--tag", required=True)
    s.add_argument("--thinking", choices=["disabled", "adaptive"], default="disabled",
                   help="reasoning before the answer: billed as output tokens; off by default")
    s.add_argument("--only", help="request ids (case__chunk, as collect prints them), comma-separated or a file")
    s.add_argument("--offset", type=int, default=0, help="skip the first N chunks (to send a large set in parts)")
    s.add_argument("--limit", type=int, help="only N chunks (a dry run, or one part)")
    c = sub.add_parser("collect")
    c.add_argument("--jobs", required=True)
    c.add_argument("--tag", required=True)
    k = sub.add_parser("cancel", help="cancel a batch that has not finished; unprocessed requests are not billed")
    k.add_argument("--jobs", required=True)
    k.add_argument("--tag", required=True)
    args = ap.parse_args()
    {"submit": submit, "collect": collect, "cancel": cancel}[args.cmd](args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
