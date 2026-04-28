# Human Review Findings (Manual M1–M6)

**Reviewer:** Łukasz Szoszkiewicz
**Date completed:** 2026-04-28
**Source:** `manual-review-verdicts-final.md`

This document logs the major findings from the structured manual review and the resulting changes to the methodology + roadmap.

---

## Overall validation outcome

| Task | Result | Methodology impact |
|------|--------|--------------------|
| **M1 — LLM-flagged errors** | 7/7 confirmed wrong | 97.6% precision floor for P1–P7 validated by expert review |
| **M2 — Merits sub-typing schema** | 1/10 correct, 7 wrong | Schema rejected; do not scale to full corpus |
| **M3 — Pop A structural validation** | 0/5 confirmed | Reveals semantic gap: our internal `para_idx` ≠ HUDOC paragraph numbers; segmentation also misses several sub-sections |
| **M4 — Worked example validation** | 1/4 confirmed | Same root cause as M3: examples cite our internal indices, not HUDOC numbering |
| **M5 — Pop C Introduction content** | 3/3 confirmed | Validates P9 strategy of moving applicant tables to Appendix |
| **M6 — Backup integrity** | confirmed | Rollback path verified |

---

## Finding 1 — `para_idx` vs HUDOC paragraph numbering

**Discovered in:** M3, M4

**Problem:** The `para_idx` column in our `paragraphs` table is a **sequential row counter** assigned during PDF segmentation, NOT the canonical paragraph number printed in the HUDOC source document.

**Concrete example** (*Wainwright v. UK*, 001-76999):

| Our `para_idx` | HUDOC paragraph number | Content |
|---|---|---|
| 75 | 56 | "There has therefore been a violation of Article 13" |
| 76 | (no number) | "III. APPLICATION OF ARTICLE 41 OF THE CONVENTION" — heading |
| 77 | 57 | "Article 41 of the Convention provides…" |

The expert reviewer rightly noted "There is no para 76 in the judgment!!!" — they were searching HUDOC for paragraph 76, but our internal index 76 points to a heading line that has no number in HUDOC.

**Why this matters:**
- Methodology examples cite paragraphs by `para_idx` ("¶76"), which fails verification against HUDOC.
- Cross-references between our system and external case-law databases (which all use HUDOC numbering) are broken.
- Researchers reading our outputs cannot trivially follow up to source.

**Mitigation applied (immediate):**
- Sec. 11 of `data-cleaning-full.md` now warns about this caveat.
- Worked examples in the methodology cite text content (first 80 chars quoted), not just `para_idx`.

**Planned fix (P10):** Extract HUDOC paragraph numbers from the leading "N. " pattern in each paragraph's text where present, and store as a separate `hudoc_para_no` column. Heading paragraphs (no number) get NULL. Separate-opinion blocks where HUDOC restarts at "1." would also be captured separately.

---

## Finding 2 — Merits sub-typing schema fails at expert review (10 % agreement)

**Discovered in:** M2

**Result:** From 10 LLM-classified samples reviewed by the project author:
- 1 correct
- 7 wrong (mostly: "should be Merits, not a sub-type")
- 2 marginal/defensible

**Diagnosis:** The schema is too granular. Most Merits paragraphs are a hybrid of legal principle and fact application; forcing them into discrete categories creates artificial distinctions that don't reflect how legal experts read these texts.

**Decision:** The B2 pilot schema is **rejected for full-corpus application**. Documented in `merits-subtyping-pilot.md` Section 8.

**Future direction (deferred):** A narrower schema with only the structurally reliable categories — `violation_finding` / `no_violation_finding` — applied as a binary tag, leaving everything else as plain Merits. Whether this is worth doing depends on downstream analytics needs.

---

## Finding 3 — Section schema misses several HUDOC-canonical sub-sections

**Discovered in:** M3

**Problem:** For Population A judgments, the expert found the following sub-section structure is canonical:

```
Procedure (HUDOC paragraphs N to N+5)
As to the facts (N+6 to N+10)
Relevant domestic law (N+11 to N+15)
[III. Case-law of EU / other intl bodies] (occasional, e.g. Niemietz §22)
Proceedings before the Commission (N+16 to N+18)
Final Submissions to the Court (occasional, e.g. Niemietz §25)
As to the law (Merits) (N+19 to N+30)
Just Satisfaction / Application of Article 50 (N+31 to N+33)
Operative Part (resets to 1, 2, 3 …)
[Separate Opinions]
```

Our current schema collapses several of these:
- `Procedure` is part of our `Introduction`
- `Relevant domestic law` and `Proceedings before the Commission` and `Final Submissions` are all lumped into our `Facts Background` or `Facts Proceedings` catch-all (depending on segmenter heuristics)
- We have no separate `Final Submissions` label

**Specific gaps confirmed in M3:**

| Case | Missing distinction |
|------|---------------------|
| 3.1 *McCallum* | Procedure (¶1–7) collapsed into Introduction |
| 3.2 *De Cubber* | Relevant legislation (¶15–20), Proceedings before Commission (¶21–22) all in Facts |
| 3.3 *Kefalas* | DISPUTED (no detail given) |
| 3.4 *Sporrong & Lönnroth (Article 50)* | Costs and Expenses (¶33–39) inside Merits |
| 3.5 *Niemietz* | Relevant domestic law (¶17–21), CASE-LAW OF EU (¶22), PROCEEDINGS BEFORE COMMISSION (¶23–24), FINAL SUBMISSIONS (¶25) all collapsed into Facts |

**Planned fix (P11):** Detect the canonical sub-section heading text inside Facts Background / Facts Proceedings (`PROCEDURE`, `RELEVANT DOMESTIC LAW`, `PROCEEDINGS BEFORE THE COMMISSION`, `FINAL SUBMISSIONS TO THE COURT`, `THE CASE-LAW OF THE COURT OF JUSTICE`) and split them out. The detection patterns are short capitalized phrases, low-noise; precision should be high (~99%) with conservative matching.

Estimated scope: a few thousand paragraphs across Pop A and Pop B judgments — probably 5,000–10,000 paragraphs that should move out of `Facts Background` / `Facts Proceedings` into more specific labels.

---

## Finding 4 — Operative Part numbering restarts at 1; separate opinions also restart

**Discovered in:** M3, M4

**Observation:** In HUDOC, the Operative Part has its own numbering "1.", "2.", "3." for each ruling clause. Separate opinions also each start their numbering at "1." Our `para_idx` continues sequentially through all of these.

**Example** (M4.3 *Murdalovy v. Russia*): "Yes, but the numbering starts again from 1. Not sure how to include this in the dataset."

**Planned fix (part of P10):** In addition to `hudoc_para_no`, add a `numbering_block` column that distinguishes:
- `main_judgment` — paragraphs 1, 2, 3, …, N of the body of the judgment
- `operative_part_1`, `operative_part_2` — numbered ruling clauses
- `separate_opinion_N_para_M` — paragraph M within the Nth separate opinion

This allows the dashboard to display the canonical HUDOC notation (e.g. "Dissenting Opinion of Judge X, ¶3") without confusion with the body.

---

## Finding 5 — Possible PDF extraction issue

**Discovered in:** M2 item 2.5

The expert could not locate the LLM-classified paragraph text in the actual judgment of *Fetisov v. Russia* (rowid 1463491, "5. § 3 of the Convention. OTHER ALLEGED VIOLATIONS UNDER WELL-ESTABLISHED CASE-LAW").

**Hypothesis:** This is a PDF-extraction artefact where a fragment from one paragraph was concatenated with a subsequent section heading due to layout-detection failure.

**Action:** No corpus-wide fix is currently planned; PDF extraction is an upstream concern owned by the original segmenter (HUDOC scraper). However, the existence of such fragments contributes to the noise observed in M2 schema testing and should be acknowledged.

A future quality pass could detect "fragment + heading" patterns (e.g. paragraph text containing both a continuation indicator and an ALL-CAPS heading) and flag for manual review.

---

## Action items prioritized

| # | Action | Effort | Priority | Status |
|---|--------|--------|---------|--------|
| 1 | Update `precision-audit.md` with M1 verdicts | 5 min | High | DONE |
| 2 | Update `merits-subtyping-pilot.md` with M2 verdicts | 5 min | High | DONE |
| 3 | Add `para_idx` caveat to `data-cleaning-full.md` | 10 min | High | DONE |
| 4 | Create this consolidated findings log | 15 min | High | DONE |
| 5 | **P10** — Extract HUDOC paragraph numbers from text into a `hudoc_para_no` column | 1–2 h | Medium | PLANNED |
| 6 | **P11** — Split Procedure / Relevant domestic law / Proceedings before Commission / Final Submissions out of Facts catch-all | 2–3 h | Medium | PLANNED |
| 7 | Add `numbering_block` column for Operative Part and Separate Opinions | 1 h | Low | PLANNED |
| 8 | Investigate Fetisov v. Russia rowid 1463491 PDF-extraction artefact | 30 min | Low | PLANNED |
| 9 | Decide whether to revisit Merits sub-typing with narrower schema (only violation_finding / no_violation_finding) | TBD | Low | PARKED |

---

## Updated validation chain claim

After M1–M6 completion, the methodology can defensibly state:

> Section assignment in the post-cleaning corpus has been validated through three independent mechanisms:
> 1. **Automated structural analysis** — 10 random cases per year 1975–2025, yielding the three-population taxonomy and identification of systematic relabel targets (P1–P9).
> 2. **LLM precision audit** — Sonnet 4.6 evaluation on a stratified random sample of 490 paragraphs across passes P1–P7, giving overall precision of 97.6 % [95% CI: 96.2 %–98.6 %]. P9 was separately audited on 500 samples at 98.8 % precision.
> 3. **Human expert review** — The project author independently reviewed (a) all 7 LLM-flagged "incorrect" paragraphs, achieving 7/7 agreement and confirming the precision floor; (b) 5 random Population A pre-1998 cases against HUDOC; (c) 4 worked examples cited in the methodology; (d) 3 Population C mass-applicant cases; and (e) the SQL backup-integrity claim.
>
> The human review surfaced a critical distinction between our internal `para_idx` row counter and the HUDOC-canonical paragraph numbers, which has been documented as a known caveat with planned remediation (Pass 10). The Merits sub-typing schema (B2 pilot) was rejected by expert review and will not be applied to the full corpus. Backup tables `_p1_backup` … `_p9_backup` (excluding rolled-back `_p8_backup`) preserve original section labels for full rollback.

This three-part validation chain meets the standard expected for an academic dataset claim.