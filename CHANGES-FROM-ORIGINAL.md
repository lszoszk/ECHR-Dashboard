# Changes from the original dataset and pipeline

This document records every substantive modification to the ECHR Dashboard dataset, backend or frontend, made since the initial public version, for formal documentation and reproducibility. Each entry links the affected file(s) and the commit hash that introduced the change.

The repository root is `/Users/lszoszk/Desktop/HURIDOCS/ECHR-Dashboard-tier1/`. The live deployment target is `150.254.115.204` (FastAPI + nginx via `docker-compose.yml`) with the static frontend published on GitHub Pages at `https://lszoszk.github.io/ECHR-Dashboard/`.

---

## 1. Dataset changes (content / classification)

### 1.1 Merged `Facts (Background)` and `Facts (Proceedings)` into a single `facts` bucket
**Commit:** `20260410-factsmerge` (frontend-only; no database rewrite)
**Files:** `docs/assets/search-app.js`, `docs/index.html`

**Rationale.** The upstream paragraph segmenter assigns two labels to "facts": `Facts Background` (~36,463 paragraphs) and `Facts Proceedings` (~437,933 paragraphs), a 92 : 8 imbalance. Manual inspection of the underlying text and direct comparison with live HUDOC judgments revealed that these labels are **semantically inverted versus the HUDOC convention**:

- In a classical Chamber or Grand Chamber judgment (verified on Hirst v UK (No. 2) [GC], Selmouni, Handyside) the document structure is: `PROCEDURE` → `THE FACTS` → `I. THE CIRCUMSTANCES OF THE CASE` → `II. RELEVANT DOMESTIC LAW` → `III. RELEVANT INTERNATIONAL MATERIALS` → `THE LAW`. The short administrative block is `PROCEDURE` (who lodged, composition, interveners, hearing date) and the substantive narrative is `THE CIRCUMSTANCES OF THE CASE`.
- Since 1 September 2021 the Court itself has merged facts and procedure for Committee cases into a single `SUBJECT MATTER OF THE CASE` / `FACTS AND PROCEDURE` block (verified on T.M.V. v Romania 2024, Vokáč v Czech Republic 2022, Di Giuseppe v Italy 2023).

The upstream labels do not follow either convention, and lawyers cite by paragraph number, not by sub-section heading. Splitting an unreliable classification into two filter checkboxes produced user confusion and a filter that was effectively useless.

**What changed.**

- The two raw DB values `Facts Background` and `Facts Proceedings` are still stored verbatim in the SQLite `paragraphs` table — the backend was not rewritten. No paragraph has been deleted or renamed.
- The frontend collapses both raw values into a single normalized UI key `facts` labelled **"Facts of the case"**. The collapse happens at three points:
  1. `normalizeSectionKey()` in `docs/assets/search-app.js`, which maps both `"facts background"` and `"facts proceedings"` aliases to `"facts"`.
  2. `SECTION_DB_NAMES["facts"] = ["Facts Background", "Facts Proceedings"]` so when the user ticks the merged filter, both raw values are passed to the server in the `sections=` query parameter.
  3. The analytics renderer (`fetchAndRenderServerAnalytics`) aggregates counts across both DB values into a single row labelled "Facts of the case".
- Filter checkboxes in the advanced filter panel now show a single **"Facts of the case"** entry; the sections-in-dataset list deduplicates after normalization.
- CSV export continues to include the raw `section` field per paragraph, so power users can still split in pandas if needed.

**What did NOT change.**

- No change to `backend/main.py`, `backend/build_db.py`, `backend/ranking.py`, the SQLite schema, the `paragraphs` table contents, or any stored facets. The merge is presentational.
- Section-level ranking weights in `backend/ranking.py` and full-text search behaviour are unaffected.

**Deferred improvement.** A proper reclassifier against the real HUDOC PROCEDURE / CIRCUMSTANCES / SUBJECT MATTER structure is scheduled as Phase 2 — see `docs/TODO-facts-reclassify.md`. That work would be an actual database rewrite; Phase 1 here is a zero-downtime UI-only change.

### 1.2 Re-segmentation of misclassified sections
**Commits:** `83eb23d` (initial re-segmentation), `aebee5c` (process `Header` paragraphs and detect headings in long text)
**Files:** `backend/build_db.py`

Fixed ~3000+ paragraphs where the upstream segmenter had assigned the wrong section label (primarily mis-attributed `Header` and misplaced transitions between `THE FACTS` and `THE LAW`). The re-segmentation walks each case's paragraphs in order and re-assigns sections whenever a canonical heading string is encountered inside paragraph text.

### 1.3 Inferred violation / non-violation outcomes from conclusion text
**Commit:** `bd2ab40`
**File:** `backend/build_db.py`

HUDOC metadata occasionally omits the structured `violation` / `non_violation` fields on judgments (particularly older ones). The build pipeline now parses the free-text `conclusion` field and infers the structured outcome lists, closing gaps visible in the dashboard KPI row and the outcome filter.

### 1.4 Document-type distinction: judgments vs press releases
**Commits:** `615162a`, `4a2e0c3`
**Files:** `backend/build_db.py`, `backend/main.py`, `docs/assets/search-app.js`

Added a `document_type` field so press releases are labelled and bucketed separately. In the UI, press releases receive their own outcome bucket (`press_release`) instead of polluting the `neither` bucket, and the ranking module multiplicatively demotes them (`document_type: "press_release" → ×0.75`) so real judgments surface above press-release duplicates in relevance ranking.

### 1.5 Population of advanced filters from server-side facets
**Commit:** `5053341`
**File:** `docs/assets/search-app.js`

When the API is available, the advanced-filter dropdowns (articles, states, importance, bodies, outcomes, sections) are populated from `/api/facets` rather than from the locally-loaded JSONL sample, ensuring that the filters always reflect the full 18,429-case corpus rather than the 50-case offline sample.

### 1.6 Merged `Legal Framework` and `Legal Context` into a single `legal_framework` bucket
**Commit:** `20260411-legalmerge` (frontend-only; no database rewrite)
**Files:** `docs/assets/search-app.js`, `docs/index.html`

**Rationale.** Corpus-wide tally of the upstream segmenter's section labels revealed a 4,147 : 1 imbalance:

| Label | Paragraphs | Distinct cases | % of corpus |
|---|---|---|---|
| `Legal Framework` | 24,882 | 1,361 | 1.81% |
| `Legal Context` | **6** | **2** | 0.0004% |

The 6 `Legal Context` paragraphs live in exactly two 2026 Polish judicial-overhaul judgments — Morawiec v. Poland (5 Feb 2026) and Biliński v. Poland (15 Jan 2026) — where the Third Section Registry introduced a novel uppercase heading "LEGAL CONTEXT OF THE CASE" as a short case-series breadcrumb pointing at Wałęsa v. Poland (no. 50849/21) as the anchor judgment. Both cases also contain a full `RELEVANT LEGAL FRAMEWORK AND PRACTICE` section (6 and 16 paragraphs respectively), so the two labels are **parallel — not overlapping**. `Legal Context` is not an alternative legal-framework category; it is a "see also" breadcrumb.

**HUDOC convention check.** `Legal Context` is not part of the classical HUDOC template (`II. RELEVANT DOMESTIC LAW AND PRACTICE` + `III. RELEVANT INTERNATIONAL MATERIALS`), nor of the modern merged form (`RELEVANT LEGAL FRAMEWORK AND PRACTICE`) used by the Court since ~2019. It is not in the *Note explaining the mode of citation*, not in OSCOLA, not in practitioner research guides. It is a 2026 Registry experiment appearing in two judgments.

**Hick's law UX analysis.** A filter checkbox that returns 6 paragraphs across the entire corpus fails the Nielsen Norman Group rule "not more facets than the results listed" by ~3 orders of magnitude. The real cost is compounded by semantic near-confusability: `Legal Framework` vs `Legal Context` share the same morphology (adjective + "Legal" + noun) and differ only in the head noun, forcing users to spend extra decision-time disambiguating a distinction that doesn't exist in the data. Under Hick's law (T = a + b·log₂(n+1)), each filter row costs attention even when it's never ticked, and a near-empty, near-confusable label is the most expensive kind.

**What changed.**

- The two raw DB values `Legal Framework` and `Legal Context` are still stored verbatim in the SQLite `paragraphs` table. No paragraph has been deleted or renamed. The merge is purely presentational.
- The frontend collapses both raw values into a single normalized UI key `legal_framework`, now **labelled "Relevant legal framework"** (aligned with the Court's modern heading convention and closer to lawyer vocabulary than the older generic "Legal Framework").
- `SECTION_DB_NAMES["legal_framework"] = ["Legal Framework", "Legal Context"]`, so when the user ticks the merged filter, both raw values are forwarded to the server in the `sections=` query parameter.
- `normalizeSectionKey()` now maps both `"legal framework"` and `"legal context"` aliases to `"legal_framework"`, so paragraphs from the local JSONL and from server-side case detail fetches both collapse into the same bucket on preprocessing.
- Filter checkbox count drops from 11 to 10 (Hick's law gain ≈ log₂(12) → log₂(11)).
- CSV export continues to include the raw `section` field per paragraph, so the 6 "Legal Context" breadcrumb paragraphs remain reachable via full-text search and via the exported raw column.
- Cache-buster bumped from `v=20260410-factsmerge` to `v=20260411-legalmerge`.

**What did NOT change.** No change to `backend/main.py`, `backend/build_db.py`, `backend/ranking.py`, the SQLite schema, the `paragraphs` table contents, or any stored facets.

**Deferred.** If the Court expands the `LEGAL CONTEXT OF THE CASE` heading into other case-law series (rule-of-law Russia cases, Turkey post-coup cases, Article 18 abuse-of-power series), Phase 2 — see `docs/TODO-facts-reclassify.md` — should split `Legal Context` back out as a dedicated "Case-series breadcrumb" bucket. Until there is enough volume to justify a checkbox, the merge is the right default.

---

## 2. Ranking changes (relevance & sort)

### 2.1 BM25F multi-column FTS5 schema with title + keywords
**Commit:** `a94b047`
**File:** `backend/build_db.py`

Denormalized `title` and `keywords` into the `paragraphs` table and rebuilt the `paragraphs_fts` virtual table as a three-column external-content index `(title, keywords_text, text)` with `tokenize='porter unicode61'`. A single `bm25(paragraphs_fts, 5.0, 3.0, 1.0)` call now evaluates title × keywords × body together in one SQL statement.

### 2.2 Ranking module with BM25F weights and metadata boosts
**Commits:** `6a39f9b`, `863d7c3`
**Files:** `backend/ranking.py` (new), `backend/main.py`

Introduced a dedicated `backend/ranking.py` module containing:

- Field weights `BM25_WEIGHT_TITLE=5.0`, `BM25_WEIGHT_KEYWORDS=3.0`, `BM25_WEIGHT_BODY=1.0`.
- Multiplicative metadata priors:
  - `importance`: `1 → ×1.40`, `2 → ×1.15`, `3 → ×1.00`, `4 → ×0.90`
  - `originating_body`: Grand Chamber → `×1.25`, Chamber → `×1.00`, Committee → `×0.85`
  - `document_type`: Press Release → `×0.75`, Judgment / Decision → `×1.00`
- `compute_final_score()`, `rerank_candidates()`, `should_rerank()` helpers.

The aggregate changed from `min(-bm25)` (one best-matching paragraph decided a case's rank) to `sum(-bm25) / log(1 + hit_count)` so cases that match many paragraphs are rewarded without long-judgment bias.

### 2.3 Phase 1 ranking bug fixes
**Commit:** `b033d68`
**File:** `backend/main.py`

Fixed two bugs in the ranking integration: the metadata row layout was mis-indexed, and the `pf.rank` value was being double-negated. Verified with the golden query set (`torture`, `margin of appreciation`, `Hirst`, `Soering OR Chahal`, `O'Halloran`, `positive obligations article 8`).

### 2.4 Full-corpus rerank + `Key cases` alias
**Commit:** `ff98f73`
**Files:** `backend/ranking.py`, `backend/main.py`

Removed the page-size candidate-pool truncation: the rerank now runs over the full match set rather than over `page_size × 3` candidates, which fixed the inconsistency where `Hirst v UK (No. 2)` ranked #1 at `page_size=10` but only #5 at `page_size=100`. Also added a lower-case `"key cases"` lookup alias to `IMPORTANCE_BOOST` so rows where importance is recorded as the string `"Key cases"` instead of the numeric `1` still receive the ×1.40 boost.

### 2.5 Date-sort lex-bug fix
**Commit:** `13b487d`
**File:** `backend/main.py`

The original `ORDER BY judgment_date` statements in `/api/search`, `/api/browse`, and the sample-dataset fallback were sorting `DD/MM/YYYY` strings lexicographically, which produces nonsense (`31/01/1960` sorts after `01/01/2024`). Replaced with an ISO substring key:

```sql
ORDER BY (substr(c.judgment_date,7,4)
       || substr(c.judgment_date,4,2)
       || substr(c.judgment_date,1,2)) DESC
```

Applied in both the date-sort branch and wherever date windows were compared.

### 2.6 Date-range KPI lex-bug fix
**Commit:** `8d9dc7f`
**File:** `backend/main.py`

Same DD/MM/YYYY lex bug had crept into the `/api/stats` and `/api/facets` min / max date calculations, producing a wrong "01/02/2000 → 31/10/2023" range in the KPI bar. Fixed with the same ISO substring key as 2.5.

---

## 3. KPI and analytics fixes

### 3.1 `total_countries` multi-respondent fix (79 → 46)
**Commit:** `58add73`
**File:** `backend/main.py`

The `total_countries` KPI was returning 79 — far above the 46 Council of Europe member states — because it used `COUNT(DISTINCT respondent_state)` over strings that sometimes contain multiple comma-joined respondents (e.g. `"France, Belgium"`). Replaced the naive `COUNT(DISTINCT)` with a Python-side set that splits each cell on `,`, trims whitespace, and deduplicates. The KPI now correctly reports 46.

### 3.2 Server-side analytics endpoint
**Commit:** `c1f396f`
**File:** `backend/main.py`

Added `/api/analytics` that aggregates facets for the full result set (articles, countries, sections, bodies, importance, outcomes, document types) server-side rather than requiring the frontend to request thousands of cases and aggregate in JavaScript. Commit `940db21` wires this into the frontend analytics panel when the server is available.

### 3.3 Analytics rendering in server-search mode
**Commit:** `940db21`
**File:** `docs/assets/search-app.js`

The analytics tab now calls `/api/analytics?q=…` and renders the server response. After the Phase 1 facts merge, the analytics renderer aggregates counts from both `Facts Background` and `Facts Proceedings` server rows into a single `Facts of the case` row.

### 3.4 Document-type aware analytics
**Commit:** `4a2e0c3`
**File:** `docs/assets/search-app.js`

The analytics tab now distinguishes judgments and press releases; the outcome chart and document-type chart reflect the distinction introduced in 1.4.

---

## 4. Default view and pagination

### 4.1 Default view loads 100 most recent cases, paginated
**Commit:** `13b487d`
**Files:** `backend/main.py`, `docs/assets/search-app.js`

On initial page load (empty query, no filters), the dashboard now calls `/api/browse?sort=date_desc&page_size=20&page=1` and caps the result at 100 cases paginated across 5 pages. This replaces the previous behaviour where the browse-all view showed the full 18,429-case list, which was overwhelming and slow to paginate. The cap is implemented frontend-side via `state.defaultView` and `state.defaultViewCap`, and the results header renders as "server · 100 most recent".

### 4.2 Sample50 preload removal (fix for 18k → 50 flicker)
**Commit:** `af5efb8`
**File:** `docs/assets/search-app.js`

Earlier code fetched the bundled 50-case sample dataset "for local browse fallback" even when the server was successfully reached. Because `activateDataset()` calls `preprocessDataset()`, which replaces `state.cases` with whatever rows it receives, loading the sample after a successful server connection overwrote the 18,429 cases the dashboard had just connected to with only 50, producing a visible "18000+ → 50" flicker on page load. The sample preload is now skipped entirely when the server is available; offline reload via `loadSampleBtn` still handles the genuine offline fallback.

### 4.3 Pagination in server mode uses server totals
**Commit:** `84cfc11`
**File:** `docs/assets/search-app.js`

Pagination controls now use `data.total_hits` / `data.total_pages` from the server response rather than the length of the locally-loaded sample dataset.

---

## 5. UI / UX fixes

### 5.1 Country filter normalization
**Commit:** `5b402e6`
**File:** `docs/assets/search-app.js`

Fixed country filters to match the comma-split respondent logic introduced for `total_countries` (3.1), and removed the now-redundant `Header` section from the filter list (its content is rendered in the modal metadata bar, not as a scrollable section).

### 5.2 Advanced filters populate from server facets
**Commits:** `5053341`, `22ebde2`
**File:** `docs/assets/search-app.js`

The advanced filter panel now populates from `/api/facets` when the server is reachable, including a DB → normalized key mapping for sections, bodies and outcomes. See 1.5.

### 5.3 Modal UI: highlights, XLSX export, structural headings
**Commits:** `a5e5b48`, `10c924b`, `cde10cd`
**Files:** `docs/assets/search-app.js`, `docs/index.html`

- Modal UI overhauled with per-paragraph text highlighting stored in-memory per case.
- Replaced the legacy PDF export with XLSX export that carries highlights and section labels.
- Structural headings inside a judgment (e.g. `PROCEDURE`, `I. THE CIRCUMSTANCES OF THE CASE`) are now detected via `HEADING_ONLY_RE` and rendered as styled sub-headings rather than as plain paragraphs.

### 5.4 `HEADING_ONLY_RE` SyntaxError fix
**Commit:** `d9bd5df`
**File:** `docs/assets/search-app.js`

An earlier version of `HEADING_ONLY_RE` used identity escapes inside a character class with the `/u` flag (`\-\(\)\/\:`), which is a `SyntaxError` in Unicode mode. Because a SyntaxError at parse time kills the entire script, the dashboard reported "Server unavailable" even though the API was healthy — `serverSearch.probe()` never ran. The fix removes the backslashes and moves the literal `-` to the end of the class.

### 5.5 Cache-busting for GitHub Pages
**Commits:** `58f195e`, `d9bd5df`, `20260410-factsmerge`
**File:** `docs/index.html`

GitHub Pages caches assets with a 10-minute max-age header. The `<script src="assets/search-app.js?v=…">` query-string cache-buster is bumped on every user-visible frontend change so users see the new version without manual hard-reload.

### 5.6 Modal fetches from server API
**Commits:** `baf264c`, `d5b32ec`
**File:** `docs/assets/search-app.js`

Opening a case modal always fetches full paragraphs from `/api/cases/{id}` rather than relying on the locally-loaded sample, so the modal shows the complete judgment even when the browsing list came from the server.

### 5.7 CSV export fetches all results
**Commit:** `8d1fc3e`
**File:** `docs/assets/search-app.js`

CSV export now iterates the API over all pages of the current query rather than exporting only the current page.

### 5.8 CORS handling moved to nginx
**Commit:** `64866cf`
**Files:** `backend/main.py`, `deploy/nginx.conf`

Removed FastAPI `CORSMiddleware` and let nginx handle CORS exclusively to avoid double-headers and simplify the cross-origin setup between GitHub Pages and the VM.

### 5.9 KPI bar overhaul
**Commit:** `48ff6d0`
**File:** `docs/assets/search-app.js`

The top-of-page KPI bar was reworked for server-first display: shows total cases, total countries, date range, and data-source badge. The badge no longer disappears after the sample dataset loads (`243a583`).

---

## 6. Summary table of commits

| Area | Commit(s) | Short description |
|---|---|---|
| Facts merge (Phase 1) | `20260410-factsmerge` | Merge `Facts Background` + `Facts Proceedings` into single `facts` bucket |
| Re-segmentation | `83eb23d`, `aebee5c` | Re-segment ~3000+ misclassified paragraphs |
| Document type | `615162a`, `4a2e0c3` | Press release vs judgment distinction |
| Outcome inference | `bd2ab40` | Infer violation/non-violation from conclusion text |
| BM25F schema | `a94b047` | Multi-column FTS5 with title + keywords |
| Ranking module | `6a39f9b`, `863d7c3`, `b033d68` | `backend/ranking.py` with BM25F weights and metadata priors |
| Full-corpus rerank | `ff98f73` | Removed candidate-pool truncation + `"Key cases"` alias |
| Date sort fix | `13b487d` | ISO substring key for `/api/search` and `/api/browse` |
| Date range KPI fix | `8d9dc7f` | Same ISO substring key for `/api/stats` and `/api/facets` |
| Country KPI fix | `58add73` | Python-side comma-split in `total_countries` (79 → 46) |
| Server analytics | `c1f396f`, `940db21` | `/api/analytics` endpoint and frontend renderer |
| Default view | `13b487d` | Load 100 most recent cases, paginated |
| Sample preload removal | `af5efb8` | Stop overwriting server state with sample on load |
| Modal + highlights | `a5e5b48`, `cde10cd`, `d9bd5df` | Highlights, XLSX export, structural headings, regex fix |
| Cache-busting | `58f195e`, `d9bd5df`, `20260410-factsmerge` | Force client refresh after each release |
| CORS | `64866cf` | Moved to nginx |
| KPI bar | `48ff6d0`, `243a583` | Server-first KPI display |

---

## 7. Files touched

- `backend/main.py` — ranking integration, date-sort fixes, KPI fixes, analytics endpoint, CORS removal.
- `backend/build_db.py` — multi-column FTS5 schema, paragraph re-segmentation, document-type + outcome inference, denormalized title/keywords.
- `backend/ranking.py` — new module.
- `docs/assets/search-app.js` — server-first data flow, default view, analytics rendering, modal UX, facts merge.
- `docs/index.html` — cache-buster bumps.
- `deploy/nginx.conf` — CORS.
- `docker-compose.yml` — service definitions.
- `docs/TODO-facts-reclassify.md` — deferred Phase 2 plan for a real HUDOC PROCEDURE / CIRCUMSTANCES / SUBJECT MATTER classifier.

---

*Last updated:* 2026-04-10 (Phase 1 facts merge).
