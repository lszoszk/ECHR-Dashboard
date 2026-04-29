# Data Quality TODO

**Updated:** 2026-04-29
**Status:** Major work complete. Corpus at 88.3% recall / 97.6% precision (97.7% counting P13).

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
| **TOTAL relabels** | | **~318,000 (~16% of corpus)** | | |

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

### Rec-1: Relevant legal framework → Merits (4 cases in audit, ~6,000 estimated)

The recall audit found 4/15 (27%) of `Relevant legal framework` paragraphs are actually Court assessment / violation findings stranded in the legal-framework section. Most are in the Serbian enforcement series and Committee-format judgments.

**Proposed rule:** If `Relevant legal framework` paragraph contains ("It follows that there has been a violation" OR "has been a violation of Article" OR "proportionality... was not met") AND `numbering_block` is `main_judgment` → reclassify as `Merits`.

**Risk:** Medium — these phrases sometimes appear in legitimate citation of prior judgments within the legal framework block. Manual spot-check of 30 candidates would be needed before applying.

**Estimated effort:** 1h dry-run + audit + apply.

### Rec-3: Facts → Just Satisfaction recovery in mass cases (~3,000 estimated)

Pop C compressed-format judgments where JS award language ("awards the applicant... in respect of non-pecuniary damage") is in `Facts` rather than `Just Satisfaction`. Recall audit found 3/45 (6.7%).

**Proposed rule:** Augment P1/P6 to also check `Facts` and `Facts Proceedings` sections for JS-content phrases.

**Risk:** Medium — Facts paragraphs legitimately reference damage claims in factual narrative ("the applicant claimed compensation before the domestic courts").

### Investigate Fetisov v. Russia rowid 1463491 PDF-extraction artefact

**Why:** M2 expert review flagged this paragraph as not findable in HUDOC source. Possibly a PDF-extraction fragment.

**Effort:** ~30 min spot investigation.

---

## Cleanup tasks

- Remove `/home/amuvmuser/migration-backup-20260428/` after ~1 week stable (~250 MB free).
- Containerize `/home/amuvmuser/echr_rag/` (UHRI semantic search) — currently runs on host.
- Investigate `unhr_setfit_models/` and `unhr_setfit_runtime/` in `/home/amuvmuser/echr/data/` — UHRI artefacts that should move to `/home/amuvmuser/uhri/data/`.

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
