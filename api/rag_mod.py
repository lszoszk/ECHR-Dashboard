"""RAG sub-application mounted into echr-api at /rag.

Lazy-loads a MEMORY-MAPPED FAISS SQ8 index + metadata from /data/rag (low RAM —
the index stays on disk, OS page-cache reclaimable). Loading happens on first
request, so the dashboard API isn't delayed at container start and RAM is only
used if the RAG is actually queried.

Pipeline: voyage-4-large embedding -> FAISS mmap ANN -> rerank-2.5 (top 100)
-> +importance authority boost -> group by case.
Endpoints (served under /echr-api/rag via nginx): / , /health , /respondents ,
/sections , /similar .
"""
from __future__ import annotations
import os, json, math, sqlite3, time, threading
from pathlib import Path
from collections import OrderedDict
import numpy as np, faiss
from fastapi import FastAPI, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
import embed  # voyage HTTP client (ships alongside in backend/)

BASE = Path("/data/rag")
STATIC = Path(__file__).resolve().parent / "rag_static"
VOYAGE_MODEL = "voyage-4-large"; RERANK_MODEL = "rerank-2.5"
NPROBE = 128; FETCH = 300; RERANK_POOL = 100; IMP_BOOST = 0.05
# Hybrid lexical arm (P0 measurement, Aug 2026): case-level OR-mode BM25 fused
# with the dense ranking. Offline on the de-anchoring benchmark: expert-register
# queries 87.7 -> 92.9 docHit@10, raw 94.8 -> 97.3, lay ~unchanged (at ceiling).
# Contentless FTS5 (index only, no stored text): 181 MB. Optional — absent file
# or ECHR_HYBRID=0 simply disables fusion.
HYBRID_KEEP = 5   # max keyword-only cases appended per query
SEP_PENALTY = 0.12  # demote separate/dissenting-opinion paragraphs so the Court's holding ranks first
# Legal Framework sections quote instruments (constitutions, statutes,
# Convention articles), not the Court's reasoning — a bare "privacy" surfaced
# 4/5 quoted constitutions at the top.  Milder than SEP_PENALTY: these hits
# stay in the list (they ARE the answer when the user hunts a provision),
# they just must not outrank Merits at comparable relevance.
LF_PENALTY = 0.06
IMP = {"Key cases": 1.0, "1": 1.0, "2": 0.5, "3": 0.25, "Unspecified": 0.0}
RANK_TOP, RANK_AVG, RANK_LOG = 0.60, 0.25, 0.15; LOGD = math.log(10)

_S = {}  # lazy-loaded state

# Query-embedding LRU cache: identical queries skip the Voyage embed call
# (~300ms faster on repeats) and return the same vector → deterministic ranking.
_QCACHE = OrderedDict(); _QLOCK = threading.Lock(); QCACHE_MAX = 512

def _embed_query(q):
    key = (q or "")[:1500]
    with _QLOCK:
        hit = _QCACHE.get(key)
        if hit is not None:
            _QCACHE.move_to_end(key); return hit.copy()
    qv = np.array(embed.voyage_embed([key], model=VOYAGE_MODEL, input_type="query")[0], dtype="float32").reshape(1, -1)
    faiss.normalize_L2(qv)
    with _QLOCK:
        _QCACHE[key] = qv; _QCACHE.move_to_end(key)
        while len(_QCACHE) > QCACHE_MAX: _QCACHE.popitem(last=False)
    return qv.copy()

def _load():
    if _S:
        return _S
    kf = BASE / "voyage_key"
    if kf.exists() and not os.environ.get("VOYAGE_API_KEY"):
        os.environ["VOYAGE_API_KEY"] = kf.read_text().strip()
    idx = faiss.read_index(str(BASE / "ann_index.index"), faiss.IO_FLAG_MMAP); idx.nprobe = NPROBE
    ids = [json.loads(l) for l in open(BASE / "ids.jsonl", encoding="utf-8")]
    rowsec = {}
    for l in open(BASE / "row_section.tsv", encoding="utf-8"):
        a, b = l.rstrip("\n").split("\t"); rowsec[int(a)] = b
    art = {}
    for l in open(BASE / "para_articles.tsv", encoding="utf-8"):
        c, s, t = l.rstrip("\n").split("\t"); art[(c, int(s))] = t
    meta = json.loads((BASE / "cases_meta.json").read_text())
    resp = set()
    for m in meta.values():
        for x in str((m or {}).get("state", "")).split(","):
            x = x.strip()
            if x: resp.add(x)
    docfts = None
    dfp = BASE / "docs_fts.db"
    if dfp.exists() and os.environ.get("ECHR_HYBRID", "1").lower() not in ("0", "false", "no"):
        docfts = sqlite3.connect(f"file:{dfp}?mode=ro", uri=True, check_same_thread=False)
    _S.update(docfts=docfts,
              index=idx, case=[r["case_id"] for r in ids], sno=[r["section_no"] for r in ids],
              rid=[r["rowid"] for r in ids], meta=meta, rowsec=rowsec, artmap=art,
              fts=sqlite3.connect(f"file:{BASE/'corpus_fts.db'}?mode=ro", uri=True, check_same_thread=False),
              respondents=sorted(resp), sections=sorted({v for v in rowsec.values() if v}))
    return _S

def _cit():
    S = _load()
    if "citgraph" not in S:  # lazy: only parsed if the citation view is used
        f = BASE / "citations.json"
        S["citgraph"] = json.loads(f.read_text()) if f.exists() else {}
    return S["citgraph"]

def _auth(cid): return IMP.get((_load()["meta"].get(cid, {}) or {}).get("importance"), 0.0)
def _split(raw): return [p.strip() for p in (raw or "").split(",") if p.strip()]

def run_paragraph_search(q, respondent=None, article=None, section=None):
    S = _load()
    qv = _embed_query(q)
    fetch = FETCH if not (respondent or article or section) else FETCH * 2
    D, I = S["index"].search(qv, fetch)
    case, sno, rid, meta, rowsec, art, fts = S["case"], S["sno"], S["rid"], S["meta"], S["rowsec"], S["artmap"], S["fts"]
    pos = [int(i) for i in I[0] if i >= 0]; rids = [rid[p] for p in pos]
    txt = {}
    if rids:
        txt = {r: t for r, t in fts.execute("SELECT rid,text FROM para WHERE rid IN (%s)" % ",".join("?" * len(rids)), rids)}
    cand = []
    for scr, p in zip(D[0], pos):
        cid = case[p]; s = sno[p]; m = meta.get(cid, {}) or {}
        if s is None or s == 0: continue  # skip uncitable sub-fragments (no HUDOC § number → would render as ¶0)
        if respondent and respondent not in _split(m.get("state", "")): continue
        arts = [str(x) for x in (m.get("violation") or [])]
        if article and article not in arts and art.get((cid, s)) != article: continue
        sec = rowsec.get(rid[p], "")
        if section and sec != section: continue
        cand.append((p, float(scr), sec, m, arts))
    rr = None; src = cand
    if len(cand) > 1:
        head = cand[:RERANK_POOL]; docs = [(txt.get(rid[p]) or "")[:1200] for p, *_ in head]
        try:
            rr = {i: sc for i, sc in embed.voyage_rerank(q, docs, model=RERANK_MODEL)}; src = head
        except SystemExit:
            rr = None; src = cand
    out = []
    for idx, (p, cos, sec, m, arts) in enumerate(src):
        cid = case[p]; s = sno[p]; base = rr.get(idx, 0.0) if rr is not None else cos
        pen = SEP_PENALTY if sec == "Separate Opinion" else LF_PENALTY if sec == "Legal Framework" else 0.0
        out.append({"score": round(float(base) + IMP_BOOST * _auth(cid) - pen, 4), "case_id": cid,
            "case_no": m.get("case_no", "") or "", "title": m.get("title", "") or "", "hudoc_url": m.get("hudoc", "") or "",
            "judgment_date": m.get("date", "") or "", "respondent": m.get("state", "") or "", "articles": arts,
            "section": sec, "para_idx": s if s is not None else 0, "text": txt.get(rid[p], "")})
    out.sort(key=lambda x: -x["score"]); return out

_HSTOP = frozenset(("the a an and or not of to in for on with at by from as is are was were be been this "
                    "that these those it its his her their which who whom whose what when where why how any "
                    "all such may must shall will would should can could has have had no nor").split())

def _htoks(q, cap=40):
    import re
    out = []
    for t in re.findall(r"[a-zA-Z0-9]{2,}", (q or "").lower()):
        if t in _HSTOP: continue
        out.append(t)
        if len(out) >= cap: break
    return out

def keyword_cases(q, limit=20):
    """OR-mode BM25 over one-row-per-case contentless FTS; [] on any failure."""
    S = _load(); con = S.get("docfts")
    if con is None: return []
    tk = _htoks(q)
    if len(tk) < 2: return []
    m = " OR ".join(f'"{t}"' for t in tk)
    try:
        rows = con.execute("SELECT d.case_id FROM doc_fts f JOIN docmap d ON d.rid=f.rowid "
                           "WHERE doc_fts MATCH ? ORDER BY bm25(doc_fts) LIMIT ?", (m, limit)).fetchall()
    except sqlite3.OperationalError:
        return []
    return [r[0] for r in rows]

def hybrid_fuse(cases, q, keep=HYBRID_KEEP, k_rrf=60):
    """RRF reorder WITHIN match tiers (badges keep their meaning) + flagged tail."""
    kw = keyword_cases(q)
    if not kw: return cases, False
    sc = {c["case_id"]: 1.0 / (k_rrf + i + 1) for i, c in enumerate(cases)}
    for i, cid in enumerate(kw):
        sc[cid] = sc.get(cid, 0.0) + 1.0 / (k_rrf + i + 1)
    cases.sort(key=lambda c: (_tier(c.get("top_score", 0.0)), -sc.get(c["case_id"], 0.0)))
    have = {c["case_id"] for c in cases}; meta = _load()["meta"]; extra = []
    for cid in kw:
        if cid in have or len(extra) >= keep: continue
        m = meta.get(cid) or {}
        extra.append({"case_id": cid, "case_no": m.get("case_no", "") or "", "title": m.get("title", "") or "",
                      "hudoc_url": m.get("hudoc", "") or "", "judgment_date": m.get("date", "") or "",
                      "respondent": m.get("state", "") or "",
                      "articles": [str(x) for x in (m.get("violation") or [])],
                      "top_score": 0.0, "hits": [], "hit_count": 0, "matched_via": "keyword"})
        have.add(cid)
    return cases + extra, True

def _tier(t): return 0 if t >= 0.80 else 1 if t >= 0.72 else 2 if t >= 0.65 else 3
def group_by_case(paras, k):
    g = OrderedDict()
    for p in paras:
        cid = p.get("case_id") or "_"
        if cid not in g:
            g[cid] = {"case_id": cid, "case_no": p["case_no"], "title": p["title"], "hudoc_url": p["hudoc_url"],
                      "judgment_date": p["judgment_date"], "respondent": p["respondent"], "articles": list(p["articles"]),
                      "top_score": p["score"], "hits": []}
        c = g[cid]
        if p["score"] > c["top_score"]: c["top_score"] = p["score"]
        for a in p["articles"]:
            if a not in c["articles"]: c["articles"].append(a)
        c["hits"].append({"score": p["score"], "section": p["section"], "para_idx": p["para_idx"], "text": p["text"]})
    cases = []
    for c in g.values():
        c["hits"].sort(key=lambda h: -h["score"]); c["hit_count"] = len(c["hits"])
        sc = [h["score"] for h in c["hits"]]; top = max(sc); avg = sum(sc) / len(sc); lf = math.log(1 + len(sc)) / LOGD
        c["avg_score"] = round(avg, 4); c["case_score"] = round(RANK_TOP * top + RANK_AVG * avg + RANK_LOG * lf, 4)
        cases.append(c)
    cases.sort(key=lambda c: (_tier(c["top_score"]), -c["hit_count"], -c["case_score"]))
    return cases[:k]

rag_app = FastAPI(title="ECHR RAG (semantic)")

@rag_app.get("/")
def root(): return FileResponse(STATIC / "search_ui.html")
@rag_app.get("/methodology")
def methodology(): return FileResponse(STATIC / "methodology.html")
@rag_app.get("/health")
def health():
    S = _load()
    return {"status": "ok", "indexed_points": S["index"].ntotal, "respondents": len(S["respondents"]),
            "sections": S["sections"], "gemini_enabled": False, "version": "rag-1.0"}
class CitReq(BaseModel):
    case_ids: list[str] = []

@rag_app.post("/citations")
def citations(req: CitReq):
    """Citation edges + global in/out degrees for the result set, from the
    prebuilt graph (citations.json). Powers the Discovery Workspace constellation."""
    t0 = time.time(); graph = _cit()
    ids = list(dict.fromkeys([c for c in (req.case_ids or []) if c]))
    empty = {"edges": [], "cited_by_total": {}, "cites_total": {}, "cited_by_sample": {},
             "cites_sample": {}, "meta": {}, "stats": {"source": "none", "elapsed_seconds": 0.0}}
    if not ids or not graph:
        return empty
    id_set = set(ids); SAMPLE = 12
    edges = []; cbt = {}; ct = {}; cbs = {}; cs = {}; meta = {}
    def expand(lst):
        e = []
        for c in lst:
            m = graph.get(c)
            if not m: continue
            e.append({"case_id": c, "title": m.get("title", ""), "judgment_date": m.get("judgment_date", ""),
                      "cited_by_count": len(m.get("cited_by", []))})
        e.sort(key=lambda x: -x["cited_by_count"]); return e[:SAMPLE]
    for cid in ids:
        node = graph.get(cid)
        if not node:
            cbt[cid] = ct[cid] = 0; cbs[cid] = []; cs[cid] = []
            meta[cid] = {"title": "", "case_no": "", "judgment_date": ""}; continue
        meta[cid] = {"title": node.get("title", ""), "case_no": node.get("case_no", ""),
                     "judgment_date": node.get("judgment_date", "")}
        cites = node.get("cites", []); citedby = node.get("cited_by", [])
        cbt[cid] = len(citedby); ct[cid] = len(cites)
        for tgt in cites:
            if tgt in id_set and tgt != cid: edges.append({"from": cid, "to": tgt})
        cs[cid] = expand(cites); cbs[cid] = expand(citedby)
    return {"edges": edges, "cited_by_total": cbt, "cites_total": ct, "cited_by_sample": cbs,
            "cites_sample": cs, "meta": meta,
            "stats": {"source": "graph", "elapsed_seconds": round(time.time() - t0, 3)}}

@rag_app.get("/respondents")
def respondents(): return {"respondents": _load()["respondents"]}
@rag_app.get("/sections")
def sections(): return {"sections": _load()["sections"]}
@rag_app.get("/similar")
def similar(q: str = Query(...), k: int = Query(10, ge=1, le=50),
            respondent: str | None = Query(None), article: str | None = Query(None), section: str | None = Query(None)):
    t0 = time.time(); paras = run_paragraph_search(q, respondent, article, section); cases = group_by_case(paras, k)
    cases, hyb = hybrid_fuse(cases, q)
    return {"mode": "expert", "query": q, "count": len(cases), "hybrid": hyb, "results": cases,
            "stats": {"paragraphs_pooled": len(paras), "elapsed_ms": int((time.time() - t0) * 1000)}}
