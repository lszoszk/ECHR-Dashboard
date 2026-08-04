# Methodology

> A brief overview of how this dataset was built and validated. Detailed specifications, pass-by-pass change logs, and per-sample audit verdicts are available **on request**.

## What's in the dataset

- **20,010 court rulings** from the European Court of Human Rights (14 November 1960 – **23 July 2026**)
- **3.30 million segmented text rows** — body paragraphs, headings, quoted passages and operative formulae — of which **1.25 million carry the Court's own paragraph numbering** (`¶ 1`, `¶ 2`…)

> **Cut-off.** The corpus ends at the newest judgment listed above, not at
> today's date. It is topped up by a monthly ingest, and the Court publishes
> faster than HUDOC renders the source documents those passes read — so the
> last few weeks before the cut-off are thinner than they will eventually be,
> and anything decided after it is absent entirely. Charts with a time axis
> therefore show a short final year; that is the harvest boundary, not a drop
> in the Court's output. The live corpus size is shown in the Search header,
> and the Statistics page prints the build date of its own snapshot.
- **Source:** the official HUDOC portal (cases harvested by the Court itself)
- **Coverage:** all 47 Council of Europe contracting parties plus their successor states

### Scope: judgments, in English

Two deliberate boundaries a HUDOC user should know about:

- **Judgments only.** The corpus covers the Court's judgments (including ~6,300 Committee judgments, which HUDOC's default search omits). HUDOC's other collections — admissibility **Decisions**, Communicated Cases, Legal Summaries, Advisory Opinions, Commission decisions — are not included. A landmark *decision* (e.g. *Banković*) will therefore return no results here; consult HUDOC for those collections.
- **English texts only.** Judgments delivered only in French — a substantial share of Chamber and Committee output — are not yet ingested. On the Semantic Search page, "describe your case in any language" refers to the *query* (the embedding model is multilingual); the retrieved paragraphs are always the English texts.

The Statistics page is a static snapshot (its build date is printed under its title) and can lag the live counts shown in the Search header.

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

### Splitting Procedure from Circumstances (P63–P64, 31 July 2026)

Until July 2026 everything between the start of a judgment and its legal reasoning sat in one undifferentiated `Facts` bucket — 718,093 rows across 19,808 cases — so the filter could not distinguish the Court's short administrative opening from the substantive account of what happened. These are different things to a researcher: one records who lodged what and when, the other is the evidence.

The split does not use a classifier. HUDOC judgments mark the transition with the Court's own headings (`THE FACTS`, `AS TO THE FACTS`, `I. THE CIRCUMSTANCES OF THE CASE`, and for post-2021 Committee judgments `SUBJECT MATTER OF THE CASE`), and because these sections are contiguous blocks the unit of work is one boundary per case — 19,808 decisions, not 718,093. A marker is present in **97.2 % of cases (99.0 % of rows)**; everything before it is `Procedure`, everything from it onward `Circumstances` (or `Subject Matter`).

A follow-up pass cleared the remaining 564 cases, which turned out to be four identifiable templates rather than hard cases: hyphenated `SUBJECT-MATTER OF THE CASE`; `PROCEDURE AND FACTS` (the Court's merged Committee block, not a procedure heading); Just Satisfaction, Revision and Interpretation judgments, which have no circumstances section by design; and French-language judgments (`PROCÉDURE` / `EN FAIT` / `OBJET DE L'AFFAIRE`).

Resulting distribution: **Circumstances 611,473 · Procedure 99,887 · Subject Matter 13,448**. Sixteen cases (1,254 rows) have no usable heading and keep an unsegmented `Facts` label.

Two labelling conventions follow from deferring to the Court's own structure:

- Since roughly 2019 the Court prints the applicant's identity and legal representation **after** the `THE FACTS` heading. Those paragraphs are therefore `Circumstances`, though a human labeller might call them procedure. This affects **166 cases**.
- Bare section headings inherit the label of the block they introduce, as in the earlier audits.

## How we validated it

Three independent validation mechanisms support the published labels:

1. **Automated structural analysis** of 10 random cases per year (1975 – 2025) used to map the population taxonomy and characterise drafting drift over time.
2. **LLM-as-judge precision audits.** Stratified random samples (490 paragraphs across the early passes; 50 each for later passes) were independently reviewed by Anthropic's Sonnet 4.6 model, with full surrounding context. **Aggregate precision: 97.6 %** [95 % Wilson CI: 96.2 % – 98.6 %].
3. **End-to-end recall audit.** A separate 300-sample stratified draw of *current* labels (not just relabelled paragraphs) measured **88.3 % overall correctness** [95 % Wilson CI: 84.2 % – 91.5 %], characterising the residual error rate the rule-based pipeline could not reach without sacrificing precision.
4. **Human expert review.** All LLM-flagged errors were independently reviewed by a domain expert; 7/7 were confirmed. Worked examples for several Pop A and Pop C cases were inspected end-to-end.

The 9.3-percentage-point gap between precision (≈98 %) and recall (≈88 %) reflects boundary cases that the conservative, rule-based approach could not handle without introducing new errors. We chose precision over recall.

### Validating the Procedure / Circumstances boundary (P65, 31 July 2026)

The boundary split above needed a different test from the precision audits. Because every paragraph label is derived from one per-case boundary, scoring 725,000 paragraphs would present roughly 19,800 independent decisions as 725,000, and would flatter the result: a case with a 400-paragraph narrative and a 4-paragraph procedure block scores 99 % simply by getting the tail right. The unit of accuracy is therefore **the case boundary**.

Nor can the boundary be checked against the Court's headings — those are what produced it, so that test is circular. The independent signal is whether the resulting blocks *contain* what they claim, measured against the Court's own stereotyped procedural vocabulary.

On a seeded, stratified sample of **127 cases**: 112 passed automatically, 6 raised the representation-placement convention above, and 9 were flagged and then read individually against the source text. Of those 9, seven were correct procedure blocks that the keyword test scored too harshly, and two were genuine candidates — pre-1995 Article 50 just-satisfaction judgments, the older form of a template family the July passes already handle in its modern version. **Confirmed boundary errors: 0. Effective accuracy: 98–100 %.** A corpus-wide scan for procedure blocks absorbed into the narrative found **none** in 19,808 cases.

One finding is worth recording for anyone measuring this corpus: the first version of that vocabulary reported 78.7 % and was measuring itself. It encoded only the post-Protocol-11 formula (*"the case originated in an application… lodged under Article 34"*), so pre-1998 judgments — whose procedure blocks read *"The case was referred to the Court by the European Commission of Human Rights… The Chamber to be constituted included ex officio Mr B. Walsh, the elected judge of Irish nationality"* — scored zero and were reported as segmentation failures. Any keyword metric applied to six decades of Strasbourg drafting has to know both vocabularies.

### Boilerplate relabelling (P60, July 2026)

A user-experience audit found ~90,000 unnumbered rows (procedural formulae such
as "Having deliberated in private on …", court-composition and appearance
lines, signature blocks, elision rows) stored with the body-paragraph role, so
they could surface as search hits despite having no citable § number. They were
relabelled (`metadata` / `signature` / `heading` / `quote`) using curated
template rules plus an LLM cross-check on every remaining distinct text;
numbered paragraphs were never touched, and search now excludes these roles by
default. A full pre-change snapshot and a row-level undo table are retained.

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

### Why low-importance cases look metadata-poor everywhere

HUDOC itself analyses cases unevenly. Per the HUDOC FAQ (§ 12, "Which texts are analysed?"), only cases of importance *Key cases*, *1* and *2* receive a full analysis; from 2007 onwards, importance-3 judgments get no **Strasbourg Case-Law**, **Rules of Court**, **Applicability**, **Separate Opinion**, **Domestic Law** or **International Law** fields. So sparse HUDOC-sourced metadata on a level-3 case reflects the Registry's triage, not a gap in this dataset.

Because this tool parses the **full judgment text** rather than relying on those curated fields, two things work here that HUDOC's own filters cannot do for level-3 cases: the *Separate opinion* filter (opinions are detected in the text) and the citation graph above (references are extracted from the text).

## Analytics & privacy

This site uses Google Analytics 4 only to see which views are used, and only
after you accept the banner. Consent Mode v2 defaults to denied — nothing is
sent to Google, not even a request for the analytics library, before you
choose. A Do Not Track or Global Privacy Control setting skips analytics
entirely and no banner is shown.

We record **view names only** (Search, Statistics, Methodology, About, Semantic
Search). We never send your search queries, the filters or countries you
select, or the judgments you open. The page address is stripped to its path
before being sent, so a query cannot leak through the URL or through the
referrer on the next page. Ad personalisation and Google signals are disabled.

Your choice lives in this browser's local storage
(`echr-analytics-consent`) and can be changed at any time from the
[Privacy & analytics](../methodology.html#privacy-analytics) box on the
Methodology page.

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
