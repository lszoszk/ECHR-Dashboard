# Introduction Audit — Pilot

**Date:** 2026-04-28
**Auditor:** Claude Sonnet 4.6 (Anthropic) on a 500-paragraph stratified sample
**Goal:** Decide whether the `Introduction` section in Population C mass cases can be cleanly split into `procedural` (keep as Introduction) vs `applicant_table` (move to `Appendix`).

---

## 1. Pilot setup

**Mass cases**: Population C cases (`para_idx IS NULL`) with ≥10 paragraphs in the `Introduction` section. There are **3,290 such cases** containing **132,544 Introduction paragraphs** combined. The largest is *Çetin and Others v. Türkiye* with 1,604 paragraphs; eleven cases exceed 500.

**Sample**: 500 paragraphs, length-stratified (125 each from buckets <30, 30–80, 81–200, >200 chars), `seed=2024`. Each sample includes 2 paragraphs of context before and after.

**Schema**: Each paragraph classified as `procedural` / `applicant_table` / `unclear`.

---

## 2. Distribution by category

Overall (n=500):

| Category | Count | % of sample |
|---|---|---|
| `applicant_table` | 382 | **76.4%** |
| `procedural` | 61 | 12.2% |
| `unclear` | 57 | 11.4% |

**Three out of four** paragraphs in mass-case Introductions are tabular data, not procedural history.

### By length bucket

| Length | applicant_table | procedural | unclear | n |
|---|---|---|---|---|
| <30 chars | **94%** | 0% | 6% | 125 |
| 30–80 chars | **84%** | 8% | 8% | 125 |
| 81–200 chars | 69% | 17% | 14% | 125 |
| >200 chars | 59% | 24% | 17% | 125 |

The pattern is monotonic: the shorter a paragraph in the Introduction of a mass case, the more likely it is tabular. But even at length >200 the majority (59%) is still applicant-table — typically a full row stitched together: name + date of birth + dates + application number + amount awarded.

### Confidence

| Category | high | medium | low |
|---|---|---|---|
| `applicant_table` | 316 (83%) | 66 (17%) | 0 |
| `procedural` | 18 (30%) | 43 (70%) | 0 |
| `unclear` | 0 | 38 | 19 |

`applicant_table` is classified with high confidence in 83% of cases. `procedural` is mostly medium-confidence — the boundary between a fragmentary procedural statement and a tabular fragment is genuinely fuzzy in this corpus.

---

## 3. High-confidence detection patterns

Four deterministic rules were tested against the 500 LLM verdicts:

| Rule | Description | Hits | Precision |
|---|---|---|---|
| `column_header` | Text matches an exact column header phrase ("Applicant's name", "Year of birth", "Date of birth", "Sq. m per inmate", "(in euros)", "Total length", etc.) | 41 | **100.0%** |
| `footnote` | Text matches `^\[\d+\]$` (e.g. `[1]`, `[2]`) | 11 | **100.0%** |
| `app_number` | Text contains `\d{4,5}/\d{2}` application-number pattern AND length<150 | 65 | **96.9%** |
| `applicant_row` | Text starts with `\d+\.?\s+\d{1,2}/\d{1,2}/\d{2,4}` (numbered row prefix + date) | 11 | 63.6% |

The first three rules combined: **128 hits, 95.3% precision** (122 true positives, 6 unclear, 0 procedural false positives). The `applicant_row` rule is too noisy and is dropped.

### Recall

The combined high-precision rule catches only **31.9%** of true `applicant_table` paragraphs (122 of 382 in the sample). The remaining 260 are middle-length and >200-char paragraphs where the row data is wrapped into a sentence-like form ("Mr Smith, born 1955, lodged application no. 12345/14 on 6 June 2014, claiming…") that the simple patterns do not capture.

---

## 4. Recommended deterministic pass (P9)

A conservative pass with high precision, low recall:

```sql
UPDATE paragraphs SET section = 'Appendix'
WHERE section = 'Introduction'
  AND para_idx IS NULL                                 -- Population C only
  AND case_id IN (
        SELECT case_id FROM paragraphs
        WHERE para_idx IS NULL AND section = 'Introduction'
        GROUP BY case_id HAVING COUNT(*) >= 10
      )                                                -- Mass cases only (≥10 intro paras)
  AND (
        -- Rule 1: exact column header match
        text IN ('Applicant', 'Applicant''s name', 'Applicant name',
                 'Year of birth', 'Date of birth', 'Place of residence',
                 'Representative', 'Representative''s name',
                 'Facility', 'Start and end date', 'Duration',
                 'Sq. m per inmate', 'Specific grievances',
                 'Amount awarded', '(in euros)', 'Annex',
                 'Total length', 'Levels of jurisdiction',
                 'Start of proceedings', 'End of proceedings')
     OR text LIKE 'Applicant''s name %' OR text LIKE 'Applicant name %'
     OR text LIKE 'Applicant 1%' OR text LIKE 'Applicant 2%' OR text LIKE 'Applicant 3%'
     OR text LIKE 'Applicant 4%' OR text LIKE 'Applicant 5%' OR text LIKE 'Applicant 6%'
        -- Rule 2: footnote markers
     OR text REGEXP '^\[\d+\]$'
        -- Rule 3: contains application-number pattern + short
     OR (text REGEXP '\d{4,5}/\d{2}' AND length(text) < 150)
      )
```

(SQLite `REGEXP` requires the `re` extension; in Python with sqlite3 it can be enabled per-connection.)

### Estimated scope

The combined rule fires on roughly **31.9% of `applicant_table` paragraphs** = 0.319 × 0.764 × 132,544 ≈ **32,300 paragraphs** moved from `Introduction` to `Appendix`.

`Appendix` would grow from 12,282 to ~44,500 paragraphs. `Introduction` in mass cases would shrink from 132,544 to ~100,000 — still noisy but the most easily-identified table fragments removed.

### Trade-off

- **Precision = 95.3%** — high enough to commit without LLM re-audit, but should still get a 50-sample verification audit after apply.
- **Recall = 31.9%** — leaves 60%+ of table content in `Introduction`. The `ⓘ` hint icon on the section filter therefore remains relevant for the unhandled majority.

---

## 5. Adversarial cases

A handful of patterns the LLM flagged as `unclear` or where the rule would over-fire:

- **Continuation fragments**: paragraphs that are continuation of a prior sentence due to PDF extraction split (e.g. a procedural sentence broken across two paragraph boundaries). Hard to classify without lexical context.
- **Application number INSIDE procedural text**: e.g. "On 14 November 2011 the Government were given notice of the applications (nos. 12345/14, 12346/14, 12347/14)." Length >150 saves us in this case (the rule excludes long matches), but a borderline case of length 140 with embedded app numbers would be a false positive.
- **Text "Annex"**: standalone "Annex" appears in 2-3 sample paragraphs as a section heading INSIDE Introduction (the table sits under a sub-heading). This is correctly captured but raises the question of whether we should also detect the heading.
- **"Applicant 1:", "Applicant 2:" etc.** as standalone — these are sub-headings before per-applicant blocks of mixed data (procedural + tabular). Whether they belong to Introduction or Appendix is genuinely ambiguous; the rule classifies them as table.

---

## 6. Recommendation

**Apply P9 with the conservative rule above.** It:

1. Has 95%+ precision (verified by LLM audit on 500 stratified samples).
2. Moves an estimated 32,000+ paragraphs to a more appropriate section (`Appendix`).
3. Visibly cleans up the `Introduction` filter for users searching mass cases.
4. Creates a `_p9_backup` table for rollback.
5. Keeps the `ⓘ` hint icon on the filter, since 60%+ of table content remains unhandled.

A second LLM-driven pass (P10) on the residual is feasible but expensive (~$20 for full 100k+ paragraphs at Sonnet 4.6 rates) and runs into per-account rate limits. Defer until end-to-end recall audit (Phase 2 Option B) is funded.

---

## 7. Audit artefacts

- `scripts/b3_intro_samples.json` — 500 input samples
- `scripts/b3_intro_verdicts.json` — 500 Sonnet 4.6 classifications
- `methodology-internal/introduction-audit-pilot.md` — this report
- (Pending) `scripts/p9_intro_to_appendix.py` — the relabeling script
