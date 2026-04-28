# Data Cleaning Methodology — Summary

> One-page overview of the data cleaning pipeline applied to the ECHR Dashboard corpus. For internal specifications, change log, precision audit, and validation reports, please contact the project author.

## Corpus

- **24,669 cases** scraped from the ECHR HUDOC database (1960–2026)
- **2,001,447 paragraphs** segmented from judgment, decision, and press-release texts
- **51 respondent states**, all 47 Council of Europe contracting parties + their successors
- Sources: HUDOC official portal + complementary metadata (ECLI, citations)

## Three structural populations

The corpus is **not homogeneous**. Three distinct document formats exist, each with its own segmentation behaviour:

| Population | Years | Cases | `para_idx` | Typical structure |
|---|---|---|---|---|
| **A. Classical** | 1960–~1998 | ~4,500 | yes, sequential | Header → Introduction (PROCEDURE) → Facts Background → Facts Proceedings → Merits → Operative Part → Separate Opinion |
| **B. Modern Chamber** | 1999–present | ~13,400 | yes, sequential | Header → Introduction → Facts Background → Facts Proceedings → Legal Framework → Merits → [Just Satisfaction] → [Article 46] → Operative Part |
| **C. Committee / new-segmenter** | 2009–present | ~6,236 | **NULL** | Introduction → [Relevant legal framework] → Facts → Merits → Operative part *(lowercase)* |

Population C cases lack paragraph ordering, lowercase the operative section, and frequently mix substantive analysis into the `Facts` bucket. They demand different handling than A/B.

## Cleaning passes (Phase 2)

Four rule-based passes were applied, each with a backup table preserved in the database for rollback. **~225,000 paragraphs** (≈11.2% of corpus) were relabeled.

| Pass | What it does | Paragraphs moved | Backup |
|---|---|---|---|
| **P1 — Just Satisfaction recovery** | Article 41/50 reasoning blocks were lumped into Merits/Admissibility/Facts. Detect "APPLICATION OF ARTICLE 41" headings and the following content blocks, relabel to `Just Satisfaction`. | **82,989** | `_p1_backup` |
| **P2 — Separate Opinion recovery** | Dissenting/concurring opinions sometimes bled into `Operative Part`. Detect "DISSENTING/CONCURRING OPINION" headings, relabel to `Separate Opinion`. | **2,370** | `_p2_backup` |
| **P3 — Legal Framework extraction** | "II. RELEVANT DOMESTIC LAW AND PRACTICE" sub-sections embedded inside `Facts Proceedings` extracted to `Legal Framework`, matching how newer cases organize this content. | **83,377** | `_p3_backup` |
| **P4 — Population C segmentation** | In Committee cases (no `para_idx`), "ALLEGED VIOLATION" / "JOINDER" / "APPLICATION OF ARTICLE 41" headings inside `Facts` signal merits or just-satisfaction content. Walk by `rowid` and relabel. | **56,241** | `_p4_backup` |

## Result

Section coverage **before** cleaning was effectively 7–10 sections; **after** all 14 are populated:

```
Merits                547,270 paras   18,993 cases
Facts Proceedings     354,152 paras   12,987 cases
Introduction          215,531 paras   19,080 cases
Facts                 187,053 paras    5,649 cases
Admissibility         169,056 paras    9,029 cases
Just Satisfaction     122,321 paras   12,090 cases   ← 3.3× larger after P1+P4
Legal Framework       108,244 paras    9,501 cases   ← 4.4× larger after P3
Operative Part         67,717 paras   13,270 cases
Operative part         60,851 paras    6,232 cases   (lowercase, Population C)
Facts Background       36,463 paras   13,095 cases
Separate Opinion       31,575 paras    2,635 cases   ← +200 cases after P2
Relevant legal framework 15,743 paras   1,838 cases
Appendix               12,282 paras      546 cases
Article 46              3,981 paras      374 cases
```

## Validation

The cleaning pipeline has been validated through three independent mechanisms:

1. **Automated structural analysis** — 10 random cases per year 1975–2025 confirmed the three-population taxonomy.
2. **LLM precision audit** — Sonnet 4.6 evaluated a stratified random sample of 490 paragraphs across passes P1–P7. Result: **97.6 % overall precision** with 95 % Wilson confidence interval [96.2 %, 98.6 %]. A separate 500-sample audit of P9 gave 98.8 % precision.
3. **Human expert review** — The project author independently reviewed (a) all 7 LLM-flagged errors (7/7 agreement); (b) 5 random Pop A pre-1998 cases; (c) 4 worked examples; (d) 3 mass-applicant cases; (e) backup integrity. Results: precision floor confirmed; some refinements identified for future passes.

Targeted-query smoke tests:

- `"just satisfaction" pecuniary` (filter: `Just Satisfaction`) → 1,642 cases (was much lower)
- `"Code of Criminal Procedure"` (filter: `Legal Framework`) → 2,354 cases (vs 2,019 in `Facts Proceedings`)
- `"I respectfully dissent"` (filter: `Separate Opinion`) → 20 cases, **0** in `Operative Part`

A representative example — *Wainwright v. United Kingdom* — shows P1 working precisely:

```
¶75 [Merits]              "56. There has therefore been a violation of Article 13."
¶76 [Just Satisfaction]   "III. APPLICATION OF ARTICLE 41 OF THE CONVENTION"   ← heading moved
¶77 [Just Satisfaction]   "57. Article 41 of the Convention provides..."       ← block moved
¶78 [Just Satisfaction]   "A. Damage"
...
¶87 [Just Satisfaction]   "64. Default interest..."
¶88 [Operative Part]      "FOR THESE REASONS, THE COURT UNANIMOUSLY"           ← block boundary
```

12 paragraphs precisely between the two boundaries.

## Reproducibility

All transformation scripts are versioned in the project repository under `scripts/`. Every relabel script supports a default dry-run mode and an `--apply` flag, and creates a backup table (`_p1_backup` … `_p7_backup`) before any UPDATE. Rollback is a single SQL command per pass.

## Known limitations

1. **`para_idx` ≠ HUDOC paragraph number.** Our internal `para_idx` is a sequential row counter from segmentation. The HUDOC-canonical paragraph number printed in the source document differs because HUDOC skips section headings and restarts numbering inside operative parts and separate opinions. A planned future pass will extract HUDOC numbers from the leading "N. " pattern and store them as a separate column for verifiability.
2. **Population C `Introduction` still contains some tabular content.** Pass 9 cleaned ~27,000 of ~100,000 applicant-table fragments in mass cases. The remaining majority sits in longer sentence-form rows that simple regex cannot reliably distinguish; the `ⓘ` icon on the section filter warns researchers.
3. **Some sub-section distinctions are absent.** In Population A judgments, our `Facts Background` / `Facts Proceedings` collapses several HUDOC-canonical sub-sections (`PROCEDURE`, `RELEVANT DOMESTIC LAW`, `PROCEEDINGS BEFORE THE COMMISSION`, `FINAL SUBMISSIONS TO THE COURT`). Splitting these out is planned.
4. Two raw section labels coexist: `Operative Part` (Pop A/B) and `Operative part` (Pop C, lowercase). The frontend filter merges them under one bucket.

## Citation

If you use this dataset in research, please cite the cleaning methodology:

> Szoszkiewicz, Ł. (2026). *ECHR Dashboard: tier-1 paragraph-level search across European Court of Human Rights case law.* Adam Mickiewicz University, Poznań.
> Source: <https://github.com/lszoszk/ECHR-Dashboard>
