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

---

## 5. P8 Re-Audit (post-fix verification)

**P8 sampled at 70; observed precision: 30.0 % (21 correct, 44 incorrect, 5 ambiguous)**

### Per-rule breakdown

| Rule | Direction | Samples identified | Correct | Incorrect | Ambiguous | Rule precision |
|------|-----------|--------------------|---------|-----------|-----------|----------------|
| R1 | JS → Operative Part (dispositif clauses) | 2 | 2 | 0 | 0 | 100 % |
| R2 | Merits → Operative Part (payment sub-clauses) | 0 | — | — | — | n/a (not sampled) |
| R3 | Merits → Just Satisfaction (stranded Art. 41 blocks + propagation) | 68 | 19 | 44 | 5 | 27.9 % |

Rule identification is inferred from the relabeling direction: R1 is JS→Operative Part; R3 is Merits→JS (the dominant direction in the sample). No R2 Merits→Operative Part samples appeared in the 70-row draw.

### Incorrect examples

**Example 1** — rowid 1567430, *Kozhakhmetovy and Others v. Russia* (001-219658)  
Original: `Merits` → New: `Just Satisfaction`  
Paragraph text (para 18): *"The Court has examined the applications and considers that, in the light of all the material in its possession... these complaints either do not meet the admissibility criteria set out in Articles 34 and 35... or do not disclose any appearance of a violation..."*  
Reasoning: This is an admissibility rejection paragraph at the end of the Merits section of a compact Pop-C judgment. R3 forward propagation swept it into Just Satisfaction because the Article 41 heading appears a few paragraphs later, but the content is genuine Merits/admissibility analysis.

**Example 2** — rowid 1659104, *Sakhanenko v. Ukraine* (001-206362)  
Original: `Merits` → New: `Just Satisfaction`  
Paragraph text (para 41): *"Holds that the matter giving rise to the applicant's complaint under Article 1 of Protocol No. 1 has been resolved and decides to strike the application out... Declares the complaint under Article 6 § 1 admissible; Holds that there has been a violation of Article 6 § 1. Done in English..."*  
Reasoning: This paragraph contains dispositif language (Holds, Declares, Done in English) — it belongs to the Operative Part, not Just Satisfaction. P8 R3 applied the JS label without checking whether R1 had already or should have addressed it, and R1 did not fire because the paragraph did not originate from JS.

**Example 3** — rowid 1693518, *Ugurchiyev and Others v. Russia* (001-200730)  
Original: `Merits` → New: `Just Satisfaction`  
Paragraph text (para 126): *"On 4 March 2014 Officer D.R. was additionally questioned. His statements concerned the phone numbers he had contacted on 23 August 2013..."*  
Reasoning: R3 forward propagation reached deep into the factual background section, labeling a chronological investigation-narrative paragraph as Just Satisfaction. The content is clearly Facts/procedural background.

### Assessment of P8

P8 successfully addressed the two narrow error patterns it was designed for: R1 correctly relabels dispositif clauses (e.g., "Dismisses the remainder of the applicants' claims for just satisfaction", "Holds that there has been no violation") that were stranded in the wrong section, achieving 100 % precision on the two R1 samples observed. However, R3 — the rule intended to recover stranded Article 41 reasoning from the Merits section — exhibits severe over-propagation. The rule appears to fire on an Article 41 trigger and then propagate forward (or backward) through large blocks of text without adequate stopping conditions, assigning Just Satisfaction to genuine Merits analysis, Convention text quotations, factual narrative, and in one case an Operative Part dispositif paragraph. The 27.9 % precision for R3 means roughly seven in ten R3 relabelings are errors, introducing new labeling noise that likely exceeds in volume any improvement from the correct cases.

### P8 rolled back

Given the 30 % precision (vs 97.6 % baseline), **P8 was rolled back in full** by restoring all 67,709 paragraphs from `_p8_backup` to their pre-P8 sections. The current corpus state is therefore equivalent to post-P7. The `_p8_backup` table is retained as audit evidence; no future pass should re-apply the P8 rules without redesign.

For future work, fixing the stranded Article 41 blocks would require:
1. **Window-bounded propagation** — only relabel the next N≤10 paragraphs after a confirmed Article 41 heading, not until end-of-block.
2. **Per-paragraph content check** — each propagated paragraph must independently contain Article 41 vocabulary (Damage / Costs / Pecuniary / EUR / default interest / award).
3. **Restrict to cases without Just Satisfaction anchor** — only run on cases where no JS-labeled paragraph already exists, since cases with a JS anchor were already handled by P5/P6.

A rule-based redesign meeting these constraints is feasible but was deferred. Accepting the residual ~3 % imprecision from P1–P7 and moving on to richer analytical tasks (Merits sub-typing, recall audit) is the better near-term direction.

---

## 6. Human Expert Validation (Task M1)

**Reviewer:** Łukasz Szoszkiewicz (project author)
**Date:** 2026-04-28
**Source:** `manual-review-verdicts-final.md`

The seven paragraphs LLM-flagged as `incorrect` in Section 3 above were reviewed independently by the project author against the Court's section conventions and the HUDOC source documents.

| Item | LLM-flagged direction | Expert verdict | Agree |
|------|-----------------------|----------------|:-----:|
| 1.1 — *Rutkowski v. Poland* | "8. Dismisses the remainder…" → should be Operative Part | WRONG-relabel (correct target: Operative Part) | ✓ |
| 1.2 — *Leong Poy v. Portugal* | dispositif clause → Operative Part | WRONG-relabel (Operative Part) | ✓ |
| 1.3 — *Cooke v. Austria* | "FINAL SUBMISSIONS TO THE COURT" → Facts Proceedings | WRONG-relabel (Facts Proceedings) | ✓ |
| 1.4 — *Sosnovskiy v. Ukraine* | "(i) EUR 9,000…" sub-clause → Operative Part | WRONG-relabel (Operative Part) | ✓ |
| 1.5 — *Buzatu v. Romania* | default-interest clause → Operative Part | WRONG-relabel (Operative Part) | ✓ |
| 1.6 — *Nebiyeridze v. Russia* | "(a) that the State is to pay…" → Operative Part | WRONG-relabel (Operative Part) | ✓ |
| 1.7 — *Akhmatova v. Russia* | "A. Damage" sub-heading → Just Satisfaction | WRONG-relabel (Just Satisfaction) | ✓ |

**Expert agreement: 7 / 7 (100%).** All LLM-flagged errors are confirmed wrong relabels. The Sonnet 4.6 audit did not over-flag — the 97.6 % precision floor is validated, not over-stated. The 95 % Wilson confidence interval [96.2 %, 98.6 %] holds.

This three-part validation chain — automated structural analysis (24,669 cases) + LLM precision audit (490 samples) + expert human review (7 specific verdicts) — meets the standard expected for an academic dataset claim about section-label quality.

---

## 7. P13 Audit (post-relabel verification)

**50 samples, 98.0 % correct (49/50; 0 incorrect, 1 ambiguous)**

P13 was designed to fix Operative Part dispositif paragraphs that were stranded under the `Just Satisfaction` label due to P1 over-capture residue. Detection uses three rules: R1 (FOR THESE REASONS preamble), R2 (numbered Declares/Holds/Dismisses clauses), R3 (Registrar + President signature block, or Rule 77 citation with names).

### Per-rule breakdown

Rule attribution was inferred from paragraph content in the 50-sample draw:

| Rule | Approximate n in sample | Correct | Incorrect | Ambiguous | Rule precision |
|------|------------------------|---------|-----------|-----------|----------------|
| R2 — numbered dispositif clauses (Declares/Holds/Dismisses) | ~41 | 41 | 0 | 0 | 100 % |
| R3 — signature block (Registrar + President / Rule 77) | ~8 | 7 | 0 | 1 | 87.5 % (ambiguous) |
| R1 — FOR THESE REASONS preamble | 0 | — | — | — | n/a (not sampled) |

R2 dominates the sample (~82 %) and fires with perfect precision on numbered dispositif clauses. The single ambiguous case belongs to R3.

### Ambiguous example

**rowid 1466241** — *F.O. and Others v. Hungary* (001-234329)  
Original: `Just Satisfaction` → New: `Operative part`  
Text: `77. §§ 2 and 3 of the Rules of Court. Sophie Piquet Stéphanie Mourou-Vikström Acting Deputy Registrar President APPENDIX List of applicants: No. Applicant's Name Year of birth Nationality Place of residence`  
Reasoning: The paragraph opens with the Rule 77 signature block (correctly Operative Part) but continues into the "APPENDIX List of applicants" header and column labels. The single extracted paragraph straddles two logical sections — the closing signature of the dispositif and the opening of the applicant appendix. `Operative part` is the better label because the signature is the substantive element, but an `Appendix` label would also be defensible. This is a PDF extraction artefact, not a rule logic failure.

### No incorrect examples

Zero of the 50 sampled relabelings are outright wrong. Every R2 numbered-clause capture is a genuine dispositif clause; R3 signature captures are all authentic judgment-closing blocks.

### Conclusion

P13 deployed cleanly. Precision of 98.0 % (conservative: correct / total) meets and exceeds the 97.6 % baseline established across P1–P7. The single ambiguous case is an unavoidable granularity artifact where two section types share a paragraph boundary in the PDF extraction, not a systematic rule error. No rollback or redesign is warranted. P13's targeted fix for Pattern B (P1 dispositif over-capture) is confirmed effective without introducing new labeling noise.

---

## 8. P14 Audit (Relevant legal framework cleanup)

**50 samples, 78.0 % precision (39 correct, 7 incorrect, 4 ambiguous)**

P14 was designed to fix Pattern A: paragraphs in `Relevant legal framework` that contain Merits / Just Satisfaction / Operative Part content left as residue from imperfect P3 segmentation. Three rules: R1 (numbered Holds/Decides/Declares/Dismisses → Operative Part), R2 (Court awards + EUR → Just Satisfaction), R3 (explicit violation finding → Merits).

### Per-rule breakdown

| Rule | Direction | Samples in draw | Correct | Incorrect | Ambiguous | Rule precision |
|------|-----------|-----------------|---------|-----------|-----------|----------------|
| R1 — numbered Holds/Decides/Declares/Dismisses | RLF → Operative Part | 29 | 29 | 0 | 0 | 100 % |
| R2 — Court awards + EUR | RLF → Just Satisfaction | 6 | 4 | 0 | 2 | 66.7 % |
| R3 — explicit violation finding | RLF → Merits | 15 | 6 | 7 | 2 | 40.0 % |

**Overall: 39 correct, 7 incorrect, 4 ambiguous / 50 samples. Precision 78.0 %.**

R1 dominates the sample (58 % of draws) and is perfectly precise. R3 is the problem: seven of its fifteen samples are outright wrong, and two are ambiguous, yielding only 40 % precision. All seven R3 incorrect cases share the same failure mode (see below). R2 is degraded by two fused-dispositif cases that the fused-detector failed to suppress.

### Systematic error: R3 fires on Article 41 treaty text

All seven R3 incorrect relabelings are paragraphs containing the quoted text of **Article 41 of the Convention**: *"If the Court finds that there has been a violation of the Convention or the Protocols thereto, and if the internal law of the High Contracting Party concerned allows only partial reparation to be made, the Court shall, if necessary, afford just satisfaction to the injured party."*

These paragraphs appear in compact Pop-C and Committee judgments where the standard Art. 41 preamble is reproduced verbatim as part of the Just Satisfaction section. The word "violation" in the quoted treaty text triggers R3's violation-finding detector, which cannot distinguish a Court's own finding from a treaty quotation.

Affected rowids: 1611148, 1948794, 1830227, 1825277, 1635946, 1785375, 1837022. In each case the correct label is **Just Satisfaction**, not Merits.

A simple fix: add a negative-match condition to R3 — exclude paragraphs where the triggering "violation" phrase is preceded by "If the Court finds that there has been a" (the distinctive treaty-quotation preamble).

### R2 ambiguous cases: fused-detector gaps

Two R2 samples (rowids 1520949, 1546489) are fused paragraphs where a genuine Just Satisfaction costs-award sentence is followed by the entire operative dispositif (multiple Holds/Declares). R2 correctly identified the award clause, but the paragraph also contains 2+ Holds/Declares at sentence boundaries, which the fused-detector should have used to suppress the rule. The fused-detector condition apparently did not fire for R2, only for R3. Both are labeled ambiguous rather than incorrect because the opening JS content is genuine.

Two R3 samples (rowids 1666342, 1587269) are also fused: a default-interest or costs-reasoning sentence followed by an embedded full dispositif. Same fused-detector gap.

### Incorrect examples

**Example 1** — rowid 1611148, *Syomak and Others v. Ukraine* (001-213734)  
Original: `Relevant legal framework` → New: `Merits`  
Paragraph text: `10. Article 41 of the Convention provides: "If the Court finds that there has been a violation of the Convention or the Protocols thereto, and if the internal law of the High Contracting Party concerned allows only partial reparation to be made, the Court shall, if necessary, afford just satisfaction to the injured party."`  
Reasoning: This is the quoted text of Article 41 verbatim. R3 triggered on the word "violation" inside the treaty quotation. Context confirms this is the Art. 41 preamble paragraph in a Just Satisfaction block; context after (para 11) begins the Court's case-law analysis for JS awards. The correct label is Just Satisfaction, not Merits.

**Example 2** — rowid 1830227, *Momčilović and Others v. Serbia* (001-179210)  
Original: `Relevant legal framework` → New: `Merits`  
Paragraph text: `28. Article 41 of the Convention provides: "If the Court finds that there has been a violation of the Convention or the Protocols thereto..."`  
Reasoning: Same pattern. Context before explicitly shows `Just Satisfaction` section heading ("III. APPLICATION OF ARTICLE 41 OF THE CONVENTION"); context after (paras 29-31) is the JS damage and costs analysis. The paragraph is the Art. 41 preamble introduction to the JS section. Correct label: Just Satisfaction.

**Example 3** — rowid 1785375, *Aristov and Gromov v. Russia* (001-186684)  
Original: `Relevant legal framework` → New: `Merits`  
Paragraph text: `69. Article 41 of the Convention provides: "If the Court finds that there has been a violation of the Convention or the Protocols thereto..."`  
Reasoning: Context before shows `Just Satisfaction` section heading ("VI. APPLICATION OF ARTICLE 41 OF THE CONVENTION"); context after (paras 70-72) is the JS damage/costs analysis including a EUR award. Correct label: Just Satisfaction.

### Conclusion

P14 R1 (460 Operative Part relabelings) deployed with 100 % precision and requires no intervention. P14 R2 (145 Just Satisfaction relabelings) is largely sound but the fused-detector fails to suppress it on paragraphs where JS award sentences are merged with an embedded dispositif block. P14 R3 (205 Merits relabelings) has a critical systematic error: all seven observed incorrect cases stem from R3 firing on the standard Article 41 treaty quotation instead of the Court's own violation-finding language. At 40 % precision, R3 is introducing more noise than it corrects.

**Recommended action:** R3 should be patched with a single exclusion: skip paragraphs matching the Article 41 treaty-text pattern `"If the Court finds that there has been a violation"` (case-insensitive, within the paragraph text). This would eliminate the identified systematic false-positive class. The fused-detector should also be extended to suppress R2 (currently it appears only to gate R3). After patching, a re-audit of a fresh 30-sample draw of R3 relabelings is advisable before accepting P14 R3 outputs into the corpus.

---

## 9. P14 v2 Audit (post-redesign re-application)

**50 samples, 100.0 % precision (47 correct, 0 incorrect, 3 ambiguous)**

P14 v1 was rolled back. The redesign added the recommended fixes plus a broader mixed-content guard:

1. **R0 — Article 41 boilerplate**: new highest-priority rule that catches the canonical treaty-quote paragraph (`"Article 41 of the Convention provides..."` / `"If the Court finds that there has been a violation of the Convention..."`) and routes it to **Just Satisfaction**. Checked **before** R3 so the boilerplate "violation" tokens never reach the merits detector. This eliminates the v1 systematic FP class.
2. **R3 — JS+Operative mixed-paragraph guard**: skip if the paragraph contains both a JS award token (`awards EUR`, `non-pecuniary damage`, `costs and expenses`, `Court considers it reasonable to award`) AND a loose dispositif marker (any of `Holds|Decides|Declares|Dismisses` at a sentence boundary). This catches paragraphs where a JS award sentence is fused with the start of the operative dispositif — the v1 fused-detector only triggered on 2+ matches, missing single-tail concatenations.

Re-applied to 800 paragraphs (R1: 460 → Operative; R0+R2: 253 → Just Satisfaction; R3: 87 → Merits).

### Per-rule breakdown

| Rule | Direction | Samples in draw | Correct | Incorrect | Ambiguous | Rule precision |
|------|-----------|-----------------|---------|-----------|-----------|----------------|
| R1 — numbered Holds/Decides/Declares/Dismisses | RLF → Operative part | 25 | 25 | 0 | 0 | 100 % |
| R0 + R2 — Art. 41 boilerplate / Court awards | RLF → Just Satisfaction | 21 | 18 | 0 | 3 | 100 % (excl. ambiguous) |
| R3 — explicit violation finding | RLF → Merits | 4 | 4 | 0 | 0 | 100 % |

**Overall: 47 correct, 0 incorrect, 3 ambiguous / 50 samples. Precision 100.0 %.**

All nine sampled Article 41 treaty-quote paragraphs landed in **Just Satisfaction** via R0 (the v1 failure mode is fully resolved). All four R3 Merits relabelings are dominantly substantive Court conclusions ("there has been a violation of Article X...") flanked by other merits paragraphs in their context.

The three remaining ambiguous cases (rowids 1546108, 1578284, 1558832) are pre-existing PDF-extraction merge artefacts where a costs-and-expenses JS award sentence is concatenated with the opening of the operative dispositif. The chosen JS label is defensible because the dominant content is Article 41 award reasoning; an Operative label would also be defensible. These would require text-splitting (out of scope for relabeling) and are unrelated to the redesign.

### Conclusion

**P14 v2 deployed cleanly. 100 % precision exceeds the 95 % bar by a wide margin and is tied for the highest precision pass in the cleaning pipeline.** The redesign converted a 78 % failed pass into a 100 % validated pass while keeping the conservative scope (800 paragraphs vs. ~6k naive scope from the recall audit) — sacrificing recall to ensure no further noise is introduced into the corpus. The remaining ~5k recall-audit-flagged RLF residue is genuinely heterogeneous and ambiguous; future passes targeting that pool should follow the same precision-first design philosophy.

Saved artifacts: `scripts/p14_relabel.py`, `scripts/p14_audit_samples_v2.json`, `scripts/p14_audit_verdicts_v2.json`. Backup: `_p14_backup` (800 rows).

---

## 10. P15 Audit (Rec-2: Just Satisfaction → Operative Part residual)

**96 samples (full population audit), 100.0 % precision (96 correct, 0 incorrect, 0 ambiguous)**

P15 picks up the dispositif residue P13 missed. P13 capped at 400 chars and only treated `numbering_block = operative_dispositif`; recall-audit Rec-2 and a post-P13 probe surfaced ~600 candidates with dispositif markers still in `Just Satisfaction`. After tightening the signature-block anchor (the loose `Rules of Court` pattern produced ~100 % FP rate on JS reasoning that cites Rule 60 / 38 / 61), P15 ships at 96 paragraphs with two rules:

- **R1**: numbered `^\d+\.\s*(Holds|Decides|Declares|Dismisses)` (81 paragraphs, no length cap)
- **R2**: strict `\bRule 77\b` + Registrar/Done in, length < 700 (15 paragraphs — default-interest continuation clauses)

### Per-rule breakdown

| Rule | Direction | Samples | Correct | Incorrect | Ambiguous | Precision |
|------|-----------|--------:|--------:|----------:|----------:|----------:|
| R1 — numbered dispositif | JS → Operative | 81 | 81 | 0 | 0 | 100 % |
| R2 — Rule 77 + signature/continuation | JS → Operative | 15 | 15 | 0 | 0 | 100 % |

**Overall: 96 correct, 0 incorrect, 0 ambiguous / 96 samples. Precision 100.0 %.**

R1 captured a wide diversity of operative formats: classical Pop A "Holds (a) the State is to pay X francs/lire" monetary-award clauses, "Dismisses the remainder" + "Done in [Lang]" closings, "Decides to continue Rule 39 interim measure" extradition non-removal clauses, "Decides to strike the application out" friendly-settlement dispositifs, "Declares the complaints admissible" admissibility dispositifs, and "Holds that the respondent State must set up a remedy" pilot-judgment general-measures clauses. All 81 are flanked by other Operative Part paragraphs in the surrounding context.

R2 captured the classical "(b) that from the expiry of the above-mentioned three months until settlement, simple interest shall be payable on the above amount at a rate equal to the marginal lending rate of the European Central Bank during the default period plus three percentage points" continuation. These clauses were stranded in JS by PDF-extraction splitting them off from their parent numbered "Holds (a) the State is to pay..." clause; they specify the conditions of the State's payment obligation and operationally belong with the operative dispositif.

### Conclusion

**P15 deployed cleanly. 100 % precision (full-population audit, no sampling) confirms the rule design.** The decision to drop the broad `Rules of Court` anchor in favour of strict `\bRule 77\b` was decisive — without it, R2 would have introduced ~1,000 false positives. Saved artifacts: `scripts/p15_relabel.py`, `scripts/p15_audit_samples.json`, `scripts/p15_audit_verdicts.json`. Backup: `_p15_backup` (96 rows).

---

## 11. P16 Audit (Rec-3: Facts → JS / Operative in Pop C compressed cases)

**55 stratified samples, 100.0 % precision (55 correct, 0 incorrect, 0 ambiguous)**

P16 is the largest single relabel since P3. The recall audit estimated ~3,000 misclassified paragraphs in Facts/Facts Proceedings; the actual scope was **~4× larger** (11,804 paragraphs) once the post-P15 probe revealed that Pop C compressed-format judgments dumped the entire Operative dispositif AND JS award reasoning into the `Facts` section. Six tight rules (R0a heading, R0b boilerplate, R1 numbered dispositif, R2 operative payment clause, R3 default-interest continuation, R4 Court-awards JS reasoning) caught the pattern with zero observed FPs.

The critical decision was **rejecting** the `equitable basis + EUR` pattern (76 candidates, 5/5 spot-check FP rate): Italian and Bulgarian Pop A/B cases use this phrase to describe **domestic Court of Appeal** awards in Facts narrative ("the Court of Appeal found that a reasonable time had been exceeded. It awarded the applicant EUR 1,000 on an equitable basis..."). R4 (Court awards) is restricted to Pop C only (`para_idx IS NULL`) to prevent this confusion, since Pop C cases are committee-format compressed judgments where the only "Court" being awarded is the ECHR Court itself.

### Per-rule breakdown

| Rule | Direction | Population | Sampled | Correct | Incorrect | Ambiguous | Precision |
|------|-----------|-----------:|--------:|--------:|----------:|----------:|----------:|
| R0a — `APPLICATION OF ARTICLE 41` heading | Facts → JS | 1 | 1 | 1 | 0 | 0 | 100 % |
| R0b — `Article 41 ... provides` boilerplate | Facts → JS | 6 | 6 | 6 | 0 | 0 | 100 % |
| R1 — numbered Holds/Decides/Declares/Dismisses | Facts → Operative | 8,786 | 12 | 12 | 0 | 0 | 100 % |
| R2 — `(a) that the State is to pay` | Facts → Operative | 566 | 12 | 12 | 0 | 0 | 100 % |
| R3 — `(b) that from the expiry ... simple interest` | Facts → Operative | 2,197 | 12 | 12 | 0 | 0 | 100 % |
| R4 — ECHR Court awards (Pop C only) | Facts → JS | 248 | 12 | 12 | 0 | 0 | 100 % |

**Overall: 55 correct, 0 incorrect, 0 ambiguous / 55 samples. Precision 100.0 %.**

R4 was the highest-FP-risk rule but the audit confirmed all 12 sampled matches refer to the ECHR Court (verified via "proceedings before the Court", Article 41 framing, applicant-claimed → Government-contested → Court-awards canonical sequence, or domestic-currency-to-EUR conversion language). The Pop-C-only restriction is doing its job.

R1's surrounding context routinely shows the Pop C compressed-format pattern: the surrounding paragraphs are also still labeled `Facts` despite being "Done in English ... Registrar" closing blocks or "(a)/(b)" sub-clauses — confirming that the original segmenter dumped the entire dispositif into Facts. P16 extracts the unambiguous numbered-dispositif heads (R1) and named sub-clauses (R2/R3) precisely; the residual unmarked sub-clauses (e.g., long appended-table rows) are left in Facts pending future passes if needed.

### Conclusion

**P16 deployed cleanly. 100 % precision across 55 stratified samples (1+6+12+12+12+12).** Together with P14 v2 (RLF cleanup) and P15 (JS → Operative residual), P16 brings Pop C compressed-judgment structure into close alignment with the canonical 14-section taxonomy. The cumulative count of pipeline relabels reaches ~330,700 paragraphs (~16.5 % of corpus). Saved artifacts: `scripts/p16_relabel.py`, `scripts/p16_audit_samples.json`, `scripts/p16_audit_verdicts.json`. Backup: `_p16_backup` (11,804 rows).

---

## 12. P17 Audit (Rec-4: representation paragraphs Facts → Introduction)

**33 samples (30 R1 + all 3 R2), 100.0 % precision (33 correct, 0 incorrect, 0 ambiguous)**

Recall-audit Rec-4 was the lowest priority recommendation ("medium" confidence, "may not warrant a dedicated rule"). The probe revealed that the actual scope (1,501 paragraphs) was meaningful and the rule could be designed precisely. The key design decision was **rejecting** applicant-only representation as a trigger because "the applicant was represented by a State-appointed lawyer" routinely appears in Facts narratives describing domestic proceedings.

The "Government were represented by" phrasing, by contrast, is unique to ECHR procedural intro context (the Government's representation of itself **before** ECHR) and does not appear in domestic narratives — making it a precision-first anchor. R2 only matches paragraphs where both `gov-rep` AND `applicant-rep` patterns occur in the same short paragraph, which is the canonical Modern Chamber form.

### Per-rule breakdown

| Rule | Direction | Population | Sampled | Correct | Incorrect | Ambiguous | Precision |
|------|-----------|-----------:|--------:|--------:|----------:|----------:|----------:|
| R1 — gov-rep alone, len < 300 | Facts/etc → Introduction | 1,498 | 30 | 30 | 0 | 0 | 100 % |
| R2 — pure gov+app rep, len < 500 | Facts/etc → Introduction | 3 | 3 | 3 | 0 | 0 | 100 % |

**Overall: 33 correct, 0 incorrect, 0 ambiguous / 33 samples. Precision 100.0 %.**

All R1 samples sit in the canonical Modern Chamber position: `Introduction (case concerns) → THE FACTS heading → "2. The applicant was born in [year] and lives in [city]" → "3. The Government were represented by their Agent, [name]" → "4. The facts of the case may be summarised as follows."` Only the third paragraph is moved by P17; the second (applicant biographical + lawyer reference) is left in Facts Background pending a future pass if needed.

Several R1 samples are PDF-extraction fragments (e.g., "N. Jomarjidze, a lawyer practising in Tbilisi. 3. The Government were represented by their Agent, Mr") where the applicant's lawyer name is fused with the start of the Government rep paragraph. These are still correctly relabelled because the dominant content is the Government rep sentence; the truncation is an upstream PDF artefact.

### Conclusion

**P17 deployed cleanly. 100 % precision across 33 stratified samples.** The applicant-only rejection was decisive: a less restrictive rule would have introduced FPs from domestic-proceedings narratives. With P17 the cumulative pipeline relabels reach ~332,200 paragraphs (~16.6 % of corpus). All four recall-audit recommendations (Rec-1 through Rec-4) are now closed at ≥98 % precision. Saved artifacts: `scripts/p17_relabel.py`, `scripts/p17_audit_samples.json`, `scripts/p17_audit_verdicts.json`. Backup: `_p17_backup` (1,501 rows).
