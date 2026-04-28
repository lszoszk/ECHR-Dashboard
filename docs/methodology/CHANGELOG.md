# CHANGELOG — ECHR Dashboard Data Cleaning

Chronological record of every transformation applied to the corpus, with commit hashes for replay/audit.

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
