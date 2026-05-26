#!/usr/bin/env python3
"""Phase B — score a Voyage embedding set on the guides benchmark.

Loads data/emb/<model>/{ids.jsonl,vecs.f32.dat}, embeds the benchmark queries
(input_type='query'), and computes docHit@k / paraHit@k / MRR / recall.

Unlike the Chroma harness, paraHit is EXACT: every embedded row carries its true
(case_id, section_no) from the DB, so no leading-number regex is needed.

Dense-only here (the pure embedding signal — that's what the bake-off compares).
Memory-bounded: the N×dim matrix is read from a memmap in row-chunks; a running
top-K per query is kept, so peak RAM ≈ one chunk, not the whole 5GB matrix.

  python3 eval_voyage.py --model voyage-4-large
  python3 eval_voyage.py --model voyage-4-large --items ../data/items_sample.jsonl --topk 20
"""
from __future__ import annotations
import argparse, json, struct, sys, time
from pathlib import Path
from collections import defaultdict
import numpy as np
import embed

HERE = Path(__file__).resolve().parent
DEF_ITEMS = HERE.parent / "data" / "items_sample.jsonl"

def load_emb(model):
    d = HERE / "data" / "emb" / model
    meta = json.loads((d / "meta.json").read_text())
    dim = meta["dim"]
    ids = [json.loads(l) for l in open(d / "ids.jsonl", encoding="utf-8")]
    n = len(ids)
    vecs = np.memmap(d / "vecs.f32.dat", dtype="<f4", mode="r", shape=(n, dim))
    case = np.array([x["case_id"] for x in ids], dtype=object)
    sec = np.array([(-1 if x["section_no"] is None else x["section_no"]) for x in ids], dtype=np.int64)
    return vecs, case, sec, dim, n

def topk_scores(qmat, vecs, n, dim, K, chunk=100_000):
    """qmat: (Q,dim) L2-normalized. Returns (Q,K) row-indices of nearest corpus rows."""
    Q = qmat.shape[0]
    best_idx = np.full((Q, K), -1, dtype=np.int64)
    best_val = np.full((Q, K), -1e9, dtype=np.float32)
    for s in range(0, n, chunk):
        e = min(s + chunk, n)
        block = np.array(vecs[s:e], dtype=np.float32)  # copy (memmap slice is read-only)
        nrm = np.linalg.norm(block, axis=1, keepdims=True); nrm[nrm == 0] = 1
        block /= nrm
        sims = qmat @ block.T            # (Q, e-s)
        merged_val = np.concatenate([best_val, sims], axis=1)
        merged_idx = np.concatenate([best_idx, np.broadcast_to(np.arange(s, e), (Q, e - s))], axis=1)
        part = np.argpartition(-merged_val, K - 1, axis=1)[:, :K]
        best_val = np.take_along_axis(merged_val, part, axis=1)
        best_idx = np.take_along_axis(merged_idx, part, axis=1)
        print(f"  scanned {e:,}/{n:,}", end="\r", file=sys.stderr, flush=True)
    print(file=sys.stderr)
    # final sort within the K
    order = np.argsort(-best_val, axis=1)
    return np.take_along_axis(best_idx, order, axis=1)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="voyage-4-large")
    ap.add_argument("--items", default=str(DEF_ITEMS))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--topk", type=int, default=20)
    ap.add_argument("--chunk", type=int, default=100_000)
    a = ap.parse_args()

    items = [json.loads(l) for l in open(a.items, encoding="utf-8")]
    if a.limit: items = items[:a.limit]
    print(f"[load] emb model={a.model}")
    vecs, case, sec, dim, n = load_emb(a.model)
    print(f"[load] {n:,} rows, dim={dim}")

    qtexts = [(it["query"] or "")[:1500] for it in items]
    print(f"[embed] {len(qtexts)} queries ...")
    qv = embed.voyage_embed(qtexts, model=a.model, input_type="query")
    qmat = np.array(qv, dtype=np.float32)
    qmat /= (np.linalg.norm(qmat, axis=1, keepdims=True) + 1e-9)

    t0 = time.time()
    nn = topk_scores(qmat, vecs, n, dim, a.topk, chunk=a.chunk)
    print(f"[search] {time.time()-t0:.0f}s")

    agg = defaultdict(float); npin = 0; N = len(items)
    for i, it in enumerate(items):
        gold_docs = set(it["expectedDocIds"])
        gold_refs = {(r["case_id"], r["section_no"]) for r in it.get("expectedParaRefs", [])}
        idxs = nn[i]
        cases, cseen = [], set()
        pkeys, pseen = [], set()
        for j in idxs:
            cid = case[j]; sc = int(sec[j])
            if cid not in cseen: cseen.add(cid); cases.append(cid)
            if sc != -1:
                k = (cid, sc)
                if k not in pseen: pseen.add(k); pkeys.append(k)
        fr = next((r for r, c in enumerate(cases) if c in gold_docs), None)
        if fr is not None: agg["mrr"] += 1.0 / (fr + 1)
        agg["recall10"] += len(gold_docs & set(cases[:10])) / max(1, len(gold_docs))
        for x in (1, 5, 10, 20): agg[f"doc{x}"] += bool(gold_docs & set(cases[:x]))
        if gold_refs:
            npin += 1
            for x in (1, 5, 10, 20): agg[f"para{x}"] += bool(gold_refs & set(pkeys[:x]))

    pct = lambda k, d: 100 * agg[k] / d if d else 0.0
    print(f"\n{'='*60}\n  VOYAGE DENSE — {a.model} — {N} items, {npin} pinpoint\n{'='*60}")
    for lab, key, d in [("docHit@1","doc1",N),("docHit@5","doc5",N),("docHit@10","doc10",N),
                        ("docHit@20","doc20",N),("recall@10","recall10",N),
                        ("paraHit@1","para1",npin),("paraHit@5","para5",npin),
                        ("paraHit@10","para10",npin),("paraHit@20","para20",npin)]:
        print(f"  {lab:<12}{pct(key,d):6.1f}%")
    print(f"  {'MRR(doc)':<12}{agg['mrr']/N:6.3f}")
    print("=" * 60)
    out = {"model": a.model, "n": N, "n_pinpoint": npin, "topk": a.topk,
           "docHit@1": round(pct('doc1',N)/100,4), "docHit@5": round(pct('doc5',N)/100,4),
           "docHit@10": round(pct('doc10',N)/100,4), "docHit@20": round(pct('doc20',N)/100,4),
           "recall@10": round(pct('recall10',N)/100,4), "MRR": round(agg['mrr']/N,4),
           "paraHit@1": round(pct('para1',npin)/100,4) if npin else None,
           "paraHit@5": round(pct('para5',npin)/100,4) if npin else None,
           "paraHit@10": round(pct('para10',npin)/100,4) if npin else None,
           "paraHit@20": round(pct('para20',npin)/100,4) if npin else None}
    op = HERE / "data" / f"results_{a.model}.json"
    op.write_text(json.dumps(out, indent=1))
    print(f"wrote {op}")

if __name__ == "__main__":
    main()
