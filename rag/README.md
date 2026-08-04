# RAG — ECtHR paragraph-level semantic retrieval

Semantic search over **19,822 ECtHR judgments / 1.31 M paragraphs**, evaluated
against the Court's **41 official Case-Law Guides** used as a pinpoint-citation
answer key.

## Pipeline (current, validated)
```
query
  → voyage-4-large embedding (query side)
  → FAISS SQ8 ANN over 1.31M paragraph vectors   (top ~300)
  → rerank-2.5 cross-encoder on the top 100       (relevance)
  → + 0.05 × HUDOC importance                     (authority of the case)
  → group paragraphs into cases
```
`relevance ≠ authority`: rerank decides *which paragraph*, the importance boost
nudges toward *leading cases*. ~1 s/query (one Voyage embed + one rerank call).

## Folders
- **`app/`** — the deployable service: `rag_api.py` (FastAPI) + `search_ui.html`
  + `methodology.html` + `embed.py`. This is what runs the search UI.
- **`pipeline/`** — build the corpus & index:
  - `extract_corpus.py` → Option-C paragraph corpus from the DB
  - `embed_corpus.py` → voyage-4-large embeddings (checkpointed, token-aware batching)
  - `build_fts_local.py` → BM25/FTS5 + text store
  - `ann_build_eval.py` → FAISS SQ8 index (+ exact-vs-ANN check)
  - `eval_voyage.py`, `serve.py` (in-RAM tester)
- **`benchmark/`** — the guides benchmark + evaluation:
  - `extract_guides.py`, `build_gold.py`, `sample_items.py` (build the eval set)
  - `eval_*`, `run_*`, `*_experiment.py`, `judge_eval.py` (dense/hybrid/rerank,
    fusion sweep, function/article/importance/citation-graph studies, LLM judge,
    natural-vs-expert).

## Run the app
```bash
cd app
pip install -r requirements.txt
echo "YOUR_VOYAGE_KEY" > voyage_key     # free tier ok; rerank-2.5 uses the same key
# data/ must contain the prebuilt index + metadata (see "Build the index")
python rag_api.py                       # → http://127.0.0.1:8000
```
Modes/features: expert search, Advanced filters (respondent / section / N),
themes (Modern / Classic / Accessible), and an in-page "How it works" methodology
tab. Gemini "natural" mode and the draft-complaint feature are intentionally off.

## Build the index (artifacts are git-ignored)
From the corpus DB on the VM, in order: `extract_corpus.py` →
`embed_corpus.py` → `build_fts_local.py` → `ann_build_eval.py --build`.
Outputs land in `data/` (the 1.3 GB SQ8 index, `corpus_fts.db`, `ids.jsonl`,
`cases_meta.json`, tag files) — none committed to git.

## Rebuilding after a corpus update

New judgments are NOT searchable semantically until the index is rebuilt — the
FAISS index is a snapshot, and the monthly corpus update does not touch it.

Full rebuild (last run 2026-08-04, 1,318,250 paragraphs / 20,010 cases):

```
extract_corpus.py > data/corpus_textsC.jsonl.gz   # run against the live DB
embed_corpus.py --model voyage-4-large            # resumable; skips done rows
build_fts_local.py                                # BM25/FTS5, ~25 s
ann_build_eval.py --build                         # FAISS index, ~10 min
ann_build_eval.py --eval --nprobe 128             # gate: compare against below
build_row_section.py  > row_section.tsv           # section facets
build_cases_meta.py   > cases_meta.json           # titles + importance boost
```

Then upload `ann_index.index`, `ids.jsonl`, `corpus_fts.db`, `cases_meta.json`
and `row_section.tsv` to the VM's `/data/rag/` and restart `echr-api`.

**`ann_index.index` and `ids.jsonl` must be swapped together** — the n-th
vector corresponds to the n-th line, and a mismatch produces no error, just
results pointing at the wrong paragraphs.

**Keep `data/emb/voyage-4-large/vecs.f32.dat`** (5.4 GB). It is the only thing
that makes the next top-up cheap: with it, adding a month of judgments costs
cents; without it, the whole corpus has to be re-embedded. It was missing
before the August 2026 rebuild, which is why that rebuild was full rather than
incremental.

Known gap: `para_articles.tsv` has no generator in this repo, so paragraphs
from cases added after it was last built carry no article tag and will not
match the article filter.

## Accuracy (Court-Guides benchmark, 409-item sample)
| config | docHit@10 | paraHit@10 |
|---|--:|--:|
| dense (voyage-4-large) | 84 | 68 |
| + importance boost | 86 | 71 |
| **+ rerank-2.5 (top 100)** | **88** | **73** |

An independent Gemini relevance-judge rated ~85–90 % of the top-10 paragraphs
genuinely relevant (the strict gold metric understates real usefulness, since the
Guides cite only some of the relevant paragraphs).

## Key findings (what worked / didn't)
- **voyage-4-large** beat mpnet/BM25/old-hybrid decisively, esp. on lay queries — free tier.
- **rerank-2.5** improves true relevance more than the gold metric shows.
- **importance** (HUDOC) authority boost: the single best add (+5–10 pts). Citation-graph PageRank *lost* to it.
- Article filter, HyDE, and Gemini query-rewrite (“natural”) all *hurt* or were neutral → not used.
- SQ8 quantization ≈ exact (recall@50 98 %) at ¼ the size → deployable on a small VM.

**Research aid, not legal advice.** Not affiliated with the ECtHR.
