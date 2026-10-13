# Methodology

> A brief overview of how this dataset was built and validated. Detailed specifications, pass-by-pass change logs, and per-sample audit verdicts are available **on request**.

## What's in the dataset

Figures of the live corpus on 13 October 2026:

- **20,060 judgments** of the European Court of Human Rights in English (14 November 1960 – **8 October 2026**), against **47 respondent States**, and **3,557 decisions** (1986–2026), a selection for now: about 12 % of HUDOC's 29,001 English decisions of the Court (see [Scope](#scope-judgments-in-english))
- **3.73 million segmented text rows** — body paragraphs, headings, quoted passages and operative formulae — of which **1.33 million carry the Court's own paragraph numbering** (`¶ 1`, `¶ 2`…); **1.23 million** of these are paragraphs of the judgments themselves, outside the operative part and the separate opinions, and 77,000 are paragraphs of the decisions (older decisions are not numbered)
- **2,460 judgments that HUDOC publishes only in French**, as unofficial English machine translations (390,000 rows, 174,000 numbered paragraphs), left out of every search unless switched on (see [Machine translations](#machine-translation))
- **9,284 judgments that HUDOC publishes only in French**, in their authentic French text (1 April 1999 – 8 October 2026; 1.1 million rows, 460,490 numbered paragraphs), searched when *Français* is chosen in Search (see [French originals](#french-originals))
- **286,825 citation links** between the judgments and decisions of the corpus, and **58,867** more from 8,356 French-only judgments to judgments of the corpus, which count in *Cited by* (see [Citation graph](#influence) below)
- **Source:** the official HUDOC portal (cases harvested by the Court itself)
- **Coverage:** all 47 Council of Europe contracting parties plus their successor states

<a id="data-currency"></a>

### How current the case-law is

The corpus is a copy of HUDOC taken on a given day, not a live feed. The Search page shows its date in the bar at the bottom, *Case-law to …*, read from the database each time the page opens; hover it for both dates below.

| | Date |
|---|---|
| Newest judgment in the corpus (the cut-off) | **8 October 2026** |
| Last check against HUDOC (metadata: importance, outcome, keywords, citations listed by HUDOC) | **9 October 2026** |
| Oldest judgment | 14 November 1960 |

- **Anything delivered after the cut-off is not here.** Check HUDOC for later judgments and decisions, and for corrections HUDOC made after the last check (a rectified text, a changed importance level).
- **Updates are run by hand**, not on a fixed schedule: each one fetches from HUDOC the judgments published since the cut-off, re-reads HUDOC's metadata, rebuilds the citation graph and moves both dates forward. The decisions, the French originals and the machine translations are added in separate batches (see their sections).
- **The last weeks before the cut-off are thinner** than they will be: the Court publishes a judgment on HUDOC before HUDOC renders the Word file this tool reads, so a judgment whose text was not yet there on the day of the update comes in with the next one. Charts with a time axis therefore end with a short year; that is the edge of the copy, not a drop in the Court's output.
- **Semantic Search** has its own index, a snapshot of 8 October 2026 that the updates do not extend automatically (see [How the tools use the data](#tools-data)), and the **Statistics** page prints the build date of its own.

<a id="scope-judgments-in-english"></a>

### Scope: judgments, in English and in French

Two deliberate boundaries a HUDOC user should know about:

- **Judgments, and a selection of decisions.** The corpus covers the Court's judgments (including ~6,500 Committee judgments, which HUDOC's default search omits) and 3,557 of its decisions, which appear when *Decisions* is ticked in Search. The decisions are a selection for now, about 12 % of the 29,001 decisions of the Court that HUDOC has in English: those the judgments of the corpus cite (as `(dec.)` references) and those HUDOC rates as key cases or importance level 1, among them the Grand Chamber decisions such as *Banković*. Most are on admissibility; some strike an application out. More will be added. The other collections — Communicated Cases, Legal Summaries, Advisory Opinions, Commission decisions — are not included; consult HUDOC for those.
- **English texts, and the French-only judgments in French.** About 9,300 judgments were delivered only in French — a substantial share of Chamber and Committee output. They are not in the English corpus; their authentic French texts can be searched by choosing *Français* (see [French originals](#french-originals)), and unofficial English machine translations of the 2,460 most-cited of them can be switched on in the English search (see [Machine translations of French-only judgments](#machine-translation)). On the Semantic Search page, "describe your case in any language" refers to the *query* (the embedding model is multilingual); the retrieved paragraphs are the English texts, and the French originals as well when *Also judgments only in French* is ticked.
- **The Court's texts, not translations.** HUDOC also publishes translations of judgments by governments and NGOs, each as a document of its own (titled *[… Translation]*). They are not in the corpus: on 12 October 2026, 13 translations into Ukrainian, Turkish, Armenian, Lithuanian and Czech that monthly updates had loaded were removed (the Court's own text of each is here) and three titles taken from a translation were corrected. The one exception is five English translations by the European Roma Rights Centre of judgments HUDOC has only in French — *Wallová and Walla v. the Czech Republic*, *Sampanis and Others v. Greece*, *Paraskeva Todorova v. Bulgaria*, *Sampani and Others v. Greece* and *Lavida and Others v. Greece* — which HUDOC itself lists as English. They are kept, as the only English text of these judgments, and labelled *Only in French on HUDOC · third-party translation, unofficial*, with a link to the French original: quote that.

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

### Text and numbering repairs (October 2026)

An audit against fresh copies of the HUDOC documents found the text itself essentially complete (0.4 % of rows differed, all hyphenation) and three systematic faults, each repaired by a guarded, reversible pass:

- **Hyphens.** The DOCX parser had dropped Word's non-breaking hyphens, so *non-pecuniary* read *nonpecuniary* and a phrase search for *"manifestly ill-founded"* missed 598 judgments. Restored in **46,013 rows** of 8,919 judgments.
- **Stray "Operative part" labels.** In 21 % of judgments a few rows before *FOR THESE REASONS* (headings, quotation fragments, award lists) were labelled as the operative part, and in older judgments the separate opinions after it were filed under the operative part or the appendix. **15,935 rows** relabelled.
- **Paragraph numbers.** Rows whose number sat behind a hidden marker or in Word's automatic numbering were stored unnumbered. Where HUDOC's own page confirms the number, **7,664 rows** received it.

Measured number by number with full text against HUDOC's pages on 300 judgments, **98.6 %** of paragraph numbers match after the repairs (98.4 % before). Verify a pinpoint on HUDOC before citing it.

<a id="influence"></a>

## Citation graph (Cites / Cited by)

Each result card has an **Influence** panel with two numbers for that judgment (how many of its paragraphs match your search is on the button that opens them):

- **Cites** — how many other judgments and decisions it refers to.
- **Cited by** — how many later judgments and decisions refer to it, including judgments that HUDOC publishes only in French.

Search covers the English judgments by default, and a click in the left pane extends it to the machine translations of French-only judgments. That switch changes only which judgments are searched: **Cites** and **Cited by** always count English, translated and untranslated French-only judgments together, so they are the same whether it is on or off.

**Cites** and **Cited by** count judgments, not mentions: a judgment that refers to the case in ten paragraphs counts once. This is the usual measure in citation studies of courts, and it is what the data supports: the Court gives a precedent's application number once and then refers back to it in short form ("*Kudła*, cited above, § 152"), which is not detected, so the number of paragraphs that mention a case is only a minimum. Where it is shown, it is given as "at least N paragraphs" and is not part of the influence figures.

The bars compare the two numbers of the same judgment: the largest fills the bar. Compare judgments by the numbers, not the bar lengths. A dash (—) means the citation graph has no data for that judgment, not that it has never been cited.

**Cites** and **Cited by** come from a citation graph rebuilt after every corpus update, from three sources.

| Source | What it finds | Share of links (October 2026) |
| --- | --- | ---: |
| Our text: application numbers | `no. 30210/96` resolved to the judgment that carries it | 81.5 % |
| Our text: name and date | references without a number, as pre-1999 judgments are cited | 16.5 % |
| HUDOC: Strasbourg case-law list | items of the list the Court's documentalists compile for each judgment that our text pass did not find | 1.2 % |
| HUDOC: extracted application numbers | numbers HUDOC extracted from the full document that do not occur in our text — mostly in footnotes, which our paragraph text does not include | 0.8 % |

The figures count distinct links between a judgment and a cited case (286,825 in the current graph, of which 27,117 come from decisions and 24,340 point to decisions); a link found by more than one source is counted under the first source in the table. The last two sources are taken from HUDOC's own "Case details" metadata and are marked as such in the data (`extraction_method` `hudoc_caselaw` / `hudoc_extracted`); they have no paragraph attached.

1. **Application numbers.** The `NNNNN/YY` identifier the Court uses when citing a precedent (e.g. *Kudła v. Poland*, no. 30210/96) is looked up in the case index; a number that does not resolve to a case in the corpus is ignored, which discards date-like false positives. When one number belongs to several documents of the same case (a Chamber and a Grand Chamber judgment, merits and just satisfaction, a revision), a date or an `ECHR 2005` year written next to the number decides, then the `[GC]` marker, then the principal judgment. A reference marked `(dec.)` counts only if that admissibility decision is itself in the corpus; it is never credited to a later judgment that happens to share the number.
2. **Name and date.** Judgments before about 1999 are cited without a number — *Handyside v. the United Kingdom, 7 December 1976, Series A no. 24*. Such a reference is accepted only if exactly one judgment in the corpus was delivered on that date, the applicant's name is contained in its title and the respondent State matches. A number written in the reference that belongs to a different application rejects the match, as does a reference to a request for revision (its date belongs to the judgment under revision). The translations HUDOC hosts into other languages (titles marked *[… translation]*) are never cited or citing; the five English translations by the European Roma Rights Centre, the only English text of their judgments, are cited and citing like any judgment. Our machine translations of French-only judgments can be cited like any judgment, by number or by name and date, but their own *Cites* come from HUDOC's metadata (see [Machine translations](#machine-translation)). A judgment cannot cite a later one.
3. **HUDOC metadata.** Each item of the Strasbourg case-law list is resolved with the same rules as the text. An extracted number is used only when it does not occur in our text: where it does, the text pass has already decided (for example, it dropped a `(dec.)` reference whose decision is not in the corpus). A case the judgment already cites is never added twice, and a judgment cannot cite a later one.

> **Example.** *Handyside v. the United Kingdom* (1976) is cited by about 250 later judgments. Counting application numbers alone found two of them, because nothing before 1999 was cited that way.

### Agreement with HUDOC

Measured on the October 2026 corpus at the level of cases (all documents sharing an application number count as one case):

- **The Court's curated list.** Of the 101,890 Strasbourg case-law items that resolve to a judgment in this corpus, our text pass finds **97.9 %** on its own (95 % for judgments before 2000, 99 % since 2020). The remaining items are added from the list itself (source 3).
- **HUDOC's automatic extraction.** HUDOC and our text pass agree on about 178,000 links. About 40,400 are found only by our text pass: almost all are name-and-date references to older judgments, which an extraction based on application numbers cannot see. About 5,700 are found only by HUDOC: after source 3 is added, 208 of them remain unlinked, 185 of which are `(dec.)` references to admissibility decisions that are not in the corpus and are left out on purpose.

### How the name-and-date matching was checked

A random sample of 300 name-and-date matches was judged blind by a second model, mixed with 60 pairs that were wrong on purpose. All 60 wrong pairs were rejected, and 297 of the 300 matches were correct; the three errors (a same-day namesake with initials only, and two references to revision requests) were closed by the rules above. This is a precision check on a sample, not a guarantee.

A reference that gives only a short name without a date (for example *Handyside, cited above* with no earlier full citation in the same judgment) is not counted from the text, so a figure can still be lower than the true number. Footnotes are not part of the searchable text; their references reach the graph only through HUDOC's extracted numbers.

Citation coverage is necessarily partial: a case whose precedents fall outside the corpus shows fewer links than reality. A `—` (rather than `0`) marks cases with no recorded citations, so an absence of data is not mistaken for genuine legal isolation.

### Why low-importance cases look metadata-poor everywhere

The importance level of every document is HUDOC's own (Key cases, 1, 2, 3), as its search shows it. Until 11 October 2026 the documents added by the monthly updates, the decisions and the French-only judgments sat one level too low (HUDOC's API codes the levels 1–4), and part of the corpus showed level 3 as *Unspecified*; all were set to HUDOC's levels that day.

HUDOC itself analyses cases unevenly. Per the HUDOC FAQ (§ 12, "Which texts are analysed?"), only cases of importance *Key cases*, *1* and *2* receive a full analysis; from 2007 onwards, importance-3 judgments get no **Strasbourg Case-Law**, **Rules of Court**, **Applicability**, **Separate Opinion**, **Domestic Law** or **International Law** fields. So sparse HUDOC-sourced metadata on a level-3 case reflects the Registry's triage, not a gap in this dataset.

Because this tool parses the **full judgment text** rather than relying on those curated fields, two things work here that HUDOC's own filters cannot do for level-3 cases: the *Separate opinion* filter (opinions are detected in the text) and the citation graph above (references are extracted from the text).

<a id="machine-translation"></a>

## Machine translations of French-only judgments

HUDOC publishes about 9,300 judgments only in French. The Court has no duty to publish every Chamber or Committee judgment in both official languages, so for these there is no English text at all. To make them findable next to the English case-law, we translate them into English by machine.

> **These are not translations by the Court.** They are left out of every search unless you tick *English translations of French-only judgments* in the left pane; each one is labelled *Only in French on HUDOC · machine translation, unofficial* and links to the authentic French text on HUDOC. Quote the French original, never the translation.

### Which judgments

| Tier | Selection | Judgments | State |
| --- | --- | ---: | --- |
| 1 | French-only judgments cited by at least 5 judgments in the corpus | 503 | translated, checked and repaired |
| 2 | cited by 1 to 4 judgments | 1,892 | translated, checked and repaired |
| 3 | cited, but sharing its application number with another document (a citation cannot tell which one is meant) | 65 | translated, checked and repaired |
| — | not cited by any judgment in the corpus | about 6,890 | not yet translated; to be added |

The translations of tiers 1 to 3 (2,460 judgments) are in the search since 10 October 2026; the rest will be added.

### How a judgment is translated

Each judgment is split into chunks of consecutive paragraphs, so that the paragraph numbers, sections and quotations of the French text are kept one to one. Every request carries the case title, the terms of a glossary built from the Court's own bilingual judgments (only pairs the Court translates the same way at least 9 times in 10, e.g. *requérant* → *applicant*, *dommage moral* → *non-pecuniary damage*) and examples from judgments the Court published in both languages. The instructions give the Court's English citation conventions (`c.` → `v.`, `(déc.)` → `(dec.)`, `série A` → `Series A`, from the Court's citation notes); no French citation form is left in the tier-1 texts.

| Step | Model / method | What it does | Tier 1 | Tier 2 |
| --- | --- | --- | ---: | ---: |
| 1. Translate | Claude Haiku 5.5 (Anthropic Message Batches, no extended reasoning) | translates every chunk | 10,657 chunks, 99,034 paragraphs; 10,628 chunks answered | 30,497 chunks, 283,799 paragraphs; 30,478 chunks answered |
| 2. Check by rule | deterministic checks | numbers, dates, application numbers, § references, citation format, French left untranslated, length out of proportion, missing paragraphs | every paragraph | every paragraph |
| 3. Review | Jev (TypeSafe System One), a calibrated yes/no judge | asks of each paragraph whether the English is a complete and faithful translation of the French, and returns a probability | every paragraph | every paragraph |
| 4. Repair | Claude Sonnet 5.5 | translates again, paragraph by paragraph, every paragraph scored below the threshold (0.8 for tier 1, 0.7 for tier 2) or failing a check | 12,902 paragraphs (13 %) | 13,863 paragraphs (4.9 %) |
| 5. Re-check | Jev and the rules again | paragraphs still in doubt are listed for human review | 361 paragraphs (0.36 %) | 862 paragraphs (0.30 %) |

What the repair changed, on tier 2: of the 13,592 paragraphs Sonnet answered, 30 % came back unchanged, 44 % with light edits and 25 % substantially reworded; in 6.3 % a number changed. The rewordings are mostly terminology and the official wording of quoted provisions; a few correct the facts.

The threshold of step 4 is deliberately cautious: in a calibration test, at 0.8 Jev caught all 43 errors we had planted in correct translations, while it also doubts about one in ten of the Court's own official translations. More paragraphs are therefore sent to repair than are actually wrong. For tier 2 the threshold is 0.7.

In tier 2, 30 paragraphs could not be translated (the model declined them) and are shown in French; in tier 3 (7,134 paragraphs, repaired at 0.7 like tier 2), 10 such paragraphs, and 29 are listed for human review.

Of the 361 paragraphs listed for review, 197 scored below 0.3 after the repair, 132 failed a rule check and 32 have no translation; those 32 are shown in French.

### How good it is

On a judgment the Court published in both languages and that was kept out of the examples (*Aksu v. Turkey* [GC]), the machine translation scored chrF 85.2 (Haiku) and 86.0 (Sonnet) against the Court's official English, with no lost citations, dates or numbers and every glossary term used. chrF measures overlap with the official wording on a 0–100 scale; at this level the two texts mostly differ in wording, not in content. This is one test, not a guarantee for every paragraph.

### Limits

- Errors remain possible, especially in legal terms of art, long quotations and tables. The human review of the listed paragraphs is not finished.
- The translations are not in Semantic Search. In the citation graph a translated judgment can be cited (a reference to it in an English judgment, by application number or by name and date, resolves to it, as to any judgment), but its own *Cites* come from HUDOC's metadata, never from the translated text, so that a translation slip cannot create a link. A French-only judgment that cites a case counts in that case's *Cited by* whether or not it has been translated; the cards show how many of the citing judgments exist only in French, and the Statistics page counts the same way.
- Corrections are welcome: <l.szoszkiewicz@amu.edu.pl>.

<a id="french-originals"></a>

## French originals of French-only judgments

HUDOC publishes about 9,300 judgments only in French. Their authentic texts form a second, separate
collection: choosing *Français* above the filters searches it instead of the English corpus. Queries
are written in French; accents are optional (*requerant* finds *requérant*), there is no stemming, so a
word ending is matched with `*` (*discrimin\**), and the other operators work as in English. The
filters (Article, State, years, formation, importance, outcome) use the same values as the English
corpus, taken from HUDOC's records of these judgments.

- **Which judgments:** the 9,284 judgments for which HUDOC holds a record in English but a text only in French
  (1999–2026), downloaded as Word files from HUDOC's French items and split into
  the Court's numbered paragraphs by the same parser as the English texts.
  On 12 October 2026, 50 judgments of 2026 that earlier monthly updates had loaded into the English corpus with their French text (HUDOC's French item) were moved out of it: 49 were already here under HUDOC's English record of the same judgment, and one was added.
- **Checks:** in 3,040 rows (0.3%) the text opens with a paragraph number the row does not carry, and
  in 418 places the numbering of a judgment goes backwards, about the same rates as in the English
  texts. These have not been corrected one by one: check the paragraph on HUDOC before citing it.
- **Citations (84,139 links):** *Cites* and *Cited by* of a French original are built from three sources,
  with the rules of the citation graph (a `(dec.)` or `(déc.)` reference is a decision, not the judgment;
  no judgment cites a later one; where several judgments share an application number, the date and
  the principal judgment decide):
  - what it cites: the judgments of the corpus in HUDOC's records of it, and the French-only judgments
    whose application numbers appear in its text;
  - who cites it: English judgments whose text names its application number, or whose numbers extracted
    by HUDOC include it (mostly references in footnotes), and French-only judgments that name it;
  - a judgment that has been machine-translated keeps the links of its translation, so the counts are
    the same in both languages.

  4,603 French originals are cited by at least one judgment; the most cited is *Gencel c. Turquie* (198
  citing judgments).
- **Translations:** where an English machine translation exists, the result carries an *EN translation*
  chip and the case details a switch, *Français · original | English · machine translation*, that
  shows the other text at the same paragraphs. The translation is marked as unofficial while it is
  shown. Cite produces the English form of the name (*Flamenbaum and Others v France*), as the Court
  does when it cites a French-only judgment in English; quote the French text.
- **In Semantic Search,** on request: ticking *Also judgments only in French* adds their 515,044 paragraphs to the
  English ones (an English query finds them too); see [How the tools use the data](#how-the-tools-use-the-data).

<a id="tools-data"></a>

## How the tools use the data

- **Search** is a full-text index (SQLite FTS5) over the rows described above, searched paragraph by paragraph (the French originals have an index of their own: accents ignored, no stemming); headings, signature blocks and procedural formulae without a § number are left out by default. Two boxes under *Also search in* add what is left out: *Cover page (judges) & headings* — the caption, the application number and the list of judges who sat, so a judge's name finds the judgments they sat in — and *Appendix*, the annexes (lists of applicants, compensation tables), where mass judgments name most applicants. Decisions are searched when *Decisions* is ticked (with judgments, or alone when the judgments box is unticked); a decision's card shows its outcome as read from its conclusion (inadmissible, partly inadmissible, admissible, struck out). A very common word (*detention*, *torture*) matches tens of thousands of paragraphs and can take a few seconds. A case name or application number typed as the query also finds the judgment itself, from the case titles and application numbers rather than the text, because the text index has no title for part of the corpus.
- **Semantic Search** (experimental) runs on its own index: 1,328,635 paragraphs of 20,150 English judgments and Grand Chamber decisions, as of 8 October 2026, embedded with Voyage voyage-4-large; the 100 closest are re-read against the query by Voyage rerank-3, and leading cases are nudged up. It is measured against the Court's 41 Case-Law Guides (the cited case is in the top 10 for about 89 % of items, the cited paragraph for about 75 %); the details are in the note on the Semantic Search page. Ticking *Also judgments only in French* (off by default) adds the 515,044 paragraphs of the 9,283 French originals, embedded with the same model: on 400 propositions of the French editions of the Guides whose cited judgment exists only in French, that judgment is in the top 10 for 78.5 % of items (first for 37 %), where without the option it cannot be found; the English results lose a little (cited case in the top 10: 88.0 % → 86.6 %), hence the default. Judgments added after its snapshot, the decisions other than the Grand Chamber ones, and the machine translations are not in it.
- **Check** finds the citations in a pasted text in the browser and sends only what identifies each cited judgment (application numbers, the name, a date, the `[GC]` and `(dec.)` markers); the text itself never reaches the server. Each citation is resolved with the rules of the citation graph — the application number, then the date, then `[GC]`, then the principal judgment of the case — and, failing that, against HUDOC's French-only judgments. A pinpointed § is checked to exist, and a quotation is compared word by word with the judgment.
- **AI assistant (MCP).** A hosted connector gives Claude or another assistant that takes MCP connectors seven tools over the same data (`echr_search`, `echr_get_case`, `echr_get_paragraphs`, `echr_cites`, `echr_cited_by`, `echr_facets`, `echr_stats`), so that it quotes paragraphs verbatim with their § numbers instead of from memory. Setup: [About](about.html#mcp).
- **Workspace** keeps saved paragraphs, notes and searches in your browser only; nothing is sent to the server.
- **Statistics** is a static snapshot of the corpus, rebuilt after an update; its build date is printed under its title.
- **Downloads** say what they are and where they come from. The Excel export of a search has a second
  sheet, *About this export*: the query, filters and collection, the number of judgments and
  paragraphs, the time and address of the export, the corpus snapshot, how to cite the tool and the
  judgments, the source and licences, and a disclaimer. CSV files end with the same rows, after an
  empty row; a chart exported as PNG carries its title and the source as it is cited.

## Analytics & privacy

Two counters, both limited to which pages are used:

- **GoatCounter**, an open-source counter that sets no cookies and stores
  nothing in your browser, counts each page opened: the page path and view name,
  the referring page cut to its address without query, your screen width and the
  browser named in your User-Agent. It runs without the banner because it keeps
  nothing on your device.
- **Google Analytics 4**, only after you accept the banner. Consent Mode v2
  defaults to denied — nothing is sent to Google, not even a request for the
  analytics library, before you choose.

A Do Not Track or Global Privacy Control setting turns both off and no banner is
shown.

We record **view names only** (Search, Semantic Search, Check, Workspace,
Statistics, Methodology, About). We never send your search queries, the filters or countries you
select, or the judgments you open. The page address is stripped to its path
before being sent, so a query cannot leak through the URL or through the
referrer on the next page. Ad personalisation and Google signals are disabled.

Your choice lives in this browser's local storage
(`echr-analytics-consent`) and can be changed at any time from the
[Privacy & analytics](methodology.html#privacy-analytics) box on the
Methodology page.

## Honest limits

- **Some misclassifications remain.** Approximately one paragraph in eight still sits in a slightly imperfect section. Most are boundary cases where a single PDF-extracted paragraph genuinely contains content from two adjacent sections.
- **Population C (Committee / mass cases) is the hardest.** These cases lack reliable paragraph ordering, lowercase the operative section, and frequently compress substantive analysis into the `Facts` block. A `ⓘ` warning icon flags affected sections in the search UI.
- **Sub-paragraph splitting is out of scope.** Where a single physical paragraph spans two logical sections (e.g., end of Just Satisfaction concatenated with the start of the Operative Part), we keep it intact and assign the dominant label.
- **Older templates.** Judgments before about 1995 use a different DOCX template; segmentation was verified on a stratified 50-case battery, but edge cases (e.g. pilot judgments with more than 12,000 applicant rows, such as *Burmych and Others v. Ukraine*) can show drift. In judgments before about 1999 some unnumbered text and separate opinions may sit under the wrong section or show no § number.
- **Citation counts are indicative.** A reference that gives only a short name without a date is not counted, and a reference to a decision counts only if that decision is in the corpus (a selection, see [Scope](#scope-judgments-in-english)), so a figure can be lower than the true one.
- **Keywords** from the HUDOC thesaurus are not available for every judgment, and there is no filter by judge: bench composition is not ingested.

## Reproducibility & citation

All transformation scripts are versioned in the project repository under `scripts/`. Each script supports a default dry-run mode, an `--apply` flag, and writes a backup table before any change. The full per-pass change log, precision-audit reports, and per-sample LLM verdicts are maintained internally and available on request.

If you use the tool or its data in research, please cite (copy buttons on the [About](about.html#cite) page):

> Szoszkiewicz, Ł., & Marcisz, S. (2026). *HUDOC Researcher — ECtHR case-law search and RAG* [Computer software]. Zenodo. <https://doi.org/10.5281/zenodo.21319703>

The paragraph-level corpus is published as a dataset on Hugging Face: <https://huggingface.co/datasets/lszoszk/ecthr-judgments>. Code: <https://github.com/lszoszk/ECHR-Dashboard>.

For methodology questions, validation reports, or access to internal documentation: **<l.szoszkiewicz@amu.edu.pl>**.
