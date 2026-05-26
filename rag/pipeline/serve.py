#!/usr/bin/env python3
"""Tiny local tester: type a query, see which paragraphs Voyage retrieves.

Loads the voyage-4-large embeddings + the local BM25 (FTS5) index once, then
serves a one-page UI. Modes: dense / hybrid (dense+BM25 RRF) / rerank (+rerank-2.5).

  python3 serve.py            # then open http://127.0.0.1:8765
Needs the Voyage key (phaseB/voyage_key or $VOYAGE_API_KEY) for query embedding.
"""
from __future__ import annotations
import json, sqlite3, re, html, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from collections import defaultdict
import numpy as np
import embed

HERE = Path(__file__).resolve().parent
MODEL = "voyage-4-large"
EMB = HERE / "data" / "emb" / MODEL
FTS = HERE / "data" / "corpus_fts.db"
PORT = 8766
STOP = set("the a an and or not near of to in for on with at by from as is are was were be been this "
           "that these those it its his her their which who whom whose what when where why how any all "
           "such may must shall will would should can could has have had no nor".split())

print("[load] reading ids + vectors ...")
ids = [json.loads(l) for l in open(EMB / "ids.jsonl", encoding="utf-8")]
N = len(ids)
dim = json.loads((EMB / "meta.json").read_text())["dim"]
CASE = [x["case_id"] for x in ids]
SEC = [x["section_no"] for x in ids]
RID = [x["rowid"] for x in ids]
RID2POS = {r: i for i, r in enumerate(RID)}
META = json.loads((HERE / "data" / "cases_meta.json").read_text())
print(f"[load] {len(META):,} case metadata records")
mm = np.memmap(EMB / "vecs.f32.dat", dtype="<f4", mode="r", shape=(N, dim))
try:
    M = np.array(mm, dtype=np.float32)
    M /= (np.linalg.norm(M, axis=1, keepdims=True) + 1e-9)
    IN_RAM = True
    print(f"[load] {N:,} vectors in RAM (normalized)")
except MemoryError:
    M = mm; IN_RAM = False
    print(f"[load] {N:,} vectors via memmap (low RAM mode)")

def toks(q):
    out = []
    for t in re.findall(r"[a-zA-Z]{3,}", (q or "").lower()):
        if t not in STOP: out.append(t)
        if len(out) >= 40: break
    return out

def dense_topk(qv, k):
    if IN_RAM:
        s = M @ qv
        idx = np.argpartition(-s, k)[:k]
        idx = idx[np.argsort(-s[idx])]
        return [(int(i), float(s[i])) for i in idx]
    # memmap chunked
    best_i = np.full(k, -1); best_v = np.full(k, -1e9, dtype=np.float32)
    for st in range(0, N, 100000):
        en = min(st + 100000, N)
        b = np.array(mm[st:en], dtype=np.float32)
        b /= (np.linalg.norm(b, axis=1, keepdims=True) + 1e-9)
        s = b @ qv
        mv = np.concatenate([best_v, s]); mi = np.concatenate([best_i, np.arange(st, en)])
        p = np.argpartition(-mv, k)[:k]; best_v = mv[p]; best_i = mi[p].astype(int)
    o = np.argsort(-best_v)
    return [(int(best_i[j]), float(best_v[j])) for j in o]

def bm25_topk(con, query, k):
    tk = toks(query)
    if not tk: return []
    match = " OR ".join(f'"{t}"' for t in tk)
    try:
        rows = con.execute(
            "SELECT p.rid, bm25(para_fts) FROM para_fts f JOIN para p ON p.rid=f.rowid "
            "WHERE para_fts MATCH ? ORDER BY bm25(para_fts) LIMIT ?", (match, k)).fetchall()
    except sqlite3.OperationalError:
        return []
    return [(RID2POS[r], -float(b)) for r, b in rows if r in RID2POS]  # higher = better

def fetch_text(con, rids):
    if not rids: return {}
    qm = ",".join("?" * len(rids))
    return {r: t for r, t in con.execute(f"SELECT rid,text FROM para WHERE rid IN ({qm})", rids)}

def cosine_of(pos, qv):
    v = np.asarray(M[pos], dtype=np.float32)
    return float(v @ qv) / (float(np.linalg.norm(v)) + 1e-9)  # memmap rows aren't pre-normalized

def build(con, ranked, qv, drank, rr_score):
    txt = fetch_text(con, [RID[p] for p in ranked])
    out = []
    for pos in ranked:
        cid = CASE[pos]; sec = SEC[pos]; m = META.get(cid, {})
        out.append({
            "case_id": cid, "section_no": sec, "text": txt.get(RID[pos], ""),
            "cosine": round(cosine_of(pos, qv), 3),
            "rerank": round(rr_score[pos], 3) if pos in rr_score else None,
            "in_dense": pos in drank, "dense_rank": drank.get(pos),
            "title": m.get("title"), "date": m.get("date"), "state": m.get("state"),
            "importance": m.get("importance"), "conclusion": m.get("conclusion"),
            "violation": m.get("violation") or [], "body": m.get("body"),
            "hudoc": m.get("hudoc") or f"https://hudoc.echr.coe.int/eng?i={cid}",
        })
    return out

def rank_dense(dense, k):
    return [pos for pos, _ in dense][:k]

def rank_hybrid(drank, brank, k):
    rrf = defaultdict(float)
    for pos, r in drank.items(): rrf[pos] += 1 / (60 + r + 1)
    for pos, r in brank.items(): rrf[pos] += 1 / (60 + r + 1)
    return [p for p, _ in sorted(rrf.items(), key=lambda x: -x[1])][:k]

def rank_rerank(con, query, dense, bm, k):
    pool, seen = [], set()
    for pos, _ in dense + bm:
        if pos not in seen: seen.add(pos); pool.append(pos)
    txt = fetch_text(con, [RID[p] for p in pool])
    docs, valid = [], []
    for p in pool:
        t = txt.get(RID[p])
        if t: docs.append(t[:1200]); valid.append(p)
    order = embed.voyage_rerank(query, docs, model="rerank-2.5")
    rr_score = {valid[i]: sc for i, sc in order}
    return [valid[i] for i, _ in order][:k], rr_score

def _retrieve(con, query, pool):
    qv = np.array(embed.voyage_embed([query[:1500]], model=MODEL, input_type="query")[0], dtype=np.float32)
    qv /= (np.linalg.norm(qv) + 1e-9)
    dense = dense_topk(qv, pool)
    bm = bm25_topk(con, query, pool)
    return qv, dense, bm

def search(query, mode, k):
    con = sqlite3.connect(f"file:{FTS}?mode=ro", uri=True)
    qv, dense, bm = _retrieve(con, query, max(k, 50))
    drank = {pos: r for r, (pos, _) in enumerate(dense)}
    brank = {pos: r for r, (pos, _) in enumerate(bm)}
    rr_score = {}
    if mode == "hybrid":
        ranked = rank_hybrid(drank, brank, k)
    elif mode == "rerank":
        ranked, rr_score = rank_rerank(con, query, dense, bm, k)
    else:
        ranked = rank_dense(dense, k)
    res = build(con, ranked, qv, drank, rr_score)
    con.close()
    return res

def compare(query, k):
    """Run all three modes from a single retrieval pass."""
    con = sqlite3.connect(f"file:{FTS}?mode=ro", uri=True)
    qv, dense, bm = _retrieve(con, query, max(k, 50))
    drank = {pos: r for r, (pos, _) in enumerate(dense)}
    brank = {pos: r for r, (pos, _) in enumerate(bm)}
    rr_ranked, rr_score = rank_rerank(con, query, dense, bm, k)
    res = {
        "dense": build(con, rank_dense(dense, k), qv, drank, {}),
        "hybrid": build(con, rank_hybrid(drank, brank, k), qv, drank, {}),
        "rerank": build(con, rr_ranked, qv, drank, rr_score),
    }
    con.close()
    return res

def context(case_id, sec, span=1):
    """Neighbouring numbered paragraphs (±span §) in the same case."""
    con = sqlite3.connect(f"file:{FTS}?mode=ro", uri=True)
    lo, hi = sec - span, sec + span
    rows = con.execute(
        "SELECT section_no,text FROM para WHERE case_id=? AND section_no BETWEEN ? AND ? ORDER BY section_no",
        (case_id, lo, hi)).fetchall()
    con.close()
    return [{"section_no": s, "text": t, "active": s == sec} for s, t in rows]

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>ECHR retrieval tester</title>
<style>
body{font:15px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;max-width:920px;margin:24px auto;padding:0 16px;color:#1a1a1a}
h1{font-size:19px} .row{display:flex;gap:8px;margin:10px 0}
input[type=text]{flex:1;padding:9px 11px;border:1px solid #bbb;border-radius:6px;font-size:15px}
select,button,input[type=number]{padding:9px;border:1px solid #bbb;border-radius:6px;font-size:14px}
button{background:#7a1f2b;color:#fff;border:0;cursor:pointer;padding:9px 16px}
.r{border:1px solid #e3e3e3;border-left:3px solid #7a1f2b;border-radius:6px;padding:10px 12px;margin:9px 0}
.meta{font-size:12.5px;color:#666;margin-bottom:4px}
.cid{color:#7a1f2b;font-weight:600}
.title{font-weight:600;font-size:14.5px}
.sub{font-size:12px;color:#555;margin:3px 0 7px;display:flex;flex-wrap:wrap;gap:4px 12px;align-items:center}
.tag{font-size:11px;background:#eee;border-radius:4px;padding:1px 6px}
.viol{color:#0a7a4b} .imp{color:#b8860b}
.bartrack{display:inline-block;width:90px;height:9px;background:#eee;border-radius:5px;overflow:hidden;vertical-align:middle}
.bar{display:block;height:100%;background:#7a1f2b}
.score{font-variant-numeric:tabular-nums;font-size:12px;color:#333}
.ptext{font-size:14px;cursor:pointer} .ptext:hover{background:#fcfafa}
mark{background:#ffe9a8;padding:0 1px;border-radius:2px}
.hint{font-size:11px;color:#aaa;margin-top:3px}
.ctx{margin-top:8px;border-top:1px dashed #ddd;padding-top:6px}
.ctx .p{font-size:13px;color:#555;margin:5px 0} .ctx .p.active{color:#1a1a1a;background:#fff7e6;padding:4px 6px;border-radius:4px}
.ctx .pn{color:#7a1f2b;font-weight:600;margin-right:5px}
.cols{display:flex;gap:12px;align-items:flex-start} .cols>div{flex:1;min-width:0}
.colh{font-weight:600;font-size:13px;color:#7a1f2b;border-bottom:2px solid #7a1f2b;padding-bottom:3px;margin-bottom:6px;position:sticky;top:0;background:#fff}
.cols .r{padding:8px 9px} .cols .title{font-size:12.5px} .cols .ptext{font-size:12px;max-height:5.6em;overflow:hidden}
label.cmp{font-size:13px;color:#444;display:flex;align-items:center;gap:5px;white-space:nowrap}
a{color:#7a1f2b} #status{color:#888;font-size:13px}
</style></head><body>
<h1>ECHR paragraph retrieval — local tester <span style="font-weight:400;color:#888">(voyage-4-large)</span></h1>
<div class="row">
  <input id="q" type="text" placeholder="Type a query in any phrasing (lay or precise)..." autofocus>
  <select id="mode">
    <option value="dense">dense</option>
    <option value="hybrid">hybrid (dense+BM25 RRF)</option>
    <option value="rerank">rerank-2.5</option>
  </select>
  <input id="k" type="number" value="10" min="1" max="50" style="width:64px" title="results">
  <label class="cmp"><input type="checkbox" id="cmp"> compare all 3</label>
  <button onclick="go()">Search</button>
</div>
<div class="hint">Tip: click any paragraph to expand its neighbouring §§ for context. Query terms are highlighted.</div>
<div id="status"></div><div id="out"></div>
<script>
const STOP=new Set("the a an and or not near of to in for on with at by from as is are was were be been this that these those it its his her their which who whom whose what when where why how any all such may must shall will would should can could has have had no nor".split(" "));
let TERMS=[];
function escapeHtml(s){return (s||'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}
function hl(s){
  let h=escapeHtml(s);
  for(const t of TERMS){ h=h.replace(new RegExp('\\\\b('+t.replace(/[.*+?^${}()|[\\]\\\\]/g,'\\\\$&')+'\\\\w*)','gi'),'<mark>$1</mark>'); }
  return h;
}
function card(x,i,compact){
  const sec=x.section_no==null?'—':'§'+x.section_no;
  const dr=x.in_dense?'<span class=tag>dense #'+(x.dense_rank+1)+'</span>':'<span class=tag>BM25-only</span>';
  const primary=(x.rerank!=null)?x.rerank:x.cosine;
  const pct=Math.max(0,Math.min(100,Math.round(primary*100)));
  const lvl=primary>=0.6?'strong':primary>=0.45?'moderate':'weak';
  const extra=(x.rerank!=null)?` · cos ${x.cosine}`:'';
  const label=(x.rerank!=null)?'rerank':'cosine';
  const score=`<span class=score title="${label} ${primary} (${lvl})"><span class=bartrack><span class=bar style="width:${pct}%"></span></span> ${primary.toFixed(3)} ${lvl}${extra}</span>`;
  const imp=x.importance?`<span class=imp>imp ${x.importance}${x.importance==1?' (key)':''}</span>`:'';
  const viol=(x.violation&&x.violation.length)?`<span class=viol>viol: ${x.violation.join(', ')}</span>`:'';
  const concl=(!compact&&x.conclusion)?`<div class=meta>${escapeHtml(x.conclusion)}</div>`:'';
  const sub2=compact?'':`<div class=sub>${score}</div>`;
  const subc=compact?` &nbsp; ${score}`:'';
  return `<div class=r data-cid="${x.case_id}" data-sec="${x.section_no==null?'':x.section_no}">
    <div class=meta>#${i+1} &nbsp; <span class=cid>${x.case_id}</span> ${sec} ${dr} &nbsp; <a href="${x.hudoc}" target="_blank">HUDOC↗</a></div>
    <div class=title>${escapeHtml(x.title||'(untitled)')}</div>
    <div class=sub>${[x.date,x.state,imp,viol].filter(Boolean).join(' &nbsp;·&nbsp; ')}${subc}</div>
    ${sub2}${concl}
    <div class=ptext>${hl(x.text)}</div>
    <div class=ctx></div>
  </div>`;
}
async function go(){
  const q=document.getElementById('q').value.trim(); if(!q)return;
  const mode=document.getElementById('mode').value, k=+document.getElementById('k').value;
  const cmp=document.getElementById('cmp').checked;
  TERMS=q.toLowerCase().match(/[a-z]{3,}/g)||[]; TERMS=TERMS.filter(t=>!STOP.has(t)).slice(0,40);
  document.getElementById('status').textContent='searching…'; const t=Date.now();
  const out=document.getElementById('out');
  if(cmp){
    const r=await fetch('/compare',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query:q,k})});
    const d=await r.json();
    document.getElementById('status').textContent=((Date.now()-t)/1000).toFixed(1)+'s · compare (dense | hybrid | rerank)';
    const col=(name,arr)=>`<div><div class=colh>${name}</div>${(arr||[]).map((x,i)=>card(x,i,true)).join('')}</div>`;
    out.innerHTML=`<div class=cols>${col('dense',d.dense)}${col('hybrid',d.hybrid)}${col('rerank-2.5',d.rerank)}</div>`;
  } else {
    const r=await fetch('/search',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query:q,mode,k})});
    const d=await r.json();
    document.getElementById('status').textContent=(d.results||[]).length+' results · '+((Date.now()-t)/1000).toFixed(1)+'s · '+mode;
    out.innerHTML=(d.results||[]).map((x,i)=>card(x,i,false)).join('');
  }
}
// click a paragraph -> toggle neighbouring §§ context
document.getElementById('out').addEventListener('click',async e=>{
  const p=e.target.closest('.ptext'); if(!p)return;
  const r=p.closest('.r'), box=r.querySelector('.ctx');
  if(box.dataset.open){ box.innerHTML=''; box.dataset.open=''; return; }
  const cid=r.dataset.cid, sec=r.dataset.sec; if(!sec){box.innerHTML='<div class=meta>no § to anchor context</div>';return;}
  box.innerHTML='<div class=meta>loading context…</div>';
  const res=await fetch('/context',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({case_id:cid,sec:+sec,span:2})});
  const d=await res.json();
  box.dataset.open='1';
  box.innerHTML=(d.results||[]).map(c=>`<div class="p${c.active?' active':''}"><span class=pn>§${c.section_no}</span>${hl(c.text)}</div>`).join('')||'<div class=meta>(no neighbours)</div>';
});
document.getElementById('q').addEventListener('keydown',e=>{if(e.key==='Enter')go();});
</script></body></html>"""

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, body, ctype="application/json"):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        self._send(200, PAGE, "text/html; charset=utf-8")
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        req = json.loads(self.rfile.read(n) or "{}")
        path = self.path.split("?")[0]
        try:
            if path == "/compare":
                self._send(200, json.dumps(compare(req.get("query", ""), int(req.get("k", 10)))))
            elif path == "/context":
                res = context(req.get("case_id", ""), int(req.get("sec", 0)), int(req.get("span", 1)))
                self._send(200, json.dumps({"results": res}))
            else:
                res = search(req.get("query", ""), req.get("mode", "dense"), int(req.get("k", 10)))
                self._send(200, json.dumps({"results": res}))
        except Exception as e:
            self._send(500, json.dumps({"error": str(e)}))

if __name__ == "__main__":
    print(f"[ready] open http://127.0.0.1:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
