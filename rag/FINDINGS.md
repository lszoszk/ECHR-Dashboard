# Findings — ECtHR paragraph-level retrieval

Consolidated conclusions from the two benchmarks (Court-Guides, Summary) and the
pipeline ablations. Numbers are docHit@k / paraHit@k (% of items whose gold
case / gold paragraph appears in the top k). Retriever unless stated:
voyage-4-large dense → rerank-2.5 → +0.05×importance.

## Bottom line
Strong **semantic** paragraph retrieval: **~88 docHit@10 on two independent
benchmarks**, robust to paraphrase and — crucially — to **lay language**, where
classical lexical search fails. The validated stack (voyage + rerank +
importance) is near the ceiling for API-only methods; the next real gain needs a
different class of intervention (fine-tuning an open embedder), not more
pipeline tweaks.

## 1. Two independent benchmarks converge
| benchmark | N | gold | docHit@10 | paraHit@10 | note |
|---|--:|---|--:|--:|---|
| **Court-Guides** (independent) | 409 | 41 official Case-Law Guides, doc+§ | ~88 | ~73 | primary |
| **Summary** (self-sourced) | 1,570 | the summarised case, doc-level | 89.4 (expert) | — | secondary |

An independent Gemini relevance-judge rated **~85–90 %** of the returned top-10
paragraphs genuinely relevant (the strict gold understates usefulness, since the
Guides cite only *some* supporting paragraphs). Two unrelated gold sources
landing in the same 86–90 band → the figure is **robust, not an artefact** of
one gold set.

## 2. The retrieval is semantic, not lexical (bullet-proof)
Summary benchmark, full 1.31 M-paragraph corpus, N=1,570, three query tiers of
decreasing surface overlap (raw verbatim → de-anchored expert → de-anchored lay):

| tier | dense@10 | BM25@10 | dense−BM25 | trigram-overlap |
|---|--:|--:|--:|--:|
| raw (circular) | 95.8 | 89.9 | +5.9  | 0.353 |
| expert | 89.4 | 78.2 | +11.2 | 0.240 |
| lay | 86.8 | 60.4 | **+26.4** | 0.124 |

- **BM25 collapses 29.5 pts** (89.9→60.4) as surface overlap is removed; **dense
  drops only 9.0** (95.8→86.8).
- Dense's margin **widens** raw→lay (+5.9 → +26.4) — the opposite of what
  leakage would produce. The more copied anchors are stripped, the *bigger*
  dense wins. On plain-language descriptions dense still recovers the case in the
  top-10 **87 %** of the time.
- Trigram containment (0.353→0.124) tracks the BM25 collapse, confirming the
  effect is real and not a metric artefact.

**Reading:** the system matches *meaning*, not vocabulary — it answers the
layperson's question even when none of the Court's words appear.

## 3. Levers that work (the validated stack)
| lever | effect | notes |
|---|---|---|
| **voyage-4-large** (embedding) | largest single win | beat mpnet / BM25 / old hybrid, esp. lay queries |
| **rerank-2.5** (top 100) | precision at the top | pool=100 optimal (150 exceeds token cap); rerank-3 better in the October 2026 tests (§6) |
| **+ importance** (HUDOC authority) | **best single add, +5–10 pts** | beat citation-graph PageRank |
| SQ8 quantization | ≈ exact (recall@50 98 %) | ¼ size → deployable on a small VM |

## 4. What does NOT work (negative results — these save effort)
| tried | result | verdict |
|---|---|---|
| **paragraph-context window ±1 / ±2** | paraHit@1 **−16.5 / −25.0**; paraHit@10 −5.6 / −10.9 | **rejected** — dilutes the pinpoint; keep 1 paragraph = 1 vector |
| selective window (only short paras) | still paraHit@1 −6.7 (±1) | rejected — no threshold is pinpoint-neutral *and* useful |
| metadata prefix (title·article·section) | docHit@1 **+2.9**, paraHit ~0 | not worth a full re-embed; only real "context" idea that doesn't hurt |
| citation-graph PageRank | lost to importance | dropped |
| Article filter · HyDE · Gemini query-rewrite | hurt or neutral | dropped |

**Implication:** the current architecture sits near a local optimum for
no-fine-tune retrieval. Further quality requires **contrastive fine-tuning of an
open embedder** on the guides gold (query→cited-paragraph positives, hard
negatives) — a separate project, not a tweak. RAFT-style methods target the
*generator*, which this system deliberately does not have, so they do not apply
to retrieval.

## 5. Results-list quality (from the lawyer-perspective audit)
Segmentation is **citation-grade** for numbered paragraphs (pinpoint = the §
number in the text; sections correct). Corpus-wide defects found & addressed:

| issue | corpus | over-surfaced to | action |
|---|--:|--:|---|
| `¶0` no-number sub-fragments (uncitable) | 5.6 % | ~10 % of hits | **suppressed at serve time** |
| separate/dissenting-opinion paragraphs | 3.8 % | ~17 % of hits | **rank-penalised (0.12) + amber badge** |
| leading § number stripped from text | 0.1 % | rare | left (pinpoint still correct); cosmetic |

On a 15-query lawyer panel (446 passages): after the fixes, uncitable ¶0 = 0 %,
boilerplate 0 %, mid-sentence starts 0 %, near-duplicate 0 %, and
dissent-out-ranks-holding 0/120.

## 6. October 2026 tests: index update, rerank-3, smaller index, voyage-context-4
Run locally on 10 October 2026; **nothing deployed** (the VM still serves the July index with
rerank-2.5). Pipeline as in production: dense top 300 → drop ¶0 → rerank top 100 → +0.05 ×
importance − section penalties. Guides n=409 (284 with pinpoints); Summary = expert tier, n=1,570,
doc-level. Exact McNemar on paired items; each reranker run twice (Guides identical across runs,
Summary differs by 1–3 items).

**Same-model update.** The July index (1,318,250 rows, 20,010 cases) brought up to the live DB:
160 new cases, 40,536 rows with changed text (October hyphen and number repairs), 16 deleted
duplicate cases removed, 6,298 section labels and 308 § numbers refreshed → 1,328,635 rows,
20,150 cases. Only the 52,122 new/changed rows re-embedded (~8M tokens); re-embedding 20 unchanged
rows gave cosine 1.0000 with the stored vectors. Self-retrieval 200/200 at rank 1. Artifacts:
`rag/pipeline/data_2026-10/` (git-ignored), deploy plan in the session notes.

| configuration | G d@1 | G d@10 | G p@1 | G p@10 | S d@1 | S d@10 | index |
|---|--:|--:|--:|--:|--:|--:|--:|
| July index + rerank-2.5 | 61.6 | 87.8 | 37.7 | 72.9 | — | — | 1.39 GB |
| October index + rerank-2.5 | 62.6 | 88.5 | 37.3 | 72.9 | 58.5 | 89.6 | 1.39 GB |
| **October index + rerank-3** | **63.6** | **89.0** | **39.4** | **75.0** | **64.8** | **92.0** | 1.39 GB |
| + 1024-d SQ4 | — | 88.0 | — | 74.6 | 64.8 | 92.0 | 0.71 GB |
| + 512-d SQ8 | — | 87.8 | — | 74.3 | 64.8 | 91.7 | 0.70 GB |
| + 512-d SQ4 | — | 87.8 | — | 74.6 | 64.9 | 91.9 | 0.36 GB |
| voyage-context-4 + rerank-3 | 54.5 | 71.1 | 31.0 | 51.8 | 64.6 | 79.4 | 1.39 GB |

- **Index update:** parity with July (all differences n.s.); it adds the new judgments and repairs.
- **rerank-3 vs rerank-2.5** (identical candidate pools): better on every metric; on Summary
  significant (d@1 −45/+145 items, d@10 −15/+52, p<0.001), on Guides not (p@10 −2/+8, p=0.11).
  Same price ($0.05/M tokens, ~30K tokens per query) and latency (median 0.6–0.7 s per call).
  rerank-2.5 is now listed as legacy by Voyage. **Adopt** (one constant, `RERANK_MODEL`).
- **Smaller index:** voyage-4 vectors truncate exactly to 512-d (cosine 1.0000 against the API's
  512-d output). 512-d and/or 4-bit cost ~1 point Guides d@10, n.s. (p ≥ 0.18). The FAISS step is
  a small part of query time (single thread, nprobe 128, top 300, 49 queries on the Mac):

  | index | size | median | p90 |
  |---|--:|--:|--:|
  | 1024 SQ8 (current) | 1.39 GB | 19 ms | 44 ms |
  | 1024 SQ4 | 0.71 GB | 35 ms | 44 ms |
  | 512 SQ8 | 0.70 GB | 11 ms | 25 ms |
  | 512 SQ4 | 0.36 GB | 18 ms | 26 ms |

  against ~0.2–0.3 s for the query embedding and ~0.6–0.7 s for the rerank call, so the user does
  not notice. The gain is memory: a smaller memory-mapped index stays in the VM's page cache, so a
  query after a quiet spell or under memory pressure does not wait on disk. **Keep 1024 SQ8**; use
  512-d SQ4 if the VM runs short of memory.
- **voyage-context-4** (each judgment's paragraphs embedded together; 825 long judgments split into
  windows of whole paragraphs; 136.9M tokens): **rejected**. Paragraphs of one judgment become
  near-duplicates (mean within-case cosine 0.80 vs 0.51 with voyage-4-large), so the top-100 pool
  covers ~10 cases instead of ~50 and holds the right case 73 % of the time on Guides (94 % now).
  Capping paragraphs per case in the pool does not fix it. Same lesson as the ±1 window in §4:
  for pinpoint retrieval, one paragraph = one context-free vector.

Experiment files: `rag/pipeline/data_2026-10_exp/` (scripts, logs, pools, per-item results; git-ignored).

## 7. Limitations (honest)
- **Summary is a *secondary* instrument** — self-sourced; even de-anchored, some
  residual paraphrase overlap remains. Court-Guides is the independent primary.
- **Leading-case skew** — both Guides and summaries cover prominent cases; little
  evidence on obscure judgments.
- **Paragraph-level validated only on Guides**; the Summary set is doc-level.
- **Not deterministic** — embedding jitter (cosine ~0.999) yields 2–3 distinct
  rankings across runs; cacheable if bit-exactness is needed.

## Artifacts
- Court-Guides: `benchmark/echr-guides/` (build + eval scripts; gold gitignored).
- Summary: `benchmark/echr-guides/phaseB/summary_benchmark/` — `METHODOLOGY.md`,
  `rewrite_prompt*.txt`, `items_summary_{raw,rewritten,lay}.jsonl`,
  `review_pairs*.txt`, `results/*.json` (local-only tree).
- Pipeline ablations: `rag/benchmark/*_experiment.py`, `fusion_sweep.py`,
  `rerank_*`, `importance_experiment.py`, `authority2_experiment.py`.
