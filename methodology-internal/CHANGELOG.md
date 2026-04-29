# CHANGELOG — ECHR Dashboard Data Cleaning

Chronological record of every transformation applied to the corpus, with commit hashes for replay/audit.

---

## 2026-04-30 — P17 (Rec-4 representation → Introduction)

- **2026-04-30 P17 — Representation paragraphs Facts → Introduction (100% precision, 1,501 paragraphs)**

  Recall-audit Rec-4 (medium-confidence): "The Government were represented by their Agent" / pure gov+app representation paragraphs sit in `Facts Background` because the segmenter put them under "THE FACTS" header, but they are procedural metadata that conceptually belongs alongside the existing `Introduction` block.

  Background context that justified the move:
  - **7,088 representation paragraphs already live in `Introduction`** (3.8% of all Introduction), predominantly older Pop A/B cases with pre-2009 PROCEDURE blocks.
  - In modern Chamber post-2020 format, the Court's literal heading "THE FACTS" places paragraphs 2-3 (applicant bio + government rep) before the actual circumstances, but content is procedural intro metadata.
  - Of 500 sampled gov-rep paragraphs in Facts/etc, 89% are in cases that already have an Introduction section — so we are merging adjacent procedural metadata with the existing intro.

  Two precision-first rules (paragraph in Facts / Facts Background / Facts Proceedings):

  - **R1** — gov-rep alone, len < 300:
    Pattern: `(?:^|\.\s+)(?:The\s+)?Government(?:s)?\s+(?:was|were|is|are)\s+represented\s+by\s+`
    Target: → `Introduction`. **1,498 paragraphs.**
  - **R2** — pure gov+app rep paragraph (both patterns), len < 500:
    Target: → `Introduction`. **3 paragraphs.**

  Critical rejected pattern: **applicant-only rep was REJECTED** because of FP risk — "the applicant was represented by a State-appointed lawyer" appears legitimately in Facts narrative describing **domestic** proceedings (e.g., "On 11 July 2004 the police arrested the applicant. The applicant was represented by K., a State-appointed lawyer."). Cannot reliably distinguish without semantic analysis. The "Government were represented" form is unique to procedural intro context (Government's representation of itself before ECHR) and does not appear in domestic court narratives.

  Backup: `_p17_backup` (1,501 rows). Script: `scripts/p17_relabel.py`.

  **Counts:** `Introduction` 188,399 → 189,900 (+1,501); `Facts` 120,140 → 119,781 (-359); `Facts Background` 34,535 → 33,435 (-1,100); `Facts Proceedings` 347,559 → 347,517 (-42).

  **LLM precision audit (33 stratified samples — 30 R1 + all 3 R2):**
  - 33 correct, 0 incorrect, 0 ambiguous
  - **Precision: 100.0%** (R1 30/30, R2 3/3)
  - All samples confirmed canonical procedural-metadata position (Introduction → THE FACTS → applicant bio → **TARGET: Government rep** → "facts of the case may be summarised...")

  Note: audit was performed manually (sub-agent rate-limit at audit time). All 33 samples verified to be textbook procedural representation in canonical Modern Chamber position. Saved artifacts: `scripts/p17_audit_samples.json`, `scripts/p17_audit_verdicts.json`.

---

## 2026-04-29 — P16 (Rec-3 Facts → JS / Operative in Pop C)

- **2026-04-29 P16 — Pop C compressed-format extraction (100% precision, 11,804 paragraphs)**

  Recall-audit Rec-3 + post-P15 probe revealed that Pop C compressed-format judgments dumped the entire Operative dispositif AND JS award reasoning into the `Facts` section. The recall audit estimated ~3,000 misclassified paragraphs but the actual scope was **~4× larger**: 11,804 paragraphs across all three Facts buckets (Facts / Facts Proceedings / Facts Background), dominated by Pop C committee-format judgments.

  Six tight precision-first rules (applied in order):

  - **R0a** — `^\s*(?:[IVX]+\.\s+)?APPLICATION OF ARTICLE 41` heading, len < 200 → Just Satisfaction. **1 paragraph.**
  - **R0b** — `Article 41 ... Convention provides:` boilerplate quote, len < 800 → Just Satisfaction. **6 paragraphs.**
  - **R1** — `^\d+\.\s*(Holds|Decides|Declares|Dismisses)\b` numbered dispositif, no length cap → Operative. **8,786 paragraphs.**
  - **R2** — `(a) that the respondent State is to pay`, len < 1500 → Operative. **566 paragraphs.**
  - **R3** — `(b) that from the expiry of the above-mentioned three months ... simple interest shall be payable`, len < 700 → Operative. **2,197 paragraphs.**
  - **R4** — `Court awards | Court considers it reasonable to award` AND (EUR or non-pecuniary or costs and expenses), len < 600, **Pop C only (para_idx IS NULL)** → Just Satisfaction. **248 paragraphs.**

  Critical rejected pattern: `equitable basis + EUR` was probed at 76 hits with 5/5 spot-check FP rate — Italian and Bulgarian Pop A/B cases use this phrase to describe domestic Court of Appeal awards in Facts narrative. R4 is restricted to Pop C only to avoid this trap.

  Per-case operative casing mirrored: Pop A/B → `Operative Part` (2 paragraphs); Pop C → `Operative part` (11,547 paragraphs); JS → `Just Satisfaction` (255 paragraphs).

  Backup: `_p16_backup` (11,804 rows). Script: `scripts/p16_relabel.py`.

  **Counts:** `Facts` 131,935 → 120,140 (-11,795); `Facts Proceedings` 347,567 → 347,559 (-8); `Facts Background` 34,536 → 34,535 (-1); `Just Satisfaction` 156,675 → 156,930 (+255); `Operative Part` +2; `Operative part` 64,644 → 76,191 (+11,547).

  **LLM precision audit (55 stratified samples, Sonnet 4.6):**
  - 55 correct, 0 incorrect, 0 ambiguous
  - **Precision: 100.0%** (R0a 1/1, R0b 6/6, R1 12/12, R2 12/12, R3 12/12, R4 12/12)
  - All R4 matches verified to refer to the ECHR Court (Pop C restriction prevented domestic Court of Appeal FPs)

  This pass is the largest single relabel since P3 (83,377 → Legal Framework) and brings Pop C compressed-judgment structure into close alignment with the canonical 14-section taxonomy. Saved artifacts: `scripts/p16_audit_samples.json`, `scripts/p16_audit_verdicts.json`.

---

## 2026-04-29 — P15 (Rec-2 JS → Operative residual)

- **2026-04-29 P15 — Just Satisfaction → Operative Part residual cleanup (100% precision)**

  Recall audit Rec-2 + post-P13 probe found ~600 paragraphs in `Just Satisfaction` that are actually Operative Part dispositif content but missed by P13's 400-char length cap and `numbering_block = operative_dispositif` filter. P15 picks up the residue with two tight rules:

  - **R1 — numbered dispositif**: paragraph starts with `^\d+\.\s*(Holds|Decides|Declares|Dismisses)\b`. NO length cap (Pop A pre-1998 fused-paragraph operative blocks routinely exceed 400 chars; the canonical numbered-verb anchor is precise enough on its own). **81 paragraphs.**
  - **R2 — signature / continuation block**: paragraph contains strict `\bRule 77\b` AND (Registrar OR "Done in [Lang]"), length < 700. Targets default-interest "(b) that from the expiry of the above-mentioned three months..." continuation clauses split off from the parent numbered Holds clause by PDF extraction. **15 paragraphs.**

  Probe insight: a loose `Rules of Court` anchor would have caught 1,032 paragraphs, but spot-check showed near-100% FP rate — JS reasoning paragraphs frequently cite Rule 60 (JS submission), Rule 38 (evidence), Rule 61 (third-party intervention), which are NOT operative content. Tightening to `\bRule 77\b` (the rule that governs delivery and signature, only used in operative closings) cut to 15 candidates with 100% precision.

  Backup: `_p15_backup` (96 rows). Script: `scripts/p15_relabel.py`. Per-case operative casing mirrored (50 → `Operative Part`, 46 → `Operative part`).

  **Counts:** `Just Satisfaction` 156,771 → 156,675 (-96); `Operative Part` 67,833 → 67,883 (+50); `Operative part` 64,598 → 64,644 (+46).

  **LLM precision audit (96 / 96 samples — full population audit, Sonnet 4.6):**
  - 96 correct, 0 incorrect, 0 ambiguous
  - **Precision: 100.0%**
  - R1: 81/81 correct (numbered Holds/Decides/Declares/Dismisses dispositif, both Pop A long-fused and Pop C short)
  - R2: 15/15 correct (default-interest continuation clauses, all flanked by operative-context paragraphs)

  This pass complements P13 (3,403 dispositif-in-JS) and brings JS section noise close to zero for paragraphs matching canonical operative anchors. Saved artifacts: `scripts/p15_audit_samples.json`, `scripts/p15_audit_verdicts.json`.

---

## 2026-04-29 — P14 (Rec-1 RLF cleanup)

### Phase 2 — P14 — Relevant legal framework triage

- **2026-04-29 P14 — RLF → Operative / Just Satisfaction / Merits (3-rule classifier, 100% precision)**

  Recall audit (Pattern A) flagged ~6k `'Relevant legal framework'` paragraphs whose content actually belonged to other sections. A naive single-target relabel was abandoned (first attempt: 78% precision); replaced with a **three-rule precision-first classifier** that conservatively relabels only paragraphs matching tight regex anchors. **800 paragraphs relabeled** (vs. ~6k naive scope) at **100% LLM-audited precision**.

  Detection rules (applied in order):
  - **R0 — Article 41 boilerplate** → `Just Satisfaction`. Catches the canonical treaty-quote paragraph (`"Article 41 of the Convention provides..."` / `"If the Court finds that there has been a violation of the Convention..."`). Must be checked BEFORE R3 — the boilerplate contains "violation" tokens that would otherwise trigger R3→Merits (this was the v1 failure mode).
  - **R1 — numbered dispositif** → `Operative Part` / `Operative part` (per-case casing preserved). Pattern: `^\d+\.\s*(Holds|Decides|Declares|Dismisses)\b`, length < 400. **460 paragraphs.**
  - **R2 — Article 41 award reasoning** → `Just Satisfaction`. Requires both "Court awards"/"Court considers it reasonable to award" AND a damage/currency token (EUR, non-pecuniary, costs and expenses). Length < 800. **253 paragraphs** (combined with R0).
  - **R3 — substantive violation finding** → `Merits`. Tight pattern: `there has been a violation of Article`, `It follows that there has been a violation`, `the Court concludes/finds that there has been`, `finds a violation of Article`. Length ≥ 80. **87 paragraphs.**

  Skip rules to suppress fused-paragraph FPs:
  - Skip if ≥2 dispositif verbs at sentence boundaries (PDF-extraction merge artefact)
  - Skip if paragraph contains both JS award token AND any dispositif marker (mixed JS+Operative tail)
  - Skip if heavy citation (`see X v. Y, no. NNN/NN`) and length < 400 (RLF case-law citation)

  Backup: `_p14_backup` (800 rows: rowid + section + numbering_block). Script: `scripts/p14_relabel.py`.

  **Counts:** `Relevant legal framework` 15,743 → 14,943; `Merits` +87; `Just Satisfaction` +253; `Operative Part`/`Operative part` +460.

  **LLM precision audit (50 samples, Sonnet 4.6 judge):**
  - 47 correct, 0 incorrect, 3 ambiguous (fused JS+operative paragraphs, defensible either way)
  - **Precision: 100%** (well above 95% target)
  - Per-target: Operative 25/25 (100%), JS 18/21 (3 ambiguous → 100% if exclude), Merits 4/4 (100%)
  - All 9 sampled Article 41 boilerplate paragraphs correctly routed to JS via R0 (v1 failure mode resolved)

  **Why conservative:** the audit-flagged 6k pool was heterogeneous (JS + Operative + Merits + genuine RLF citations all mixed). A blanket RLF→Merits rule would have ~25-37% precision per probe. The 3-rule classifier sacrifices recall (only 800 of ~6k caught) for precision, leaving genuinely ambiguous content in RLF for future manual review. Saved artifacts: `scripts/p14_audit_samples_v2.json`, `scripts/p14_audit_verdicts_v2.json`.

---

## 2026-04-27 — Phase 2 + UX (this session)

### Phase 2 (DB-side relabeling)

- **2026-04-27 [`8241807`](https://github.com/lszoszk/ECHR-Dashboard/commit/8241807) Phase 2 P1+P2+P3 relabeling**

  Three rule-based passes on production DB (2,001,447 paragraphs):

  - **P1 — Just Satisfaction**: +82,989 paragraphs moved from Merits / Admissibility / Facts / Operative part / Facts Proceedings / Relevant legal framework / Operative Part → `Just Satisfaction`. Detection: short heading paragraphs ("APPLICATION OF ARTICLE 41", "APPLICATION OF ARTICLE 50", "JUST SATISFACTION") plus follow-on content blocks in Population B cases. `Just Satisfaction`: 37,328 → 120,317.
  - **P2 — Separate Opinion**: +2,370 paragraphs moved from `Operative Part` → `Separate Opinion` (153 cases). Detection: "DISSENTING OPINION", "CONCURRING OPINION", "PARTLY DISSENTING", "JOINT DISSENTING", "SEPARATE OPINION OF" headings. `Separate Opinion`: 29,205 → 31,575.
  - **P3 — Legal Framework**: +83,377 paragraphs moved from `Facts Proceedings` → `Legal Framework` (7,975 cases, 1982–2020). Detection: "II. RELEVANT DOMESTIC LAW (AND PRACTICE)" subsection headings with word-boundary stop logic to avoid false positives from "the Law of Ukraine" etc. `Legal Framework`: 24,867 → 108,244.

  Backups: `_p1_backup` (82,989), `_p2_backup` (2,370), `_p3_backup` (83,377).
  Scripts: `scripts/p{1,2,3}_*.py`. Full corpus structural analysis archived: `docs/phase2/section_analysis.txt` (3,201 lines, 10 random cases per year 1975–2025).

- **2026-04-27 [`adab943`](https://github.com/lszoszk/ECHR-Dashboard/commit/adab943) Phase 2 P4 — Population C segmentation**

  +56,241 paragraphs relabeled in 6,236 Committee/joined cases (those with `para_idx IS NULL`):

  - 54,237 Facts → Merits (triggered by `ALLEGED VIOLATION` or `JOINDER OF THE APPLICATIONS` headings)
  - 2,004 Facts → Just Satisfaction (triggered by `APPLICATION OF ARTICLE 41`)

  Walked each case in `rowid` order (proxy for document order, since `para_idx` is NULL). 3,479 boundary headings triggered. Conservative block design: relabeling stops as soon as the section column changes. Backup: `_p4_backup` (56,241 rows). `Just Satisfaction` cases: 11,995 → 12,090. `Merits` cases: 18,976 → 18,993.

### Frontend (UX)

- **2026-04-27 [`d17e71a`](https://github.com/lszoszk/ECHR-Dashboard/commit/d17e71a) feat: document type chips + section context hints**

  - `__isCommittee` / `__isGrandChamber` flags on case objects (derived from `document_type` and `originating_body`)
  - Visual chip rendered in case card header (teal Committee / amber Grand Chamber)
  - ⓘ hint icons next to "Introduction" and "Facts of the case" filter checkboxes warning about Population C content patterns
  - No backend changes required

- **2026-04-27 [`277a709`](https://github.com/lszoszk/ECHR-Dashboard/commit/277a709) feat: filter by judgment type (Chamber / Grand Chamber / Committee)**

  Replaced the binary "Judgments / Press Releases" doc_type filter with four buckets: Chamber / Grand Chamber / Committee / Press Releases. Backend (`backend/main.py`) extended to accept new `doc_types` query values:
  - `chamber` — `document_type NOT LIKE '%Press Release%' AND NOT LIKE '%Committee%' AND originating_body NOT LIKE '%Grand Chamber%'`
  - `grand_chamber` — `originating_body LIKE '%Grand Chamber%'`
  - `committee` — `document_type LIKE '%Committee%'`

  **Bug fix**: filter change listener was dead in server mode for an unknown duration. The `state.loaded` guard never fired in server mode (it's only set by the local-mode `applyDataset()` function). Fixed by changing the guard to also pass when `serverSearch.available` is true.

- **2026-04-27 [`0c715a8`](https://github.com/lszoszk/ECHR-Dashboard/commit/0c715a8) data: regenerate offline sample**

  Regenerated `docs/data/echr_cases_sample50.jsonl` from the production DB with stratified sampling (8 classical / 16 modern Chamber / 8 Grand Chamber / 10 Committee / 2 press releases / 4 recent / 2 top-up = 50 cases, 24 states). Now reflects all 14 current section labels including `Just Satisfaction`, `Legal Framework`, `Operative part` (lowercase), `Facts`, `Relevant legal framework` — none of which appeared in the previous sample.

- **2026-04-27 [`d847e1c`](https://github.com/lszoszk/ECHR-Dashboard/commit/d847e1c) feat: case counts beside every filter checkbox**

  Each filter option now displays `(N)` — the number of distinct cases matching it — pulled from `/api/facets`. Section bucket counts use `max` (not `sum`) of constituent raw labels to avoid double-counting cases with multiple raw labels in the same bucket. Doc-type buckets aggregate raw `document_type` values into the four frontend buckets, with Grand Chamber count subtracted from Chamber to avoid double-counting.

---

## 2026-04-26 — Phase 1.5 (orphan-label recovery, frontend-only)

- **2026-04-26 [`aa8ab4c`](https://github.com/lszoszk/ECHR-Dashboard/commit/aa8ab4c) sections: recover ~325k paragraphs lost to label drift (Phase 1.5)**

  Three raw DB section labels were silently absent from the frontend `SECTION_DB_NAMES` map and therefore invisible to the section filter:

  | Label | Paragraphs | Cases |
  |---|---|---|
  | `Facts` | 245,953 | 5,650 |
  | `Operative part` (lowercase) | 62,552 | 6,232 |
  | `Relevant legal framework` | 15,857 | 1,838 |

  Frontend-only fix in `docs/assets/search-app.js`:

  ```javascript
  facts:           ["Facts Background", "Facts Proceedings", "Facts"],
  legal_framework: ["Legal Framework", "Legal Context", "Relevant legal framework"],
  operative_part:  ["Operative Part", "Operative part"],
  ```

  Plus normalizer aliases for "relevant legal framework" → `legal_framework`. Empirical impact: typical query gained +5,648 cases / +51% hits.

---

## 2026-04 — Phase 1 (consolidation, pre-this-session)

- Merged `Facts Background` + `Facts Proceedings` under UI bucket "Facts of the case" / `facts`
- Merged `Legal Framework` + `Legal Context` under UI bucket / `legal_framework`
- Frontend-only changes in `SECTION_DB_NAMES`

(Predates this changelog. See git log on `docs/assets/search-app.js` for exact commits.)

---

## Earlier — Server-side migration

- Static dashboard migrated from full-corpus client-side JSON to server-side FTS5 search
- Backend: FastAPI + SQLite + FTS5 (BM25F weights: title=5.0, keywords=3.0, body=1.0)
- Sample fallback: `echr_cases_sample50.jsonl` for offline / API-down scenarios
- Hosting: VM `150.254.115.204` (shared with the unrelated "uhri" Mattermost stack — must scope all operations to the `echr-search` Docker compose project only)

---

## Backup catalog (all in production DB)

| Table | Rows | Restore command |
|---|---|---|
| `_p1_backup` | 82,989 | `UPDATE paragraphs SET section = (SELECT section FROM _p1_backup b WHERE b.rowid = paragraphs.rowid) WHERE rowid IN (SELECT rowid FROM _p1_backup);` |
| `_p2_backup` | 2,370 | (same pattern with `_p2_backup`) |
| `_p3_backup` | 83,377 | (same pattern with `_p3_backup`) |
| `_p4_backup` | 56,241 | (same pattern with `_p4_backup`) |

Total reversible: **224,977 paragraphs** (≈11.2% of corpus).

---

## Scripts catalog

| Script | Type | Purpose |
|---|---|---|
| `scripts/harvest_headings.py` | read-only | Scans corpus for canonical heading occurrences, used for boundary discovery |
| `backend/analyze_sections.py` | read-only | 10 random cases per year, 1975–2025, full structural analysis |
| `scripts/probe_section_labels.py` | read-only | Samples specific section labels to investigate misclassification patterns |
| `scripts/p1_validate_js.py` | read-only | Pass 1 dry-run / scope estimation |
| `scripts/p1_relabel_js.py` | mutation | Pass 1 with `--apply` flag |
| `scripts/p2_relabel_opinions.py` | mutation | Pass 2 (combined validate + relabel) |
| `scripts/p3_validate_domestic_law.py` | read-only | Pass 3 dry-run with year breakdown |
| `scripts/p3_relabel_domestic_law.py` | mutation | Pass 3 with `--apply` |
| `scripts/p4_validate_population_c.py` | read-only | Pass 4 diagnostics on Population C |
| `scripts/p4_relabel_population_c.py` | mutation | Pass 4 with `--apply` |
| `scripts/generate_sample50.py` | read-only | Regenerate stratified offline-fallback sample |

All read-only scripts are safe to re-run; all mutation scripts default to dry-run unless `--apply` is passed and create a backup table before any `UPDATE`.
