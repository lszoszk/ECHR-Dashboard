"""RAG sub-application mounted into echr-api at /rag.

Lazy-loads a MEMORY-MAPPED FAISS SQ8 index + metadata from /data/rag (low RAM —
the index stays on disk, OS page-cache reclaimable). Loading happens on first
request, so the dashboard API isn't delayed at container start and RAM is only
used if the RAG is actually queried.

Pipeline: voyage-4-large embedding -> FAISS mmap ANN -> rerank-3 (top 100)
-> +importance authority boost -> group by case.
Endpoints (served under /echr-api/rag via nginx): / , /health , /respondents ,
/sections , /similar .
"""
from __future__ import annotations
import os, json, math, sqlite3, time, threading
from pathlib import Path
from array import array
from collections import OrderedDict
import numpy as np, faiss
from fastapi import FastAPI, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
import embed  # voyage HTTP client (ships alongside in backend/)

BASE = Path(os.environ.get("ECHR_RAG_DIR", "/data/rag"))
STATIC = Path(__file__).resolve().parent / "rag_static"
VOYAGE_MODEL = "voyage-4-large"; RERANK_MODEL = "rerank-3"
NPROBE = 128; FETCH = 600; RERANK_POOL = 100; IMP_BOOST = 0.05
# At most CASE_CAP paragraphs of one judgment go to the reranker: uncapped, one judgment took up to
# 82 of the 100 places. 10 is neutral on both benchmarks; 4 or fewer cost paragraph recall, because a
# judgment's best paragraph is often its 5th or later by cosine (rag/FINDINGS.md §6).
CASE_CAP = 10
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
# The French originals (judgments HUDOC publishes only in French), searched only when asked for (fr=1):
# a second index over the English rows followed by the French ones (ann_comb.index, same settings as
# ann_index.index), with fr_ids.jsonl naming the French rows; their text and record come from the
# French database the main API also reads. Without fr=1 the English index is used, unchanged.
FR_DB = Path(os.environ.get("ECHR_FR_DB_PATH", "/data/echr_fr.db"))
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
    comb, fr = None, None
    if (BASE / "ann_comb.index").exists() and (BASE / "fr_ids.jsonl").exists() and FR_DB.exists():
        comb = faiss.read_index(str(BASE / "ann_comb.index"), faiss.IO_FLAG_MMAP); comb.nprobe = NPROBE
        # Compact columns (half a million rows; lists of Python objects would take ~300 MB):
        # case and section as indexes into short lists, § 0 where the row has none.
        names, secs, ci, si = [], [], {}, {}
        fcase, fsno, frid, fsec = array("I"), array("i"), array("I"), array("B")
        with open(BASE / "fr_ids.jsonl", encoding="utf-8") as fh:
            for line in fh:
                r = json.loads(line)
                c, sec = r["case_id"], r.get("section") or ""
                if c not in ci: ci[c] = len(names); names.append(c)
                if sec not in si: si[sec] = len(secs); secs.append(sec)
                fcase.append(ci[c]); fsno.append(r["section_no"] or 0); frid.append(r["fr_rowid"]); fsec.append(si[sec])
        fcon = sqlite3.connect(f"file:{FR_DB}?mode=ro", uri=True, check_same_thread=False)
        fmeta = {}
        for r in fcon.execute("SELECT case_id, title, title_en, judgment_date, respondent_state, importance, "
                              "originating_body, case_no, hudoc_url, violation FROM cases"):
            try: viol = json.loads(r[9] or "[]")
            except ValueError: viol = []
            fmeta[r[0]] = {"title": r[1], "title_en": r[2], "date": r[3], "state": r[4], "importance": r[5],
                           "body": r[6], "case_no": r[7], "hudoc": r[8], "violation": viol, "lang": "fr"}
        fr = {"names": names, "secs": secs, "case": fcase, "sno": fsno, "rid": frid, "sec": fsec,
              "meta": fmeta, "db": fcon}
        if comb.ntotal != len(ids) + len(fcase):   # a mismatched pair would point at the wrong rows
            comb, fr = None, None
    _S.update(comb=comb, fr=fr, n_en=len(ids))
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

def _split(raw): return [p.strip() for p in (raw or "").split(",") if p.strip()]

def french_available() -> bool:
    return _load()["comb"] is not None

def run_paragraph_search(q, respondent=None, article=None, section=None, include_fr=False):
    S = _load()
    use_fr = bool(include_fr and S["comb"] is not None)
    index = S["comb"] if use_fr else S["index"]
    qv = _embed_query(q)
    if qv.shape[1] > index.d:  # a smaller (Matryoshka) index: the query's leading dims, re-normalised
        qv = np.ascontiguousarray(qv[:, :index.d]); faiss.normalize_L2(qv)
    fetch = FETCH if not (respondent or article or section) else FETCH * 2
    D, I = index.search(qv, fetch)
    case, sno, rid, meta, rowsec, art, fts = S["case"], S["sno"], S["rid"], S["meta"], S["rowsec"], S["artmap"], S["fts"]
    ne, F = S["n_en"], S["fr"]

    def row(p):   # (case_id, §, text key, section, record) of an English or a French row
        if p < ne:
            return case[p], sno[p], rid[p], rowsec.get(rid[p], ""), meta.get(case[p], {}) or {}
        j = p - ne
        cid = F["names"][F["case"][j]]
        return cid, F["sno"][j], ("fr", F["rid"][j]), F["secs"][F["sec"][j]], F["meta"].get(cid, {}) or {}

    pos = [int(i) for i in I[0] if i >= 0]
    cand = []; per_case = {}
    for scr, p in zip(D[0], pos):
        cid, s, key, sec, m = row(p)
        if not m: continue  # no longer in the corpus (cases_meta.json is rebuilt from it; the index is not)
        if s is None or s == 0: continue  # skip uncitable sub-fragments (no HUDOC § number → would render as ¶0)
        if respondent and respondent not in _split(m.get("state", "")): continue
        arts = [str(x) for x in (m.get("violation") or [])]
        if article and article not in arts and art.get((cid, s)) != article: continue
        if section and sec != section: continue
        if per_case.get(cid, 0) >= CASE_CAP: continue
        per_case[cid] = per_case.get(cid, 0) + 1
        cand.append((p, float(scr), sec, m, arts))
        if len(cand) >= RERANK_POOL: break
    keys = [row(p)[2] for p, *_ in cand]; txt = {}
    rids = [k for k in keys if not isinstance(k, tuple)]
    if rids:
        txt = {r: t for r, t in fts.execute("SELECT rid,text FROM para WHERE rid IN (%s)" % ",".join("?" * len(rids)), rids)}
    frids = [k[1] for k in keys if isinstance(k, tuple)]
    if frids:
        txt.update({("fr", r): t for r, t in F["db"].execute(
            "SELECT rowid, text FROM paragraphs WHERE rowid IN (%s)" % ",".join("?" * len(frids)), frids)})
    rr = None; src = cand
    if len(cand) > 1:
        head = cand[:RERANK_POOL]; docs = [(txt.get(row(p)[2]) or "")[:1200] for p, *_ in head]
        try:
            rr = {i: sc for i, sc in embed.voyage_rerank(q, docs, model=RERANK_MODEL)}; src = head
        except SystemExit:
            rr = None; src = cand
    out = []
    for idx, (p, cos, sec, m, arts) in enumerate(src):
        cid, s, key, _, _ = row(p); base = rr.get(idx, 0.0) if rr is not None else cos
        pen = SEP_PENALTY if sec == "Separate Opinion" else LF_PENALTY if sec == "Legal Framework" else 0.0
        auth = IMP.get(m.get("importance"), 0.0)
        extra = {"lang": "fr", "title_en": m.get("title_en", "") or ""} if m.get("lang") == "fr" else {}
        out.append({**extra, "score": round(float(base) + IMP_BOOST * auth - pen, 4), "case_id": cid,
            "case_no": m.get("case_no", "") or "", "title": m.get("title", "") or "", "hudoc_url": m.get("hudoc", "") or "",
            "judgment_date": m.get("date", "") or "", "respondent": m.get("state", "") or "", "articles": arts,
            "importance": m.get("importance", "") or "", "body": m.get("body", "") or "",
            "section": sec, "para_idx": s if s is not None else 0, "text": txt.get(key, "")})
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
    meta = S["meta"]
    return [r[0] for r in rows if r[0] in meta]   # not judgments since removed from the corpus

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
                      "importance": m.get("importance", "") or "", "body": m.get("body", "") or "",
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
                      "importance": p["importance"], "body": p["body"],
                      **({"lang": "fr", "title_en": p.get("title_en", "")} if p.get("lang") == "fr" else {}),
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
            "sections": S["sections"], "gemini_enabled": False, "version": "rag-1.0",
            "french": S["comb"] is not None,
            "french_points": (S["comb"].ntotal - S["n_en"]) if S["comb"] is not None else 0}
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
        # + judgments HUDOC has only in French (not in the corpus yet), as the Search page counts them
        cbt[cid] = len(citedby) + int(node.get("cited_by_french_only", 0)); ct[cid] = len(cites)
        for tgt in cites:
            if tgt in id_set and tgt != cid: edges.append({"from": cid, "to": tgt})
        cs[cid] = expand(cites); cbs[cid] = expand(citedby)
    return {"edges": edges, "cited_by_total": cbt, "cites_total": ct, "cited_by_sample": cbs,
            "cites_sample": cs, "meta": meta, "established": _established(graph, ids[:20], edges),
            "stats": {"source": "graph", "elapsed_seconds": round(time.time() - t0, 3)}}


def _established(graph: dict, top: list, edges: list) -> dict:
    """How established the issue looks among the top results, from the full citation graph:
    the judgments most of them cite (shared authority), and how densely they cite each other."""
    from collections import Counter
    shared = Counter()
    for cid in top:
        for tgt in set((graph.get(cid) or {}).get("cites", [])):
            shared[tgt] += 1
    lead = []
    for tgt, n in shared.most_common(3):
        node = graph.get(tgt) or {}
        lead.append({"case_id": tgt, "title": node.get("title", ""), "case_no": node.get("case_no", ""),
                     "judgment_date": node.get("judgment_date", ""), "cited_by_top": n,
                     "in_results": tgt in top})
    inner = [e for e in edges if e["from"] in top and e["to"] in top]
    linked = {e["from"] for e in inner} | {e["to"] for e in inner}
    n = len(top)
    return {"top_n": n, "shared": lead, "links": len(inner), "linked": len(linked),
            "density": round(len(inner) / (n * (n - 1)), 3) if n > 1 else 0.0}

@rag_app.get("/respondents")
def respondents(): return {"respondents": _load()["respondents"]}
@rag_app.get("/sections")
def sections(): return {"sections": _load()["sections"]}
@rag_app.get("/similar")
def similar(q: str = Query(...), k: int = Query(10, ge=1, le=50),
            respondent: str | None = Query(None), article: str | None = Query(None), section: str | None = Query(None),
            fr: bool = Query(False, description="also search the French originals of judgments HUDOC publishes only in French")):
    t0 = time.time(); paras = run_paragraph_search(q, respondent, article, section, include_fr=fr); cases = group_by_case(paras, k)
    cases, hyb = hybrid_fuse(cases, q)
    return {"mode": "expert", "query": q, "count": len(cases), "hybrid": hyb, "results": cases,
            "stats": {"paragraphs_pooled": len(paras), "elapsed_ms": int((time.time() - t0) * 1000)}}
