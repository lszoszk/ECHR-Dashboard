# Section-Label Recall Audit

**Date:** 2026-04-28  
**Auditor:** Claude Sonnet 4.6 (Anthropic)  
**Scope:** 300 paragraphs sampled from all 16 section labels across the full corpus  
**Corpus:** ECHR-Dashboard-tier1 case corpus  
**Companion document:** `precision-audit.md` (section-relabeling precision, 490 samples)

---

## 1. Setup

### Sample design

A stratified-random sample of 300 paragraphs was drawn from the corpus, allocating samples to each of the 16 section label variants in proportion to their prevalence, subject to a floor of 10 and a ceiling of 30 per label. The final allocation was:

| Section label | Samples |
|---|---|
| Merits | 30 |
| Facts Proceedings | 25 |
| Introduction | 25 |
| Just Satisfaction | 25 |
| Legal Framework | 25 |
| Admissibility | 20 |
| Facts | 20 |
| Operative Part | 20 |
| Separate Opinion | 20 |
| Facts Background | 15 |
| Commission Proceedings | 15 |
| Operative part | 15 |
| Relevant legal framework | 15 |
| Article 46 | 10 |
| Appendix | 10 |
| Final Submissions | 10 |

Each sample record included: full paragraph text (up to 1500 characters), three context paragraphs before and after with their current section labels, the internal para\_idx, the HUDOC paragraph number (where available), and the numbering\_block identifier.

Random seed: controlled by the sampling query; samples drawn without replacement within each stratum. Total: 300 paragraphs across the full corpus date range.

### Classification procedure

Each paragraph was judged against the 13 canonical user-facing section types documented in the project specification. Three verdicts were possible:

- **correct** — the current label is the appropriate one for this paragraph.
- **wrong** — the paragraph clearly belongs in a different section; the `should_be` field records the correct label.
- **ambiguous** — reasonable disagreement is possible; the paragraph is plausibly consistent with more than one section.

Surrounding context was used to resolve borderline cases: a paragraph is more likely correctly labelled when all six neighbours carry the same section type. Confidence in each verdict (high / medium / low) was recorded separately.

---

## 2. Headline Numbers

| Metric | Value |
|---|---|
| Total samples | 300 |
| Correct | 265 |
| Wrong | 21 |
| Ambiguous | 14 |
| **Overall correctness rate** | **88.3 %** |
| Wrong rate | 7.0 % |
| Ambiguity rate | 4.7 % |

**Wilson 95% confidence interval for the true correctness rate: [84.2%, 91.5%].**

Treating ambiguous cases as correct raises the estimate to 93.0 %; treating them as wrong lowers it to 81.3 %. The 88.3 % figure uses the conservative denominator of all 300 samples.

---

## 3. Per-Section Breakdown

| Section | n | Correct | Wrong | Ambiguous | Correctness % | Top misclassification targets |
|---|---|---|---|---|---|---|
| Admissibility | 20 | 20 | 0 | 0 | 100.0% | — |
| Appendix | 10 | 10 | 0 | 0 | 100.0% | — |
| Article 46 | 10 | 6 | 1 | 3 | 60.0% | Just Satisfaction (1) |
| Commission Proceedings | 15 | 15 | 0 | 0 | 100.0% | — |
| Facts | 20 | 12 | 6 | 2 | 60.0% | Merits (2), Just Satisfaction (2), Legal Framework (1), Introduction (1) |
| Facts Background | 15 | 14 | 1 | 0 | 93.3% | Introduction (1) |
| Facts Proceedings | 25 | 23 | 1 | 1 | 92.0% | Just Satisfaction (1) |
| Final Submissions | 10 | 10 | 0 | 0 | 100.0% | — |
| Introduction | 25 | 22 | 0 | 3 | 88.0% | — |
| Just Satisfaction | 25 | 20 | 3 | 2 | 80.0% | Operative Part (3) |
| Legal Framework | 25 | 24 | 0 | 1 | 96.0% | — |
| Merits | 30 | 25 | 3 | 2 | 83.3% | Legal Framework (2), Just Satisfaction (1) |
| Operative Part | 20 | 20 | 0 | 0 | 100.0% | — |
| Operative part | 15 | 15 | 0 | 0 | 100.0% | — |
| Relevant legal framework | 15 | 9 | 6 | 0 | 60.0% | Merits (4), Just Satisfaction (1), Operative Part (1) |
| Separate Opinion | 20 | 20 | 0 | 0 | 100.0% | — |

Nine section labels achieved 100% correctness in this sample. The three worst-performing labels are **Facts** (60.0%), **Relevant legal framework** (60.0%), and **Article 46** (60.0%).

---

## 4. Top Error Patterns

The 21 wrong verdicts cluster into five dominant patterns, listed in descending frequency.

### Pattern A: Relevant legal framework → Merits (4 cases)

The most frequent error. Paragraphs containing the Court's substantive legal assessment — including violation findings, proportionality analyses, and general-principles recitals applied to the facts — are labelled `Relevant legal framework` instead of `Merits`. This arises in two sub-types:

1. **Compact repetitive cases** (Committee format, Serbia enforcement series): the judgment structure compresses the legal reasoning into a section that carries the `Relevant legal framework` heading rather than creating a separate `Merits` section. Examples: rowid 1540851 ("It follows that there has been a violation of Article 1 of Protocol No. 1…"), rowid 1456499 (CAO confiscation proportionality analysis), rowid 1695553 (Court's assessment of proceedings complexity and violation conclusion).

2. **Government submissions in ALLEGED VIOLATION structure**: rowid 1877956 — Government's factual submission on detention conditions appears under the heading "II. ALLEGED VIOLATION OF ARTICLE 3" but the section label assigned is `Relevant legal framework` rather than `Merits`.

### Pattern B: Just Satisfaction → Operative Part (3 cases)

Three paragraphs in the `Just Satisfaction` section are dispositif clauses:

- rowid 72047: the text "FOR THESE REASONS, THE COURT" is the opening line of the operative dispositif.
- rowid 1703182: the closing formula "Rule 77 §§ 2 and 3 of the Rules of Court. [Registrar] [President]" is the operative part's signature block.
- rowid 1961353: the text "5. Dismisses the remainder of the applicant's claim for just satisfaction" is a numbered operative clause surrounded by other `Operative part` numbered clauses.

This pattern is the recall-side counterpart of the P1 precision-audit error: the P1 pass grabs paragraphs that contain "just satisfaction" from non-Just-Satisfaction sections and relabels them Just Satisfaction, while this error shows cases where operative dispositif paragraphs that happen to mention just satisfaction remain in `Just Satisfaction` rather than being promoted to `Operative Part`.

### Pattern C: Merits → Legal Framework (2 cases) and Facts → Legal Framework (1 case)

Domestic law quotations (a Croatian Criminal Code article; a domestic Compensation Act provision) are embedded in the `Merits` or `Facts` section rather than in `Legal Framework`. Examples: rowid 1737720 (Croatian Criminal Code Article 66 § 1 in a Merits block), rowid 1633874 (Compensation Act 1994 text fragment in Merits), rowid 1978849 (Compensation Act section 2 text in Facts).

These are the mirror of the P3 pass target: P3 moves domestic-law blocks from Facts Proceedings into Legal Framework, but cannot cover content that is already in Merits or Facts.

### Pattern D: Facts → Merits (2 cases)

Paragraphs containing the Court's procedural-violation assessment (rowid 1720256 — Article 2 investigation principles applied to findings) and legal-principles recitals under a "THE COURT'S ASSESSMENT" heading (rowid 1456304 — Bouyid general principles) are labelled `Facts` instead of `Merits`. These arise in simplified Committee-format judgments where the Facts section absorbs early Court reasoning before the structural Merits heading appears.

### Pattern E: Facts → Just Satisfaction (2 cases) and Facts Proceedings → Just Satisfaction (1 case)

In mass and repetitive cases with compressed structure, paragraphs containing the just satisfaction award (rowid 1395849 — equitable award and admissibility declaration; rowid 1395337 — costs assessment and operative payment clause) and a Commission-era costs recommendation (rowid 59901) are labelled `Facts` or `Facts Proceedings`. These arise where the judgment's pagination does not clearly separate the Article 41 reasoning from the factual narrative section.

---

## 5. Comparison with Precision Audit (Section 6 of precision-audit.md)

The precision audit (April 2026, 490 samples across seven relabeling passes P1–P7) measured the fraction of *relabeled* paragraphs that were assigned the correct label. The recall audit (this document) measures the fraction of paragraphs *currently in each section* that genuinely belong there.

| Dimension | Precision audit | Recall audit |
|---|---|---|
| Question | Of paragraphs we relabeled, how many were relabeled correctly? | Of paragraphs in their current section, how many genuinely belong there? |
| Samples | 490 relabelings | 300 current-state paragraphs |
| Overall correctness | 97.6% | 88.3% |
| Wilson 95% CI | [95.9%, 98.7%] | [84.2%, 91.5%] |
| Primary error pattern | Over-propagation into adjacent sections | Boundary confusion between adjacent section types |

The 9.3 percentage-point gap between precision (97.6%) and recall (88.3%) is expected and explicable. The relabeling passes each targeted specific structural patterns with high precision; however, they necessarily operated on a subset of the corpus and could not cover all boundary cases. The recall audit surfaces the *residual* labeling errors in the paragraphs that the passes did not touch — principally:

- Domestic-law quotations embedded in Merits/Facts that were never exposed to P3 (which only targets the Facts Proceedings section).
- Operative dispositif fragments that were captured by P1's just-satisfaction trigger but belong to Operative Part.
- Court assessment paragraphs in compact Committee-format judgments where the section heading structure does not create a distinct Merits block.

The precision audit also documented a severe failure in P8 (R3 sub-rule, 27.9% precision for Article 41 content recovery from Merits), which was not deployed. The recall audit confirms that a meaningful number of Just Satisfaction and Operative Part paragraphs remain stranded in other sections — precisely the population P8 targeted — but the recall audit's 7.0% error rate is far more tractable than the ~20% error rate that P8's R3 would have introduced.

---

## 6. Error Severity Assessment

Each of the 21 wrong verdicts is classified on a three-point severity scale.

**Minor** — current section is plausible-adjacent; the misclassification does not substantially distort any downstream analytical query.

**Moderate** — different content type but same structural region; a user querying one section would occasionally retrieve content from another.

**Severe** — cross-population or cross-region error; the paragraph's content type is definitively inconsistent with its current label.

| rowid | Current section | Should be | Severity | Notes |
|---|---|---|---|---|
| 1737720 | Merits | Legal Framework | Minor | Domestic law text adjacent to Merits analysis; minor content-type confusion. |
| 1633874 | Merits | Legal Framework | Minor | Domestic Compensation Act text fragment. |
| 910203 | Merits | Just Satisfaction | Moderate | Article 41 costs award embedded in Merits block. |
| 1720256 | Facts | Merits | Moderate | Court's Article 2 assessment in Facts section. |
| 1456304 | Facts | Merits | Moderate | Bouyid general principles under Court assessment heading in Facts. |
| 1978849 | Facts | Legal Framework | Minor | Domestic law provision text in Facts. |
| 1395337 | Facts | Just Satisfaction | Moderate | Costs assessment and operative payment clause in Facts. |
| 1395849 | Facts | Just Satisfaction | Moderate | Just satisfaction award and operative declarations in Facts. |
| 1659827 | Facts | Introduction | Minor | Government representation sentence in Facts. |
| 59901 | Facts Proceedings | Just Satisfaction | Moderate | Commission Delegate's compensation recommendation in Facts Proceedings. |
| 72047 | Just Satisfaction | Operative Part | Moderate | Opening dispositif line "FOR THESE REASONS, THE COURT" in Just Satisfaction. |
| 1703182 | Just Satisfaction | Operative Part | Moderate | Operative closing formula / registrar-president signature in Just Satisfaction. |
| 1961353 | Just Satisfaction | Operative Part | Moderate | Numbered operative clause 5 in Just Satisfaction. |
| 1208093 | Facts Background | Introduction | Minor | Government representation sentence in Facts Background. |
| 1540851 | Relevant legal framework | Merits | Moderate | Violation finding embedded in Relevant legal framework. |
| 1456499 | Relevant legal framework | Merits | Severe | Proportionality analysis and violation conclusion labelled Relevant legal framework. |
| 1877956 | Relevant legal framework | Merits | Moderate | Government submission under ALLEGED VIOLATION heading labelled Relevant legal framework. |
| 1695553 | Relevant legal framework | Merits | Moderate | Court's length-of-proceedings assessment in Relevant legal framework. |
| 1971871 | Relevant legal framework | Just Satisfaction | Severe | Equitable just satisfaction award labelled Relevant legal framework. |
| 1965493 | Relevant legal framework | Operative Part | Severe | Numbered operative clause labelled Relevant legal framework. |
| 540085 | Article 46 | Just Satisfaction | Minor | "APPLICATION OF ARTICLE 41" heading in Article 46 section. |

**Severity summary:** 6 minor, 12 moderate, 3 severe.

All three severe errors originate in the `Relevant legal framework` section (60% correctness rate), specifically in compact Serbian enforcement and Committee-format judgments where the labeling logic conflated the just satisfaction and Merits content with the legal-framework block.

---

## 7. Confidence Breakdown

| Confidence | n | % of all verdicts |
|---|---|---|
| High | 253 | 84.3% |
| Medium | 40 | 13.3% |
| Low | 7 | 2.3% |

All 21 wrong verdicts were given medium or high confidence. The 7 low-confidence verdicts (for ambiguous cases) arise from structural ambiguity in mass case table rows, where the same row format appears in both Introduction and Appendix sections depending on the case, and in simplified repetitive-case formats where Facts and Merits are deliberately compressed.

---

## 8. Recommendations

Based on error patterns and severity assessments, the following targeted remediation passes are recommended for a future P13+ pipeline iteration.

### Rec-1 (High priority): Relevant legal framework → Merits recovery

**Target:** Paragraphs in `Relevant legal framework` that contain Court assessment language (violation findings, proportionality conclusions, "It follows that…" formulas, or text immediately following an "ALLEGED VIOLATION" heading).

**Estimated population:** The 60% correctness rate in this sample, projected to the full corpus `Relevant legal framework` population, suggests a non-trivial number of misplaced Merits paragraphs.

**Proposed rule:** If a paragraph labelled `Relevant legal framework` contains "It follows that there has been a violation", "has been a violation of Article", "proportionality… was not met", or is immediately preceded by an "ALLEGED VIOLATION" heading, reclassify as `Merits`. Apply only to paragraphs in the `main_judgment` numbering block.

**Precision risk:** Low — these phrases are definitive Merits markers. The main risk is over-capture in the sub-cases where a legal framework section quotes from prior ECHR judgments that themselves state violation findings.

### Rec-2 (Medium priority): Just Satisfaction → Operative Part recovery

**Target:** Paragraphs in `Just Satisfaction` that are numbered operative clauses or carry the opening "FOR THESE REASONS, THE COURT" formula.

**Estimated population:** Three errors in 25 Just Satisfaction samples (12%) indicates this pattern is common enough to warrant a dedicated rule.

**Proposed rule:** Extend the existing P1/P8 logic with a reverse guard: if a paragraph in `Just Satisfaction` matches the pattern of a numbered operative clause (starts with an integer followed by a period and "Holds", "Declares", "Decides", "Dismisses", or "Done in [language]"), or contains the exact string "FOR THESE REASONS, THE COURT", and the `numbering_block` is `operative_dispositif`, reclassify as `Operative Part` (or `Operative part` depending on case vintage).

**Precision risk:** Low for the "FOR THESE REASONS" trigger; medium for the numbered-clause trigger (the "Dismisses the remainder of the applicant's claim for just satisfaction" clause is genuinely borderline, but operationally belongs with the other Holds/Declares clauses).

### Rec-3 (Medium priority): Facts / Facts Proceedings → Just Satisfaction recovery in mass cases

**Target:** Paragraphs in `Facts` or `Facts Proceedings` that contain just satisfaction award language ("awards the applicant", "equitable basis", "in respect of non-pecuniary damage") or operative payment clauses ("(a) that the respondent State is to pay").

**Estimated population:** Three errors in 45 Facts/Facts Proceedings samples (6.7%). In mass cases, just satisfaction reasoning is sometimes compressed into the Facts block.

**Proposed rule:** Existing P1/P6 rules should be augmented to check `Facts` and `Facts Proceedings` sections, not only `Merits` and `Admissibility`.

**Precision risk:** Medium — Facts paragraphs can legitimately reference damage claims in their factual narrative (e.g., "the applicant claimed compensation before the domestic courts"). A trigger on "awards" + "euros" is more precise.

### Rec-4 (Low priority): Representation sentences in Facts Background / Facts

**Target:** Paragraphs of the form "The Government were represented by their Agent, Mr X" that appear in `Facts Background` or `Facts` rather than `Introduction`.

**Estimated population:** Two errors in 35 Facts Background/Facts samples (5.7%). These are single-paragraph anomalies.

**Note:** This may not warrant a dedicated rule since it involves a very small number of isolated paragraphs. Manual correction for affected cases may be more efficient.

---

## Appendix: Verdict file

Per-paragraph verdicts are stored in `scripts/recall_audit_verdicts.json`. Each record contains: `rowid`, `case_id`, `current_section`, `verdict` (`correct` / `wrong` / `ambiguous`), `should_be` (null if not wrong), `reason`, and `confidence` (`high` / `medium` / `low`).
