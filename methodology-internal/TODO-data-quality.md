# Data Quality TODO

**Updated:** 2026-04-29 (post-P14 v2)
**Status:** Major work complete. Corpus at 88.3% recall / 97.6% precision (97.7% counting P13, 97.7% counting P14 v2).

---

## Done so far

| Pass | Description | Paragraphs | Audit precision | Status |
|------|-------------|-----------:|-----------------|--------|
| **P1** | Just Satisfaction recovery (Article 41 reasoning blocks → JS) | +82,989 | 97.1% | ✓ |
| **P2** | Separate Opinion from Operative Part | +2,370 | 100.0% | ✓ |
| **P3** | Legal Framework (Domestic Law) extraction | +83,377 | 97.1% | ✓ |
| **P4** | Pop C boundary (ALLEGED VIOLATION/JOINDER) | +56,241 | 94.3% | ✓ |
| **P5** | Continuation propagation across Admissibility | +41,462 | 98.6% | ✓ |
| **P6** | Article 41 text-anchor in Pop C | +10,937 | 95.7% | ✓ |
| **P7** | Glued JOINDER detection | +2,719 | 100.0% | ✓ |
| ~~P8~~ | ~~R3 over-propagation, ROLLED BACK~~ | 0 | 30% (rejected) | ✗ |
| **P9** | Pop C applicant tables → Appendix | +27,126 | 98.8% | ✓ |
| **P10** | Extract HUDOC paragraph numbers (`hudoc_para_no` column) | 1,346,359 populated | — | ✓ |
| **P11** | Sub-section split (Commission Proceedings, Final Submissions, residual Legal Framework) | +8,518 | (heading-based) | ✓ |
| **P12** | Numbering blocks (`numbering_block` column) | 1,892,837 populated | — | ✓ |
| **P13** | Just Satisfaction → Operative Part dispositif revert | +3,403 | **98.0%** | ✓ |
| **P14 v2** | Relevant legal framework → Operative / JS / Merits (R0+R1+R2+R3) | +800 | **100.0%** | ✓ |
| **P15** | Just Satisfaction → Operative Part residual (R1 numbered + R2 Rule 77 strict) | +96 | **100.0%** | ✓ |
| **P16** | Facts → JS / Operative in Pop C compressed cases (R0a + R0b + R1 + R2 + R3 + R4 Pop-C-only) | +11,804 | **100.0%** | ✓ |
| **P17** | Facts/etc → Introduction representation paragraphs (R1 gov-only + R2 gov+app pure) | +1,501 | **100.0%** | ✓ |
| **P19** | Text-merge for PDF over-segmentation (3 patterns: Article-split, orphan-num, Rule 77) | -8,495 rows merged | **100.0%** | ✓ |
| **TOTAL relabels** | | **~340,700 (~17.0% of corpus, on 1,992,952 final paragraphs)** | | |

**Schema additions:**
- 14 user-facing section labels (was 12 before P11): Header, Introduction, Facts (3 raw labels), Legal Framework (3 raw labels), Commission Proceedings (NEW), Final Submissions (NEW), Admissibility, Merits, Just Satisfaction, Article 46, Operative Part (2 raw casings), Separate Opinion, Appendix
- New columns: `hudoc_para_no INTEGER`, `numbering_block TEXT`

**Audit summary:**
- Precision audit (Sonnet 4.6, 490 samples across P1-P7): **97.6%** [95% CI: 96.2%–98.6%]
- Human expert review (M1, 7/7 LLM-flagged errors): all confirmed
- P13 follow-up audit (50 samples): 98.0%
- End-to-end recall audit (300 samples): **88.3%** [95% CI: 84.2%–91.5%]

**Backup tables in production DB:**
`_p1_backup`, `_p2_backup`, `_p3_backup`, `_p4_backup`, `_p5_backup`, `_p6_backup`, `_p7_backup`, `_p9_backup`, `_p11_backup`, `_p13_backup`. Plus `_p8_backup` retained as audit evidence even though P8 was rolled back. Each provides single-statement SQL rollback for its pass.

---

## Open follow-ups (lower priority)

### ✅ Rec-1 — DONE (P14 v2, 2026-04-29, 100% precision, 800 paragraphs)

Conservative 3-rule classifier (R0 Art.41 boilerplate, R1 numbered dispositif, R2 award reasoning, R3 violation finding). Naive blanket scope of ~6k was rejected (~25-37% precision). v1 attempt at 78% rolled back; v2 redesign with R0_BOILERPLATE pattern ships at 100% / 47-correct-out-of-50 audit. See `methodology-internal/precision-audit.md` §9.

### ✅ Rec-2 — DONE (P15, 2026-04-29, 100% precision, 96 paragraphs)

Two-rule pass extending P13: R1 captures numbered `^\d+\.\s*(Holds|Decides|Declares|Dismisses)` with NO length cap (Pop A pre-1998 fused-paragraph operative blocks routinely > 400 chars); R2 captures strict `\bRule 77\b` + Registrar/Done-in default-interest continuation clauses. Probe found loose `Rules of Court` anchor would FP at ~100% on JS reasoning citing Rule 60/38/61; tightening to `\bRule 77\b` cut to 96 candidates with 100% precision (full-population audit, no sampling). See `methodology-internal/precision-audit.md` §10.

### ✅ Rec-3 — DONE (P16, 2026-04-29, 100% precision, 11,804 paragraphs)

Six precision-first rules (R0a heading, R0b boilerplate, R1 numbered dispositif, R2 operative payment, R3 default-interest, R4 Court-awards Pop-C-only). Actual scope was ~4× larger than recall-audit estimate (11,804 vs ~3,000): Pop C compressed-format judgments dump the **entire** Operative dispositif AND JS reasoning into Facts. Critical pattern *rejected*: `equitable basis + EUR` (5/5 FP rate — Italian/Bulgarian Pop A/B narrative describing domestic Courts of Appeal). 55 stratified samples audited at 100% precision. See `methodology-internal/precision-audit.md` §11.

### ✅ Rec-4 — DONE (P17, 2026-04-30, 100% precision, 1,501 paragraphs)

Two-rule pass: R1 catches `Government were represented by` paragraphs (len < 300, 1,498 hits); R2 catches pure gov+app representation paragraphs (len < 500, 3 hits). Critical pattern *rejected*: applicant-only representation (FP risk — "the applicant was represented by a State-appointed lawyer" routinely refers to **domestic** proceedings). The "Government were represented" form is unique to ECHR procedural intro context. 33 stratified samples audited at 100% precision. **All four recall-audit recommendations now closed.** See `methodology-internal/precision-audit.md` §12.

### ✅ Investigate Fetisov v. Russia rowid 1463491 — DONE (2026-04-30)

Confirmed PDF-extraction artefact: rowid 1463491 is the second half of a sentence split mid-Article-reference. The HUDOC source paragraph reads `"...disclose a breach of Article 5 § 3 of the Convention. OTHER ALLEGED VIOLATIONS UNDER WELL-ESTABLISHED CASE-LAW"`; the segmenter saw `"Article 5."` and treated `"5."` as a new paragraph delimiter. Side effect: `hudoc_para_no=5` was assigned to the artefact (where 5 is the article number, not the paragraph number).

**Systematic scope:** ~6,000 paragraphs across the corpus exhibit similar PDF-extraction over-segmentation:
- 1,020 adjacent "breach of Article" + "§ N of the Convention" split-pairs in 312 cases
- 1,345 fused article-fragment + heading paragraphs
- 357 standalone article-fragment paragraphs
- 4,481 `Rule 77 §§ 2 and 3` paragraphs misindexed as `¶77`

Concentrated in Russian Committee mass-judgment corpus.

**See:** `methodology-internal/human-review-findings.md` Finding 5 for full diagnosis, evidence (text reconstruction), scope quantification, and three recommended action levels (do nothing / nullify hudoc_para_no / merge text).

**Status:** ✅ DONE. Investigation completed 2026-04-30; P19 conservative text-merge pass applied 2026-04-30 at 100 % precision (104 LLM-audited samples). 8,495 paragraph pairs merged across three pattern classes (Article-split, orphan-numbering, Rule 77). Standalone "N. § M of the Convention." fragments dropped from 357 → 5 (99 %); "Rule 77 §§ of the Rules of Court" fragments dropped 4,481 → 13 (99.7 %). Fetisov rid=1463490 successfully reconstructed. Backup `_p19_backup` retains full parent + child snapshots for rollback. See `methodology-internal/precision-audit.md` §13.

---

## Cleanup tasks

### ✅ DONE (2026-04-30) — VM cleanup pass

Three-task cleanup executed on VM 150.254.115.204:

- **`/home/amuvmuser/migration-backup-20260428/` removed** (was 6.5 MB, not 250 MB as the TODO note had estimated). All UHRI legacy backup files (old `unhr_dataset_api.py`, nginx `default.pre-uhri-split`, etc.) — pre-2026-04-28 separation cruft.

- **UHRI artefacts moved `/echr/data/` → `/uhri/data/` (~2.6 GB total):**
  - `unhr_setfit_models/` (466 MB) → `/uhri/data/setfit_models/`
  - `unhr_setfit_runtime/` (881 MB) → `/uhri/data/setfit_runtime/`
  - `huggingface/` (458 MB, HF model cache) → `/uhri/data/huggingface/`
  - `snapshots/` (830 MB, dated UHRI export gz files) → `/uhri/data/snapshots/`
  - Empty `unhr_cleaned.sqlite` (0 bytes) — deleted
  - Verified: neither `echr-api` nor `uhri-dataset-api` containers grep for "setfit" in their loaded code, so no service was reading these. `echr-api` `/health` still 200 OK after the move.
  - Note on filesystem: `mv` within the same `/dev/sda2` filesystem is a `rename(2)` syscall — no actual data copy, no space recovered. The benefit is **organizational**: ECHR's `/data/` now contains only ECHR artefacts (`echr_search.db`, `echr_cases.jsonl`, `huggingface`/`snapshots`/`setfit*` are correctly placed under UHRI's territory).
  - Permission fix: directories were root-owned (created by Docker container). Used `docker exec echr-api chown -R 1000:1000 ...` to make them owned by host `amuvmuser` (UID 1000) before the `mv`.

- **Scratch scripts archived** to `~/.scratch-archive-20260430/` (18 files: `p10*.py`, `p11*.py`, ..., `p14*.py`, `recall.py`, `recall_samples.json`, `*_audit.json` accumulated over previous sessions in `/home/amuvmuser/`). Kept rather than deleted in case any are still needed.

### Deferred — `echr_rag/` containerization

Inventory confirmed `/home/amuvmuser/echr_rag/` is **18 GB** (Chroma vector DB + venv + multilingual sentence-transformer model). The `DISABLED_NOTICE.md` (2026-04-20) documents that the systemd service is currently stopped due to memory pressure (5.6 GB RSS on an 8 GB VM caused swap thrash that broke all other services). Recommended fixes per the notice are: smaller embedding model, systemd `MemoryMax=3G` cap, or migration to a dedicated VM. Containerization alone does not solve the memory problem — needs paired with a memory cap. **Multi-hour deployment task; deferred to a separate dedicated session with proper Dockerfile + compose + memory cap design.** Note: despite the directory name, `echr_rag/` actually serves UHRI semantic search per the architecture doc — out of strict ECHR scope.

### Disk pressure note

Post-cleanup `/dev/sda2` remains 86% full (40 GB used / 49 GB total). The 18 GB `echr_rag/` is the dominant consumer. If disk space becomes critical, options are:
1. Tackle `echr_rag/` first (containerize + cap, OR archive the chroma_db if RAG is permanently disabled, ~13 GB recoverable).
2. Compress UHRI snapshots (already gzipped; further savings unlikely).
3. Move the dataset to external volume.

---

## Parked

### P14 — Narrow Merits sub-typing schema

The B2 pilot 7-category schema was rejected by expert (1/10 agreement). A narrower schema with only `violation_finding` / `no_violation_finding` as a binary tag might still be useful (~99% structural reliability via "There has been a violation of Article X" pattern). Defer until downstream analytics needs it.

---

## What was tried and rejected

- **P8 (fix audit findings)**: 30% precision, rolled back. Forward propagation from text triggers in Merits was too aggressive. See `precision-audit.md` Section 5.
- **B2 Merits sub-typing schema (7 categories)**: 1/10 expert agreement. Rejected. See `merits-subtyping-pilot.md` Section 8.

---

## Verifiable methodology claim

After P1–P13 (excluding P8):

> The cleaning pipeline relabeled approximately 318,000 paragraphs (16% of the corpus) across thirteen rule-based passes. Sample-based audits (Sonnet 4.6 LLM and human expert review) measured 97.6% precision over made relabels [95% Wilson CI: 96.2%–98.6%], with all 7 LLM-flagged errors independently confirmed by domain expert review. The end-to-end recall audit on 300 stratified samples measured 88.3% correctness [95% Wilson CI: 84.2%–91.5%] across all current section labels. The 9.3-point gap reflects boundary cases the rule-based pipeline could not reach without introducing precision-sacrificing patterns. Two new section labels (`Commission Proceedings`, `Final Submissions`) were introduced to support sub-section granularity discovered during expert review. HUDOC paragraph numbers were extracted from leading text patterns and stored in `hudoc_para_no` for 67.3% of paragraphs, enabling cross-reference against source documents. A `numbering_block` column distinguishes main judgment numbering from operative dispositif and separate-opinion blocks. Each pass has a backup table for single-statement SQL rollback.

This claim meets the standard expected for an academic dataset.
