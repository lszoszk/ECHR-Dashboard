#!/usr/bin/env python3
"""Phase B embedding client — provider-pluggable (Voyage / Gemini), HTTP only.

Key handling: read from env VOYAGE_API_KEY / GEMINI_API_KEY, else from a gitignored
file next to this script (phaseB/voyage_key or phaseB/gemini_key). NEVER hardcode.

Pilot:  python3 embed.py --pilot --model voyage-4-large
  → embeds a few benchmark queries, prints dim/latency + a cosine sanity check
    (confirms key works + model exists on your account).

Batch:  embed_texts(texts, model, input_type) → list[list[float]]
"""
from __future__ import annotations
import json, ssl, sys, time, urllib.request, urllib.error
from pathlib import Path

HERE = Path(__file__).resolve().parent
VOYAGE_URL = "https://api.voyageai.com/v1/embeddings"
VOYAGE_RERANK_URL = "https://api.voyageai.com/v1/rerank"

def _sslctx():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()
_SSL = _sslctx()

def load_key(provider="voyage"):
    import os
    env = {"voyage": "VOYAGE_API_KEY", "gemini": "GEMINI_API_KEY"}[provider]
    k = os.environ.get(env, "").strip()
    if k: return k
    f = HERE / f"{provider}_key"
    if f.exists():
        return f.read_text().strip()
    raise SystemExit(f"No {provider} key. Set ${env} or put it in {f} (gitignored).")

def _embed_request(chunk, model, input_type, key):
    """POST one chunk. On the 120K-token batch error, halve and retry (self-heal)
    so a token-estimate miss never crashes the run. Returns list of embeddings."""
    body = json.dumps({"input": chunk, "model": model, "input_type": input_type}).encode()
    req = urllib.request.Request(VOYAGE_URL, data=body, method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120, context=_SSL) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", "ignore")[:300]
        if e.code == 400 and "max allowed tokens" in msg and len(chunk) > 1:
            mid = len(chunk) // 2
            print(f"  [split] batch of {len(chunk)} over token cap -> {mid}+{len(chunk)-mid}")
            return _embed_request(chunk[:mid], model, input_type, key) + \
                   _embed_request(chunk[mid:], model, input_type, key)
        raise SystemExit(f"Voyage HTTP {e.code}: {msg}")
    if data.get("usage"):
        print(f"  request: {len(chunk)} texts, {data['usage'].get('total_tokens','?')} tokens")
    return [d["embedding"] for d in sorted(data["data"], key=lambda x: x["index"])]

def voyage_embed(texts, model="voyage-4-large", input_type="document", key=None, batch=128):
    key = key or load_key("voyage")
    out = []
    for i in range(0, len(texts), batch):
        out.extend(_embed_request(texts[i:i+batch], model, input_type, key))
    return out

def voyage_rerank(query, documents, model="rerank-2.5", top_k=None, key=None):
    """Return list of (orig_index, relevance_score) sorted best-first.

    A single 429 (rate limit) is retried once after a short backoff: measured
    Aug 2026, bursty traffic tripped 429s on ~5% of consecutive calls and each
    silently degraded that query to plain cosine order.  Anything else, and a
    second 429, still fail fast to the cosine fallback in rag_mod."""
    key = key or load_key("voyage")
    body = {"query": query[:4000], "documents": documents, "model": model}
    if top_k: body["top_k"] = top_k
    payload = json.dumps(body).encode()
    for attempt in (0, 1):
        req = urllib.request.Request(VOYAGE_RERANK_URL, data=payload, method="POST",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=120, context=_SSL) as r:
                data = json.loads(r.read())
            break
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "ignore")[:300]
            if e.code == 429 and attempt == 0:
                time.sleep(2.5); continue
            raise SystemExit(f"Voyage rerank HTTP {e.code}: {detail}")
    res = [(d["index"], d["relevance_score"]) for d in data["data"]]
    res.sort(key=lambda x: -x[1])
    return res

def cosine(a, b):
    import math
    dot = sum(x*y for x, y in zip(a, b))
    na = math.sqrt(sum(x*x for x in a)); nb = math.sqrt(sum(y*y for y in b))
    return dot/(na*nb) if na and nb else 0.0

def pilot(model):
    items = [json.loads(l) for l in open(HERE.parents[0] / "data" / "items_sample.jsonl")][:8]
    qs = [it["query"][:1500] for it in items]
    print(f"[pilot] embedding {len(qs)} benchmark queries with {model} ...")
    t0 = time.time()
    vecs = voyage_embed(qs, model=model, input_type="query")
    dt = time.time() - t0
    print(f"[ok] dim={len(vecs[0])}  latency={dt:.1f}s  ({len(qs)} texts)")
    # sanity: two same-guide propositions should be more similar than unrelated ones
    print(f"  cosine(q0,q1)={cosine(vecs[0],vecs[1]):.3f}  cosine(q0,q7)={cosine(vecs[0],vecs[7]):.3f}")
    print("  (positive, <1, and varying = embeddings look healthy)")

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", action="store_true")
    ap.add_argument("--model", default="voyage-4-large")
    a = ap.parse_args()
    if a.pilot: pilot(a.model)
    else: print("use --pilot to validate, or import embed_texts/voyage_embed")
