# Section-Label Recall Audit (v2 — post-P19)

**Date:** 2026-04-30
**Auditor:** Claude Sonnet 4.6 (Anthropic), two parallel sub-agent runs
**Scope:** 300 paragraphs sampled from all 16 section labels across the post-P19 corpus
**Corpus:** ECHR-Dashboard-tier1, 1,992,952 paragraphs (after P19 text-merge of 8,495 PDF-extraction artefacts)
**Baseline:** `recall-audit.md` (2026-04-28, 88.3 % overall correctness, 300 samples)
**Companion:** `precision-audit.md` (per-pass precision, all 18 passes deployed at ≥97 %)

---

## 1. Setup

Same stratified-random allocation as the baseline audit, with new random seed (`20260430`) for a fresh draw. Each record includes the paragraph text (capped at 1500 chars), three context paragraphs before and after with their section labels, internal `para_idx`, `hudoc_para_no`, and `numbering_block`.

Allocation (16 sections, 300 total):

| Section | n |
|---|---:|
| Merits | 30 |
| Facts Proceedings, Introduction, Just Satisfaction, Legal Framework | 25 each |
| Admissibility, Facts, Operative Part, Separate Opinion | 20 each |
| Facts Background, Operative part, Relevant legal framework, Commission Proceedings | 15 each |
| Final Submissions, Appendix, Article 46 | 10 each |

Two independent Sonnet sub-agent runs each judged 150 samples (random shuffle then split). Verdicts merged into `scripts/recall_audit_v2_verdicts.json`.

---

## 2. Headline Numbers

| Metric | v2 (post-P19) | v1 baseline (2026-04-28) | Δ |
|---|---|---|---|
| Total samples | 300 | 300 | — |
| Correct | 229 | 265 | −36 |
| Wrong | 50 | 21 | +29 |
| Ambiguous | 21 | 14 | +7 |
| **Strict correctness** | **76.3 %** | **88.3 %** | **−12.0 pp** |
| Strict 95 % Wilson CI | [71.2 %, 80.8 %] | [84.2 %, 91.5 %] | non-overlapping |
| Lenient (correct + ambig) | 83.3 % | 93.0 % | −9.7 pp |

The strict 95 % CIs do **not overlap**: the v2 audit measures genuinely lower observed correctness than the baseline. Two factors contribute, in unknown proportion:

1. **Auditor variability** — the v1 baseline used a single Sonnet run; v2 used two parallel runs that were stricter on Pop C compressed-case content (counted as "wrong" rather than "ambiguous"). Honest comparison requires acknowledging this isn't a clean A/B.
2. **Real regressions** — the v2 audit revealed patterns the baseline draw missed. These are concentrated in three sections (see §3 below).

The **new cleaning passes (P14 v2, P15, P16, P17, P19) are NOT the source of the regression** — each was independently audited at 100 % precision in `precision-audit.md` §§9–13. The drop is from **pre-existing residual errors that the new passes did not reach**.

---

## 3. Per-Section Breakdown

| Section | n | Correct | Wrong | Ambig | Correctness % | v1 baseline % | Δ |
|---|---:|---:|---:|---:|---:|---:|---:|
| **Legal Framework** | 25 | 25 | 0 | 0 | 100.0 % | 92.0 % | +8.0 |
| **Operative Part** | 20 | 20 | 0 | 0 | 100.0 % | 95.0 % | +5.0 |
| **Operative part** | 15 | 15 | 0 | 0 | 100.0 % | 86.7 % | +13.3 |
| **Separate Opinion** | 20 | 20 | 0 | 0 | 100.0 % | 100.0 % | — |
| **Facts Background** | 15 | 15 | 0 | 0 | 100.0 % | 93.3 % | +6.7 |
| **Appendix** | 10 | 10 | 0 | 0 | 100.0 % | 100.0 % | — |
| **Facts Proceedings** | 25 | 23 | 1 | 1 | 92.0 % | 92.0 % | — |
| **Final Submissions** | 10 | 9 | 1 | 0 | 90.0 % | 100.0 % | −10.0 |
| **Merits** | 30 | 25 | 3 | 2 | 83.3 % | 83.3 % | — |
| **Just Satisfaction** | 25 | 20 | 3 | 2 | 80.0 % | 92.0 % | −12.0 |
| **Commission Proceedings** | 15 | 12 | 3 | 0 | 80.0 % | 100.0 % | −20.0 |
| **Article 46** | 10 | 5 | 2 | 3 | 50.0 % | 60.0 % | −10.0 |
| **Introduction** | 25 | 12 | 11 | 2 | 48.0 % | 96.0 % | **−48.0** |
| **Admissibility** | 20 | 8 | 4 | 8 | 40.0 % | 100.0 % | **−60.0** |
| **Facts** | 20 | 7 | 10 | 3 | 35.0 % | 60.0 % | −25.0 |
| **Relevant legal framework** | 15 | 3 | 12 | 0 | **20.0 %** | 80.0 % | **−60.0** |

### Sections that improved or held: P14-P19 are working

`Operative Part`, `Operative part`, and `Legal Framework` all rose to 100 % — direct benefit of P15 (operative residual cleanup) and P3/P11 (Legal Framework extraction). `Separate Opinion`, `Facts Background`, `Facts Proceedings` are stable. `Appendix` remains at 100 % (P9 baseline still holds).

### Sections that regressed: where the new gaps live

Six sections show double-digit regressions. Three failure modes account for almost all of them:

#### Failure mode 1: Pop C mass-applicant table rows leak into `Introduction` / `Relevant legal framework` / `Facts` / `Merits` (16 wrongs, 33 % of all wrongs)

Russian, Ukrainian, Bosnian, Greek, Romanian, Serbian, and Hungarian Committee mass-applicant cases include appendix-format tables of applicants (one row per applicant: case number, applicant name, dates, EUR amounts, prison name, etc.). The segmenter put many of these rows into `Introduction` (because they lead the case) or into `Relevant legal framework` (when they appear after the dispositif). They should be `Appendix`.

P9 caught the major appendix-table patterns (~27 k applicant table rows → Appendix) but the residue still affects ~16 of 300 sample paragraphs (≈5.3 % of corpus).

#### Failure mode 2: `Relevant legal framework` is collecting noise (12 wrongs in 15 samples)

Pop C compressed-format judgments dump everything after the merits into "Relevant legal framework" rather than splitting into Just Satisfaction + Operative + Appendix. Specific patterns observed:
- Article 41 payment instructions ("(a) that the respondent State is to pay…") in RLF (3)
- Mass-applicant table rows in RLF (4)
- Court's substantive Article 5 / Article 11 / Article 6 reasoning in RLF (3)
- Admissibility rulings ("Article 35 § 3(a) admissibility") in RLF (2)

P14 v2 cleaned the *opposite* direction (RLF → Operative/JS/Merits) at 100 % precision but only caught 800 paragraphs. The residue here suggests the RLF cleanup is incomplete and a follow-up pass with tighter "Pop C admissibility/JS in RLF" detectors would help.

#### Failure mode 3: Pop C Court reasoning in `Facts` / Court conclusion in non-Merits sections (8 wrongs)

In Pop C compressed cases, the Court's substantive analysis is sometimes still labelled `Facts` after P16 (which moved 11,804 paragraphs but only via the 6 strict patterns). Examples:
- Court's Article 8 / 11 / 1-P1 conclusions left in Facts (4)
- Court's exhaustion-objection analysis in Facts (1)
- Domestic legal provisions left in Facts (2)
- Numbered "B. Merits" subsection header still in Admissibility (1)

#### Pre-Protocol-11 Commission Proceedings sub-section breakouts (3 wrongs)

The Commission Proceedings section legitimately contains pre-1998 procedural history before the European Commission. Within these sections, sub-headings like "B. Compliance with Article 6 § 1" or "Article 50 costs" should break out into Merits or Just Satisfaction. P11 didn't reach inside the Commission Proceedings block. Three sample wrongs all in cases 001-58113/58114 (Vasilescu / Vasilescu II family).

---

## 4. Top Mis-Classifications (Sankey-style)

| From → To | Count | Pattern |
|---|---:|---|
| Introduction → Appendix | 8 | Pop C mass-applicant table rows mistaken for procedural intro |
| Facts → Merits | 4 | Court reasoning in Pop C compressed cases |
| Relevant legal framework → Appendix | 4 | Mass-applicant table rows in RLF |
| Admissibility → Merits | 4 | Section header `B. Merits` not breaking out |
| Relevant legal framework → Just Satisfaction | 3 | Article 41 payments and default-interest in RLF |
| Merits → Appendix | 2 | Pop C committee mass-applicant table data |
| Facts → Legal Framework | 2 | Domestic legal provisions in Pop C Facts |
| Article 46 → Just Satisfaction | 2 | Article 41 awards in cases that have both |
| Introduction → Merits | 2 | Court conclusions in Pop C compressed cases |
| Facts → Appendix | 2 | Single-applicant-name rows in mass cases |
| Relevant legal framework → Admissibility | 2 | Admissibility rulings in RLF |
| Just Satisfaction → Merits | 2 | Violation finding mis-routed to JS |
| Relevant legal framework → Merits | 2 | Court substantive reasoning in RLF |
| Commission Proceedings → Merits | 2 | Pre-P11 sub-section breakouts |

---

## 5. Comparison with Precision Audit (No Contradiction)

The precision audit (`precision-audit.md`) measures the precision of *each cleaning pass on its own scope*: when P14 v2 moved 800 paragraphs to JS/Operative/Merits, were those 800 moves correct? Answer: yes, 100 %. Same for P15, P16, P17, P19.

The recall audit measures the **end-to-end correctness of the current label across all paragraphs**, including ones the cleaning pipeline never targeted. A 76.3 % recall ≠ a precision regression — it means there are paragraphs in the corpus that no pass has touched, and some of them are wrong.

The pipeline is **conservative and precision-first by design**. P14 v2 alone left ~5,200 paragraphs in `Relevant legal framework` because they did not match the strict R0-R3 rules. Several of those residue paragraphs land in this audit's RLF sample at low correctness rates.

---

## 6. Recommendations

Three new patterns surfaced. None require revisiting existing passes.

### Rec-5 (High priority): Mass-applicant table rows → Appendix in Pop C

**Target:** Paragraphs in `Introduction`, `Relevant legal framework`, `Facts`, or `Merits` whose text is a single-row mass-applicant table entry. Distinguishing pattern: short paragraph (50–500 chars) with structured comma- or semicolon-separated fields like applicant name, application number, case dates, EUR amount, prison name. Often appears after the operative dispositif in compressed Pop C judgments.

**Estimated population:** Conservative probe needed. Recall audit found 16/300 (5.3 %); projected to corpus ~100 k.

**Risk:** Medium — must avoid catching legitimate biographical paragraphs in modern Chamber Introduction ("The applicant was born in 1984 and lives in Skopje."). Detection should require multi-cell tabular signals, not just length + applicant name.

### Rec-6 (Medium priority): Pop C `Relevant legal framework` further cleanup

**Target:** Paragraphs in `Relevant legal framework` (post-P14 v2 residue) that contain (a) Article 41 payment instructions ("(a) that the respondent State is to pay…"), (b) numbered "Article 35 § 3" admissibility rulings, or (c) Court's substantive Article 5/6/8/10/11 conclusions ("there has been a violation of Article…", but with section header context confirming Merits).

**Estimated population:** ~12/15 sampled = 80 % of RLF paragraphs in Pop C cases. RLF section currently has 14,760 paragraphs total; conservatively 5–8 k may need relabel.

**Risk:** Medium — overlap with Rec-5 (table rows) and with P14 v2 patterns. Need probe + careful design.

### Rec-7 (Low priority): Pre-Protocol-11 Commission Proceedings sub-section breakouts

**Target:** Within `Commission Proceedings` blocks, detect "B. Compliance with Article…" / "Article 50" sub-sections and re-route their content to Merits or Just Satisfaction.

**Estimated population:** Tiny — probably <500 paragraphs across the pre-1998 Pop A corpus. Manual case-by-case review may be more efficient than a regex pass.

---

## 7. Updated Validation Chain Statement

After P19 (post-2026-04-30), the methodology can defensibly state:

> Section assignment in the post-cleaning corpus has been validated through three independent mechanisms:
>
> 1. **Automated structural analysis** — 10 random cases per year 1975–2025, yielding the three-population taxonomy and identification of systematic relabel targets (P1–P19).
> 2. **Per-pass precision audit** — Sonnet 4.6 evaluation across 18 deployed passes (P1–P7, P9, P11, P13–P17, P19) on stratified random samples totalling ≈1,150 paragraphs. Aggregate precision: ≥97.6 %, with all passes since P14 v2 at 100.0 %.
> 3. **End-to-end recall audit (v2)** — Sonnet 4.6 evaluation on a stratified random sample of 300 paragraphs across all 16 section labels, measuring **76.3 % strict correctness** [95 % Wilson CI: 71.2 %–80.8 %], or **83.3 %** when ambiguous boundary cases are counted as correct.
>
> The 21-percentage-point gap between per-pass precision (97.6 %+) and end-to-end recall (76.3 %) reflects boundary cases the rule-based pipeline does not reach without precision-sacrificing patterns. Three recommended follow-up passes (Rec-5: Pop C appendix-table extraction; Rec-6: further `Relevant legal framework` cleanup; Rec-7: pre-Protocol-11 sub-section breakouts) would address the largest remaining error patterns.
>
> Two new section labels (`Commission Proceedings`, `Final Submissions`) were introduced to support sub-section granularity discovered during expert review. HUDOC paragraph numbers were extracted into `hudoc_para_no` for 67.3 % of paragraphs. A `numbering_block` column distinguishes main judgment numbering from operative dispositif and separate-opinion blocks. P19 merged 8,495 PDF-extraction artefact paragraph pairs (the Fetisov-style mid-Article-reference splits) at 100 % precision. Each pass has a backup table for single-statement SQL rollback.

---

## 8. Honest Caveat

This audit's lower correctness rate vs. the v1 baseline is partly real (new patterns surfaced) and partly auditor variance (parallel sub-agent runs were stricter than the single v1 run on Pop C committee cases, where mass-applicant table rows were sometimes counted as "wrong" rather than "ambiguous"). A neutral expert spot-check on the 50 v2 wrongs would clarify the split. Until that's done, the conservative reading is: **end-to-end correctness is in the range 76 %–88 %** depending on how strictly Pop C residue is judged, with three known patterns accounting for the bulk of remaining errors.

Saved artifacts: `scripts/recall_audit_v2_extract.py`, `scripts/recall_audit_v2_samples.json`, `scripts/recall_audit_v2_verdicts.json`.
