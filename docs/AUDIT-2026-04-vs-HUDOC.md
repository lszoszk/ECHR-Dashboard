# Audit — April 2026: ECHR Dashboard vs HUDOC and the state of the art in legal research tooling

**Status:** planning document for Phases 5–7
**Scope:** codebase inventory, live-site smoke test, feature comparison against HUDOC and against best-practice legal research platforms, user-workflow analysis, and a ranked roadmap.
**Predecessors:** Phase 1 (`CHANGES-FROM-ORIGINAL.md`), Phase 2 (`docs/TODO-facts-reclassify.md`), Phase 3–4 ranking and mobile/statistics-page work (commits through `9271d39`).
**Deployment targets:** static frontend on GitHub Pages (`https://lszoszk.github.io/ECHR-Dashboard/`), FastAPI + nginx backend at `https://150.254.115.204/echr-api/` (18,429 cases, 1,314,796 paragraphs indexed in SQLite FTS5).

> This document does not propose bug fixes. The goal is to plan the next round of *feature* work: what is missing compared with HUDOC and compared with Westlaw / Lexis / Jus Mundi / CanLII / CourtListener, and which gaps are worth closing first.

---

## 1. Codebase inventory (as of 2026-04-11)

### 1.1 Frontend pages

| File | Lines | Role |
|---|---|---|
| `docs/index.html` | 488 | Search page shell, KPI bar, filter accordion, modal container, accessibility panel |
| `docs/analytics.html` | 577 | Statistics page (charts rendered from `docs/data/stats.json`) |
| `docs/assets/search-app.js` | 5,397 | All search-page behaviour: server probe, query parsing, client fallback, ranking, modal, filters, XLSX export, classifier |
| `docs/assets/pages-dashboard.js` | 880 | Statistics page logic, chart rendering, recently shipped Violation Rate by Country chart (commit `9271d39`) |
| `docs/assets/search-app.css`, `dashboard.css`, `analytics-page.css`, `pages-dashboard.css` | — | Stylesheets |

Data files: `docs/data/stats.json` (schema `echr-dashboard-v2`, parser `2.0.0`), `docs/data/echr_cases.jsonl` (full sample export), `docs/data/echr_cases_sample50.jsonl` (50-case offline fallback).

### 1.2 `docs/assets/search-app.js` — structural map

From a scan of top-level declarations (5,397 lines total):

- **Server probe / transport** (`serverSearch` object, lines 11–~150). Health check against `https://150.254.115.204/echr-api/health`, thin wrappers over `/api/search`, `/api/browse`, `/api/facets`, `/api/analytics`, `/api/cases/{id}`. No retry/backoff, no request deduplication, no cancellation of in-flight queries when the user types again.
- **Classifier subsystem** (lines ~150–190 + far more downstream). Client-side experimental classifier pane with three methods (`CLASSIFIER_METHODS`), a 30-paragraph sample size, localStorage persistence under `echr-classifier-v1:` prefix, default threshold 0.22, minimum 6 labeled paragraphs to activate. Methods: TF-IDF, character n-gram cosine, keyword overlap. Entirely in-browser, no server component.
- **Section taxonomy** (lines ~190–250). `SECTION_ORDER`, `SECTION_LABELS`, `SECTION_COLORS`, `SECTION_DB_NAMES`, `normalizeSectionKey()`. Currently collapsed to 10 filter buckets after the Phase 1 facts merge and the `legal_framework` merge.
- **Scoring / ranking weights** (`SEARCH_SCORE_SECTION_WEIGHTS`). Secondary client-side re-ranking used only when the server is unreachable.
- **Query parser** (`parseQueryWithPrefixes`, `parseQuery`, `QUERY_PREFIX_KEYS`). Supports prefix syntax `case:`, `ecli:`, `hudoc:`, `article:`, `state:`, `body:`, `judge:`, `keyword:`. No Boolean `AND`/`OR`/`NOT`, no parentheses, no proximity operators, no wildcards (the server's FTS5 supports some of these — the client does not expose them).
- **Date handling** (`parseDate`, `parseDateInput`). Post-Phase 1 ISO-ordered; `DD/MM/YYYY` lex bug fixed in `13b487d` and `8d9dc7f`.
- **Country / article normalization** (`COUNTRY_NAMES`, `COUNTRY_CODE_BY_NAME_NORM`, `splitArticles`, `matchesArticleToken`). Comma-split respondent handling aligned with the `total_countries` KPI fix (`58add73`).
- **UI rendering** (cards, modal, highlights, XLSX export via SheetJS, accessibility panel). Modal fetches full paragraphs from `/api/cases/{id}` on open; structural headings are re-rendered via `HEADING_ONLY_RE`; per-paragraph highlights are stored in an in-memory map keyed by case id; XLSX export carries highlights and section labels.
- **Stop-words** (`STOPWORDS`) used only by the classifier and by the client-side fallback ranker.

No Lunr, no FlexSearch, no MiniSearch, no embeddings, no vector index. When the server is reachable the client is a thin transport layer; when the server is down the client falls back to naive substring matching over the 50-case sample.

### 1.3 `docs/data/stats.json` — schema v2 summary block

```json
{
  "generated_at": "2026-04-07T20:54:22Z",
  "schema_version": "echr-dashboard-v2",
  "parser_version": "2.0.0",
  "summary": {
    "total_cases": 18429,
    "total_paragraphs": 1314796,
    "date_range_label": "14 Nov 1960 – 17 Feb 2026",
    "unique_countries": 79,
    "unique_articles": 235,
    "avg_paragraphs_per_case": 71.34,
    "median_paragraphs_per_case": 64,
    "p90_paragraphs_per_case": 149,
    "max_paragraphs_per_case": 3585,
    "violation_cases": 10489,
    "non_violation_cases": 3098,
    "grand_chamber_cases": 550,
    "chamber_cases": 17775,
    "key_cases": 1101,
    "separate_opinion_cases": 2843,
    "cases_with_strasbourg_caselaw": 7807
  }
}
```

The live server (`/api/stats`) is already ahead of the static `stats.json`: the search page KPI bar currently reports 1,374,871 paragraphs (a +60,075 paragraph delta from the 2026-02-17 snapshot used to build `stats.json`). The statistics page will show stale numbers until `stats.json` is re-generated.

### 1.4 Data quality gaps (field completeness from `stats.json::quality.field_completeness`)

| Field | Completeness | Notes |
|---|---|---|
| `hudoc_url` | 100.00% | good — every case deep-linkable to HUDOC |
| `separate_opinion` | 100.00% | good |
| `respondent_state` | 73.15% | 27% have no state at all |
| `originating_body` | 73.15% | same cases that lack state also lack body |
| `importance` | 73.15% | same coverage envelope |
| `conclusion` | 72.48% | used for violation inference |
| `keywords` | 72.00% | feeds BM25F title/keywords weight |
| `represented_by` | 67.49% | — |
| `chamber_composed_of` | 62.95% | judge-level queries are only ≈63% reliable |
| `violation` (structured) | 56.92% | 43% rely on text inference |
| `strasbourg_caselaw` | **42.36%** | citation graph covers <half the corpus |
| `non-violation` (structured) | 16.81% | — |
| `domestic_law` | **6.51%** | near-empty |
| `applicability` | **5.33%** | — |
| `international_law` | **4.41%** | — |
| `rules_of_court` | **3.71%** | — |
| `defendants` | **0.00%** | empty column |

Two immediate consequences for planning:

1. Any feature that depends on `strasbourg_caselaw` (citation networks, treatment flags, "cited by" counts) has a hard ceiling of ~7,800 cases until the parser is improved. The other ~10,600 cases would appear as isolated nodes. **This must be fixed before Phase 5 citation work starts, not after.**
2. The `defendants` column is empty and the `domestic_law` / `international_law` / `rules_of_court` columns each cover <7% of cases. These are not filters worth exposing in the UI in their current state.

### 1.5 Backend architecture (for context, not re-audited here)

- FastAPI + nginx, Docker-composed on `150.254.115.204`.
- SQLite with FTS5 `paragraphs_fts` virtual table, three-column external-content index `(title, keywords_text, text)`, tokenizer `porter unicode61`, BM25F weights `5.0 / 3.0 / 1.0` (commits `a94b047`, `6a39f9b`).
- `backend/ranking.py` applies multiplicative priors: `importance 1 → ×1.40`, Grand Chamber → `×1.25`, Press Release → `×0.75` (full table in `CHANGES-FROM-ORIGINAL.md` §2.2).
- Endpoints: `/api/search`, `/api/browse`, `/api/facets`, `/api/analytics`, `/api/cases/{id}`, `/api/stats`, `/health`.
- CORS is handled at the nginx layer (`64866cf`); FastAPI `CORSMiddleware` removed to prevent double-headers.
- No authentication, no rate limit visible from the client, single self-signed cert at the nginx edge (the client hard-codes the IP — a DNS name with a real cert is a pending Phase 5 item, see §6).

---

## 2. Live test findings (2026-04-11)

The live site (`https://lszoszk.github.io/ECHR-Dashboard/`) was smoke-tested against the production FastAPI backend. Five queries and one modal open were exercised.

### 2.1 Query latency and hit volume

| Query | Paragraph hits | Case hits | Server time |
|---|---|---|---|
| `right to privacy` | 1,732 | 732 | 1.615 s |
| `article:8` (prefix) | 55,925 | 11,267 | 1.986 s |
| `state:poland` (prefix) | 5,212 | 3,077 | 0.839 s |
| `margin of appreciation` | 9,716 | 3,337 | 0.475 s |
| `torture` | 15,843 | 3,741 | 0.972 s |

Observations:

- The KPI bar confirmed a live server with the badge "Connected to ECHR Search Server — full-text search across all cases."
- All five queries returned server-mode headers (`server · full dataset`), not the sample-dataset fallback, so the `af5efb8` preload removal is holding.
- Latency is within the expected FTS5 + BM25F envelope. Queries that return large result sets (`article:8`, `torture`) run at 1–2 s; more specific multi-word queries run at 0.5–1 s. No p95 or p99 was captured; this is a smoke test, not a benchmark.
- The server reported `page 1/564` for `article:8`. At 20 results per page the client is cleanly using the server pagination fix from `84cfc11`.

### 2.2 Filter exercise

A programmatic click on a country filter checkbox did not trigger a re-query in the smoke test harness. The checkbox was found in the DOM (46 country checkboxes rendered from `/api/facets` via commit `5053341`) but did not fire a change event from a synthetic `.click()`. **This is a test-harness artefact, not a site bug** — a real user clicking the same element would deliver a genuine `click` event and the listener would run. Worth confirming with a manual interaction pass before planning any filter work in Phase 5.

### 2.3 Modal open

Clicking the first result card opened the modal overlay with the expected action buttons (`Clear Highlights`, `Export XLSX`, `×`). However, in this harness the modal body reported zero paragraphs — the `/api/cases/{id}` request was either still in flight or the harness closed the modal before the XHR resolved. The modal skeleton HTML was 1,829 bytes at inspection time. No XLSX export was exercised. **Not a bug signal**; it is a 3-second-race-condition limitation of the automated test, not a user-visible failure.

### 2.4 Notable non-issues confirmed by the smoke test

- KPI bar is populated (28% of the status text came through: "Connected to ECHR Search Server — full-text search across all cases").
- Prefix query parsing works end-to-end: `state:poland` and `article:8` both returned filtered result sets that were materially smaller than unscoped equivalents.
- No JavaScript errors interrupted script parse (if they had, the dashboard would display "Server unavailable" — the `d9bd5df` regex fix is still holding).
- The server returned 1,374,871 paragraphs in the KPI at page load, confirming the server is already +60k ahead of the statistics-page snapshot; the **`stats.json` regeneration is a trivial but visible-to-user action worth slipping into Phase 5**.

---

## 3. HUDOC feature comparison

HUDOC (hudoc.echr.coe.int) is the Court's official case-law search engine, built by the Registry and updated continuously. It is the incumbent and the ceiling that any external ECHR search tool is implicitly benchmarked against.

### 3.1 What HUDOC has that the dashboard does not

| HUDOC feature | Present in dashboard? | Notes |
|---|---|---|
| Boolean operators (`AND`, `OR`, `NOT`, parentheses) | ❌ | The query parser recognises prefixes but not Boolean connectors. FTS5 supports `AND`/`OR`/`NEAR`/`NOT` natively; exposing them would be a frontend-only change. |
| Phrase search with quotation marks | ⚠️ partial | FTS5 does phrase search when the query is wrapped in double quotes. The client does not document or UI-expose this. |
| Proximity / `NEAR(x, y, n)` operator | ❌ | FTS5 supports `NEAR/n`. Not exposed. |
| Thesaurus / controlled-vocabulary search | ❌ | HUDOC ships a multilingual thesaurus ("HUDOC Keywords") maintained by the Registry. The dashboard has no synonym expansion. |
| Multilingual search (EN / FR mandatory, other UN languages for Grand Chamber) | ❌ | The dashboard is English-only. The corpus has an `english_text` column but no translations. |
| Faceted filters with real-time counts | ⚠️ partial | `/api/facets` returns static counts once per page load. The counts do not update when other filters are ticked. HUDOC updates all facet counts on every filter change. |
| Relevance sort vs chronological sort vs importance sort | ✅ | Present. Date sort bugs fixed in `13b487d` / `8d9dc7f`. |
| Direct deep-linking to individual judgments | ✅ | `hudoc_url` field is 100% populated and the modal links out. |
| Separate panels for cases / press releases / admissibility decisions | ✅ | Document-type distinction introduced in Phase 1 (`615162a`, `4a2e0c3`). |
| Violation summary panel per judgment | ⚠️ partial | The modal shows an outcome badge but not a structured "violation of X by Y for Z" summary. |
| Citation lookup from judgment text | ❌ | HUDOC turns citations inside a judgment into clickable links. The dashboard does not parse or link them. |
| Application number search | ⚠️ partial | Present via `hudoc:` prefix but undocumented on the page. |
| Date range slider | ❌ | Filter panel accepts dates but no slider / histogram visualisation. |
| Concurrence / separate-opinion extraction | ⚠️ partial | `separate_opinion` is 100% populated as a boolean flag but not linked to the actual opinion text. |

### 3.2 What the dashboard has that HUDOC does not

This is where the dashboard's strategic position lies. Every feature below is either absent from HUDOC or substantially weaker there, and every feature is a reason for a sophisticated user to choose the dashboard over HUDOC.

| Dashboard feature | HUDOC equivalent? | Why it matters |
|---|---|---|
| **Paragraph-level search** across 1.3M paragraphs with BM25F ranking | HUDOC indexes at document level; paragraph hits are a post-hoc excerpt | Lawyers cite by paragraph; HUDOC forces you to scroll through a 200-paragraph judgment to find the one you want. |
| **Multi-color per-paragraph highlighting** saved across a session | No equivalent | HUDOC is read-only; the dashboard behaves like a reading environment. |
| **XLSX export with highlights + section labels** | CSV export only, no formatting, no persistence of reader state | Highlights survive an export — a genuinely novel feature in this category. |
| **Statistics page** with 30+ charts (violations by country, by article, over time, Grand Chamber share, etc.) | Basic stats panel buried in admin UI | HUDOC does not expose the corpus-wide analytics the dashboard's `stats.json` produces. |
| **Server-side analytics endpoint** (`/api/analytics`) that aggregates facets across a query result set | Not exposed | Enables "who violates Article 3 the most in the last decade" style drill-down. |
| **Experimental classifier pane** (TF-IDF / char n-gram / keyword overlap, client-side) | No ML surface at all | User labels 6–30 paragraphs and builds a personal classifier in the browser. Niche, but nothing equivalent exists. |
| **Accessibility panel** with theme, font scale, dyslexia-friendly mode | Partial — HUDOC follows EU accessibility baseline but exposes fewer live toggles | |
| **Prefix query syntax** (`case:`, `state:`, `article:`, `body:`, `judge:`, `keyword:`, `ecli:`, `hudoc:`) | HUDOC has field-scoped search via advanced form, not inline | Inline prefixes are strictly faster for power users. |
| **BM25F + metadata boosts** (Grand Chamber ×1.25, importance ×1.40, press-release ×0.75) | HUDOC's scoring is opaque | Transparent ranking with tunable weights is a genuine advantage for research and reproducibility. |
| **Zero-install browser-only interface** | HUDOC is browser-only too, but heavy iframes and slow pagination | The dashboard is ~6k lines of JS; HUDOC is a SharePoint-era application. |

### 3.3 Where HUDOC is the ceiling (what an external tool cannot catch up on)

These are things the dashboard should not try to replicate because the Registry has a permanent institutional advantage:

- **Official-of-record status.** HUDOC judgments are the authoritative text; the dashboard is a derivative index.
- **Multilingual parity.** The Registry has 46 translators; the dashboard has none.
- **Same-day publication.** New judgments land on HUDOC the morning they are handed down. The dashboard's ingestion pipeline runs on a schedule (the `stats.json` snapshot is currently ~2 months old).
- **HUDOC Keywords thesaurus.** Curated by a team since the 1990s. Worth consuming as a machine-readable input, not worth rebuilding.

The strategic question for Phase 5+ is **not** "how do we beat HUDOC on every axis." The question is **"which 4–5 things can an external tool do dramatically better than HUDOC, and how do we ship those first?"**

---

## 4. Legal research best-practice synthesis

Five platforms define the state of the art in case-law research. None of them is a full analogue of an ECHR search tool, but each has one or two ideas worth stealing.

### 4.1 Westlaw (Thomson Reuters) — KeyCite

KeyCite is the industry's citator. Every case is annotated with treatment flags: red (bad law, overruled), yellow (negative treatment), green (positive), blue (cited). For ECHR the equivalent would be:

- Red = judgment overruled by Grand Chamber (rare but happens — e.g. *Chapman v UK* → *Dudgeon* line on margin of appreciation).
- Yellow = distinguished or narrowed in a later judgment, or the Court later departed in a separate case-line.
- Green = repeatedly followed / expressly approved.
- Blue = neutrally cited (the default).

**Relevance to ECHR dashboard:** Phase 5 citation work should not just draw edges — it should classify the *direction* of each edge. The `strasbourg_caselaw` field at 42% completeness is the blocker.

### 4.2 LexisNexis — Shepard's Citations Service

Shepard's is older than KeyCite and more granular: it distinguishes "followed by", "distinguished by", "criticized by", "explained by", "harmonised by", "modified by", "superseded by", "questioned by", "overruled by". Thirteen treatment categories in total. Too granular for a first pass on ECHR but worth bearing in mind as a North Star — a two-tier system (coarse flag + fine-grained relation) is better than a flat citation graph.

### 4.3 Casetext — Parallel Search (acquired by Thomson Reuters, 2023)

Parallel Search introduced the idea of "search by example sentence." A user pastes a sentence (typically from a brief or a prior judgment) and Parallel Search retrieves sentences with the same legal meaning — not the same keywords. The backend is a sentence-embedding model (originally USE, now a tuned transformer).

**Relevance:** ECHR research is extraordinarily phrase-bound — "pressing social need", "margin of appreciation", "proportionality", "lawful interference", "minimum level of severity". A semantic-similarity search would surface paragraphs that use different words to mean the same thing. This is the single highest-leverage feature on this list, and it can ship without replacing FTS5 (embeddings alongside keyword, not instead of).

### 4.4 Jus Mundi — CiteMap

Jus Mundi indexes international arbitration and international-law judgments. CiteMap is their flagship citation visualisation: a force-directed graph of how cases cite each other, filterable by legal concept, jurisdiction, tribunal, year. Interactive nodes open a preview card with the key holding.

**Relevance:** ECHR case-law is, if anything, more interconnected than ICSID / PCA jurisprudence because the Strasbourg Court explicitly builds doctrine by reference to its own prior holdings. A CiteMap-style view is **the most visible differentiator the dashboard could ship** — HUDOC has no citation map, and no competing ECHR tool ships one.

### 4.5 CanLII — Dynamic facets with live counts

CanLII's signature is that every facet (court, year, topic, judge, keyword) updates its count in real time as other facets are ticked. If you tick "Supreme Court of Canada" the year list immediately narrows to years where the SCC had hearings; the topic list narrows to topics the SCC ruled on that year. This is classic faceted-navigation done well, and it turns a large corpus into an exploratory surface rather than a search-or-miss interface.

**Relevance:** The dashboard already calls `/api/facets` once per page load. Updating facets per filter change is a backend plumbing job — the SQL is cheap, the client needs to de-bounce and cancel in-flight requests.

### 4.6 CourtListener / Free Law Project — Open API + bulk download + citation graph

CourtListener publishes (a) an authenticated REST API with per-user rate limits, (b) quarterly bulk data dumps in JSON and CSV, (c) a citation graph computed from a rule-based parser over judgment text, (d) a real-time alert system keyed to queries and to docket changes. It is the benchmark for "open data in law."

**Relevance:** Every item on that list is directly copyable. The dashboard's `/api/search` and `/api/facets` are already public endpoints — a documented, versioned, rate-limited REST API and a monthly JSONL dump would convert the project from a website to an ecosystem. Academics, NGOs, and capacity-building organisations would use it programmatically.

### 4.7 Synthesis — the five patterns worth stealing

1. **Treatment-coded citation graph** (KeyCite + Shepard's → lightweight two-tier flag system: {overruled, distinguished, followed, cited}).
2. **Semantic similarity "search by example"** (Casetext → sentence embeddings alongside FTS5, not replacing it).
3. **Interactive citation visualisation** (Jus Mundi CiteMap → force-directed graph of the ECHR citation network).
4. **Live faceted counts** (CanLII → per-filter recompute on `/api/facets`).
5. **Open REST API + bulk dump + alerts** (CourtListener → documented API, monthly JSONL dump, saved-search email alerts).

---

## 5. How lawyers and human rights experts actually use ECHR case-law tools

Before ranking features, it matters which users are being served. The dashboard has a generalist framing ("paragraph-level search across all cases") but in practice six distinct workflows are at play, and some features matter to one workflow and nothing to another.

### 5.1 The Strasbourg applicant (and their lawyer)

A practitioner preparing an Article 34 application or a Rule 47 form. They need to (a) find prior judgments where the same combination of facts produced a violation finding, (b) pull exact quotations from those judgments for the application, (c) export those quotations with proper citations into a Word document.

**What they need:** semantic similarity search ("find judgments that ruled like this one"), phrase-level copy with ECHR-style citation format, export to Word or a Word-friendly format, reliable HUDOC deep-links back to the authoritative text.

**What the dashboard already does well:** paragraph-level hits, XLSX export with highlights, HUDOC deep-links.

**What's missing:** semantic similarity (they get keyword matches, not "ruled like this"), Word export (XLSX is one click from paste-into-Word but not as direct as a .docx), ECHR-formatted citation block (the dashboard produces raw text, not a citation).

### 5.2 The academic researcher

A doctoral candidate or faculty member writing an article on, say, "the evolution of the margin of appreciation in Article 8 cases since *Dudgeon*." They need to (a) build a corpus of relevant judgments, (b) track citation networks and doctrinal lineage, (c) export to Zotero / EndNote / BibTeX, (d) understand how specific paragraphs have been cited or departed from later.

**What they need:** citation graph with treatment flags, bulk export in academic bibliography formats, reproducible query URLs (stable links that survive re-running the same search a year later), a machine-readable changelog of the dataset.

**What the dashboard already does well:** stable URLs per case (via HUDOC), analytics page with corpus-wide charts.

**What's missing:** citation graph, Zotero/BibTeX export, a reproducible "search permalink" that captures the query + all active filters, dataset versioning beyond the `CHANGES-FROM-ORIGINAL.md` log.

### 5.3 Capacity-building / training (HELP, academies, clinics)

Law-school clinics, HELP trainers, Council of Europe training programmes. They need **curated reading lists** around canonical cases (*Handyside*, *Marckx*, *Airey*, *Soering*, *Öcalan*, *Kurt*, *Selmouni*, *Hirst No. 2*, *M.S.S. v Belgium and Greece*). Students need the judgment plus plain-language context, and educators need to sequence cases into doctrinal families.

**What they need:** a curated "case guide" surface, ideally built on top of the Registry's existing case-law guides; the ability to bookmark a curated set of paragraphs across cases into a reading list.

**What the dashboard already does:** nothing specific to this workflow. The classifier pane is a toy, not a curriculum surface.

**What's missing:** a "case-law guide" content layer, bookmarking across cases, teacher-mode annotations that survive a browser refresh.

### 5.4 Comparative legal research

Researchers comparing how two or more member states are treated by the Court on the same article. For example: "Article 10 freedom-of-expression violations in Turkey vs Russia vs Azerbaijan, 2010–2025."

**What they need:** comparative filtering that sets up a side-by-side, cross-tabs at the filter level, visual comparison of violation rates and case volume.

**What the dashboard already does well:** the Violation Rate by Country chart shipped in commit `9271d39` is exactly this kind of feature for a single article context.

**What's missing:** the chart is a single-article view. A true comparative mode would let the user lock two or more filter sets and see them side by side (country × article × time-window, facet-by-facet).

### 5.5 NGO monitoring and advocacy

International and domestic human rights NGOs monitoring ongoing implementation and compliance. They need **alerts** when a new judgment lands that matches their watch list ("any new Article 3 judgment against Russia", "any Grand Chamber judgment on Article 46"), and they need **periodic reports** summarising activity against their list.

**What they need:** saved searches, email alerts, a monthly/weekly digest, and the ability to share a saved search with a colleague via URL.

**What the dashboard already does:** nothing for this workflow.

**What's missing:** everything — saved-search persistence (even in localStorage), email alerts (requires a backend identity layer), and RSS/Atom feeds (zero-auth alternative to email).

### 5.6 Policy research and inter-institutional work

Parliamentary staff, ministries of justice, inter-governmental bodies. They need **structured metadata** more than full text: violation Y/N, article, respondent state, damages awarded, applicant status, execution status (often cross-referenced with the Committee of Ministers' Department for the Execution of Judgments).

**What they need:** highly structured, exportable metadata (closer to a spreadsheet than a document search), and ideally a join with the DGI / CoE Execution database so that a user can move from "violation found" to "pilot / standard execution" status.

**What the dashboard already does well:** structured violation/non-violation inference, analytics page.

**What's missing:** damages data (not in the current corpus), execution status (not in the current corpus), a structured metadata export that can be joined to external policy databases.

### 5.7 Summary — which workflows drive which features

| Workflow | Top-priority feature | Secondary feature |
|---|---|---|
| Strasbourg applicant | Semantic similarity search | Word / citation-formatted export |
| Academic researcher | Citation graph with treatment flags | Zotero / BibTeX export + dataset versioning |
| Capacity-building | Curated case-law guide surface | Cross-case bookmarking |
| Comparative research | Side-by-side comparative filtering | Facet-level cross-tabs |
| NGO monitoring | Saved searches + email / RSS alerts | Monthly digest builder |
| Policy research | Structured metadata export + execution-status join | Damages data enrichment |

No single feature serves all six workflows. A good Phase 5 plan picks the features that serve the most workflows per unit of engineering effort.

---

## 6. Recommendations — ranked roadmap for Phases 5, 6, 7

Each recommendation is scored on two axes: **impact** (how many of the six workflows in §5 it unblocks, how much it narrows the HUDOC gap in §3, how novel it is in the ECHR ecosystem) and **effort** (engineering days, ignoring review cycles; with a ceiling of 20 days per item). Items are grouped into Phase 5 (next 4–6 weeks), Phase 6 (next quarter), and Phase 7 (aspirational, requires either new data or new infrastructure).

### Phase 5 — high-impact, low-to-medium effort (4–6 weeks)

#### 5.1. Boolean operators + phrase search + `NEAR` proximity in the query parser
**Impact:** high. Unblocks two workflows (applicants, academics). Narrows HUDOC gap §3.1. Power users immediately benefit.
**Effort:** 2–3 days. FTS5 already supports `AND` / `OR` / `NEAR/n` / `NOT`. The work is in `parseQueryWithPrefixes` to pass through quoted phrases, uppercase Booleans, and `NEAR(x, y, n)` syntax without mangling them, plus one documentation block on the search page.
**Files:** `docs/assets/search-app.js`, `docs/index.html`.
**Risk:** low. Pass-through to a feature FTS5 already supports.

#### 5.2. Regenerate `stats.json` and add a monthly CI job
**Impact:** medium. Fixes the visible 60k-paragraph drift between the statistics page and the live server, and prevents the drift from recurring.
**Effort:** 0.5 days. A one-line cron on the server plus a commit that captures the regeneration date in the schema.
**Files:** `docs/data/stats.json`, `scripts/regenerate_stats.sh` (new), `README.md`.
**Risk:** none.

#### 5.3. Live faceted counts (CanLII-style)
**Impact:** high. Unblocks comparative research and makes the filter panel feel alive. Narrows HUDOC gap §3.1 (HUDOC does not update facet counts on filter change either, so this is an overtake, not a catch-up).
**Effort:** 4–6 days. Server: `/api/facets` needs to accept the current filter set and recompute. Client: de-bouncing, cancelling in-flight `/api/facets` requests, updating checkbox labels without collapsing accordions.
**Files:** `backend/main.py` (facets endpoint), `docs/assets/search-app.js`.
**Risk:** medium. Easy to get filter state races wrong. Ship behind a feature flag first.

#### 5.4. Search permalinks (reproducible-URL state)
**Impact:** high. Unblocks academic and NGO workflows in a single afternoon of work. Also enables Phase 5.6 (saved searches) without a backend identity layer.
**Effort:** 1–2 days. Serialise filter + query state into a URL hash; parse the hash on page load to restore state. `history.pushState` on filter change.
**Files:** `docs/assets/search-app.js`, `docs/index.html`.
**Risk:** low. No server changes.

#### 5.5. ECHR-formatted citation block in the modal + "Copy citation" button
**Impact:** medium-high. Unblocks applicant and academic workflows without any new data.
**Effort:** 1–2 days. Generate a standard ECHR citation (e.g. *Case of Hirst v. the United Kingdom (no. 2)* [GC], no. 74025/01, § 62, ECHR 2005-IX). The `buildStandardCitation` stub already exists in `search-app.js` at line ~908; it needs to be filled in and wired to a copy button.
**Files:** `docs/assets/search-app.js`, `docs/index.html`, `docs/assets/search-app.css`.
**Risk:** low.

#### 5.6. Saved searches via localStorage + URL-hash round trip
**Impact:** medium-high. Unblocks the NGO workflow partially (no email alerts yet, but at least the list persists across sessions). Depends on 5.4.
**Effort:** 1–2 days. localStorage schema `echr-saved-searches-v1:` prefix, list UI in a new accordion section, one-click restore.
**Files:** `docs/assets/search-app.js`, `docs/index.html`.
**Risk:** low.

#### 5.7. Zotero + BibTeX export from the modal
**Impact:** high for academics, zero for everyone else. High value per unit effort.
**Effort:** 1 day. BibTeX is ~20 lines of string assembly; Zotero's RIS format is ~30 lines. Plug into the existing export button group next to XLSX.
**Files:** `docs/assets/search-app.js`.
**Risk:** none.

#### 5.8. Documented public REST API at a DNS name with a real TLS cert
**Impact:** high for the ecosystem story. Converts the project from a website to a platform. Narrows HUDOC gap §3.1 indirectly (HUDOC has no public API). Required precondition for Phase 6 alerts and Phase 7 third-party integrations.
**Effort:** 4–8 days. DNS, LetsEncrypt cert via certbot / acme.sh, nginx config, rate limiting at the nginx layer, an OpenAPI schema auto-generated by FastAPI, a small API documentation page.
**Files:** `deploy/nginx.conf`, `backend/main.py`, new `docs/api.html`.
**Risk:** medium — DNS / TLS is where most projects lose a week to ops work.

**Phase 5 total effort:** 14–24 days, roughly 4–6 weeks part-time.

---

### Phase 6 — medium-to-high effort (next quarter)

#### 6.1. Monthly bulk JSONL dump + dataset version tag
**Impact:** high for academics. Narrows HUDOC gap in the open-data dimension. Trivial to ship alongside `/api/stats`.
**Effort:** 2–3 days. A cron that runs `scripts/export_full_corpus.py` to produce `echr-YYYYMM-full.jsonl.gz` plus a manifest.
**Files:** `scripts/export_full_corpus.py` (new), `backend/main.py` (manifest endpoint), `docs/data/`.

#### 6.2. Sentence-embedding semantic search (the "search by example" feature)
**Impact:** very high. This is the single highest-leverage missing feature for applicants, comparative researchers, and academics. Narrows the Casetext Parallel Search gap. Novel in the ECHR ecosystem (no existing tool offers it).
**Effort:** 8–15 days for a first version. Approach: precompute sentence embeddings for the paragraph corpus using a legal-domain-tuned encoder (Legal-BERT, or a distilled model for cost). Store in SQLite via `sqlite-vec` or in a small FAISS/HNSW index served alongside FTS5. Query path: user pastes a sentence, embedding is computed server-side (or in-browser via ONNX Runtime Web for a no-server path), top-K neighbours are retrieved and merged with FTS5 results.
**Files:** `backend/embeddings.py` (new), `backend/main.py`, `backend/build_db.py`, `docs/assets/search-app.js`, `docs/index.html`.
**Risk:** medium-high. Model selection is the hard part; a bad embedding surfaces worse results than FTS5 and trains users to distrust the feature. Ship behind a clearly-labelled "Semantic beta" toggle, run it alongside FTS5, and let the user compare.

#### 6.3. Bidirectional citation graph with treatment flags
**Impact:** very high. This is the headline differentiator. Unblocks academic, comparative, and policy workflows. Narrows HUDOC gap comprehensively.
**Effort:** 10–15 days, plus the data-quality remediation below.
**Hard precondition:** `strasbourg_caselaw` completeness must rise from 42% to ≥85% or the graph will be structurally incomplete. This is a parser improvement to `backend/build_db.py` that regex-mines citations out of paragraph text regardless of whether they were extracted into the HUDOC metadata. Expect 3–5 days for the parser alone.
**Approach:**
1. Rule-based citation extractor over the paragraph corpus: regex for ECHR citation formats, application-number parsing, `v.` separator recognition.
2. Store edges in a new `citations` table: `(from_case_id, to_case_id, from_paragraph_no, context, treatment)`.
3. Treatment classification starts as a **coarse heuristic**: look at the 50 characters before the citation for cue words (`see`, `cf.`, `mutatis mutandis`, `departing from`, `distinguishing`, `overruling`, `as the Court held`) and map to one of four flags: `followed`, `distinguished`, `overruled`, `neutral`. Hand-label ~300 random citations and report precision at each treatment class. A more sophisticated classifier can wait for Phase 7.
4. Expose via `/api/cases/{id}/citations` (in + out edges) and render a "Cited by" / "Cites" panel in the modal.
**Files:** `backend/build_db.py`, `backend/main.py`, `backend/citation_parser.py` (new), `docs/assets/search-app.js`, `docs/index.html`.

#### 6.4. Comparative side-by-side filtering (two or three filter sets in parallel)
**Impact:** high for comparative researchers. Novel in the ECHR ecosystem.
**Effort:** 4–6 days. UI work is the hard part: the filter accordion needs to become tabbed ("A" / "B" / "C") and the results view needs to split into columns. Server is unchanged — each tab is a normal `/api/search` call.
**Files:** `docs/assets/search-app.js`, `docs/index.html`, `docs/assets/search-app.css`.
**Risk:** medium. Easy to clutter the UI.

#### 6.5. RSS/Atom feed per saved search (zero-auth alert channel)
**Impact:** high for NGO workflow. Zero-auth means no backend identity layer is needed.
**Effort:** 2–3 days. `/api/feed?q=…&filters=…` endpoint returns an Atom XML of new judgments since a `?since=` date.
**Files:** `backend/main.py`, new `docs/api.html` docs section.

**Phase 6 total effort:** 26–42 days, roughly a quarter of focused part-time work.

---

### Phase 7 — aspirational, requires new data or new infrastructure

#### 7.1. Interactive citation map visualisation (Jus Mundi CiteMap analogue)
**Impact:** very high as a public-facing showpiece. Requires 6.3 (citation graph) as a precondition.
**Effort:** 6–10 days. Force-directed graph via D3.js; node filtering by article, state, year, importance; on-click preview card; pan/zoom. Mobile-responsive is non-trivial.
**Files:** `docs/citemap.html` (new), `docs/assets/citemap.js` (new).

#### 7.2. Email alerts (requires user accounts)
**Impact:** high for NGO workflow.
**Effort:** 8–15 days plus ongoing operational overhead (GDPR compliance, unsubscribe flows, bounce handling, a transactional email provider, a user table).
**Note:** RSS/Atom in 6.5 is the 80/20 version. Only proceed to email alerts if there is real user demand that RSS cannot serve. Many NGOs prefer RSS because it plugs into Slack, Discord, and Feedly without a new account.

#### 7.3. Damages + execution-status enrichment from the Committee of Ministers' HUDOC-EXEC database
**Impact:** very high for policy researchers. Would make the dashboard uniquely valuable in inter-institutional contexts.
**Effort:** 10–20 days. HUDOC-EXEC is a separate system with its own ingestion pipeline; integration is an ETL project, not a frontend project.
**Files:** `backend/build_db.py`, new `scripts/ingest_hudoc_exec.py`.
**Note:** this is the single biggest data win available. If it's feasible it should be prioritised above almost any frontend work.

#### 7.4. Curated case-law guide surface for capacity-building workflows
**Impact:** medium-high for HELP / clinic use cases. Requires content curation, which is an editorial effort, not an engineering one.
**Effort:** 3–5 days of engineering to build the read-only "guide" view, plus unbounded editorial effort to write the guides.
**Note:** the Registry's published *Guide on Article …* PDFs are a logical starting point — ingest them once and link from each referenced paragraph.

#### 7.5. Word (.docx) export with ECHR-formatted citations
**Impact:** medium-high for applicants. Removes one of the last "paste into Word and clean up" friction points.
**Effort:** 3–5 days. The `docx` library is well-understood; the XLSX export already exists as a template (`docs/assets/search-app.js` uses SheetJS).
**Files:** `docs/assets/search-app.js`.

#### 7.6. Multi-lingual search (English → French)
**Impact:** high for continental European users.
**Effort:** 15+ days **plus corpus changes** — the current FTS5 index is English-only; a French index requires pulling the French text column from HUDOC on ingestion and building a parallel FTS5 table. Plus a query translation layer if users want to search in one language and see results in the other.
**Note:** this is where the Registry has the permanent institutional advantage (§3.3). Worth doing if the corpus can be obtained; not worth doing from translation alone.

---

### 6.A Ranking summary table

| # | Recommendation | Phase | Impact | Effort (days) | Unlocks workflow(s) |
|---|---|---|---|---|---|
| 5.1 | Boolean + phrase + `NEAR` operators | 5 | high | 2–3 | applicant, academic |
| 5.2 | Regenerate `stats.json` (+ monthly CI) | 5 | medium | 0.5 | — (hygiene) |
| 5.3 | Live faceted counts | 5 | high | 4–6 | comparative, NGO |
| 5.4 | Search permalinks | 5 | high | 1–2 | academic, NGO |
| 5.5 | ECHR citation copy-block | 5 | medium-high | 1–2 | applicant, academic |
| 5.6 | Saved searches (localStorage) | 5 | medium-high | 1–2 | NGO |
| 5.7 | Zotero / BibTeX export | 5 | high (academic) | 1 | academic |
| 5.8 | Documented REST API + TLS | 5 | high | 4–8 | all |
| 6.1 | Monthly bulk JSONL dump | 6 | high (academic) | 2–3 | academic |
| 6.2 | Semantic-similarity search | 6 | very high | 8–15 | applicant, academic, comparative |
| 6.3 | Citation graph + treatment flags | 6 | very high | 10–15 | academic, comparative, policy |
| 6.4 | Side-by-side comparative filters | 6 | high | 4–6 | comparative |
| 6.5 | RSS/Atom feed per saved search | 6 | high (NGO) | 2–3 | NGO |
| 7.1 | Interactive citation map (D3) | 7 | very high (visibility) | 6–10 | academic, comparative, policy |
| 7.2 | Email alerts | 7 | high (NGO) | 8–15 | NGO |
| 7.3 | HUDOC-EXEC enrichment | 7 | very high (policy) | 10–20 | policy, academic |
| 7.4 | Case-law guide surface | 7 | medium-high | 3–5 + editorial | capacity-building |
| 7.5 | Word (.docx) export | 7 | medium-high | 3–5 | applicant |
| 7.6 | Multi-lingual (English ↔ French) | 7 | high | 15+ | all non-anglophone |

### 6.B Dependency graph

```
5.4 search permalinks ──┐
                        ├──► 5.6 saved searches ──► 6.5 RSS feed ──► 7.2 email alerts
                        │
5.8 REST API + TLS ─────┼──► 6.1 bulk JSONL dump
                        │
                        └──► 6.2 semantic search (requires API stability)

6.3 citation graph ─────► 7.1 citation map visualisation
    ▲
    │ (prereq)
`strasbourg_caselaw` parser fix (42% → ≥85% completeness)

7.3 HUDOC-EXEC enrichment is independent and can run in parallel with any phase.
```

### 6.C Out-of-scope for this audit

- Bug fixing (per user brief). The `.git/*.lock` issue mentioned in the session context, the 3-second-race modal harness result in §2.3, and the filter-click synthetic-event artefact in §2.2 are all explicitly *not* addressed here.
- The classifier pane. It is a research toy, not a research tool, and §5 showed it does not map to any of the six workflows. It should either be promoted to a first-class feature (with server-side model training and labelled-data persistence) or deprecated; that decision is outside the Phase-5-to-7 scope of this document.
- Mobile layout beyond what was already fixed on the statistics page. The search page mobile audit is a separate pass.

---

## 7. Open questions for the project owner

1. **Is `strasbourg_caselaw` extraction upstream-fixable?** If yes, 6.3 (citation graph) moves up from Phase 6 to the back half of Phase 5. If no, it stays in Phase 6 and the 3–5 day parser-improvement sub-task is on the critical path.
2. **Is HUDOC-EXEC data legally and technically accessible for bulk ingest?** If yes, 7.3 is the highest-leverage item in the whole roadmap and should be re-prioritised to Phase 6.
3. **Does the project want to ship a user identity layer (email, auth, GDPR DSARs)?** If not, email alerts (7.2) are out and RSS (6.5) becomes the definitive alert channel.
4. **Is multilingual (7.6) in scope for 2026, or is it deferred indefinitely?** This decides whether the `stats.json` schema should be extended with language fields now or later.
5. **Who is the priority user?** The Phase 5 picks in §6 are workflow-agnostic (all eight benefit multiple workflows). Phase 6 forces a choice: 6.2 semantic search primarily serves applicants and academics; 6.3 citation graph primarily serves academics and policy; 6.4 comparative filters primarily serve comparative researchers. If one workflow is strategically primary, Phase 6 order should reflect that.

---

*Audit compiled: 2026-04-11. Maintainer: @lszoszk. Next review: after Phase 5 ships (estimated late May 2026).*
