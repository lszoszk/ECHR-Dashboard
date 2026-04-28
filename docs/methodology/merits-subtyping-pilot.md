# Merits Sub-typing Pilot: Methodology Note

**Date:** 2026-04-28  
**Task:** Pilot annotation of Merits-section paragraphs from ECHR judgments into fine-grained sub-types  
**Annotator:** Claude Sonnet 4.6 (automated pilot)  
**Verdicts file:** `scripts/b2_pilot_verdicts.json`

---

## 1. Pilot Setup

### Sample design

Paragraphs were drawn from the Merits section label in the ECHR case database across three populations:

| Population | Label | Period | Judgment type | Cases sampled | Paragraphs sampled |
|---|---|---|---|---|---|
| A | Classical pre-1998 | Before 2 November 1998 | Plenary/Chamber (old Court) | 10 | 57 |
| B | Modern Chamber | Post-1998 | Section Chamber | 10 | 75 |
| C | Committee | Post-1998 | Committee of three judges | 10 | 97 |
| **Total** | | | | **30** | **229** |

The paragraph count per population is unequal because paragraph length and judgment length differ systematically across populations: Pop C batch judgments contain many short paragraphs and repeated template blocks, while Pop A judgments are longer prose with fewer, denser paragraphs.

### Case list

**Population A (pre-1998):**
OBERMEIER v. Austria (001-57631), FUNKE v. France (001-57809), WEBER v. Switzerland (001-57629), MATHIEU-MOHIN v. Belgium (001-57536), GRANGER v. UK (001-57624), LE COMPTE VAN LEUVEN DE MEYERE v. Belgium (001-57521), YOUNG JAMES AND WEBSTER v. UK (001-57608), BRANNIGAN AND MCBRIDE v. UK (001-57819), ZANDER v. Sweden (001-57862), and a tenth case sampled.

**Population B (modern Chamber):**
LEVOCHKINA v. Russia (001-81409), TARIMCI v. Turkey (001-88897), MAKSYMENKO v. Ukraine (001-119688), M.P.E.V. AND OTHERS v. Turkey (001-145348), LEELA FORDERKREIS v. Germany (001-89420), BOBIC v. Ukraine (001-110709), VERBINT v. Romania (001-110183), LEWAK v. Poland (001-82179), MUSTAFA ERDOGAN v. Turkey (001-144129), S.H. AND OTHERS v. Austria (001-157766).

**Population C (Committee):**
BOROMENSKYY v. Ukraine (001-238131), DITA AND OTHERS v. Hungary — revision (001-229172), SARKOCY v. Slovakia (001-226580), LASCAU v. Romania (001-183553), SZUCS AND OTHERS v. Hungary (001-187576), RASCHUPKIN v. Russia (001-221519), GORODILOV v. Russia (001-233777), SMAGINA v. Russia (001-219780), FETISOV v. Russia (001-234444), FOKS v. Russia (001-186765).

---

## 2. Category Definitions

The following operationalized definitions were applied during annotation. These reflect the categories as clarified by the pilot findings, including boundary cases encountered.

### `general_principles`
A paragraph that states abstract, case-law-derived standards applicable across cases. Characteristic markers: "The Court reiterates that...", "It is well established that...", "The relevant principles are set out in [case]...", followed by a general rule rather than application to the parties' specific facts. Does **not** include paragraphs that merely name a leading case as a template for the outcome (those are `application_to_facts`).

### `application_to_facts`
A paragraph that applies a legal standard, test, or principle to the specific facts of the case before the Court. Includes: parties' submissions on the merits, the Court's fact-specific analysis, framing of the complaint, applicability findings, applicants' reliance on Convention articles with case-specific reasoning, and one-line Government denials (medium confidence, as they constitute parties' positions even without elaboration). This is the workhorse category covering the bulk of reasoning paragraphs.

### `violation_finding`
A paragraph that announces a concluded violation of the Convention. Characteristic markers: "there has been a violation of Article N", "the complaints are admissible and disclose a breach of Article N" (Committee formula), "the Court finds a violation". This category captures the operative conclusion of the merits analysis, not the preceding reasoning. Note: in Committee format the violation finding often appears in a single combined sentence; in Chamber format it appears as a separate, numbered paragraph at the end of the merits section.

### `no_violation_finding`
A paragraph that announces a conclusion of no violation. In practice this category is almost exclusively found in the Operative Part of judgments, not in the Merits section; only one instance was found in this pilot (BRANNIGAN, rowid 27799 — a lex specialis finding that Article 5 § 4 habeas corpus procedure satisfied Article 13). This rarity is an expected feature of the Merits section label rather than a labeling error.

### `admissibility_within_merits`
A paragraph that decides an admissibility question (exhaustion of domestic remedies, six-month rule, victim status, manifestly ill-founded, no appearance of violation) within the Merits section label. This category covers two main patterns: (1) preliminary objections joined to the merits (Government raises non-exhaustion; Court rules before turning to the substance), and (2) the A/B sub-structure in modern Chamber judgments (section A = admissibility, section B = merits), where the admissibility ruling appears under the Merits section heading in the database.

### `joinder_or_procedural`
A paragraph that makes a purely procedural decision without substantive merits analysis. Includes: joining applications, declining to examine a complaint because another Article finding suffices (economy of analysis), locus standi rulings on continuation of proceedings, and — critically — the entire DITA AND OTHERS case (a revision judgment under Rule 80 that reconsiders the original judgment due to applicants' deaths; the entire document is procedural).

### `boundary_or_unclear`
A paragraph that should not receive a merits sub-type because it does not belong substantively to merits analysis, or because it cannot be classified reliably. Four sub-types were encountered:
- **Section headings**: "I. ALLEGED VIOLATION OF ARTICLE 6" — structural navigation text with no content.
- **Quoted Convention text**: verbatim Article text without analytical framing (often split from the surrounding paragraph due to PDF extraction).
- **Just satisfaction content** (Pop A, heavy): damages claims, Government responses, and Court awards under Article 50 / Article 41 that appear under the Merits section heading because the old Court's Merits section ran through to just satisfaction without a separate section break.
- **Appendix table data** (Pop C, heavy): structured rows from the judgment appendix (applicant names, case numbers, detention periods, award amounts) that were assigned the Merits section label by the paragraph-detection algorithm.
- **Citation fragments**: incomplete sentence fragments ("v. Croatia [GC], no. 7334/13, §§") caused by paragraph boundary misdetection during PDF extraction.

---

## 3. Distribution Table

### Overall distribution

| Category | Count | % of total |
|---|---|---|
| `application_to_facts` | 85 | 37.1% |
| `boundary_or_unclear` | 76 | 33.2% |
| `admissibility_within_merits` | 21 | 9.2% |
| `joinder_or_procedural` | 20 | 8.7% |
| `general_principles` | 16 | 7.0% |
| `violation_finding` | 10 | 4.4% |
| `no_violation_finding` | 1 | 0.4% |
| **Total** | **229** | **100%** |

### Distribution by population

| Category | Pop A | Pop B | Pop C |
|---|---|---|---|
| `application_to_facts` | 22 | 39 | 24 |
| `boundary_or_unclear` | 20 | 18 | 38 |
| `admissibility_within_merits` | 3 | 8 | 10 |
| `joinder_or_procedural` | 3 | 6 | 11 |
| `general_principles` | 7 | 3 | 6 |
| `violation_finding` | 1 | 1 | 8 |
| `no_violation_finding` | 1 | 0 | 0 |
| **Total** | **57** | **75** | **97** |

### Contamination share of `boundary_or_unclear` by sub-type

| `boundary_or_unclear` sub-type | Dominant population | Approximate count |
|---|---|---|
| Section headings | All (especially B) | ~25 |
| Just satisfaction (Article 50/41) | Pop A | ~18 |
| Appendix table data | Pop C | ~12 |
| Quoted Convention text | All | ~10 |
| Citation fragments | Pop C | ~8 |
| Operative part fragments | Pop C | ~3 |

---

## 4. Per-Case Patterns

### Ordering of categories within cases

**Pattern: general_principles precede application_to_facts**

This ordering is consistently observed in Pop A and Pop B. In GRANGER (001-57624), the structure is clear: admissibility ruling on the preliminary objection (rowids 16905–16906), then two `general_principles` paragraphs restating the Monnell and Morris standards (16908–16909), then `application_to_facts` applying those standards to Mr Granger's specific facts (16912), then a `joinder_or_procedural` disposal of un-pursued complaints (16914). This GP → ATF → procedure sequence is the canonical Pop A/B pattern.

In Pop C, the general_principles paragraph is typically compressed to a single "The Court reiterates the principles established in [leading case]" sentence. In SZUCS AND OTHERS (001-187576), the general_principles paragraph is absent entirely; instead, a citation fragment appears (rowid 1778230: "Frydlender v. France [GC]...") as a PDF extraction artifact where the case citation was split from its surrounding sentence.

**Pattern: violation_finding appears at the end of the merits analysis**

In ZANDER (001-57862), the violation finding (rowid 25723: "there has been a violation of Article 6 para. 1") immediately follows the final `application_to_facts` paragraph (rowid 25721: applicability conclusion). In LEVOCHKINA (001-81409), the violation finding (rowid 351538) follows the application paragraph (rowid 351537: Court applies the Pravednaya standard). This end-of-section placement is consistent across all three populations.

**Pattern: Committee violation findings use the combined admissibility + violation formula**

Eight of the ten Pop C cases have at least one `violation_finding`. The formula is invariably: "The Court declares the complaints admissible and finds that they disclose a breach of Article N" (or a close variant). This single sentence collapses what Pop A/B treat as two distinct acts — an admissibility decision and a merits conclusion — into one. Examples: rowid 1525403 (SARKOCY), rowid 1800332 (LASCAU), rowid 1555858 (RASCHUPKIN), rowid 1778233 (SZUCS), rowid 1574742 (SMAGINA).

**Pattern: DITA AND OTHERS is entirely procedural**

DITA AND OTHERS (001-229172) is a revision judgment under Rule 80, not a merits judgment. All seven sampled paragraphs (rowids 1509796–1509809) are `joinder_or_procedural` or `boundary_or_unclear` (one citation fragment). The case was included in Pop C because its document type ("judgment") and section label ("Merits") match the sampling criteria, but its content is entirely about striking out applications following the applicants' deaths. This case should be excluded from any merits sub-typing corpus via a document-type pre-filter.

**Pattern: just satisfaction contamination in Pop A**

Every Pop A case in this sample that was decided before the separate just satisfaction procedure became standard contains Article 50 paragraphs mislabeled as Merits. In OBERMEIER (001-57631), rowids 16253–16259 are all Article 50 content (damages, costs). In GRANGER (001-57624), rowids 16917–16921 are Article 50. In LE COMPTE (001-57521), rowids 4499–4502 are Article 50 section headings and analysis. In ZANDER (001-57862), rowids 25724–25731 are Article 50. This contamination affects at least 6 of the 10 Pop A cases sampled.

**Pattern: appendix table data contamination in Pop C**

Three Pop C cases with multiple applicants (GORODILOV 001-233777, SMAGINA 001-219780, FETISOV 001-234444) have appendix table rows that the section detector classified as Merits paragraphs. In GORODILOV, rowids 1474441–1474486 are structured applicant data rows (name, application number, complaint codes, award amounts). In FETISOV, rowids 1463502–1463530 are similarly structured. These rows have no legal analysis content and should be excluded by a structural pre-filter.

---

## 5. Schema Quality

### Overall fit

Of 229 paragraphs, 76 (33.2%) were assigned `boundary_or_unclear`. This rate indicates that approximately one-third of paragraphs in the raw Merits section label are not substantive merits analysis and are unclassifiable within the current seven-category schema. This is not a schema failure — the schema covers the substantive categories correctly — but it does mean that a **pre-filtering step is necessary** before applying the merits taxonomy at scale.

### What `boundary_or_unclear` paragraphs represent

The 76 boundary paragraphs fall into identifiable groups, none of which require new substantive categories:

1. **Section headings** (~25 paragraphs): These are pure navigation markers ("I. ALLEGED VIOLATION OF ARTICLE 6"). They have no analysis content. A heading-detection heuristic (short paragraphs, all-caps or numbered roman-numeral prefix, no verb phrase) would eliminate most of these before annotation.

2. **Just satisfaction paragraphs in Pop A** (~18 paragraphs): The old Court's Merits section runs through to just satisfaction. These paragraphs (Article 50/41 damages, costs, verbatim Article 50 text) require a section-label split in the upstream data to separate "Merits proper" from "Just satisfaction". This is a **data cleaning task**, not a schema issue.

3. **Appendix table rows in Pop C** (~12 paragraphs): Structured tabular data about applicants misclassified as Merits paragraphs. A structural detector (short paragraphs with applicant name + number + date pattern) could identify and exclude these.

4. **Quoted Convention text** (~10 paragraphs): Verbatim Article text without surrounding analysis, often split from the analytical paragraph by a PDF extraction paragraph boundary error. These are not independently classifiable. They could be merged back into adjacent paragraphs by a pre-processor.

5. **Citation fragments** (~8 paragraphs): Incomplete sentence fragments ending mid-citation ("v. Croatia [GC], no. 7334/13, §§"). These are PDF extraction artifacts. They should be merged with the preceding paragraph before annotation.

6. **Operative part and just satisfaction in Pop C** (~3 paragraphs): Interest rate clauses and operative part text mixed into the last Merits-labeled row of a case.

### Schema gap: no new categories needed

No substantive paragraph type was encountered that required a category outside the original seven. The `boundary_or_unclear` bin absorbed all non-classifiable content. The schema is fit for purpose once pre-filtering reduces the boundary rate.

### Schema tension: `admissibility_within_merits` vs. `application_to_facts`

The boundary between these two categories was occasionally uncertain. In YOUNG JAMES AND WEBSTER (001-57608), rowid 3982 — "the Court will not decide the negative right question in abstract" — straddles scope limitation and admissibility scoping. It was assigned `admissibility_within_merits` (medium confidence) because the Court is narrowing what it will decide, which is closer to a jurisdictional/admissibility scoping act than a merits analysis. This tension will recur in Pop A cases where the Court delimits issues using pre-1998 procedural conventions that blur the admissibility/merits boundary.

---

## 6. Confidence Breakdown

### Counts by confidence level

| Category | High | Medium | Low | Total | % High |
|---|---|---|---|---|---|
| `general_principles` | 16 | 0 | 0 | 16 | 100% |
| `no_violation_finding` | 1 | 0 | 0 | 1 | 100% |
| `violation_finding` | 9 | 1 | 0 | 10 | 90% |
| `joinder_or_procedural` | 19 | 1 | 0 | 20 | 95% |
| `boundary_or_unclear` | 72 | 4 | 0 | 76 | 95% |
| `admissibility_within_merits` | 19 | 2 | 0 | 21 | 90% |
| `application_to_facts` | 74 | 11 | 0 | 85 | 87% |
| **Total** | **210** | **19** | **0** | **229** | **91.7%** |

All categories exceed the 70% high-confidence threshold. No category requires schema refinement on confidence grounds.

### Medium-confidence cases and their patterns

Nineteen paragraphs received medium confidence. They group into three patterns:

1. **One-line Government denials** (8 paragraphs): Paragraphs such as "The Government contested that argument" (rowid 880949, 929893, 408925, 765219, 891536) were classified as `application_to_facts` with medium confidence. They constitute parties' positions but have essentially no content beyond the fact of denial. A reasonable alternative would be to create a sub-type `parties_submissions` to distinguish substantive party argument from bare denials; this pilot assigns both to `application_to_facts`.

2. **Admissibility-scoping paragraphs** (3 paragraphs): Paragraphs where the Court narrows the scope of its examination (e.g., "the Court will not address X in the abstract") were assigned `admissibility_within_merits` or `application_to_facts` with medium confidence, depending on whether the scoping act was directed at admissibility criteria or at delimiting the legal question.

3. **Fragment paragraphs with recoverable meaning** (3 paragraphs): Paragraphs classified despite being partial fragments (e.g., rowid 1463491, which continues a violation-finding statement from the prior paragraph). These received medium confidence because the classification depends on reading the fragment in context.

4. **Just satisfaction boundary cases** (4 paragraphs): The first and last paragraphs in a just satisfaction block were occasionally assigned medium confidence because it was unclear whether the database assigned them to the Merits or Just Satisfaction section label.

---

## 7. Recommendation for Full-Corpus Run

### Do not run the merits taxonomy on the raw Merits section label

The 33% `boundary_or_unclear` rate makes direct full-corpus classification wasteful and noisy. The following pre-filters should be applied to the Merits section label before annotation:

**Pre-filter 1 — Section headings**: Exclude paragraphs where the entire text matches the pattern `^[IVX]+\.\s+(ALLEGED VIOLATION|OTHER ALLEGED|THE LAW)` (case-insensitive). Estimated reduction: ~25 paragraphs per 229 in this sample (~11%).

**Pre-filter 2 — Just satisfaction (Pop A)**: In cases dated before 1998-11-02, exclude paragraphs occurring after a paragraph that matches "Article 50" or "Article 41" as a standalone section heading or as the first substantive mention. This requires upstream section relabeling rather than a simple text filter; the recommended approach is to add a `just_satisfaction` section label in the data pipeline for pre-1998 cases.

**Pre-filter 3 — Appendix table rows (Pop C)**: Exclude paragraphs where the text length is under 120 characters and the text matches the pattern `\d{4}-\d{2}-\d{2}.*\|` or contains a structured applicant-number/award pattern. Estimated reduction: ~12 paragraphs per 229 (~5%).

**Pre-filter 4 — Quoted Convention text and citation fragments**: Merge paragraph P with the previous paragraph if P starts mid-sentence (no capital letter after a period), or if P consists entirely of a Convention article text quote (matches `^In the determination of|^Everyone has the right|^No one shall`). This is best handled at the PDF extraction stage rather than at annotation time.

### Apply the taxonomy in two passes

**Pass 1 — Automated heuristics**: Apply rule-based classifiers for the following high-confidence patterns:
- Paragraphs containing "there has been a violation" or "the Court finds a violation" → `violation_finding`
- Paragraphs containing "there has been no violation" or "cannot find a violation" → `no_violation_finding`
- Paragraphs containing "joins the applications" or "decides to join" → `joinder_or_procedural`
- Paragraphs starting with "The Court reiterates that" or "The relevant principles are well established" followed by no case-specific facts → `general_principles`

**Pass 2 — LLM annotation**: Apply the remaining categories (`application_to_facts`, `admissibility_within_merits`, `boundary_or_unclear`, and cases not caught by the heuristics) with an LLM using the definitions in Section 2 above. The pilot definitions are sufficiently clear to allow high-accuracy annotation with a well-formed prompt; the main decision boundary to specify explicitly is `admissibility_within_merits` vs. `application_to_facts` for preliminary objection analysis.

### Expected post-filter distribution

After applying the four pre-filters, the expected category mix in the classifiable residual is approximately:
- `application_to_facts`: ~55%
- `admissibility_within_merits`: ~13%
- `joinder_or_procedural`: ~12%
- `general_principles`: ~10%
- `violation_finding`: ~6%
- `no_violation_finding`: ~1%
- `boundary_or_unclear` (residual): ~3%

### Special cases requiring document-type pre-filters

The DITA AND OTHERS case confirms that revision judgments under Rule 80 are entirely procedural and should be excluded from the merits annotation corpus. A pre-filter on `document_type = 'revision'` (or on the presence of "Rule 80" / "revision" in the judgment header) should be applied before sampling for merits sub-typing. Similarly, Grand Chamber cases referred after a Chamber judgment should be handled separately if the referral paragraphs are included under the Merits label.

### Schema stability

The seven-category schema is stable. No substantive eighth category emerged from 229 paragraphs across three structurally distinct populations. The only optional addition warranted by the pilot is a `parties_submissions` sub-category under `application_to_facts` to distinguish substantive party argument from bare one-line denials — but this distinction does not affect the primary taxonomy and can be deferred.
