#!/usr/bin/env python3
"""Build a compact FAISS IVF-PQ index from the voyage embeddings, then compare
EXACT vs ANN retrieval on the benchmark (recall@50 + docHit/paraHit with the
+0.05 importance boost). Confirms whether quantization preserves our gains.

  python3 ann_build_eval.py --build       # build + save index (once)
  python3 ann_build_eval.py --eval --nprobe 32
"""
from __future__ import annotations
import argparse, json, time
from collections import defaultdict
from pathlib import Path
import numpy as np
import faiss, embed
from eval_voyage import load_emb, topk_scores

HERE = Path(__file__).resolve().parent
IDXP = HERE / "data" / "ann_index.index"
IMP = {"Key cases": 1.0, "1": 1.0, "2": 0.5, "3": 0.25, "Unspecified": 0.0}
POOL = 50

def norm_rows(a):
    a = np.ascontiguousarray(a, dtype=np.float32)
    faiss.normalize_L2(a); return a

def build(vecs, n, dim, kind="sq"):
    nlist = 4096
    quant = faiss.IndexFlatIP(dim)
    if kind == "sq":   # 8-bit scalar quant: ~1 byte/dim -> ~1.3GB, near-exact recall
        index = faiss.IndexIVFScalarQuantizer(quant, dim, nlist,
                    faiss.ScalarQuantizer.QT_8bit, faiss.METRIC_INNER_PRODUCT)
    else:              # product quant: tiny (~110MB) but lossy
        index = faiss.IndexIVFPQ(quant, dim, nlist, 64, 8, faiss.METRIC_INNER_PRODUCT)
    rng = np.random.default_rng(0)
    tr = rng.choice(n, size=min(300000, n), replace=False)
    print(f"[train] {len(tr):,} sample vectors ...", flush=True)
    index.train(norm_rows(np.array(vecs[np.sort(tr)])))
    print("[add] streaming all vectors ...", flush=True)
    for s in range(0, n, 100000):
        e = min(s + 100000, n)
        index.add(norm_rows(np.array(vecs[s:e])))
        print(f"  added {e:,}/{n:,}", end="\r", flush=True)
    print()
    faiss.write_index(index, str(IDXP))
    mb = IDXP.stat().st_size / 1e6
    print(f"[done] index saved {IDXP}  ({mb:.0f} MB)")

def eval_(nprobe):
    items = [json.loads(l) for l in open(HERE.parent / "data" / "items_sample.jsonl", encoding="utf-8")]
    vecs, case, sec, dim, n = load_emb("voyage-4-large")
    meta = json.loads((HERE / "data" / "cases_meta.json").read_text())
    auth = np.array([IMP.get((meta.get(case[i], {}) or {}).get("importance"), 0.0) for i in range(n)], dtype=np.float32)
    index = faiss.read_index(str(IDXP)); index.nprobe = nprobe

    qv = np.array(embed.voyage_embed([(it["query"] or "")[:1500] for it in items],
                                     model="voyage-4-large", input_type="query"), dtype=np.float32)
    qn = qv.copy(); faiss.normalize_L2(qn)
    # exact top-POOL (brute force) and ANN top-POOL
    exact = topk_scores(qn, vecs, n, dim, POOL)
    t0 = time.time(); _D, ann = index.search(qn, POOL); ann_ms = 1000 * (time.time() - t0) / len(items)

    def score(nn_idx, B):
        agg = defaultdict(float); npin = 0
        for qi, it in enumerate(items):
            gd = set(it["expectedDocIds"]); gr = {(r["case_id"], r["section_no"]) for r in it.get("expectedParaRefs", [])}
            idx = [p for p in nn_idx[qi] if p >= 0]
            cosd = {}
            for p in idx:
                v = np.asarray(vecs[p], dtype=np.float32)
                cosd[p] = float(v @ qn[qi]) / (float(np.linalg.norm(v)) + 1e-9)
            scored = sorted(idx, key=lambda p: -(cosd[p] + B * auth[p]))
            cs, cse, pk, pse = [], set(), [], set()
            for p in scored:
                c = case[p]; s = int(sec[p])
                if c not in cse: cse.add(c); cs.append(c)
                if s >= 0 and (c, s) not in pse: pse.add((c, s)); pk.append((c, s))
            if gr: npin += 1
            for x in (5, 10): agg[f"doc{x}"] += bool(gd & set(cs[:x]))
            if gr:
                for x in (5, 10): agg[f"para{x}"] += bool(gr & set(pk[:x]))
        N = len(items)
        return (100*agg['doc5']/N, 100*agg['doc10']/N, 100*agg['para5']/npin, 100*agg['para10']/npin)

    # recall@50 of ANN vs exact candidate sets
    rec = np.mean([len(set(ann[i]) & set(exact[i])) / POOL for i in range(len(items))])
    print(f"\n=== EXACT vs ANN (IVF-PQ, nprobe={nprobe}) — 409 items ===")
    print(f"  ANN recall@{POOL} vs exact: {100*rec:.1f}%   ANN latency: {ann_ms:.1f} ms/query")
    print(f"\n  {'config':<16}{'docHit@5':>10}{'docHit@10':>11}{'paraHit@5':>11}{'paraHit@10':>12}")
    for label, nn_idx, B in [("exact +imp", exact, 0.05), ("ANN +imp", ann, 0.05),
                             ("exact (no boost)", exact, 0.0), ("ANN (no boost)", ann, 0.0)]:
        d5, d10, p5, p10 = score(nn_idx, B)
        print(f"  {label:<16}{d5:>9.1f}%{d10:>10.1f}%{p5:>10.1f}%{p10:>11.1f}%")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--eval", action="store_true")
    ap.add_argument("--nprobe", type=int, default=32)
    a = ap.parse_args()
    if a.build:
        vecs, case, sec, dim, n = load_emb("voyage-4-large")
        build(vecs, n, dim)
    if a.eval:
        eval_(a.nprobe)

if __name__ == "__main__":
    main()
