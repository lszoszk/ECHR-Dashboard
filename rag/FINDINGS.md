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
| **rerank-2.5** (top 100) | precision at the top | pool=100 optimal (150 exceeds token cap) |
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

## 6. Limitations (honest)
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
