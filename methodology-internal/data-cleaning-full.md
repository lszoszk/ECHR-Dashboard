# Data Cleaning Methodology — Full Specification

This document describes, in full operational detail, every transformation applied to the ECHR Dashboard corpus to bring section labels into a consistent, queryable state.

The corpus is stored as a SQLite database (`/data/echr_search.db` inside the production Docker container `echr-search-api`), with two main tables: `cases` (case-level metadata) and `paragraphs` (segmented paragraph text + section label + optional `para_idx` ordering key). FTS5 indexing on `paragraphs.text` powers full-text search.

## 1. Initial state

### 1.1 Raw corpus statistics

- **24,669 distinct cases**, range 1960-11-14 to 2026-04-09
- **2,001,447 paragraphs**, average 81 paragraphs/case (median ~50, P90 ~140)
- **51 distinct respondent states** including Russia (post-2022 expulsion), Türkiye (2022 rename from Turkey), and successor states
- **16 raw section labels** found in the database, of which 14 are user-relevant (excludes `Legal Context` with only 6 paragraphs, treated as alias of `Legal Framework`)
- **15 distinct `document_type` values** ranging from `Judgment (Merits and Just Satisfaction)` (47% of cases) through `Judgment (Committee)` (25%) to `Press Release - Chamber Judgments` (20%)

### 1.2 Section-label state before cleaning

```
Merits                            568,171 paras
Facts Proceedings                 437,934 paras
Facts                             245,953 paras   ← orphan label (not mapped in UI)
Introduction                      215,531 paras
Admissibility                     171,964 paras
Operative Part                     70,151 paras
Header                             69,202 paras
Operative part                     62,552 paras   ← orphan label, lowercase
Just Satisfaction                  37,328 paras
Facts Background                   36,463 paras
Separate Opinion                   29,205 paras
Legal Framework                    24,867 paras
Relevant legal framework           15,857 paras   ← orphan label
Appendix                           12,282 paras
Article 46                          3,981 paras
Legal Context                           6 paras
```

Three labels (`Facts`, `Operative part`, `Relevant legal framework`) — totaling **324,362 paragraphs in 16,070 cases** — were not mapped in the frontend `SECTION_DB_NAMES` table and were therefore invisible to the section filter.

## 2. Three structural populations

A diagnostic pass (`backend/analyze_sections.py`, 10 random cases per year 1975–2025) revealed that the corpus is structurally heterogeneous. Three distinct document formats coexist:

### 2.1 Population A — Classical (1960–~1998)

- ~4,500 cases
- Authored by the old Court (pre-Protocol-11) and the European Commission
- Section sequence: `Header → Introduction → Facts Background → Facts Proceedings → Merits → Operative Part → [Separate Opinion]`
- `Introduction` consistently opens with the `PROCEDURE` heading
- `Facts Background` is typically a single paragraph (`AS TO THE FACTS` heading)
- `Facts Proceedings` opens with `PROCEEDINGS BEFORE THE COMMISSION` (legacy of the Court/Commission split)
- `Merits` opens with `AS TO THE LAW` (pre-1998) or `THE LAW` (post-1998)
- `para_idx` is consistently populated and reflects document order
- Spot-check accuracy of section assignment in this population: **~100%**

### 2.2 Population B — Modern Chamber (1999–present)

- ~13,400 cases
- Authored by the new permanent Court (Sections, Grand Chamber)
- Section sequence: `Header → Introduction → Facts Background → Facts Proceedings → [Legal Framework] → Merits → [Admissibility] → [Just Satisfaction] → [Article 46] → Operative Part → [Separate Opinion] → [Appendix]`
- `Introduction` opens with `INTRODUCTION` heading (replacing `PROCEDURE`)
- `Facts Background` typically 3 paragraphs: `THE FACTS` → introductory sentence → `I. THE CIRCUMSTANCES OF THE CASE`
- `Facts Proceedings` contains the substantive facts followed by `II. RELEVANT DOMESTIC LAW AND PRACTICE` (later: extracted to `Legal Framework` by Pass 3)
- `Just Satisfaction` peaks at ~26% of cases in 2005 then declines as committee cases grow
- `para_idx` consistently populated
- Spot-check accuracy: **~98%** (the main systematic error was Article 41 reasoning misclassified as Merits — fixed by Pass 1)

### 2.3 Population C — Committee / new-segmenter (2009–present)

- 6,236 cases (~25% of corpus)
- Authored by Committees, used for repetitive cases and mass-applicant judgments
- Section sequence: `Introduction → [Relevant legal framework] → Facts → Merits → Operative part`
- Introduction often = applicant data table (column headers + per-applicant rows; in *Çetin and Others v. Türkiye* 309 paragraphs were applicant names)
- **`para_idx IS NULL`** for all paragraphs — no document ordering preserved
- `Operative part` is lowercase (semantic difference from Population A/B `Operative Part`)
- `Facts` mixes circumstances + domestic law + sometimes merits content (boundary-detection failure)
- 38% of corpus in this format (`harvest_headings.py` shows 9,382 cases without canonical headings)
- Spot-check accuracy: **~70%** (frequent misclassification fixed by Pass 4)

### 2.4 Section presence by year (% of cases with at least one paragraph in section)

```
year     Header  Intro   Facts   Facts   Legal   Adm     Merits  Just    Op.     Sep.   Appdx
                         Backgr  Proc    Frame                   Sat     Part    Op
1960:    100%   100%    100%      0%      0%     0%    100%      0%    100%    0%      0%
1975:    100%   100%    100%      0%      0%     0%    100%      0%    100%   100%     0%
1985:    100%   100%     91%     91%      0%     0%    100%      0%    100%    36%     0%
1995:    100%   100%     95%     95%      0%     0%    100%      0%    100%    52%     2%
2005:    100%    95%     94%     94%      0%    48%     95%     26%     95%    11%     1%
2010:     92%    72%     61%     61%      0%    58%     72%     17%     64%     7%     1%
2015:     84%    75%     56%     56%      0%    61%     75%     19%     59%    12%     2%
2020:     58%    67%     32%     32%     18%     7%     75%      3%     33%     8%     2%
2025:     42%    72%     24%     24%     23%     2%     69%      1%     25%     6%     7%
```

The drop in `Header`, `Facts Background`, and `Operative Part` after 2010 reflects the rise of Population C cases. The drop in `Just Satisfaction` from 26% (2005) to 1% (2025) was an artefact of mislabeling — corrected by Pass 1.

## 3. Cleaning Phase 1 (pre-Phase-2)

Before this work began, two consolidation rules had already been applied at the frontend filter layer (`SECTION_DB_NAMES` in `docs/assets/search-app.js`):

```javascript
const SECTION_DB_NAMES = {
  facts:           ["Facts Background", "Facts Proceedings"],
  legal_framework: ["Legal Framework", "Legal Context"],
  // ... others 1:1 ...
};
```

This merged the two-paragraph `Facts Background` (the bare `THE FACTS` heading) with the substantive `Facts Proceedings` under a single UI bucket "Facts of the case", and merged the legacy `Legal Context` (6 paragraphs total) into `Legal Framework`.

## 4. Phase 1.5 — Orphan-label recovery (frontend-only)

### 4.1 Problem

The diagnostic harvest script (`scripts/harvest_headings.py`) found three raw DB section labels that were not present in any frontend filter mapping:

| Label | Paragraphs | Cases | Origin |
|---|---|---|---|
| `Facts` | 245,953 | 5,650 | New segmenter (Population C) |
| `Operative part` | 62,552 | 6,232 | New segmenter (Population C, lowercase) |
| `Relevant legal framework` | 15,857 | 1,838 | New segmenter |

Because `SECTION_DB_NAMES` did not list these, the section filter checkboxes silently ignored them. A search for "torture" with the `Facts` filter checked would skip 5,650 cases worth of facts.

### 4.2 Fix

Frontend-only change in `docs/assets/search-app.js`:

```javascript
const SECTION_DB_NAMES = {
  introduction:     ["Introduction"],
  facts:            ["Facts Background", "Facts Proceedings", "Facts"],            // +Facts
  legal_framework:  ["Legal Framework", "Legal Context", "Relevant legal framework"], // +RLF
  admissibility:    ["Admissibility"],
  merits:           ["Merits"],
  just_satisfaction: ["Just Satisfaction"],
  article_46:       ["Article 46"],
  operative_part:   ["Operative Part", "Operative part"],                          // +lowercase
  separate_opinion: ["Separate Opinion"],
  appendix:         ["Appendix"],
};
```

Also added normalizer aliases in `normalizeSectionKey()`:

```javascript
"relevant legal framework": "legal_framework",
relevant_legal_framework:   "legal_framework",
```

### 4.3 Empirical impact

Before: a typical query (`"applicant" AND state:RU`, default filters) hit 13,073 cases / 254,189 paragraphs.
After: same query hits 18,721 cases / 383,685 paragraphs (**+5,648 cases, +51% more hits**).

Commit: [`aa8ab4c`](https://github.com/lszoszk/ECHR-Dashboard/commit/aa8ab4c) — "sections: recover ~325k paragraphs lost to label drift (Phase 1.5)"

## 5. Phase 2 — Database-side relabeling

Phase 2 modifies the `paragraphs.section` column directly in the SQLite database. Each pass has a dedicated `_pN_backup` table preserving original `(rowid, section)` tuples for rollback.

### 5.1 Pass 1 — Just Satisfaction recovery

#### Problem

Article 41 of the Convention regulates just satisfaction (compensation) awards. Court judgments structure this content under explicit `APPLICATION OF ARTICLE 41` headings followed by sub-sections (Damage / Costs and expenses / Default interest). In Population B cases, this content should be in the `Just Satisfaction` section, but the segmenter often left it inside `Merits`. In Population C cases, it landed in `Facts`.

The diagnostic harvest revealed:

```
"APPLICATION OF ARTICLE 41" (5,797 occurrences as standalone heading <80 chars):
  In Merits:                       8,393  (Population A/B)
  In Admissibility:                2,706
  In Facts:                        2,635  (Population C)
  In Operative part:                  13
  In Just Satisfaction:              214  (correctly labeled)
  ...
```

Only **214 of ~14,000** Article 41 heading paragraphs (~1.5%) were correctly labeled. The remainder, plus the substantive reasoning following each heading, needed to move.

#### Detection rules

A heading paragraph is a candidate if **all** conditions hold:

```sql
length(text) < 80
AND (UPPER(text) LIKE '%APPLICATION OF ARTICLE 41%'
  OR UPPER(text) LIKE '%APPLICATION OF ARTICLE 50%'
  OR UPPER(text) LIKE '%JUST SATISFACTION%')
AND section IN ('Merits', 'Admissibility', 'Facts',
                'Operative part', 'Operative Part',
                'Facts Proceedings', 'Relevant legal framework')
```

#### Block-detection algorithm (Pass B, for Population B cases with `para_idx`)

For each case where a heading was found, walk paragraphs in `para_idx` order. While inside an active Article-41 block:

- The paragraph belongs to the block if it remains in the same DB section as the trigger.
- The block ends when (a) the section column changes, OR (b) a different top-level heading fires (e.g. `FOR THESE REASONS`, `THE LAW`, `ALLEGED VIOLATION` with `length(text) < 100`).

This is implemented in `scripts/p1_relabel_js.py`. Population C (no `para_idx`) only relabels the heading paragraph itself in this pass — block continuation requires Pass 4.

#### Worked example: *Wainwright v. The United Kingdom* (case `001-76999`)

Before:
```
¶ 75 [Merits]      56. There has therefore been a violation of Article 13...
¶ 76 [Merits]      III. APPLICATION OF ARTICLE 41 OF THE CONVENTION
¶ 77 [Merits]      57. Article 41 of the Convention provides...
¶ 78 [Merits]      A. Damage
¶ 79 [Merits]      58. The applicants claimed compensation for non-pecuniary damage...
... (paragraphs 80-87) ...
¶ 88 [Operative Part]  FOR THESE REASONS, THE COURT UNANIMOUSLY
```

After Pass 1:
```
¶ 75 [Merits]              56. There has therefore been a violation of Article 13...
¶ 76 [Just Satisfaction]   III. APPLICATION OF ARTICLE 41 OF THE CONVENTION       ← moved
¶ 77 [Just Satisfaction]   57. Article 41 of the Convention provides...           ← moved
¶ 78 [Just Satisfaction]   A. Damage                                              ← moved
... (paragraphs 80-87, all moved to Just Satisfaction) ...
¶ 88 [Operative Part]      FOR THESE REASONS, THE COURT UNANIMOUSLY               ← unchanged
```

12 paragraphs precisely between the trigger heading (¶76) and the next section boundary (¶88).

#### Total impact

| Source section | Heading paragraphs | Content paragraphs (Pass B) | Total |
|---|---|---|---|
| Merits | ~9,000 | 66,448 | 75,138 |
| Admissibility | ~1,100 | 202 | 2,908 |
| Facts | ~2,635 (Pop C) | 0 | 2,659 |
| Operative part | 1,701 | 0 | 1,701 |
| Facts Proceedings | 405 | 328 | 405 |
| Relevant legal framework | 114 | 0 | 114 |
| Operative Part | 64 | 0 | 64 |
| **TOTAL** | | | **82,989** |

`Just Satisfaction` count: **37,328 → 120,317** paragraphs (3.2× larger).

Backup table: `_p1_backup` (82,989 rows).

Scripts:
- `scripts/p1_validate_js.py` — read-only enumeration with examples
- `scripts/p1_relabel_js.py` — `--apply` writes; default is dry-run

### 5.2 Pass 2 — Separate Opinion recovery

#### Problem

A small but persistent fraction of dissenting and concurring opinion paragraphs were classified as `Operative Part` rather than `Separate Opinion`. The harvest revealed:

```
"DISSENTING OPINION" (1,069 standalone matches):
  In Separate Opinion:    970  (correct)
  In Operative Part:       99  (wrong)

"PARTLY DISSENTING" (481 standalone matches):
  In Separate Opinion:    378  (correct)
  In Operative Part:      103  (wrong)

"CONCURRING OPINION" (552 standalone matches):
  In Separate Opinion:    538  (correct)
  In Operative Part:       14  (wrong)
```

#### Detection rule

```sql
length(text) < 120
AND section IN ('Operative Part', 'Operative part')
AND (UPPER(text) LIKE '%DISSENTING OPINION%'
  OR UPPER(text) LIKE '%CONCURRING OPINION%'
  OR UPPER(text) LIKE '%PARTLY DISSENTING%'
  OR UPPER(text) LIKE '%JOINT DISSENTING%'
  OR UPPER(text) LIKE '%SEPARATE OPINION OF%'
  OR UPPER(text) LIKE '%PARTLY CONCURRING%')
```

#### Block detection

Same as Pass 1 — heading paragraph + same-section follow-on until a different section appears or a stop heading (`FOR THESE REASONS`, `OPERATIVE PROVISIONS`, `DECLARES`, `HOLDS`, `DECIDES`, `THE LAW`, `ALLEGED VIOLATION`, `JUST SATISFACTION`, `APPLICATION OF ARTICLE`) takes over.

#### Worked example: *Murdalovy v. Russia* (case `001-202121`)

```
¶ 122 [Operative Part]  JOINT PARTLY DISSENTING OPINION OF JUDGES LEMMENS AND KELLER
¶ 123 [Operative Part]  1. We agree with the main conclusions adopted in this case...
¶ 124 [Operative Part]  2. We of course agree that under Article 13...
...
¶ 126 [Operative Part]  ...
¶ 127 [Appendix]        ANNEX A                                              ← block boundary
```

After Pass 2, paragraphs 122–126 all become `Separate Opinion`.

#### Total impact

- 166 heading paragraphs detected
- 153 cases affected
- 2,370 paragraphs relabeled (166 headings + 2,204 follow-on content)
- All from `Operative Part`/`Operative part`

`Separate Opinion` count: **29,205 → 31,575** paragraphs (+8.1%).

Backup table: `_p2_backup` (2,370 rows).

Scripts:
- `scripts/p2_relabel_opinions.py` — combined validate + relabel

### 5.3 Pass 3 — Legal Framework extraction

#### Problem

In Population B cases (1999–~2019), the `Facts Proceedings` section conventionally contains two distinct content types:

- `I. THE CIRCUMSTANCES OF THE CASE` — actual facts of the case (timeline, parties, decisions)
- `II. RELEVANT DOMESTIC LAW AND PRACTICE` — domestic statutes, codes, regulations

These are different content types from a legal-research perspective. Newer cases (post-~2010) extract the second part to a separate `Legal Framework` section. Older cases left them merged.

The harvest found 8,488 standalone "RELEVANT DOMESTIC LAW" headings inside `Facts Proceedings`, ranging from 1982 (peak 2008–2009) through 2020.

#### Detection rule

```sql
section = 'Facts Proceedings'
AND para_idx IS NOT NULL
AND length(text) < 120
AND (UPPER(text) LIKE '%RELEVANT DOMESTIC LAW%'
  OR UPPER(text) LIKE '%DOMESTIC LAW AND PRACTICE%'
  OR UPPER(text) LIKE '%DOMESTIC LAW AND REGULATION%'
  OR UPPER(text) LIKE '%RELEVANT NATIONAL LAW%'
  OR UPPER(text) LIKE '%DOMESTIC AND INTERNATIONAL LAW%'
  OR UPPER(text) LIKE '%RELEVANT DOMESTIC LEGISLATION%')
```

#### Stop-condition (word boundaries)

Block detection in this pass uses **strict word boundaries** to avoid false positives. The first dry-run version triggered on substring match for `THE LAW` and prematurely stopped at "the Laws and Customs of War" inside the *Kononov v. Latvia* domestic-law block. Fixed regex:

```python
STOP_RE = re.compile(
    r"(?<!\w)(THE LAW|AS TO THE LAW|ALLEGED VIOLATION|FOR THESE REASONS"
    r"|ADMISSIBILITY|JUST SATISFACTION|APPLICATION OF ARTICLE"
    r"|JOINDER OF THE APPLICATIONS)(?!\w)",
    re.IGNORECASE,
)
```

The `(?<!\w)` and `(?!\w)` lookbehinds/lookaheads ensure "the Law of Ukraine on Citizenship" doesn't trigger on `THE LAW`.

#### Worked example: *Liatukas v. Lithuania* (case `001-170452`)

```
Before:
¶ 28 [Facts Proceedings]  II. RELEVANT DOMESTIC LAW
¶ 29 [Facts Proceedings]  A. Inheritance
¶ 30 [Facts Proceedings]  20. Article 5.50 § 1 of the Civil Code provides...
¶ 31 [Facts Proceedings]  21. Article 5.50 § 2 of the Civil Code provides...
¶ 32 [Facts Proceedings]  22. Article 5.59 § 2 (1) of the Civil Code provides...
... (paragraphs 33–39) ...
¶ 40 [Merits]             THE LAW                                  ← block boundary

After:
¶ 28 [Legal Framework]    II. RELEVANT DOMESTIC LAW                ← moved
¶ 29 [Legal Framework]    A. Inheritance                            ← moved
¶ 30 [Legal Framework]    20. Article 5.50 § 1 of the Civil Code... ← moved
... (12 paragraphs total moved) ...
¶ 40 [Merits]             THE LAW                                  ← unchanged
```

#### Total impact

- 8,488 heading paragraphs detected
- 7,975 cases affected
- 83,377 paragraphs relabeled (median 7 per case, P90 22 per case)
- All from `Facts Proceedings`

`Legal Framework` count: **24,867 → 108,244** paragraphs (4.4× larger).

Backup table: `_p3_backup` (83,377 rows).

Scripts:
- `scripts/p3_validate_domestic_law.py` — read-only enumeration with year breakdown
- `scripts/p3_relabel_domestic_law.py` — `--apply` writes

### 5.4 Pass 4 — Population C segmentation

#### Problem

Population C (Committee/joined cases, 6,236 cases) lacks `para_idx` — paragraphs are stored in `rowid` order, but with `para_idx = NULL`. The original segmenter dumped content into 3–4 unordered buckets and frequently misclassified merits content as `Facts`. The diagnostic harvest revealed:

```
"ALLEGED VIOLATION" (in Population C, length < 120):
  In Merits:                   4,809  (correct)
  In Facts:                    4,108  (wrong — merits content stuck in facts)
  In Relevant legal framework:   157
  In Introduction:               108
  In Operative part:              33
  In Admissibility:               27

"JOINDER OF THE APPLICATIONS" (in Population C):
  In Merits:                   1,704  (correct)
  In Facts:                      229  (wrong)
  In Introduction:                10
  In Relevant legal framework:     5
```

#### Strategy

Without `para_idx`, fall back to `rowid` (insertion order = approximately document order). Walk each case in `rowid` order. When a paragraph in `Facts` contains a known boundary heading, the segmenter likely failed at that boundary — relabel the heading and follow-on same-section paragraphs.

#### Detection rules

```python
RULES = [
    (r"\bALLEGED VIOLATION\b",          "Facts",  "Merits"),
    (r"\bJOINDER OF THE APPLICATIONS\b","Facts",  "Merits"),
    (r"\bAPPLICATION OF ARTICLE 41\b",  "Facts",  "Just Satisfaction"),
    (r"\bAPPLICATION OF ARTICLE 41\b",  "Merits", "Just Satisfaction"),
]
```

The heading paragraph must be `length(text) < 120`. Block continues while the paragraph remains in the source section; the block ends when the section column changes or a different rule fires.

#### Conservative-block design (precision over recall)

A more aggressive design — keeping the active block alive across single-paragraph section interruptions (e.g. brief `Admissibility` insertions) — would have caught more correct relabels but risks moving genuine non-merits content. The chosen design errs on the conservative side: as soon as the section column changes, the block ends. Some merits paragraphs that the segmenter sandwiched after `Admissibility` content remain in `Facts` after this pass.

#### Worked example: *Popova and other "Privileged Pensioners" v. Russia* (case `001-100513`)

```
Before:
¶ rowid=N+0 [Introduction]  2. The applicants were represented by...
¶ rowid=N+1 [Facts]         4. The applicants are pensioners who live in the Moscow Region...
¶ rowid=N+2 [Facts]         5. In 2004–06 the courts held for the applicants...
¶ rowid=N+3 [Facts]         I. JOINDER OF THE APPLICATIONS 8. As applications are similar...   [glued to body — >120 chars, NOT triggered]
¶ rowid=N+4 [Facts]         II. ALLEGED VIOLATION OF ARTICLE 6 § 1 OF THE CONVENTION...        [triggers rule 0]
¶ rowid=N+5 [Facts]         9. The applicants complained under Article 6...
¶ rowid=N+6 [Admissibility] A. Admissibility 10. The Government argued...                       [block ends here]
¶ rowid=N+7 [Facts]         11. The applicants argued...                                        [NOT relabeled]
... etc

After Pass 4:
¶ rowid=N+4 [Merits]        II. ALLEGED VIOLATION OF ARTICLE 6 § 1...           ← relabeled
¶ rowid=N+5 [Merits]        9. The applicants complained...                     ← relabeled
¶ rowid=N+6 [Admissibility] A. Admissibility 10...                              ← block ends, unchanged
¶ rowid=N+7 [Facts]         11. The applicants argued...                        ← stays in Facts (known limitation)
```

This exposes the precision/recall tradeoff. A future Pass 5 could address the residual misclassifications either by relaxing the heading-length constraint or by allowing block continuation across single-paragraph interruptions.

#### Total impact

- 3,479 boundary headings triggered (3,250 ALLEGED VIOLATION + 229 JOINDER + 0 Article 41 in Merits + 0 FOR THESE REASONS)
- 56,241 paragraphs relabeled
  - 54,237 Facts → Merits
  - 2,004 Facts → Just Satisfaction

`Merits`: 18,976 → 18,993 cases.
`Just Satisfaction`: 11,995 → 12,090 cases (+95 cases now have a populated Just Satisfaction section).

Backup table: `_p4_backup` (56,241 rows).

Scripts:
- `scripts/p4_validate_population_c.py` — read-only diagnostics with sample cases
- `scripts/p4_relabel_population_c.py` — `--apply` writes

## 6. Frontend changes

The database changes are paired with frontend UX improvements. None of these change semantics — they make the cleaned data more discoverable.

### 6.1 Document-type chips

A `Committee` or `Grand Chamber` chip is rendered in the case-card header for cases whose `document_type` (or `originating_body`) signals committee or grand chamber composition. Color codes: teal (committee), amber (grand chamber).

### 6.2 Section hint icons (ⓘ)

Two filter checkboxes show an ⓘ icon with hover tooltip:

- **Introduction**: "In Committee and joined cases, this section may contain applicant name lists rather than procedural history"
- **Facts of the case**: "In Committee cases, this section may also contain legal analysis (ALLEGED VIOLATION headings)"

These warn researchers that the section content is not uniform across populations.

### 6.3 Granular doc-type filter

Replaced the single "Judgments" checkbox with four:

- **Chamber** — `document_type NOT LIKE '%Press Release%' AND NOT LIKE '%Committee%' AND originating_body NOT LIKE '%Grand Chamber%'`
- **Grand Chamber** — `originating_body LIKE '%Grand Chamber%'`
- **Committee** — `document_type LIKE '%Committee%'`
- **Press Releases** — `document_type LIKE '%Press Release%'`

### 6.4 Case counts beside every filter checkbox

Each filter option (sections, articles, countries, bodies, importance, doc types) shows `(N)` — number of distinct cases that match. Counts come from `/api/facets` and use **max-per-bucket** (not sum) for normalized section buckets to avoid double-counting cases that have multiple raw labels in the same bucket.

### 6.5 Bug fix: filter listener was dead in server mode

The `el.filtersPanel.addEventListener("change", ...)` callback had a `if (!state.loaded) return` guard. `state.loaded` is set inside the local-mode `applyDataset()` function which is never called when the server is reachable. Result: every filter checkbox change was silently ignored in production for an unknown duration. Fixed: the guard now passes when EITHER `state.loaded` OR `serverSearch.available` is true.

## 7. Validation

### 7.1 Targeted query checks

| Query | Filter | Expected behavior | Result |
|---|---|---|---|
| `"just satisfaction" pecuniary` | `Just Satisfaction` | Many more hits than pre-Phase-2 | 1,642 cases / 2,073 hits |
| `"Code of Criminal Procedure"` | `Legal Framework` | More hits than `Facts Proceedings` | 2,354 vs 2,019 cases |
| `"I respectfully dissent"` | `Separate Opinion` | All hits in Separate Opinion, none in Operative Part | 20 vs 0 |
| `"ALLEGED VIOLATION"` | `Merits` | Big number, dominant section | 16,436 cases / 40,491 hits |

### 7.2 Spot-checks

Three case-level spot-checks (*Wainwright*, *Liatukas*, *Popova*) verified that boundary detection moved exactly the right paragraphs in P1, P3, and P4 respectively.

### 7.3 Backup integrity

Each backup table preserves `(rowid, original_section)` for every relabeled paragraph. Rollback is one query per pass:

```sql
UPDATE paragraphs
SET section = (SELECT section FROM _pN_backup b WHERE b.rowid = paragraphs.rowid)
WHERE rowid IN (SELECT rowid FROM _pN_backup);
```

Backup row counts:
- `_p1_backup`: 82,989
- `_p2_backup`: 2,370
- `_p3_backup`: 83,377
- `_p4_backup`: 56,241

## 8. Final state

### 8.1 Section paragraph totals (post-cleaning)

```
Merits                       547,270 paras  18,993 cases
Facts Proceedings            354,152 paras  12,987 cases
Introduction                 215,531 paras  19,080 cases
Facts                        187,053 paras   5,649 cases
Admissibility                169,056 paras   9,029 cases
Just Satisfaction            122,321 paras  12,090 cases   ← P1+P4: 37,328 → 122,321
Legal Framework              108,244 paras   9,501 cases   ← P3:    24,867 → 108,244
Header                        69,202 paras  18,429 cases
Operative Part                67,717 paras  13,270 cases   ← P2:    -2,434
Operative part                60,851 paras   6,232 cases
Facts Background              36,463 paras  13,095 cases
Separate Opinion              31,575 paras   2,635 cases   ← P2:    29,205 → 31,575
Relevant legal framework      15,743 paras   1,838 cases
Appendix                      12,282 paras     546 cases
Article 46                     3,981 paras     374 cases
Legal Context                      6 paras       2 cases

TOTAL                       2,001,447 paras  24,669 cases
```

### 8.2 Net redistribution

| Section | Before | After | Δ |
|---|---|---|---|
| Just Satisfaction | 37,328 | 122,321 | **+84,993** |
| Legal Framework | 24,867 | 108,244 | **+83,377** |
| Separate Opinion | 29,205 | 31,575 | **+2,370** |
| Merits | 568,171 | 547,270 | −20,901 (≈ -P1 Merits + P4 in) |
| Facts Proceedings | 437,934 | 354,152 | −83,782 |
| Facts | 245,953 | 187,053 | −58,900 |
| Admissibility | 171,964 | 169,056 | −2,908 |
| Operative Part | 70,151 | 67,717 | −2,434 |
| Operative part | 62,552 | 60,851 | −1,701 |
| Relevant legal framework | 15,857 | 15,743 | −114 |

(All movements zero-sum across the 2,001,447 total paragraphs.)

## 9. Known limitations

1. **Glued headings in Population C**: ~3,000 cases have "ALLEGED VIOLATION" merged with body text (>120 characters) and were not caught by Pass 4. A more relaxed Pass 5 (e.g. detection at the first 80 characters of any paragraph) is feasible but increases false-positive risk.

2. **Sandwiched merits content**: In Population C cases where `Admissibility` paragraphs interrupt the merits flow (typical for joined-applicant cases), Pass 4's conservative block ends early. Subsequent merits paragraphs labeled `Facts` are not recovered.

3. **`Introduction` as applicant table**: In mass-applicant Russia/Ukraine cases, `Introduction` may contain 91–309 paragraphs of column headers and applicant data. The ⓘ hint icon warns researchers; no automated relabeling is applied because the column-header text is not unambiguously identifiable as procedural-history vs tabular-data without per-case heuristics.

4. **`Legal Context` legacy label**: 6 paragraphs in 2 cases. Treated as alias of `Legal Framework` at the frontend level (mapped via `SECTION_DB_NAMES`). Not relabeled in DB to preserve auditability.

5. **Pre-Phase-1 changes not reversible**: The original segmenter's choices for paragraph boundaries (which fragments belong to which paragraph) are inherited and cannot be re-segmented without reprocessing the source HUDOC HTML.

## 10. Reproducibility

- **All scripts**: [`scripts/`](../../scripts/) directory; each is single-file Python with a docstring.
- **Inputs**: production SQLite DB (`/data/echr_search.db` inside `echr-search-api` container).
- **Read-only validators** are safe to run repeatedly: `harvest_headings.py`, `analyze_sections.py`, `probe_section_labels.py`, `pN_validate_*.py`.
- **Mutation scripts** require `--apply` flag to write; default mode is dry-run with statistics output.
- **Backups** are created automatically inside the same database before any UPDATE.

Each pass took 1–10 minutes to dry-run and another 1–3 minutes to apply. The full cleaning pipeline can be re-executed from a fresh DB in approximately 30 minutes.

## 11. Critical caveat: `para_idx` is an internal counter, not a HUDOC paragraph number

Discovered during expert manual review (2026-04-28).

**The `para_idx` column in our `paragraphs` table is a sequential row counter assigned during PDF segmentation, NOT the canonical paragraph number printed in the HUDOC source document.** They sometimes coincide for early classical-format judgments, but in general they diverge:

- HUDOC numbering starts at "1" for the first PROCEDURE paragraph and skips section headings ("PROCEDURE", "AS TO THE FACTS", "I. ALLEGED VIOLATION OF ARTICLE 6", etc.) which do not get a number.
- Our `para_idx` starts at 0 for the case-name header and increments for every paragraph including section headings and structural fragments.
- In separate-opinion blocks, HUDOC restarts numbering at "1" within each opinion. Our `para_idx` continues monotonically.
- In Operative Part dispositions, HUDOC uses "1.", "2.", "3." for each numbered ruling; our `para_idx` continues from the merits.

**Consequence for methodology examples:** Sections 5.1–5.4 above cite paragraphs as "¶76" or "¶28" — these are our internal `para_idx` values, not the numbers a reader would find by searching HUDOC for "paragraph 76" of the case. For example, in *Wainwright v. United Kingdom* (001-76999), our `¶76` contains the heading text "III. APPLICATION OF ARTICLE 41 OF THE CONVENTION" — which in HUDOC has no paragraph number; the surrounding numbered HUDOC paragraphs are 56 (our `¶75`) and 57 (our `¶77`).

**For verifiability, examples cite paragraphs by their text content (first 80 characters quoted), not by para_idx alone.** Anyone re-checking against HUDOC should search for the quoted text, not the index number.

**Future fix (P10 — planned):** Extract the HUDOC paragraph number from the leading "N. " pattern in each paragraph text where present, and store as a separate `hudoc_para_no` column. This will allow the dashboard to display HUDOC-aligned numbering alongside our internal `para_idx`, restoring full verifiability against the source corpus.

## 12. Citation

> Szoszkiewicz, Ł. (2026). *ECHR Dashboard: tier-1 paragraph-level search across European Court of Human Rights case law.* Adam Mickiewicz University, Poznań.
> Source: <https://github.com/lszoszk/ECHR-Dashboard>

For replication, please reference the specific commit hash matching the dataset version analysed.
