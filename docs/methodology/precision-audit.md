# Section-Relabeling Precision Audit

**Date:** 2026-04-28  
**Auditor:** Claude Sonnet 4.6 (Anthropic)  
**Scope:** 490 sampled relabelings across 7 pipeline passes  
**Corpus:** ECHR-Dashboard-tier1 case corpus  

---

## 1. Headline Numbers

| Metric | Value |
|--------|-------|
| Total samples | 490 |
| Samples per pass | 70 |
| Correct relabelings | 478 |
| Incorrect relabelings | 7 |
| Ambiguous relabelings | 5 |
| **Overall precision (correct / total)** | **97.6 %** |
| Ambiguity rate | 1.0 % |

Precision is computed as `correct / (correct + incorrect + ambiguous)`. Treating ambiguous cases as correct would raise the figure to 98.6 %; treating them as incorrect would lower it to 96.5 %. The 97.6 % figure uses the conservative denominator of all 490 samples.

---

## 2. Per-Pass Precision Table

| Pass | Description | n | Correct | Incorrect | Ambiguous | Precision | Systematic error pattern |
|------|-------------|---|---------|-----------|-----------|-----------|--------------------------|
| P1 | `APPLICATION OF ARTICLE 41` headings and content blocks from Merits/Admissibility/Facts → Just Satisfaction | 70 | 68 | 2 | 0 | 97.1 % | Over-propagation into Operative Part dispositif: "Dismisses the remainder of the applicants' claim for just satisfaction" clauses that sit inside a numbered Holds/Declares sequence are grabbed by the rule because they contain the words "just satisfaction", but they belong to Operative Part. |
| P2 | Dissenting/concurring opinions in Operative Part → Separate Opinion | 70 | 70 | 0 | 0 | 100.0 % | None detected in this sample. |
| P3 | `RELEVANT DOMESTIC LAW` subsections from Facts Proceedings → Legal Framework | 70 | 68 | 1 | 1 | 97.1 % | Heading-based capture occasionally grabs procedural headings that appear inside the domestic-law block but belong to a different section type (e.g., "FINAL SUBMISSIONS TO THE COURT"). Cross-reference bridge sentences that point to prior-case domestic law summaries sit at the Legal Framework / Merits boundary. |
| P4 | `ALLEGED VIOLATION` / `JOINDER` anchors in Pop-C Facts → Merits or Just Satisfaction | 70 | 66 | 3 | 1 | 94.3 % | In compact Committee-format judgments, Operative Part sub-clauses (payment items such as "(a) that the respondent State is to pay..." and "(b) that from the expiry...") are sometimes embedded in the same paragraph block as the Article 41 award; P4 relabels them as Merits because the surrounding region matches the ALLEGED VIOLATION anchor, but the text is dispositif, not legal analysis. |
| P5 | Continuation propagation across a short Admissibility interruption in Pop-C → Merits or Just Satisfaction | 70 | 69 | 1 | 0 | 98.6 % | If the surrounding Merits block has not yet been upgraded to Just Satisfaction at the time P5 runs, a damage sub-heading ("A. Damage") that opens an Article 41 block inherits the Merits label rather than Just Satisfaction. |
| P6 | `Article 41 of the Convention provides` text anchor in Pop-C Facts → Just Satisfaction | 70 | 67 | 0 | 3 | 95.7 % | In large mass cases (Hungary, Russia) the applicant index or detention-conditions table follows the Article 41 provisions text; entries from these tables are captured by proximity and labeled Just Satisfaction. Whether such entries belong to Just Satisfaction or Appendix is genuinely ambiguous because the corpus does not consistently separate them. |
| P7 | Glued `I. JOINDER OF THE APPLICATIONS` heading in Pop-C Facts → Merits | 70 | 70 | 0 | 0 | 100.0 % | None detected in this sample. |

**Overall totals: 478 correct, 7 incorrect, 5 ambiguous across 490 samples.**

---

## 3. Adversarial Examples (Incorrect Relabelings)

Up to five cases per pass where the new section label was judged incorrect.

### P1 — Just Satisfaction over-capture of Operative Part dispositif

**Example 1** — rowid 941687, *Rutkowski and Others v. Poland* (001-155815)  
Original: `Operative Part` → New: `Just Satisfaction`  
Paragraph text: `8. Dismisses the remainder of the applicants' claim for just satisfaction;`  
Reasoning: This numbered dispositif clause is surrounded entirely by other Operative Part clauses ("Holds that there has been a violation...", "Holds (a) that the respondent State is to pay..."). The phrase "just satisfaction" in the text triggered the P1 rule, but the clause is part of the FOR THESE REASONS dispositif block, not a narrative Just Satisfaction paragraph.

**Example 2** — rowid 1914621, *Leong Poy v. Portugal* (001-159053)  
Original: `Operative part` → New: `Just Satisfaction`  
Paragraph text: `4. Dismisses the remainder of the applicant's claim for just satisfaction.`  
Reasoning: Identical pattern to Example 1. The sentence terminates a numbered dispositif sequence (clauses 1–3 are visible in context_before as Operative part). The P1 rule captures "just satisfaction" text without checking whether the paragraph is inside a dispositif block.

---

### P3 — Legal Framework capture of a procedural heading

**Example 3** — rowid 85786, *Michael Edward Cooke v. Austria* (001-59082)  
Original: `Facts Proceedings` → New: `Legal Framework`  
Paragraph text: `FINAL SUBMISSIONS TO THE COURT`  
Reasoning: This heading introduces a section in which each party sets out its final requests to the Court. It appears directly after the last domestic-law provision paragraph and before the submissions of the parties. The P3 rule matched it because it was surrounded by Legal Framework paragraphs, but the heading announces procedural content, not a statutory or regulatory provision.

---

### P4 — Merits label applied to Operative Part sub-clauses

**Example 4** — rowid 1885972, *Sosnovskiy v. Ukraine*  
Original: `Facts` → New: `Merits`  
Paragraph text: `(i) EUR 9,000 (nine thousand euros), plus any tax that may be chargeable, in respect of non-pecuniary damage;`  
Reasoning: In this Pop-C Committee judgment the Operative Part is embedded without a separate section heading. The paragraph is a sub-item of a numbered Holds clause ("Holds (a) that the respondent State is to pay...") and constitutes a damages award sub-clause, not a merits analysis. P4 improved the label from Facts (clearly wrong) but Merits is still wrong; the correct label is Operative Part.

**Example 5** — rowid 1424793, *Buzatu and Others v. Romania*  
Original: `Facts` → New: `Merits`  
Paragraph text (truncated): `(b) that from the expiry of the above-mentioned three months until settlement simple interest shall be payable... Dismisses the remainder of the applicants' claims for just satisfaction. Done in English...`  
Reasoning: This paragraph is the closing clause of the Operative Part dispositif, containing the default-interest sub-item and the dismissal sentence. P4 moved it from Facts (incorrect) to Merits (also incorrect); Operative Part is the correct label.

**Example 6** — rowid 1534992, *Nebiyeridze and Others v. Russia*  
Original: `Facts` → New: `Merits`  
Paragraph text: `(a) that the respondent State is to pay the applicants, within three months, the amounts indicated in the appended table...`  
Reasoning: Operative Part payment clause, same pattern as Example 5.

---

### P5 — Merits label inherited by an Article 41 block from residual Merits context

**Example 7** — rowid 1996788, *Akhmatova v. Russia* (001-207850-equivalent)  
Original: `Facts` → New: `Merits`  
Paragraph text: `A. Damage 70. The applicant claimed 21,211 euros (EUR) in respect of pecuniary damage and EUR 100,000 in respect of non-pecuniary damage.`  
Reasoning: The preceding paragraph (context_before[-1]) is headed "V. APPLICATION OF ARTICLE 41 OF THE CONVENTION" and is still labeled Merits because the Article 41 block was not yet upgraded by P1 at the time P5 ran (pipeline order dependency). P5 propagates the surrounding Merits label into this paragraph, but the content (Article 41 damage claim) belongs to Just Satisfaction.

---

## 4. Methodology Note

### What this audit measures

This audit estimates the **label-assignment precision** of the seven rule-based relabeling passes applied to the ECHR corpus. It answers: *of the relabelings that each pass made, what fraction assigned the correct section label?* It does **not** measure recall (how many paragraphs that should have been relabeled were missed) or end-to-end accuracy (the proportion of all paragraphs in the corpus that carry the correct label after all passes have run).

### Auditor and sample size

All 490 verdicts were produced by **Claude Sonnet 4.6** (Anthropic), a large language model, acting as a domain-informed judge. The model was given the full paragraph text, the original and new section labels, and six paragraphs of surrounding context (three before, three after, each with its section label). Judgments were made sequentially without access to aggregate statistics. One sentence of reasoning was required for each verdict.

No human re-check was performed on the AI verdicts. Results should be interpreted as an automated audit with known limitations: the model may miss subtle errors, apply inconsistent standards across passes, or be influenced by the framing of the surrounding context.

### What rule-based relabeling is fundamentally susceptible to

1. **Keyword triggers on shared vocabulary.** Terms such as "just satisfaction", "Article 41", or "JOINDER" appear in multiple structural locations. A rule that fires on these terms cannot distinguish a dispositif clause that *names* just satisfaction from a narrative paragraph that *is* a just satisfaction analysis. The P1 Operative Part over-capture (Examples 1 and 2) is the clearest instance.

2. **Pipeline ordering and residual labels.** Each pass reads the section labels that previous passes wrote. If pass P1 has not yet relabeled a block when P5 runs, P5 propagates whatever label the block currently carries rather than the intended final label. Example 7 (P5) demonstrates this dependency.

3. **Proximity propagation in dense mass-case judgments.** Pop-C formatted judgments from the Committee formation embed Operative Part, Just Satisfaction, and appendix tables in a single continuous text without section-break headings. Proximity-based rules (P4, P5, P6) cannot fully disambiguate these zones and occasionally label Operative Part sub-clauses as Merits (Examples 4–6).

4. **Ambiguous boundary paragraphs.** Some paragraphs genuinely straddle two sections. Domestic law cross-references at the end of a Facts Proceedings block (P3, rowid 184689), or applicant index tables following Article 41 award paragraphs (P6), have no single objectively correct label. Rule-based assignment will always be inconsistent at such boundaries.

5. **Structural variation across decades of ECHR judgments.** The corpus spans 1959–2024. Section heading conventions changed significantly: early judgments use "AS TO THE LAW" / "AS TO THE FACTS"; later ones use "ALLEGED VIOLATION OF ARTICLE X". Rules calibrated on modern heading patterns may fire incorrectly on older documents (or miss them entirely).

### Confidence interval note

With 490 samples and an observed precision of 97.6 % (478/490), the 95 % Wilson confidence interval for the true precision is approximately **[96.2 %, 98.6 %]**. This estimate assumes the 70-sample draws per pass are representative of the pass's full output, which was enforced by random sampling at corpus generation time.
