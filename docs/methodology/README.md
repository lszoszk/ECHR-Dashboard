# Methodology

> A brief overview of how this dataset was built and validated. Detailed specifications, pass-by-pass change logs, and per-sample audit verdicts are available **on request**.

## What's in the dataset

- **24,669 cases** from the European Court of Human Rights (1960 – present)
- **2.0 million paragraphs** segmented from judgment, decision, and admissibility-decision texts
- **Source:** the official HUDOC portal (cases harvested by the Court itself)
- **Coverage:** all 47 Council of Europe contracting parties plus their successor states

## Why labelling is non-trivial

ECHR judgments do not follow a single template. The Court's drafting style has evolved across six decades, and three structurally distinct case populations coexist in the corpus:

| Population | Years | Cases | Typical structure |
|---|---|---:|---|
| **Classical** (pre-1998) | 1960 – ~1998 | ~4,500 | Header → Procedure → Facts → As to the Law → Operative Part → Separate Opinions |
| **Modern Chamber** | 1999 – present | ~13,400 | Introduction → Facts → Legal Framework → Merits → Just Satisfaction → Operative Part |
| **Committee / mass cases** | 2009 – present | ~6,200 | Introduction → Relevant legal framework → Facts → Merits → Operative part *(lowercase, often compressed)* |

The same content (e.g., a "violation finding") can appear under quite different section headings depending on the population, the rapporteur's drafting habits, or PDF-extraction quirks. Naïve segmentation produces noisy labels — paragraphs of substantive analysis end up in `Facts`, just-satisfaction reasoning ends up in `Merits`, dispositif clauses bleed into `Just Satisfaction`, and so on.

## What we did

A series of **fourteen rule-based cleaning passes** were applied on top of the initial segmentation. Each pass targets a specific, well-defined misclassification pattern (for example: "Article 41 reasoning blocks misfiled into Merits", "dissenting opinions bleeding into the Operative Part", "numbered Holds clauses stranded in Just Satisfaction"). Together they relabelled approximately **319,000 paragraphs — about 16 % of the corpus** — to bring section labels into closer agreement with HUDOC-canonical structure.

Two new section labels (`Commission Proceedings`, `Final Submissions`) were added to capture pre-Protocol-11 procedural sub-sections that the Court no longer uses. Two structural columns (`hudoc_para_no`, `numbering_block`) were derived to support cross-reference against source PDFs.

Every pass keeps a per-row backup table in the database. Rollback is a single SQL statement.

## How we validated it

Three independent validation mechanisms support the published labels:

1. **Automated structural analysis** of 10 random cases per year (1975 – 2025) used to map the population taxonomy and characterise drafting drift over time.
2. **LLM-as-judge precision audits.** Stratified random samples (490 paragraphs across the early passes; 50 each for later passes) were independently reviewed by Anthropic's Sonnet 4.6 model, with full surrounding context. **Aggregate precision: 97.6 %** [95 % Wilson CI: 96.2 % – 98.6 %].
3. **End-to-end recall audit.** A separate 300-sample stratified draw of *current* labels (not just relabelled paragraphs) measured **88.3 % overall correctness** [95 % Wilson CI: 84.2 % – 91.5 %], characterising the residual error rate the rule-based pipeline could not reach without sacrificing precision.
4. **Human expert review.** All LLM-flagged errors were independently reviewed by a domain expert; 7/7 were confirmed. Worked examples for several Pop A and Pop C cases were inspected end-to-end.

The 9.3-percentage-point gap between precision (≈98 %) and recall (≈88 %) reflects boundary cases that the conservative, rule-based approach could not handle without introducing new errors. We chose precision over recall.

## Honest limits

- **Some misclassifications remain.** Approximately one paragraph in eight still sits in a slightly imperfect section. Most are boundary cases where a single PDF-extracted paragraph genuinely contains content from two adjacent sections.
- **Population C (Committee / mass cases) is the hardest.** These cases lack reliable paragraph ordering, lowercase the operative section, and frequently compress substantive analysis into the `Facts` block. A `ⓘ` warning icon flags affected sections in the search UI.
- **Sub-paragraph splitting is out of scope.** Where a single physical paragraph spans two logical sections (e.g., end of Just Satisfaction concatenated with the start of the Operative Part), we keep it intact and assign the dominant label.

## Reproducibility & citation

All transformation scripts are versioned in the project repository under `scripts/`. Each script supports a default dry-run mode, an `--apply` flag, and writes a backup table before any change. The full per-pass change log, precision-audit reports, and per-sample LLM verdicts are maintained internally and available on request.

If you use this dataset in research, please cite:

> Szoszkiewicz, Ł. (2026). *ECHR Dashboard: tier-1 paragraph-level search across European Court of Human Rights case law.* Adam Mickiewicz University, Poznań.
> Source: <https://github.com/lszoszk/ECHR-Dashboard>

For methodology questions, validation reports, or access to internal documentation: **<l.szoszkiewicz@amu.edu.pl>**.
