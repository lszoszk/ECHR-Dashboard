"""
search_api.py v2.21
Changes vs v2.20:
    - /smart_search accepts new ?style= param: "creative" (default) or
      "conservative". Creative = 3 rewrites at temp=0.85 (faster, wider
      exploration); Conservative = 6 rewrites at temp=0.55 (slower, tighter
      consensus). Style is echoed in response.style and response.stats.
v2.20:
Changes vs v2.19:
    - Fixed infinite key-rotation loop on quota errors (recursive gemini_call
      kept resetting the rotation start index — would burn quota forever).
    - Per-key cooldown tracking: a 429 sets cooldown for 90s (RPM) or 6h
      (daily). gemini_call skips cooled keys instead of trying them.
    - Ensemble round-robin: with 2 keys and N=3 rewrites, each key handles
      at most 2 calls so neither hits its RPM ceiling in one search.
    - ENSEMBLE_N 5 → 3 (quota-friendly default).
    - /smart_search now reports the soonest available key when all are cooled,
      e.g. "Next key #1 free in ~47s".
v2.19:
    - Ensemble bumped 3 → 5 parallel Gemini rewrites per natural-mode search.
    - Result cache REMOVED. Every search runs fresh ensemble.
    - Consensus ranking: case appearance_count drives sort within tier.
    - /cache/info and /cache/clear endpoints removed.
v2.18:
    - Case sort order: match tier first (Strong ≥0.80 → Good ≥0.72 → Possible
      ≥0.65 → Weak), then by hit_count (descending), then case_score tie-break.
      Stronger matches always come first regardless of paragraph count.
    - DRAFT_PROMPT now requires ≥4 substantive warnings with explanation of
      (a) what to verify (b) why it matters (c) what to do, covering at least
      missing facts, admissibility risks, causation gaps and tactical issues.
    - DRAFT_PROMPT adds hudoc_keywords (5-10 ECHR concept phrases) so the
      drafted complaint UI can offer copy-to-clipboard chips for HUDOC search.
v2.17:
    - /smart_search now uses MULTI-QUERY ENSEMBLE: 3 parallel Gemini rewrites
      (temperature=0.7), each runs paragraph search, results are pooled with
      max-score dedup before grouping into cases. Result: better recall and
      far steadier ranking than a single rewrite.
    - LRU result cache (in-memory, 500 entries, 6h TTL) keyed by
      (mode, query, k, filters). Identical re-searches return cached results
      instantly and identically. Cleared on server restart.
    - /similar (Expert) cached too — Expert mode was already deterministic
      but caching saves the embedding + Chroma roundtrip on repeats.
    - New diagnostic endpoints: GET /cache/info, POST /cache/clear
    - All responses now include a `stats` block with cache_hit, ensemble_runs,
      elapsed_ms, and pool size.
v2.16:
    - Added legacy URL aliases (/echr/search_ui.html, /echr/draft_ui.html, etc.)
      so older cached browser tabs still resolve to the right page.
    - Disabled HTML response caching (Cache-Control: no-store) so HTML edits
      take effect without forcing the user to Ctrl+F5.
v2.15:
    - Loads pre-built citations.json at startup (built by build_citations.py).
      Provides GLOBAL cited_by_total / cites_total counts so the constellation
      can size nodes by doctrinal importance (Klass-style "cited by 312").
    - /citations endpoint now uses the pre-built graph when available; falls
      back to on-the-fly Chroma scanning (slower, local-only counts) otherwise.
v2.14:
    - On-the-fly /citations endpoint
v2.13:
    - Disabled thinking_budget on 2.5-flash (was hanging searches indefinitely)
    - Forced response_mime_type=application/json (cleaner output)
    - Added 90s HTTP timeout on Gemini client (prevents indefinite hangs)
    - Logs elapsed time per Gemini call
"""
import json, io, math, os, sys, time
from collections import OrderedDict
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
import uvicorn
import numpy as np, faiss, sqlite3
import embed  # local: voyage query embedding + rerank (gitignored keys)

# --- Engine artifacts (voyage-4-large SQ8 ANN + BM25/text + metadata + tags) ---
ANN_INDEX   = "data/ann_index.index"
IDS_FILE    = "data/ids.jsonl"
FTS_DB      = "data/corpus_fts.db"
META_FILE   = "data/cases_meta.json"
ROWSEC_FILE = "data/row_section.tsv"
ARTMAP_FILE = "data/para_articles.tsv"
VOYAGE_MODEL = "voyage-4-large"
ANN_NPROBE  = 128            # ~98% recall@50 vs exact
IMP_BOOST   = 0.05           # importance authority boost added to cosine
IMP_W = {"Key cases": 1.0, "1": 1.0, "2": 0.5, "3": 0.25, "Unspecified": 0.0}
DB_PATH = ANN_INDEX          # lifespan existence check
SEARCH_HTML = "search_ui.html"
DRAFT_HTML  = "draft_ui.html"
METH_HTML   = "methodology.html"
GEMINI_KEY_FILE = "gemini_key.txt"
CITATIONS_FILE = "citations.json"
GEMINI_MODELS = ["gemini-2.5-flash","gemini-2.5-flash-lite","gemini-2.0-flash"]
DRAFT_GEMINI_MODELS = GEMINI_MODELS
GEMINI_RETRY_DELAY = 1.5
GEMINI_ATTEMPTS_PER_MODEL = 2
DRAFT_MAX_CASES = 8
DRAFT_PARAS_PER_CASE = 2
FETCH_POOL = 300
FETCH_POOL_FILTERED = 600
RERANK_MODEL = "rerank-2.5"   # cross-encoder re-read of the top candidates
RERANK_POOL = 100             # how many dense candidates to rerank (validated best)
RERANK_ENABLED = True         # falls back to cosine if the rerank API errors
PRELOAD_BATCH = 20000
RANK_WEIGHT_TOP = 0.60
RANK_WEIGHT_AVG = 0.25
RANK_WEIGHT_LOG = 0.15
LOG_NORM_DENOM = math.log(10)

state: dict = {}

def split_states(raw):
    if not raw: return []
    return [p.strip() for p in raw.split(",") if p.strip()]

def load_gemini_keys():
    keys = []
    p = Path(GEMINI_KEY_FILE)
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"): keys.append(line)
    if not keys:
        env_key = os.environ.get("GEMINI_API_KEY","").strip()
        if env_key: keys.append(env_key)
    return keys

def mask_key(key):
    if len(key) <= 10: return key[:2]+"***"+key[-2:]
    return key[:4]+"***"+key[-4:]

def hit_count_log_factor(n):
    if n <= 1: return 0.0
    return min(1.0, math.log(n) / LOG_NORM_DENOM)

# ---------- Gemini multi-key ----------
def init_gemini_clients(keys):
    if not keys:
        state["gemini_keys"]=[]; state["gemini_clients"]=[]; state["gemini_active_idx"]=0; state["gemini"]=None; return
    from google import genai
    from google.genai import types as genai_types
    http_opts = genai_types.HttpOptions(timeout=90000)  # 90s, prevents indefinite hangs
    clients = []
    for i,key in enumerate(keys):
        try:
            c = genai.Client(api_key=key, http_options=http_opts); clients.append(c); print(f"    Key #{i+1}: {mask_key(key)} — OK")
        except Exception as e:
            print(f"    Key #{i+1}: {mask_key(key)} — FAILED ({e})"); clients.append(None)
    state["gemini_keys"]=keys; state["gemini_clients"]=clients; state["gemini_active_idx"]=0
    state["gemini"]=clients[0] if clients else None

def get_active_gemini_client():
    clients=state.get("gemini_clients",[]); idx=state.get("gemini_active_idx",0)
    return clients[idx] if clients and idx<len(clients) else None

def _key_in_cooldown(idx):
    """True when key #idx is on a quota cooldown timer."""
    cd = state.get("gemini_cooldowns", {})
    return cd.get(idx, 0) > time.time()

def _put_key_on_cooldown(idx, seconds=90, reason=""):
    """Mark a key as quota-exhausted for `seconds`. 90s covers Gemini free-tier
    RPM bucket reset (60s + slack). Pass a larger value for daily quota."""
    cd = state.setdefault("gemini_cooldowns", {})
    cd[idx] = time.time() + seconds
    print(f"[KEY COOLDOWN] key #{idx+1} cooling down for {seconds}s ({reason})")

def _available_key_indices():
    """All key indices that are non-null AND not currently cooling down."""
    return [i for i, c in enumerate(state.get("gemini_clients", []))
            if c is not None and not _key_in_cooldown(i)]

def rotate_gemini_key(reason=""):
    """Move the global active key to the next AVAILABLE one (skips cooldowns).
    Returns False when no key is available — caller must NOT retry blindly."""
    clients=state.get("gemini_clients",[])
    if len(clients) <= 1: return False
    cur=state.get("gemini_active_idx",0)
    n=len(clients)
    for step in range(1, n+1):
        cand=(cur+step)%n
        if clients[cand] is not None and not _key_in_cooldown(cand):
            state["gemini_active_idx"]=cand; state["gemini"]=clients[cand]
            print(f"[KEY ROTATION] Switched to key #{cand+1} ({mask_key(state['gemini_keys'][cand])}). Reason: {reason}")
            return True
    return False

def reset_key_rotation():
    """No-op kept for backwards compatibility with older call sites."""
    pass

# ---------- Prompts ----------
REWRITE_PROMPT = """You are an expert in European Court of Human Rights (ECHR) case law and a search-optimization specialist. The user will describe a legal situation in any language.

OUTPUT 1 - "search_query": A SINGLE SHORT SENTENCE (max 25 words) in English, ECHR headnote style. Strip personal facts, dates, names. Keep only legal concepts and ECHR terminology.

OUTPUT 2 - "rewritten_query": DETAILED 5-8 sentence reformulation in English, "The applicant complains that..." style. Cover: alleged action/omission, Convention rights engaged, applicable legal test, procedural defects, follow-on consequences. No proper names or country names.

OUTPUT 3 - "suggested_articles": LIST of 1-4 most relevant Convention articles as plain strings ("2","3","5","6","8","10","11","13","14","1P1"). Be COMPREHENSIVE.

OUTPUT 4 - "reasoning": One sentence in the USER'S LANGUAGE explaining why these articles apply.

OUTPUT 5 - "detected_language": ISO 639-1 code.

OUTPUT 6 - "keywords": A LIST of 5-8 specific ECHR legal keywords/phrases in English that could be used for keyword-based search in HUDOC or similar databases. Each keyword should be a precise legal term or established ECHR concept (e.g. "reasonable time", "margin of appreciation", "positive obligations", "chilling effect", "exhaustion of domestic remedies", "proportionality test"). Do NOT include article numbers here — only substantive legal terminology.

Return ONLY valid JSON:
{"search_query":"...","rewritten_query":"...","suggested_articles":["8","6"],"reasoning":"...","detected_language":"en","keywords":["reasonable time","effective investigation",...]}

User description:
\"\"\"
__USER_TEXT__
\"\"\""""

DRAFT_PROMPT = """You are an experienced ECHR practitioner drafting a formal application under Rule 47.

CRITICAL INSTRUCTIONS:
1. Output in BOTH languages: user's language (__USER_LANG__) AND English.
2. Sections D, E, F only. If multiple violations, separate sub-sections in E.
3. Cite precedents as [P1], [P2] etc. Use 4-10 citations. DO NOT invent cases.
4. Section D under ~3500 chars. Each E sub-section under ~3500 chars.
5. Section F: exhaustion of domestic remedies AND six-month rule.
6. Use [TO BE COMPLETED: ...] for missing info. Never invent facts.
7. WARNINGS — produce AT LEAST 6 distinct, substantive warnings. Each warning must
   be 1-3 sentences explaining (a) what the lawyer needs to verify, (b) why it matters
   for admissibility or the merits, and (c) what concretely should be checked or done.
   Cover at minimum: (i) facts missing or stated as assumption that need documentary
   proof, (ii) admissibility risks (six-month rule, exhaustion of remedies, victim
   status, abuse of right of petition, manifestly ill-founded), (iii) gaps in the
   chain of causation or in proving the State's responsibility, (iv) tactical
   considerations (joinder, interim measures, third-party intervention, priority
   treatment, settlement risk). Add more if the facts warrant.
8. HUDOC_KEYWORDS — produce 5-10 English keyword phrases the lawyer can paste into
   HUDOC's keyword filter. Each must be a precise established ECHR concept
   (e.g. "positive obligations", "margin of appreciation", "exhaustion of domestic
   remedies", "chilling effect", "effective investigation", "proportionality test").
   No article numbers. No verbatim sentences from the case.

If user language is "en", return identical content in both user_language and english fields.

Return ONLY valid JSON:
{
  "user_language": {"language_code":"__USER_LANG__","section_d":"...","section_e":"...","section_f":"..."},
  "english": {"language_code":"en","section_d":"...","section_e":"...","section_f":"..."},
  "citations_used": [{"marker":"P1","case_title":"...","hudoc_url":"...","para_idx":61,"respondent":"..."}],
  "warnings": [
    "Verify X is documented (medical record / police report / ...). Without it the Court may find the complaint manifestly ill-founded under Art. 35 § 3(a).",
    "Confirm the six-month rule was complied with from the final domestic decision dated ___. Article 35 § 1.",
    "..."
  ],
  "hudoc_keywords": ["positive obligations", "effective investigation", "..."]
}

User description:
\"\"\"
__USER_TEXT__
\"\"\"

Relevant ECHR articles: __ARTICLES__

Top __K__ precedent paragraphs:
__PRECEDENTS__
"""

# ---------- Gemini call ----------
def _classify_gemini_error(s):
    s=s.lower()
    if "429" in s or "resource_exhausted" in s or "quota" in s: return "quota_exhausted"
    if "503" in s or "unavailable" in s: return "overloaded"
    if "401" in s or "403" in s or "permission" in s: return "auth_failed"
    return "unknown"

def _is_transient(s): return _classify_gemini_error(s) in ("overloaded","unknown")
def _is_quota(s): return _classify_gemini_error(s)=="quota_exhausted"

def _strip_json_fences(raw):
    raw=raw.strip()
    if raw.startswith("```"): raw=raw.strip("`");
    if raw.lower().startswith("json"): raw=raw[4:].strip()
    return raw

def _build_gemini_config(model, temperature=None):
    """Disable thinking on 2.5+ models (it's the default and adds 10-60s of latency
    for our structured-JSON tasks). Force JSON mime type so we don't have to
    strip ``` fences. 2.0 models don't accept thinking_config — branch on name.
    Optional temperature override for ensemble runs."""
    from google.genai import types as genai_types
    kwargs = {"response_mime_type": "application/json"}
    if temperature is not None:
        kwargs["temperature"] = float(temperature)
    if "2.5" in model or "3-" in model or "3." in model:
        kwargs["thinking_config"] = genai_types.ThinkingConfig(thinking_budget=0)
    return genai_types.GenerateContentConfig(**kwargs)

def gemini_call(prompt, models=None, temperature=None, client_idx=None):
    """One Gemini call with per-key cooldown awareness and key fallback.

    If `client_idx` is given, this call uses that specific key and does NOT
    rotate (used by ensemble where each thread is pinned to its own key).
    Otherwise it iterates over all available (non-cooldown) keys, trying each
    model. Sets cooldown on any 429 quota error. Never recurses."""
    clients = state.get("gemini_clients", [])
    if not clients: return None
    models = models or GEMINI_MODELS
    last_error = None; last_cat = None

    # Decide which keys this call may try. Pinned (ensemble) calls use exactly one.
    if client_idx is not None:
        key_order = [client_idx]
    else:
        # Start from current active key, then iterate through the rest, skipping
        # those already on cooldown. This stays in-order even across rotations.
        cur = state.get("gemini_active_idx", 0)
        n = len(clients)
        key_order = [(cur + i) % n for i in range(n)]
        key_order = [i for i in key_order
                     if clients[i] is not None and not _key_in_cooldown(i)]
        if not key_order:
            state["last_gemini_error"] = {"category": "quota_exhausted",
                                           "details": "All keys on cooldown."}
            return None

    for key_i in key_order:
        client = clients[key_i]
        for model in models:
            cfg = _build_gemini_config(model, temperature=temperature)
            for attempt in range(GEMINI_ATTEMPTS_PER_MODEL):
                try:
                    t0 = time.time()
                    resp = client.models.generate_content(model=model, contents=prompt, config=cfg)
                    elapsed = time.time() - t0
                    raw = _strip_json_fences(resp.text or "")
                    data = json.loads(raw); data["_model_used"] = model
                    # Promote this key to active so subsequent non-pinned calls start here
                    if client_idx is None:
                        state["gemini_active_idx"] = key_i; state["gemini"] = client
                    print(f"[OK] Gemini via {model} (key #{key_i+1}) in {elapsed:.1f}s")
                    return data
                except Exception as e:
                    err = str(e); last_error = f"{model}: {err[:200]}"; last_cat = _classify_gemini_error(err)
                    print(f"[WARN] {model} key #{key_i+1} attempt {attempt+1} [{last_cat}]: {err[:200]}")
                    if _is_quota(err):
                        # Long cooldown for "daily" / RPD signals, short for RPM
                        is_daily = ("RPD" in err or "daily" in err.lower() or "PerDay" in err)
                        _put_key_on_cooldown(key_i,
                                              seconds=(6*3600 if is_daily else 90),
                                              reason="429 RESOURCE_EXHAUSTED" + (" (daily)" if is_daily else ""))
                        break        # stop retrying THIS key — move to next
                    if _is_transient(err) and attempt + 1 < GEMINI_ATTEMPTS_PER_MODEL:
                        time.sleep(GEMINI_RETRY_DELAY); continue
                    break              # non-retriable error for this model — try next model on same key
            else:
                continue
            # If we broke out due to quota, no more models — go to next key
            if _is_quota(last_error or ""): break

    state["last_gemini_error"] = {"category": last_cat or "unknown", "details": last_error or ""}
    return None

def _coerce_articles(raw):
    if raw is None: return []
    if isinstance(raw,str): s=raw.strip(); return [s] if s else []
    if isinstance(raw,list): return [str(i).strip() for i in raw if i is not None and str(i).strip()]
    return []

def gemini_rewrite(text, temperature=None, client_idx=None):
    data=gemini_call(REWRITE_PROMPT.replace("__USER_TEXT__",text),
                      temperature=temperature, client_idx=client_idx)
    if not data: return None
    sq=str(data.get("search_query","")).strip()
    rq=str(data.get("rewritten_query","")).strip()
    articles=_coerce_articles(data.get("suggested_articles") if "suggested_articles" in data else data.get("suggested_article"))
    reasoning=str(data.get("reasoning","")).strip()
    dl=str(data.get("detected_language","en")).strip().lower() or "en"
    keywords=data.get("keywords",[])
    if isinstance(keywords,list): keywords=[str(k).strip() for k in keywords if k]
    else: keywords=[]
    if not sq: sq=rq or text
    if not rq: rq=sq
    return {"search_query":sq,"rewritten_query":rq,"suggested_articles":articles,
            "suggested_article":articles[0] if articles else None,"reasoning":reasoning,
            "detected_language":dl,"keywords":keywords,"model_used":data.get("_model_used")}

# ---------- Ensemble rewrite ----------
ENSEMBLE_N    = 3       # parallel rewrites per natural-mode search. Each one
                         # "votes" on which cases matter; consensus drives ranking.
                         # We round-robin across available keys so a single key's
                         # RPM quota isn't hit by all N requests at once.
ENSEMBLE_TEMP = 0.7

def gemini_rewrite_ensemble(text, n=ENSEMBLE_N, temperature=ENSEMBLE_TEMP):
    """Run N independent rewrites in parallel, distributing them round-robin
    across available (non-cooldown) keys. With 2 keys and N=3 each key handles
    at most 2 concurrent calls — well within Gemini Flash free-tier limits."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    avail = _available_key_indices()
    if not avail:
        print("[ensemble] no Gemini keys available (all on cooldown)")
        return []
    # Round-robin assignment: rewrite i -> key avail[i % len(avail)]
    assignments = [avail[i % len(avail)] for i in range(n)]
    print(f"[ensemble] {n} rewrites assigned to keys: " +
          ", ".join(f"#{idx+1}" for idx in assignments))
    rewrites = []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=n) as pool:
        futures = [pool.submit(gemini_rewrite, text, temperature, idx) for idx in assignments]
        for f in as_completed(futures):
            try:
                r = f.result()
                if r: rewrites.append(r)
            except Exception as e:
                print(f"[ensemble] one rewrite failed: {str(e)[:120]}")
    elapsed = time.time() - t0
    print(f"[ensemble] {len(rewrites)}/{n} rewrites in {elapsed:.1f}s (temp={temperature})")
    return rewrites

def _gemini_error_message():
    info=state.get("last_gemini_error",{})
    cat=info.get("category","unknown"); n=len(state.get("gemini_keys",[]))
    if cat=="quota_exhausted":
        cd = state.get("gemini_cooldowns", {})
        now = time.time()
        active_cooldowns = [(i, until - now) for i, until in cd.items() if until > now]
        if active_cooldowns:
            soonest = min(active_cooldowns, key=lambda x: x[1])
            secs = int(soonest[1])
            if secs > 300:
                hrs = secs // 3600; mins = (secs % 3600) // 60
                wait = f"{hrs}h{mins:02d}m"
            else:
                wait = f"{secs}s"
            return (f"All {n} Gemini key(s) on quota cooldown. "
                    f"Next key (#{soonest[0]+1}) free in ~{wait}. "
                    f"Free tier resets RPM every minute, daily quota at midnight Pacific.")
        return f"All {n} Gemini key(s) exhausted. Wait until ~9:00 AM Polish time or add more keys."
    if cat=="auth_failed": return "Gemini API key invalid. Update gemini_key.txt."
    if cat=="overloaded": return "Gemini temporarily overloaded. Wait 30-60 seconds."
    return "Gemini call failed. Check server log."

# ---------- Preload ----------
def preload_respondents(collection, total):
    seen=set(); offset=0; scanned=0; t0=time.time()
    while offset<total:
        try: chunk=collection.get(limit=PRELOAD_BATCH,offset=offset,include=["metadatas"])
        except: break
        metas=chunk.get("metadatas") or []
        if not metas: break
        for m in metas:
            if m and m.get("respondent"):
                for c in split_states(m["respondent"]): seen.add(c)
        scanned+=len(metas); offset+=PRELOAD_BATCH
    print(f"[*] Preload: {scanned:,} records, {len(seen)} states, {time.time()-t0:.1f}s")
    return sorted(seen)

def preload_sections(collection, total):
    seen=set(); offset=0
    while offset<total:
        try: chunk=collection.get(limit=PRELOAD_BATCH,offset=offset,include=["metadatas"])
        except: break
        metas=chunk.get("metadatas") or []
        if not metas: break
        for m in metas:
            if m and m.get("section"): seen.add(m["section"])
        offset+=PRELOAD_BATCH
    return sorted(seen)

# ---------- Lifespan ----------
@asynccontextmanager
async def lifespan(app):
    print("="*50+"\n  ECHR RAG Search v2.21 - Loading...\n"+"="*50)
    if not Path(DB_PATH).exists(): print("[ERROR] No ANN index"); sys.exit(1)
    print("[*] Loading FAISS index (voyage-4-large SQ8)...")
    state["index"]=faiss.read_index(ANN_INDEX); state["index"].nprobe=ANN_NPROBE
    count=state["index"].ntotal
    print("[*] Loading id map...")
    ids=[json.loads(l) for l in open(IDS_FILE,encoding="utf-8")]
    state["case"]=[r["case_id"] for r in ids]
    state["sno"]=[r["section_no"] for r in ids]
    state["rid"]=[r["rowid"] for r in ids]
    print("[*] Loading case metadata...")
    state["meta"]=json.loads(Path(META_FILE).read_text(encoding="utf-8"))
    print("[*] Loading section + article tags...")
    rowsec={}
    for l in open(ROWSEC_FILE,encoding="utf-8"):
        a,b=l.rstrip("\n").split("\t"); rowsec[int(a)]=b
    state["rowsec"]=rowsec
    artmap={}
    for l in open(ARTMAP_FILE,encoding="utf-8"):
        c,s,t=l.rstrip("\n").split("\t"); artmap[(c,int(s))]=t
    state["artmap"]=artmap
    state["fts"]=sqlite3.connect(f"file:{FTS_DB}?mode=ro",uri=True,check_same_thread=False)
    state["collection"]=None
    # respondents + sections from metadata (for the UI facets)
    resp=set();
    for m in state["meta"].values():
        for s in split_states((m or {}).get("state","")): resp.add(s)
    state["respondents"]=sorted(resp)
    state["sections"]=sorted({v for v in rowsec.values() if v})
    print(f"    Sections: {state['sections']}")
    # Optional pre-built citation graph (built by build_citations.py)
    cit_path = Path(CITATIONS_FILE)
    if cit_path.exists():
        try:
            t0 = time.time()
            graph = json.loads(cit_path.read_text(encoding="utf-8"))
            state["citation_graph"] = graph
            n_with_cited = sum(1 for v in graph.values() if v.get("cited_by"))
            print(f"[*] Citation graph loaded: {len(graph):,} cases, "
                  f"{n_with_cited:,} cited by ≥1 other ({time.time()-t0:.1f}s, "
                  f"{cit_path.stat().st_size/1e6:.1f} MB)")
        except Exception as e:
            print(f"[WARN] Could not load {CITATIONS_FILE}: {e}")
            state["citation_graph"] = None
    else:
        state["citation_graph"] = None
        print(f"[INFO] {CITATIONS_FILE} not found — citation graph disabled. "
              f"Run build_citations.py to enable.")
    try: import docx; state["docx_available"]=True; print("[*] python-docx OK")
    except: state["docx_available"]=False; print("[WARN] python-docx missing")
    keys=load_gemini_keys()
    if keys:
        print(f"[*] {len(keys)} Gemini key(s):")
        try:
            init_gemini_clients(keys)
            print(f"[*] Gemini enabled, capacity ~{len(keys)*1500}/day")
        except Exception as e: print(f"[WARN] Gemini disabled ({e})"); state["gemini"]=None
    else: state["gemini"]=None; state["gemini_keys"]=[]; state["gemini_clients"]=[]
    print(f"\n{'='*50}\n  Ready! Paragraphs: {count:,} | States: {len(state['respondents'])} | Keys: {len(keys)}\n  http://localhost:8000/search_ui.html\n{'='*50}\n")
    yield

app=FastAPI(title="ECHR RAG v2.21",lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=["*"],allow_methods=["*"],allow_headers=["*"])

# ---------- Search ----------
def _auth(cid):
    return IMP_W.get((state["meta"].get(cid, {}) or {}).get("importance"), 0.0)

def run_paragraph_search(query_text, respondent=None, article=None, section=None, pool_size=None):
    # 1) embed query with voyage-4-large, ANN search (cosine via inner product)
    qv = np.array(embed.voyage_embed([query_text[:1500]], model=VOYAGE_MODEL, input_type="query")[0], dtype="float32").reshape(1, -1)
    faiss.normalize_L2(qv)
    fetch_k = pool_size or (FETCH_POOL_FILTERED if (respondent or article or section) else FETCH_POOL)
    D, I = state["index"].search(qv, fetch_k)
    case, sno, rid = state["case"], state["sno"], state["rid"]
    meta, rowsec, artmap, fts = state["meta"], state["rowsec"], state["artmap"], state["fts"]
    # batch-fetch paragraph text
    pos = [int(i) for i in I[0] if i >= 0]
    rids = [rid[p] for p in pos]
    txt = {}
    if rids:
        txt = {r: t for r, t in fts.execute(
            "SELECT rid,text FROM para WHERE rid IN (%s)" % ",".join("?" * len(rids)), rids)}
    # candidate list (cosine order), after metadata filters
    cand = []   # (pos, cosine, sec, meta, articles)
    for scr, p in zip(D[0], pos):
        cid = case[p]; s = sno[p]; m = meta.get(cid, {}) or {}
        if respondent and respondent not in split_states(m.get("state", "") or ""): continue
        arts = [str(x) for x in (m.get("violation") or [])]
        if article and article not in arts and artmap.get((cid, s)) != article: continue
        sec = rowsec.get(rid[p], "")
        if section and sec != section: continue
        cand.append((p, float(scr), sec, m, arts))

    # 2) rerank top RERANK_POOL with rerank-2.5 (cross-encoder); fall back to cosine on error
    rr = None; src = cand
    if RERANK_ENABLED and len(cand) > 1:
        head = cand[:RERANK_POOL]
        docs = [(txt.get(rid[p]) or "")[:1200] for p, *_ in head]
        try:
            rr = {i: sc for i, sc in embed.voyage_rerank(query_text, docs, model=RERANK_MODEL)}
            src = head
        except SystemExit as e:
            print(f"[rerank skipped this query] {str(e)[:90]}"); rr = None; src = cand

    # 3) final score = relevance (rerank else cosine) + importance authority boost
    paragraphs = []
    for idx, (p, cos, sec, m, arts) in enumerate(src):
        cid = case[p]; s = sno[p]
        base = rr.get(idx, 0.0) if rr is not None else cos
        sc = float(base) + IMP_BOOST * _auth(cid)
        paragraphs.append({"score": round(sc, 4), "case_id": cid, "case_no": m.get("case_no", "") or "",
            "title": m.get("title", "") or "", "hudoc_url": m.get("hudoc", "") or "",
            "judgment_date": m.get("date", "") or "", "respondent": m.get("state", "") or "",
            "articles": arts, "section": sec, "para_idx": s if s is not None else 0,
            "text": txt.get(rid[p], "")})
    paragraphs.sort(key=lambda x: -x["score"])
    return paragraphs

def _match_tier(top_s):
    """Match-quality tier used for primary sort: 0=Strong, 1=Good, 2=Possible, 3=Weak."""
    if top_s >= 0.80: return 0
    if top_s >= 0.72: return 1
    if top_s >= 0.65: return 2
    return 3

def group_by_case(paragraphs, max_cases, case_appearances=None):
    """Aggregate paragraph-level search results into cases.

    When case_appearances is provided (dict: case_id -> set of run indices),
    the secondary sort key becomes appearance_count desc — cases agreed upon by
    more ensemble runs rank higher within their tier. Otherwise the secondary
    key is hit_count.
    """
    grouped=OrderedDict()
    for p in paragraphs:
        cid=p.get("case_id") or p.get("title") or "_"
        if cid not in grouped:
            grouped[cid]={"case_id":cid,"case_no":p.get("case_no",""),"title":p.get("title",""),
                "hudoc_url":p.get("hudoc_url",""),"judgment_date":p.get("judgment_date",""),
                "respondent":p.get("respondent",""),"articles":list(p.get("articles",[])),"top_score":p.get("score",0),"hits":[]}
        c=grouped[cid]
        if p.get("score",0)>c["top_score"]: c["top_score"]=p["score"]
        for a in p.get("articles",[]): 
            if a not in c["articles"]: c["articles"].append(a)
        c["hits"].append({"score":p.get("score",0),"section":p.get("section",""),"para_idx":p.get("para_idx",0),"text":p.get("text","")})
    cases=[]
    for c in grouped.values():
        c["hit_count"]=len(c["hits"]); c["hits"].sort(key=lambda h:h.get("score",0),reverse=True)
        scores=[h["score"] for h in c["hits"]]
        top_s=max(scores); avg_s=sum(scores)/len(scores); log_f=hit_count_log_factor(len(c["hits"]))
        c["avg_score"]=round(avg_s,4); c["case_score"]=round(RANK_WEIGHT_TOP*top_s+RANK_WEIGHT_AVG*avg_s+RANK_WEIGHT_LOG*log_f,4)
        cases.append(c)
    # Annotate appearance counts when we have ensemble data
    if case_appearances is not None:
        for c in cases:
            c["appearance_count"] = len(case_appearances.get(c["case_id"], set()))
        # Sort: tier first, then consensus across runs (more runs = stronger signal),
        # then hit_count, then case_score as tie-breaker.
        cases.sort(key=lambda c: (_match_tier(c.get("top_score", 0)),
                                    -c.get("appearance_count", 0),
                                    -c.get("hit_count", 0),
                                    -c.get("case_score", 0)))
    else:
        # Default single-run sort: tier → hit_count → case_score
        cases.sort(key=lambda c: (_match_tier(c.get("top_score", 0)),
                                    -c.get("hit_count", 0),
                                    -c.get("case_score", 0)))
    return cases[:max_cases]

def cases_to_flat(cases,max_total,ppc):
    flat=[]
    for r in range(ppc):
        for c in cases:
            if r<len(c["hits"]):
                h=c["hits"][r]
                flat.append({"score":h["score"],"case_id":c["case_id"],"case_no":c["case_no"],"title":c["title"],
                    "hudoc_url":c["hudoc_url"],"judgment_date":c["judgment_date"],"respondent":c["respondent"],
                    "articles":c["articles"],"section":h["section"],"para_idx":h["para_idx"],"text":h["text"]})
                if len(flat)>=max_total: return flat
    return flat

def fmt_precedents(precs):
    lines=[]
    for i,p in enumerate(precs,1):
        lines.append(f"[P{i}]\n  case_title: {p.get('title','')}\n  case_no: {p.get('case_no','')}\n  respondent: {p.get('respondent','')}\n  judgment_date: {p.get('judgment_date','')}\n  articles: {', '.join(p.get('articles',[]))}\n  section: {p.get('section','')} §{p.get('para_idx','')}\n  hudoc_url: {p.get('hudoc_url','')}")
        t=(p.get("text") or "").strip(); 
        if len(t)>1200: t=t[:1200]+" [...]"
        lines.append(f"  text: {t}\n")
    return "\n".join(lines)

# ---------- Routes ----------
NO_CACHE_HEADERS = {"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                    "Pragma": "no-cache", "Expires": "0"}

def _serve_html(path):
    if not Path(path).exists(): raise HTTPException(404, f"{path} not found on server")
    return FileResponse(path, headers=NO_CACHE_HEADERS)

# Canonical roots
@app.get("/")
def root(): return _serve_html(SEARCH_HTML)

# Methodology / accuracy page (replaces the retired draft-complaint app).
@app.get("/methodology")
@app.get("/echr/methodology")
@app.get("/draft")              # legacy: old "Draft" links now land on methodology
@app.get("/echr/draft")
def methodology_page(): return _serve_html(METH_HTML)

# Legacy / convenience aliases.
@app.get("/search_ui.html")
@app.get("/echr/")
@app.get("/echr/search_ui.html")
def search_alias(): return _serve_html(SEARCH_HTML)

@app.get("/health")
def health():
    keys=state.get("gemini_keys",[])
    return {"status":"ok","indexed_points":state["index"].ntotal,"respondents":len(state.get("respondents",[])),
        "gemini_enabled":get_active_gemini_client() is not None,"gemini_models":GEMINI_MODELS if keys else None,
        "gemini_keys_total":len(keys),"gemini_active_key":state.get("gemini_active_idx",0)+1 if keys else 0,
        "docx_available":state.get("docx_available",False),"sections":state.get("sections",[]),
        "citation_graph_loaded": state.get("citation_graph") is not None,
        "citation_graph_size": len(state.get("citation_graph") or {}),
        "version":"2.21"}

@app.get("/respondents")
def respondents(): return {"respondents":state.get("respondents",[])}

@app.get("/sections")
def sections(): return {"sections":state.get("sections",[])}

# ---------- Citation graph ----------
import re as _re
import unicodedata as _ud

def _cite_norm(s):
    if not s: return ""
    s = _ud.normalize("NFKD", str(s))
    s = "".join(c for c in s if not _ud.combining(c))           # strip diacritics
    s = s.lower().replace("'", "").replace("\u2018", "").replace("\u2019", "")
    return _re.sub(r"\s+", " ", s).strip()

def _cite_year(d):
    if not d: return None
    m = _re.search(r"(19\d{2}|20\d{2})", str(d))
    return int(m.group(1)) if m else None

def _build_pattern(meta):
    title = meta.get("title", "") or ""
    title = _re.sub(r"^\s*case of\s+", "", title, flags=_re.I)
    title = _re.sub(r"\s*\[GC\]\s*", " ", title, flags=_re.I)
    title = _re.sub(r"\s+v\..+$", "", title, flags=_re.I).strip()
    case_no_raw = meta.get("case_no", "") or ""
    case_no = _re.sub(r"[^0-9/,]", "", case_no_raw).split(",")[0]
    return {"applicant": _cite_norm(title), "case_no": _cite_norm(case_no)}

class CitationsRequest(BaseModel):
    case_ids: list[str]

@app.post("/citations")
def citations(req: CitationsRequest):
    """Return citation data for a list of case_ids.

    When the pre-built citation graph (citations.json) is loaded, this is fast
    and includes GLOBAL counts (cited_by_total, cites_total) computed across the
    entire corpus — that's what powers "this case is foundational, cited by 312
    others" in the dossier.

    When the graph isn't loaded, falls back to scanning chroma on-the-fly. Slower
    and the totals are only across the requested set (so they're labelled
    cited_by_total = local in-degree).

    Returns:
      edges:           [{"from": cid, "to": cid}, ...]    edges *within* the requested set
      cited_by_total:  {cid: int}    GLOBAL count when graph loaded, else local in-degree
      cites_total:     {cid: int}    GLOBAL count when graph loaded, else local out-degree
      cited_by_sample: {cid: [{case_id, title, judgment_date}, ...]}   for dossier
      cites_sample:    {cid: [{case_id, title, judgment_date}, ...]}   for dossier
      meta:            {cid: {title, case_no, judgment_date}}
      stats:           {source: "graph"|"on-the-fly", elapsed_seconds, ...}
    """
    t0 = time.time()
    ids = list(dict.fromkeys([c for c in (req.case_ids or []) if c]))
    if not ids:
        return {"edges": [], "cited_by_total": {}, "cites_total": {},
                "cited_by_sample": {}, "cites_sample": {}, "meta": {},
                "stats": {"source": "empty", "elapsed_seconds": 0.0}}

    graph = state.get("citation_graph")
    if graph:
        return _citations_from_graph(ids, graph, t0)
    return _citations_on_the_fly(ids, t0)

def _citations_from_graph(ids, graph, t0):
    """Fast path: precomputed graph in memory."""
    id_set = set(ids)
    edges = []
    cited_by_total = {}
    cites_total = {}
    cited_by_sample = {}
    cites_sample = {}
    cmeta = {}

    SAMPLE_LIMIT = 12

    for cid in ids:
        node = graph.get(cid)
        if not node:
            cited_by_total[cid] = 0
            cites_total[cid] = 0
            cited_by_sample[cid] = []
            cites_sample[cid] = []
            cmeta[cid] = {"title": "", "case_no": "", "judgment_date": ""}
            continue
        cmeta[cid] = {
            "title": node.get("title", ""),
            "case_no": node.get("case_no", ""),
            "judgment_date": node.get("judgment_date", ""),
        }
        cites_list = node.get("cites", [])
        cited_by_list = node.get("cited_by", [])
        cited_by_total[cid] = len(cited_by_list)
        cites_total[cid] = len(cites_list)

        # Edges within the requested set only
        for tgt in cites_list:
            if tgt in id_set and tgt != cid:
                edges.append({"from": cid, "to": tgt})

        # Sample expansions for the dossier (sorted by tgt cited_by_total desc — most prominent first)
        def expand(cid_list):
            entries = []
            for c in cid_list:
                m = graph.get(c)
                if not m: continue
                entries.append({
                    "case_id": c,
                    "title": m.get("title", ""),
                    "judgment_date": m.get("judgment_date", ""),
                    "cited_by_count": len(m.get("cited_by", [])),
                })
            entries.sort(key=lambda x: -x["cited_by_count"])
            return entries[:SAMPLE_LIMIT]

        cites_sample[cid] = expand(cites_list)
        cited_by_sample[cid] = expand(cited_by_list)

    elapsed = time.time() - t0
    print(f"[citations] graph mode · {len(ids)} cases · {len(edges)} edges · {elapsed*1000:.0f}ms")
    return {
        "edges": edges,
        "cited_by_total": cited_by_total,
        "cites_total": cites_total,
        "cited_by_sample": cited_by_sample,
        "cites_sample": cites_sample,
        "meta": cmeta,
        "stats": {"source": "graph", "elapsed_seconds": round(elapsed, 3)},
    }

def _citations_on_the_fly(ids, t0):
    """Slow fallback when citations.json isn't built yet. Local degrees only."""
    coll = state["collection"]
    if coll is None:
        return {"nodes": [], "edges": [], "note": "citation graph requires citations.json"}
    cases_meta = {}
    cases_text = {}
    paragraphs_scanned = 0
    for cid in ids:
        try:
            res = coll.get(where={"case_id": cid}, include=["documents", "metadatas"])
            docs = res.get("documents") or []
            metas = res.get("metadatas") or []
            cases_text[cid] = _cite_norm(" ".join(d for d in docs if d))
            paragraphs_scanned += len(docs)
            if metas and metas[0]:
                m = metas[0]
                cases_meta[cid] = {
                    "title": m.get("title", "") or "",
                    "case_no": m.get("case_no", "") or "",
                    "judgment_date": m.get("judgment_date", "") or "",
                }
            else:
                cases_meta[cid] = {"title": "", "case_no": "", "judgment_date": ""}
        except Exception as e:
            print(f"[citations] fetch failed for {cid}: {e}")
            cases_text[cid] = ""
            cases_meta[cid] = {"title": "", "case_no": "", "judgment_date": ""}

    patterns = {cid: _build_pattern(cases_meta[cid]) for cid in ids}

    edges = []
    in_degree  = {cid: 0 for cid in ids}
    out_degree = {cid: 0 for cid in ids}

    for src in ids:
        src_year = _cite_year(cases_meta[src]["judgment_date"])
        text = cases_text.get(src, "")
        if not text: continue
        for tgt in ids:
            if tgt == src: continue
            tgt_year = _cite_year(cases_meta[tgt]["judgment_date"])
            if src_year and tgt_year and tgt_year >= src_year:
                continue
            p = patterns[tgt]
            cited = False
            if p["case_no"] and len(p["case_no"]) >= 5 and p["case_no"] in text:
                cited = True
            elif p["applicant"] and len(p["applicant"]) >= 4 and p["applicant"] in text:
                cited = True
            if cited:
                edges.append({"from": src, "to": tgt})
                in_degree[tgt]  += 1
                out_degree[src] += 1

    chars_scanned = sum(len(t) for t in cases_text.values())
    elapsed = time.time() - t0
    print(f"[citations] on-the-fly · {len(ids)} cases · {paragraphs_scanned:,} paragraphs · "
          f"{chars_scanned:,} chars · {len(edges)} edges · {elapsed:.2f}s "
          f"(NOTE: run build_citations.py for global cited_by counts)")
    return {
        "edges": edges,
        "cited_by_total": in_degree,           # local fallback
        "cites_total": out_degree,             # local fallback
        "cited_by_sample": {cid: [] for cid in ids},   # we don't know globally here
        "cites_sample": {cid: [] for cid in ids},
        "meta": cases_meta,
        "stats": {
            "source": "on-the-fly",
            "paragraphs_scanned": paragraphs_scanned,
            "chars_scanned": chars_scanned,
            "elapsed_seconds": round(elapsed, 3),
        },
    }

@app.get("/similar")
def similar(q:str=Query(...),k:int=Query(10,ge=1,le=50),respondent:str|None=Query(None),article:str|None=Query(None),section:str|None=Query(None)):
    t0 = time.time()
    paras=run_paragraph_search(q,respondent,article,section)
    cases=group_by_case(paras,k)
    return {"mode":"expert","query":q,"count":len(cases),"results":cases,
            "stats":{"paragraphs_pooled": len(paras),
                      "elapsed_ms": int((time.time()-t0)*1000)}}

# Two search "styles" the user can pick before clicking Search precedents.
# Creative is faster and explores more breadth with higher sampling temperature.
# Conservative does twice as many rewrites at a lower temperature, so the
# consensus across runs is tighter and rankings stabilise toward the trunk
# of the relevance distribution.
STYLE_PRESETS = {
    "creative":     {"n": 3, "temp": 0.85},
    "conservative": {"n": 6, "temp": 0.55},
}

@app.get("/smart_search")
def smart_search(q:str=Query(...),k:int=Query(10,ge=1,le=50),respondent:str|None=Query(None),article:str|None=Query(None),section:str|None=Query(None),
                  style:str=Query("creative")):
    if not get_active_gemini_client(): raise HTTPException(503,"Gemini not configured.")
    t0 = time.time()
    preset = STYLE_PRESETS.get(style, STYLE_PRESETS["creative"])

    # ---- 1) Ensemble of independent Gemini rewrites (parallel) ----
    rewrites = gemini_rewrite_ensemble(q, n=preset["n"], temperature=preset["temp"])
    if not rewrites:
        raise HTTPException(503, _gemini_error_message())

    # ---- 2) For each rewrite, run paragraph search; pool results and track which
    # runs each CASE appeared in. Cases agreed upon by more runs will rank higher.
    from collections import defaultdict
    pooled = {}                              # (case_id, para_idx) -> paragraph dict
    case_appearances = defaultdict(set)       # case_id -> set of run indices
    per_run_hits = []
    for run_idx, rw in enumerate(rewrites):
        sq = rw["search_query"]
        ea = article if article else (rw["suggested_articles"][0] if len(rw["suggested_articles"]) == 1 else None)
        paras = run_paragraph_search(sq, respondent, ea, section)
        per_run_hits.append(len(paras))
        seen_in_this_run = set()
        for p in paras:
            pkey = (p.get("case_id", ""), p.get("para_idx", 0))
            existing = pooled.get(pkey)
            if existing is None or p["score"] > existing["score"]:
                pooled[pkey] = p
            seen_in_this_run.add(p.get("case_id", ""))
        for cid in seen_in_this_run:
            case_appearances[cid].add(run_idx)

    # ---- 3) Group with consensus-aware sort ----
    pooled_list = sorted(pooled.values(), key=lambda p: -p["score"])
    cases = group_by_case(pooled_list, k, case_appearances=case_appearances)
    # Annotate appearance_total for the UI ("3/5 runs found this case")
    for c in cases:
        c["appearance_total"] = len(rewrites)

    # ---- 4) Aggregate metadata across rewrites ----
    primary = rewrites[0]
    union_articles = []
    for rw in rewrites:
        for a in rw["suggested_articles"]:
            if a not in union_articles: union_articles.append(a)
    union_keywords = []
    for rw in rewrites:
        for kw in rw.get("keywords", []):
            if kw not in union_keywords: union_keywords.append(kw)
    if article: ea = article
    elif len(union_articles) == 1: ea = union_articles[0]
    else: ea = None

    data = {"mode": "natural", "style": style if style in STYLE_PRESETS else "creative",
            "original_query": q,
            "search_query": primary["search_query"],
            "rewritten_query": primary["rewritten_query"],
            "rewritten_queries": [rw["rewritten_query"] for rw in rewrites],
            "search_queries":    [rw["search_query"]    for rw in rewrites],
            "suggested_articles": union_articles,
            "suggested_article": union_articles[0] if union_articles else None,
            "effective_article": ea,
            "detected_language": primary["detected_language"],
            "reasoning": primary["reasoning"],
            "keywords": union_keywords,
            "model_used": primary["model_used"],
            "count": len(cases), "results": cases,
            "stats": {"style": style if style in STYLE_PRESETS else "creative",
                       "ensemble_runs": len(rewrites),
                       "ensemble_target": preset["n"],
                       "temperature": preset["temp"],
                       "paragraphs_per_run": per_run_hits,
                       "paragraphs_pooled": len(pooled_list),
                       "unique_cases_seen": len(case_appearances),
                       "elapsed_ms": int((time.time()-t0)*1000)}}

    print(f"[smart_search] style={style} ({preset['n']} rewrites @ temp={preset['temp']}) · "
          f"got {len(rewrites)}/{preset['n']} · pooled {len(pooled_list)} paragraphs from {per_run_hits} per-run · "
          f"{len(case_appearances)} unique cases · top {len(cases)} returned · {data['stats']['elapsed_ms']}ms")
    return data

# ---------- Drafting ----------
class DraftRequest(BaseModel):
    description:str; respondent:str|None=None; article:str|None=None

def _gen_draft(desc,lang,arts,precs,rq="",sq="",reasoning="",ea=None):
    arts_str=", ".join(arts) if arts else "null"
    prompt=DRAFT_PROMPT.replace("__USER_TEXT__",desc).replace("__USER_LANG__",lang).replace("__ARTICLES__",arts_str).replace("__K__",str(len(precs))).replace("__PRECEDENTS__",fmt_precedents(precs))
    d=gemini_call(prompt,DRAFT_GEMINI_MODELS)
    if not d: raise HTTPException(503,_gemini_error_message())
    # Normalize hudoc_keywords to a clean list of non-empty strings
    raw_kw = d.get("hudoc_keywords", []) or []
    if isinstance(raw_kw, list):
        hudoc_keywords = [str(x).strip() for x in raw_kw if x and str(x).strip()]
    else:
        hudoc_keywords = []
    return {"detected_language":lang,"suggested_articles":arts,"effective_article":ea,"reasoning":reasoning,
        "search_query":sq,"rewritten_query":rq,"precedents_used":precs,
        "draft":{"user_language":d.get("user_language",{}),"english":d.get("english",{})},
        "citations_used":d.get("citations_used",[]),"warnings":d.get("warnings",[]),
        "hudoc_keywords":hudoc_keywords,
        "model_used":d.get("_model_used")}

@app.post("/draft_complaint")
def draft_complaint(req:DraftRequest):
    if not get_active_gemini_client(): raise HTTPException(503,"Gemini not configured.")
    if not req.description or len(req.description.strip())<50: raise HTTPException(400,"Too short.")
    rw=gemini_rewrite(req.description)
    if not rw: raise HTTPException(503,_gemini_error_message())
    sa=rw["suggested_articles"]
    if req.article: ea=req.article
    elif len(sa)==1: ea=sa[0]
    else: ea=None
    paras=run_paragraph_search(rw["search_query"],req.respondent,ea)
    if not paras and ea: paras=run_paragraph_search(rw["search_query"],req.respondent,None)
    cases=group_by_case(paras,DRAFT_MAX_CASES)
    precs=cases_to_flat(cases,DRAFT_MAX_CASES*DRAFT_PARAS_PER_CASE,DRAFT_PARAS_PER_CASE)
    if not precs: raise HTTPException(404,"No precedents found.")
    return _gen_draft(req.description,rw["detected_language"],sa,precs,rw.get("rewritten_query",""),rw["search_query"],rw.get("reasoning",""),ea)

class DraftFromExistingRequest(BaseModel):
    description:str; detected_language:str; suggested_articles:list[str]; precedents:list[dict]
    rewritten_query:str=""; search_query:str=""; reasoning:str=""; effective_article:str|None=None

@app.post("/draft_from_existing")
def draft_from_existing(req:DraftFromExistingRequest):
    if not get_active_gemini_client(): raise HTTPException(503,"Gemini not configured.")
    if not req.precedents: raise HTTPException(400,"No precedents.")
    if not req.description or len(req.description.strip())<50: raise HTTPException(400,"Too short.")
    return _gen_draft(req.description,req.detected_language or "en",req.suggested_articles or [],req.precedents,
        req.rewritten_query,req.search_query,req.reasoning,req.effective_article)

# ---------- Download ----------
class DownloadRequest(BaseModel):
    section_d:str; section_e:str; section_f:str; language_code:str; citations:list[dict]=[]; format:str|None="docx"

@app.post("/download_draft")
def download_draft(req:DownloadRequest):
    want_docx=(req.format or "docx").lower()=="docx"
    docx_ok=state.get("docx_available",False)
    if want_docx and docx_ok:
        try: from docx import Document; from docx.shared import Pt
        except: docx_ok=False
    if not (want_docx and docx_ok):
        text=f"ECHR Complaint Draft ({req.language_code})\n{'='*60}\n\nD. Statement of the facts\n{'-'*40}\n{req.section_d}\n\nE. Alleged violations and arguments\n{'-'*40}\n{req.section_e}\n\nF. Admissibility\n{'-'*40}\n{req.section_f}\n\n"
        if req.citations:
            text+="Cited precedents:\n"+"-"*40+"\n"
            for c in req.citations: text+=f"[{c.get('marker','?')}] {c.get('case_title','')}\n    §{c.get('para_idx','')} | {c.get('respondent','')}\n    {c.get('hudoc_url','')}\n\n"
        text+="\nDISCLAIMER: AI-generated draft. NOT legal advice.\n"
        buf=io.BytesIO(text.encode("utf-8"))
        return StreamingResponse(buf,media_type="text/plain; charset=utf-8",headers={"Content-Disposition":f'attachment; filename="echr_draft_{req.language_code}.txt"'})
    doc=Document()
    doc.add_heading(f"ECHR Complaint Draft ({req.language_code.upper()})",level=0)
    doc.add_heading("D. Statement of the facts",level=1); doc.add_paragraph(req.section_d)
    doc.add_heading("E. Alleged violations and arguments",level=1); doc.add_paragraph(req.section_e)
    doc.add_heading("F. Admissibility",level=1); doc.add_paragraph(req.section_f)
    if req.citations:
        doc.add_heading("Cited precedents",level=1)
        for c in req.citations:
            p=doc.add_paragraph(); p.add_run(f"[{c.get('marker','?')}] ").bold=True
            p.add_run(c.get("case_title","")); p.add_run(f"  §{c.get('para_idx','')} · {c.get('respondent','')}\n").italic=True
            p.add_run(c.get("hudoc_url",""))
    doc.add_paragraph(); d_run=doc.add_paragraph().add_run("DISCLAIMER: AI-generated draft. NOT legal advice."); d_run.italic=True; d_run.font.size=Pt(9)
    buf=io.BytesIO(); doc.save(buf); buf.seek(0)
    return StreamingResponse(buf,media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition":f'attachment; filename="echr_draft_{req.language_code}.docx"'})

if __name__=="__main__":
    uvicorn.run(app,host="0.0.0.0",port=8000,log_level="warning")
