# ECHR Dashboard & Case-Law RAG

Tools for searching and analysing European Court of Human Rights (ECtHR)
case-law at the **paragraph level** — a public dashboard plus a semantic
retrieval (RAG) system anchored on the Court's official Case-Law Guides.

**Live dashboard:** https://lszoszk.github.io/ECHR-Dashboard/

---

## Repository layout

| Path | What it is |
|------|------------|
| **`docs/`** | The **live GitHub Pages dashboard** (HTML/CSS/JS). Auto-deployed from this folder on `main` (`.github/workflows/deploy-pages.yml`). Calls the API for live search. |
| **`api/`** | **Backend API** (FastAPI) powering the dashboard's search — runs in Docker on the VM (`echr-api`). |
| **`rag/`** | The **semantic retrieval system** (main research contribution): the search app, the embedding/index pipeline, and the evaluation benchmark. → [`rag/README.md`](rag/README.md) |
| **`scripts/`** | Corpus extraction, data-pipeline and audit scripts. |
| **`deploy/`** | Deployment helpers (`deploy.sh`, nginx config, `docker-compose.yml`). |
| **`legacy/`** | Archived earlier prototype (old Flask dashboard). Reference only. |
| **`notes-internal/`** | Working notes & methodology (sensitive audits are git-ignored). |
| **`data/`** | Local & VM data (corpus DB, raw JSONL…). **Git-ignored** — rebuilt by the scripts, never committed. |

## The RAG system in one paragraph
Query → **voyage-4-large** embedding → **FAISS** (compressed SQ8) over **1.31 M
ECtHR paragraphs** → **rerank-2.5** on the top 100 → **authority boost** (HUDOC
"importance") → results grouped into cases. Evaluated against the Court's 41
official Case-Law Guides. Full method, accuracy and how-to-run in
[`rag/README.md`](rag/README.md).

## Quick start — RAG search app
```bash
cd rag/app
pip install -r requirements.txt          # fastapi uvicorn faiss-cpu numpy certifi
echo "YOUR_VOYAGE_KEY" > voyage_key       # https://dashboard.voyageai.com (free tier ok)
# put the prebuilt index under rag/app/data/  (build it via rag/pipeline/ — see rag/README.md)
python rag_api.py                         # → http://127.0.0.1:8000
```

## Data & reproducibility
Large artifacts — the corpus DB, the ~1.3 GB FAISS index, the 5 GB embeddings —
are **not in git** (git-ignored). They are rebuildable from `rag/pipeline/` and
`scripts/`. Curated benchmark data is intended for separate release (e.g.
HuggingFace). The corpus is a point-in-time snapshot of English ECtHR judgments.

## Licensing / attribution
- Code: see `LICENSE`.
- ECtHR judgments & Case-Law Guides are © Council of Europe / ECtHR, reused under
  HUDOC terms. This project is **not affiliated with or endorsed by** the Court.
- The search tool is a **research aid, not legal advice.**
