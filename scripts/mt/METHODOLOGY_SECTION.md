<!-- The Methodology section on machine translations, held back until the translations are live.
     To publish: put it back into docs/methodology/README.md before "## Analytics & privacy", and restore
     the link in the "English texts only" bullet (see git history of that file). -->

<a id="machine-translation"></a>

## Machine translations of French-only judgments

HUDOC publishes about 9,300 judgments only in French. The Court has no duty to publish every Chamber or Committee judgment in both official languages, so for these there is no English text at all. To make them findable next to the English case-law, we translate them into English by machine.

> **These are not translations by the Court.** They are left out of every search unless you tick *English translations of French-only judgments* in the left pane, each one is labelled *Only in French on HUDOC · machine translation, unofficial*, and each links to the authentic French text on HUDOC. Quote the French original, never the translation.

### Which judgments

| Tier | Selection | Judgments | State |
| --- | --- | ---: | --- |
| 1 | French-only judgments cited by at least 5 judgments in the corpus | 503 | translated, checked and repaired |
| 2 | cited by 1 to 4 judgments | 1,892 | being translated |
| — | not cited by any judgment in the corpus | about 6,900 | not translated |

A judgment is selected only when its application number points to it unambiguously.

### How a judgment is translated

Each judgment is split into chunks of consecutive paragraphs, so that the paragraph numbers, sections and quotations of the French text are kept one to one. Every request carries the case title, the terms of a glossary built from the Court's own bilingual judgments (only pairs the Court translates the same way at least 9 times in 10, e.g. *requérant* → *applicant*, *dommage moral* → *non-pecuniary damage*) and examples from judgments the Court published in both languages. The instructions give the Court's English citation conventions (`c.` → `v.`, `(déc.)` → `(dec.)`, `série A` → `Series A`, from the Court's citation notes); no French citation form is left in the tier-1 texts.

| Step | Model / method | What it does | Tier 1 |
| --- | --- | --- | ---: |
| 1. Translate | Claude Haiku 5.5 (Anthropic Message Batches, no extended reasoning) | translates every chunk | 10,657 chunks, 99,034 paragraphs; 10,628 chunks answered |
| 2. Check by rule | deterministic checks | numbers, dates, application numbers, § references, citation format, French left untranslated, length out of proportion, missing paragraphs | every paragraph |
| 3. Review | Jev (TypeSafe System One), a calibrated yes/no judge | asks of each paragraph whether the English is a complete and faithful translation of the French, and returns a probability | every paragraph |
| 4. Repair | Claude Sonnet 5.5 | translates again, paragraph by paragraph, every paragraph scored below 0.8 or failing a check | 12,902 paragraphs (13 %) |
| 5. Re-check | Jev and the rules again | paragraphs still in doubt are listed for human review | 361 paragraphs (0.36 %) |

The threshold of step 4 is deliberately cautious: in a calibration test, at 0.8 Jev caught all 43 errors we had planted in correct translations, while it also doubts about one in ten of the Court's own official translations. More paragraphs are therefore sent to repair than are actually wrong. For tier 2 the threshold is 0.7.

Of the 361 paragraphs listed for review, 197 scored below 0.3 after the repair, 132 failed a rule check and 32 have no translation; those 32 are shown in French.

### How good it is

On a judgment the Court published in both languages and that was kept out of the examples (*Aksu v. Turkey* [GC]), the machine translation scored chrF 85.2 (Haiku) and 86.0 (Sonnet) against the Court's official English, with no lost citations, dates or numbers and every glossary term used. chrF measures overlap with the official wording on a 0–100 scale; at this level the two texts mostly differ in wording, not in content. This is one test, not a guarantee for every paragraph.

### Limits

- Errors remain possible, especially in legal terms of art, long quotations and tables. The human review of the listed paragraphs is not finished.
- The translations are not in Semantic Search and are not counted in the citation graph (they neither cite nor are cited).
- Corrections are welcome: <l.szoszkiewicz@amu.edu.pl>.

