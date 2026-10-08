#!/usr/bin/env python3
"""Phase B — embed the Option C corpus, checkpointed & resumable.

Reads data/corpus_textsC.jsonl.gz (rowid/case_id/section_no/section/text),
embeds `text` with the chosen provider/model (document input_type), and writes
to data/emb/<model>/ :
  - ids.jsonl     one {"rowid","case_id","section_no"} per embedded row, in order
  - vecs.f32.dat  raw float32 matrix (N x dim), row-aligned with ids.jsonl
  - meta.json     {"model","dim","n","done"}  (checkpoint)

Resumable: re-running skips the rows already in ids.jsonl. A Voyage quota stop
(HTTP 429) just halts cleanly; re-run continues from the checkpoint.

  python3 embed_corpus.py --model voyage-4-large
  python3 embed_corpus.py --model voyage-4-large --ids-file data/bakeoff_pool.txt   # subset
  python3 embed_corpus.py --model voyage-4-large --limit 2000                        # smoke test

Key: env VOYAGE_API_KEY or gitignored phaseB/voyage_key (see embed.load_key).
"""
from __future__ import annotations
import gzip, json, struct, sys, time
from pathlib import Path
import embed  # local module (voyage_embed, load_key)

HERE = Path(__file__).resolve().parent
CORPUS = HERE / "data" / "corpus_textsC.jsonl.gz"
MAXCHARS = 32000  # voyage per-input cap is generous; clip pathological rows

def iter_corpus(ids_filter=None):
    op = gzip.open(CORPUS, "rt", encoding="utf-8")
    for line in op:
        r = json.loads(line)
        if ids_filter is not None and r["rowid"] not in ids_filter:
            continue
        yield r

def already_done(outdir):
    f = outdir / "ids.jsonl"
    if not f.exists():
        return 0, set()
    done_rowids = set()
    n = 0
    with open(f) as fh:
        for line in fh:
            done_rowids.add(json.loads(line)["rowid"]); n += 1
    return n, done_rowids

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="voyage-4-large")
    ap.add_argument("--provider", default="voyage")
    ap.add_argument("--batch", type=int, default=1000, help="max texts per request (Voyage cap 1000)")
    ap.add_argument("--tok-budget", type=int, default=110000, help="max est tokens per request (Voyage cap 120k)")
    ap.add_argument("--limit", type=int, default=0, help="embed at most N new rows (smoke test)")
    ap.add_argument("--ids-file", default="", help="optional file of rowids (one per line) to restrict to")
    a = ap.parse_args()

    ids_filter = None
    if a.ids_file:
        ids_filter = {int(x) for x in open(a.ids_file) if x.strip()}
        print(f"[subset] restricting to {len(ids_filter):,} rowids from {a.ids_file}")

    outdir = HERE / "data" / "emb" / a.model
    outdir.mkdir(parents=True, exist_ok=True)
    n_done, done_rowids = already_done(outdir)
    if n_done:
        print(f"[resume] {n_done:,} rows already embedded; skipping those")

    key = embed.load_key(a.provider)  # fails fast with a clear message if missing
    ids_fh = open(outdir / "ids.jsonl", "a", encoding="utf-8")
    vec_fh = open(outdir / "vecs.f32.dat", "ab")
    dim = None
    t0 = time.time(); n_new = 0; tok = 0

    buf_rows, buf_txt, buf_tok = [], [], [0]  # buf_tok[0] = running est-token sum
    def flush():
        nonlocal dim, n_new, tok
        if not buf_txt:
            return
        # one request for the whole (token-bounded) buffer
        vecs = embed.voyage_embed(buf_txt, model=a.model, input_type="document", key=key, batch=len(buf_txt))
        if dim is None:
            dim = len(vecs[0])
            print(f"[dim] {dim}")
        for r, v in zip(buf_rows, vecs):
            ids_fh.write(json.dumps({"rowid": r["rowid"], "case_id": r["case_id"],
                                     "section_no": r["section_no"]}, ensure_ascii=False) + "\n")
            vec_fh.write(struct.pack(f"<{len(v)}f", *v))
        ids_fh.flush(); vec_fh.flush()
        n_new += len(buf_rows)
        buf_rows.clear(); buf_txt.clear(); buf_tok[0] = 0

    for r in iter_corpus(ids_filter):
        if r["rowid"] in done_rowids:
            continue
        t = (r["text"] or "")[:MAXCHARS]
        et = max(1, int(len(t) / 2.6))  # conservative token estimate (dense legal/numeric text ~2.7 chars/tok)
        # flush before adding if this row would breach either cap
        if buf_txt and (len(buf_txt) >= a.batch or buf_tok[0] + et > a.tok_budget):
            flush()
        buf_rows.append(r); buf_txt.append(t); buf_tok[0] += et
        if len(buf_txt) >= a.batch or buf_tok[0] >= a.tok_budget:
            flush()
            rate = n_new / (time.time() - t0)
            tot = n_done + n_new
            print(f"  embedded {n_new:,} new (total {tot:,}, {rate:.0f} rows/s)", flush=True)
        # --limit is checked HERE, outside the branch above, because most
        # flushes happen on the earlier token-budget path a few lines up. With
        # the check nested in that branch, --limit was silently ignored and a
        # "smoke test" ran the entire corpus.
        if a.limit and n_new >= a.limit:
            break
    flush()

    meta = {"model": a.model, "dim": dim, "n": n_done + n_new,
            "done": ids_filter is None and not a.limit}
    (outdir / "meta.json").write_text(json.dumps(meta, indent=2))
    ids_fh.close(); vec_fh.close()
    dt = time.time() - t0
    print(f"[done] +{n_new:,} new rows in {dt:.0f}s  total={meta['n']:,}  -> {outdir}")

if __name__ == "__main__":
    main()
