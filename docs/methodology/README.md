# Data Cleaning Methodology — Summary

> One-page overview. For full details see [`data-cleaning-full.md`](data-cleaning-full.md). For chronological log see [`CHANGELOG.md`](CHANGELOG.md).

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

A **stratified sample** of 50 cases (pre/post-Phase-2) was hand-checked. All four passes were also smoke-tested with targeted queries:

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

All transformation scripts are in [`scripts/`](../../scripts/):

- `harvest_headings.py` — scans corpus for canonical heading occurrences (read-only)
- `analyze_sections.py` — 10 random cases per year, 1975–2025 (read-only)
- `p1_validate_js.py` / `p1_relabel_js.py` — Pass 1
- `p2_relabel_opinions.py` — Pass 2
- `p3_validate_domestic_law.py` / `p3_relabel_domestic_law.py` — Pass 3
- `p4_validate_population_c.py` / `p4_relabel_population_c.py` — Pass 4
- `generate_sample50.py` — stratified offline-fallback sample regen

Every relabel script supports `--apply` (commit) vs default dry-run mode and creates a backup table (`_p1_backup` … `_p4_backup`) before any UPDATE. Rollback is a single SQL command per pass.

## Known limitations

1. **~3,000 Population C cases** still have "ALLEGED VIOLATION" merits content stuck in `Facts` because the segmenter glued the heading to the following paragraph (>120 chars), evading our heading detector. A Pass 5 with relaxed heading bounds is feasible but riskier.
2. **`Introduction` in mass-applicant cases** (Russia, Ukraine joined cases) still contains 91–309 paragraphs of applicant-table column headers per case. Filtering the section will retrieve these as noise. The `ⓘ` icon next to "Introduction" in the filter sidebar warns researchers about this.
3. Two raw section labels coexist: `Operative Part` (Pop A/B) and `Operative part` (Pop C, lowercase). The frontend filter merges them under one bucket.

## Citation

If you use this dataset in research, please cite the cleaning methodology:

> Szoszkiewicz, Ł. (2026). *ECHR Dashboard: tier-1 paragraph-level search across European Court of Human Rights case law.* Adam Mickiewicz University, Poznań.
> Source: <https://github.com/lszoszk/ECHR-Dashboard>
