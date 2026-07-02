# Methodology

> A brief overview of how this dataset was built and validated. Detailed specifications, pass-by-pass change logs, and per-sample audit verdicts are available **on request**.

## What's in the dataset

- **19,720 court rulings** from the European Court of Human Rights (1960 – present)
- **2.19 million paragraphs** segmented from judgment, decision, and admissibility-decision texts
- **Source:** the official HUDOC portal (cases harvested by the Court itself)
- **Coverage:** all 47 Council of Europe contracting parties plus their successor states

### Press releases excluded

The HUDOC portal indexes ~4,949 press releases alongside the actual court rulings — short journalistic summaries the Registry issues for chamber judgments. These were excluded from the dashboard corpus on 2026-05-09 because:

- They are not court rulings; they are summaries of rulings already in the corpus.
- They have no numbered paragraphs (`¶ 1`, `¶ 2`…) — segmentation produces meaningless results.
- They double-count cases in paragraph-level search (the same finding appears once in the press release and once in the underlying judgment).

Backup tables (`_press_releases_backup_*`) on the source database preserve the removed rows so the decision is fully reversible.

## Why labelling is non-trivial

ECHR judgments do not follow a single template. The Court's drafting style has evolved across six decades, and three structurally distinct case populations coexist in the corpus:

| Population | Years | Cases | Typical structure |
|---|---|---:|---|
| **Classical** (pre-1998) | 1960 – ~1998 | ~4,500 | Header → Procedure → Facts → As to the Law → Operative Part → Separate Opinions |
| **Modern Chamber** | 1999 – present | ~9,000 | Introduction → Facts → Legal Framework → Merits → Just Satisfaction → Operative Part |
| **Committee / mass cases** | 2009 – present | ~6,200 | Introduction → Relevant legal framework → Facts → Merits → Operative part *(lowercase, often compressed)* |

The same content (e.g., a "violation finding") can appear under quite different section headings depending on the population, the rapporteur's drafting habits, or PDF-extraction quirks. Naïve segmentation produces noisy labels — paragraphs of substantive analysis end up in `Facts`, just-satisfaction reasoning ends up in `Merits`, dispositif clauses bleed into `Just Satisfaction`, and so on.

## What we did

A series of **fifteen rule-based cleaning passes** were applied on top of the initial segmentation. Earlier passes (P1–P33) target specific misclassification patterns: "Article 41 reasoning blocks misfiled into Merits", "dissenting opinions bleeding into the Operative Part", "numbered Holds clauses stranded in Just Satisfaction", and similar. The most recent pass (**P34**, 2026-05-08) re-ingests every case directly from its HUDOC source DOCX as the single source of truth, replacing legacy PDF-segmenter fragments with one canonical paragraph per `<w:p>` element. Together these passes relabelled or rebuilt over **2 million paragraph rows** — substantially the entire corpus.

Two new section labels (`Commission Proceedings`, `Final Submissions`) were added to capture pre-Protocol-11 procedural sub-sections that the Court no longer uses. Two structural columns (`hudoc_para_no`, `numbering_block`) were derived to support cross-reference against source PDFs.

Every pass keeps a per-row backup table in the database. Rollback is a single SQL statement.

## How we validated it

Three independent validation mechanisms support the published labels:

1. **Automated structural analysis** of 10 random cases per year (1975 – 2025) used to map the population taxonomy and characterise drafting drift over time.
2. **LLM-as-judge precision audits.** Stratified random samples (490 paragraphs across the early passes; 50 each for later passes) were independently reviewed by Anthropic's Sonnet 4.6 model, with full surrounding context. **Aggregate precision: 97.6 %** [95 % Wilson CI: 96.2 % – 98.6 %].
3. **End-to-end recall audit.** A separate 300-sample stratified draw of *current* labels (not just relabelled paragraphs) measured **88.3 % overall correctness** [95 % Wilson CI: 84.2 % – 91.5 %], characterising the residual error rate the rule-based pipeline could not reach without sacrificing precision.
4. **Human expert review.** All LLM-flagged errors were independently reviewed by a domain expert; 7/7 were confirmed. Worked examples for several Pop A and Pop C cases were inspected end-to-end.

The 9.3-percentage-point gap between precision (≈98 %) and recall (≈88 %) reflects boundary cases that the conservative, rule-based approach could not handle without introducing new errors. We chose precision over recall.

## Citation graph (Cites / Cited by)

Each result card carries two influence metrics — **Cites** (judgments this ruling refers to) and **Cited by** (later judgments that refer back to it). They are drawn from a citation graph of **199,607 paragraph-level references** linking **18,236 cases**.

The graph is built by scanning every paragraph for ECHR application numbers — the `NNNNN/YY` identifiers the Court uses when citing a precedent (e.g. *Kudła v. Poland*, no. 30210/96). Each number is resolved against the case index; a match becomes a citation edge. Extraction is deliberately conservative — a number is counted only when it resolves to a case actually in the corpus, which discards date-like false positives.

> **Example.** *Kharchenko v. Ukraine* cites 34 earlier judgments and is itself cited by 292 later ones — shown as `Cites 34 · Cited by 292` on its card.

### Validated against HUDOC's curated list

The Court's documentalists maintain a "Strasbourg Case-Law" field — a hand-picked shortlist of the key precedents in each judgment. Comparing our extractor against this curated ground truth on a 500-case sample:

- **Recall: 98.7 %** — of the curated citations whose target is in the corpus, the extractor independently found 98.7 % (stable across the 2000s, 2010s and 2020s).
- The extractor surfaces ~1.3× *more* citations than the curated list, because that list is a selective shortlist of leading precedents whereas the extractor captures every reference in the judgment text.

The small recall gap is mostly judgments that cite a case by name only — with no application number in the text — and `[Extracts]` cases where HUDOC publishes excerpts only.

Citation coverage is necessarily partial: a case whose precedents fall outside the corpus shows fewer links than reality. A `—` (rather than `0`) marks cases with no recorded citations, so an absence of data is not mistaken for genuine legal isolation.

## Honest limits

- **Some misclassifications remain.** Approximately one paragraph in eight still sits in a slightly imperfect section. Most are boundary cases where a single PDF-extracted paragraph genuinely contains content from two adjacent sections.
- **Population C (Committee / mass cases) is the hardest.** These cases lack reliable paragraph ordering, lowercase the operative section, and frequently compress substantive analysis into the `Facts` block. A `ⓘ` warning icon flags affected sections in the search UI.
- **Sub-paragraph splitting is out of scope.** Where a single physical paragraph spans two logical sections (e.g., end of Just Satisfaction concatenated with the start of the Operative Part), we keep it intact and assign the dominant label.

## Reproducibility & citation

All transformation scripts are versioned in the project repository under `scripts/`. Each script supports a default dry-run mode, an `--apply` flag, and writes a backup table before any change. The full per-pass change log, precision-audit reports, and per-sample LLM verdicts are maintained internally and available on request.

If you use this dataset in research, please cite:

> Szoszkiewicz, Ł., & Marcisz, S. (2026). *ECHR Dashboard: tier-1 paragraph-level search across European Court of Human Rights case law.* Adam Mickiewicz University, Poznań.
> Source: <https://github.com/lszoszk/ECHR-Dashboard>

For methodology questions, validation reports, or access to internal documentation: **<l.szoszkiewicz@amu.edu.pl>**.
