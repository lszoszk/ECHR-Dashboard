# TODO — Phase 2: Rebuild a true PROCEDURE / CIRCUMSTANCES classifier

**Status:** deferred (expensive)
**Prerequisite commit:** the Phase 1 merge of `facts_background` + `facts_proceedings` into a single `facts` bucket (commit `20260410-factsmerge`).
**Owner:** unassigned

---

## Why this is on the backlog

Phase 1 resolved the immediate user-visible problem — two upstream labels ("Facts Background" ≈ 36k paragraphs and "Facts Proceedings" ≈ 438k paragraphs) were semantically inverted versus the HUDOC convention and produced a 92 : 8 imbalance that made the filter useless. The Phase 1 fix is to merge them into a single `facts` UI bucket and document the tradeoff.

Phase 2 is the "proper" fix: reclassify paragraphs against the *actual* HUDOC document structure so the dashboard can expose separate, accurate PROCEDURE and CIRCUMSTANCES filters again.

---

## What the HUDOC convention actually is

Based on direct inspection of live judgments on hudoc.echr.coe.int (Hirst v UK No. 2 [GC] 2005, T.M.V. v Romania 2024, Vokáč v Czech Republic 2022, Di Giuseppe v Italy 2023) and the Court's published *Note explaining the mode of citation*:

### Classical Chamber / Grand Chamber template

```
PROCEDURE                              ← ~5-15 short administrative paragraphs
    (who lodged, composition,
     interveners, admissibility
     decision, hearing date, etc.)

THE FACTS
  I.  THE CIRCUMSTANCES OF THE CASE    ← the substantive narrative (the bulk)
      A.  Background
      B.  The applicant's arrest
      C.  ...
  II. RELEVANT DOMESTIC LAW AND PRACTICE
  III. RELEVANT INTERNATIONAL MATERIALS

THE LAW
  I.  ALLEGED VIOLATION OF ARTICLE ...
```

### Committee summary template (since 1 September 2021)

```
SUBJECT MATTER OF THE CASE             ← merged facts + procedure
    (or "FACTS AND PROCEDURE")

THE COURT'S ASSESSMENT
```

The current upstream segmenter's labels do NOT follow either convention — its "Facts Background" class contains matter that is actually the substantive narrative, and its "Facts Proceedings" class is a catch-all that sweeps up the substantive narrative plus parts of the legal assessment. The split is unreliable and cannot be rescued by simple relabeling.

---

## Goals of Phase 2

1. Produce per-paragraph classifications that reflect real HUDOC structure:
   - `procedure` — short admin section (lodging date, composition, interveners, hearing, admissibility ruling history, friendly-settlement negotiations)
   - `circumstances` — substantive applicant narrative and facts as found by the Court
   - `subject_matter` — merged bucket for post-2021 Committee summaries
   - Keep existing labels for `merits`, `admissibility`, `just_satisfaction`, `legal_framework`, `legal_context`, `article_46`, `operative_part`, `separate_opinion`, `appendix`, `introduction` unchanged.
2. Rebuild the `paragraphs` table with the new `section` values. No changes required to `cases`.
3. Re-expose three UI buckets in the dashboard: `procedure`, `facts` (for classical Chamber/GC cases) or `subject_matter` (for post-2021 Committee cases). Keep the Phase 1 `facts` bucket as a compatibility alias that selects all three.
4. Keep the legacy column around during the rebuild so a rollback is possible.

## Non-goals

- Changing paragraph IDs or ordering.
- Revisiting the ranking pipeline (already tuned in Phase 1 — see `backend/ranking.py`).
- Adding new dense-retrieval models.

---

## Proposed approach

The key insight is that HUDOC judgments use **stable, verbatim heading strings** in uppercase that mark section boundaries. A rule-based heading detector will handle the vast majority of cases without an ML model.

### Step 1 — harvest the structural headings that already exist in the corpus

Inside each judgment, most paragraphs begin with (or consist of) one of a small set of canonical headings:

- `PROCEDURE`
- `THE FACTS`
- `I. THE CIRCUMSTANCES OF THE CASE` (and sub-headings `A.`, `B.`, …)
- `II. RELEVANT DOMESTIC LAW AND PRACTICE` (and variants)
- `III. RELEVANT INTERNATIONAL [LAW|MATERIALS|STANDARDS]`
- `THE LAW`
- `I. ALLEGED VIOLATION OF ARTICLE …`
- `SUBJECT MATTER OF THE CASE`
- `FACTS AND PROCEDURE` (post-2021 Committee)
- `THE COURT'S ASSESSMENT`
- `FOR THESE REASONS, THE COURT …`

Query the existing paragraphs table with a regex like `^[A-ZÉÀÈÙÂÊÎÔÛÇ0-9\s.()"'/:,\u201C\u201D\u2018\u2019\u2013\u2014-]+$` (the same pattern used by the modal's `HEADING_ONLY_RE` in `docs/assets/search-app.js` after the `20260410-regexfix` fix) to extract heading-only paragraphs, then tally the distinct strings. Expect a long tail but a heavy head: the top ~30 strings will cover >90% of cases.

### Step 2 — build a deterministic segmenter

Walk each case's paragraphs in order. Maintain a state variable `current_section` that flips on heading matches:

```python
HEADING_PATTERNS = [
    (re.compile(r"^\s*PROCEDURE\s*$", re.I),                    "procedure"),
    (re.compile(r"^\s*THE FACTS\s*$", re.I),                    "facts_parent"),
    (re.compile(r"^\s*I[.\s]+THE CIRCUMSTANCES", re.I),         "circumstances"),
    (re.compile(r"^\s*II[.\s]+RELEVANT DOMESTIC", re.I),        "legal_framework"),
    (re.compile(r"^\s*III[.\s]+RELEVANT INTERNATIONAL", re.I),  "legal_context"),
    (re.compile(r"^\s*THE LAW\s*$", re.I),                      "merits"),
    (re.compile(r"^\s*SUBJECT MATTER OF THE CASE", re.I),       "subject_matter"),
    (re.compile(r"^\s*FACTS AND PROCEDURE", re.I),              "subject_matter"),
    (re.compile(r"^\s*THE COURT[’']S ASSESSMENT", re.I),        "merits"),
    (re.compile(r"^\s*FOR THESE REASONS", re.I),                "operative_part"),
    # ... plus 20+ more harvested in Step 1
]
```

A paragraph that matches any pattern becomes the new boundary; subsequent paragraphs inherit that `current_section` until the next match. Handle the `facts_parent` marker by resetting on the first sub-heading.

### Step 3 — fallback for cases with non-canonical structure

Cases that don't match any classical heading (decisions, inadmissibility rulings, press releases) should fall back to a small classifier or to `unknown` — better than mis-labelling them. For the ~5% edge cases, consider:

- Rule: if a case has `document_type == "press release"` → `press_release` (already exists).
- Rule: if a case contains `SUBJECT MATTER OF THE CASE` anywhere → apply the Committee template.
- ML fallback: lightweight TF-IDF classifier trained on the successfully-segmented ~95% as gold labels.

### Step 4 — rebuild the index

- Add a new column `paragraphs.section_v2` instead of overwriting `section`. Backfill via a one-pass script.
- Update `backend/build_db.py::_SCHEMA_SQL` and the INSERT tuple to carry both columns.
- Update `backend/main.py::search()` and `/api/facets` to read from `section_v2` behind a feature flag (e.g. `USE_V2_SECTIONS=true` env var).
- Ship the frontend change behind a query-string flag (`?sections=v2`) for A/B testing before making it default.

### Step 5 — update the frontend

In `docs/assets/search-app.js`:

- Add `procedure`, `circumstances`, `subject_matter` to `SECTION_ORDER`, `SECTION_LABELS`, `SECTION_COLORS`.
- Remove the Phase 1 `facts` merged bucket (or keep as a convenience checkbox that OR-selects all three).
- Update `SECTION_DB_NAMES` so `procedure → ["procedure"]`, `circumstances → ["circumstances"]`, etc.
- Bump the cache-buster.

### Step 6 — evaluation

Hand-label ~200 randomly sampled paragraphs from 50 cases spanning 2000–2024 and all originating bodies. Compute macro-F1 per class. Target: ≥0.85 macro-F1 on `procedure` and `circumstances` (the two classes that matter most for lawyers).

---

## Cost estimate

- **Engineering:** 2–4 days of focused work, excluding review cycles.
- **Compute:** rebuild of the SQLite `paragraphs` table takes 35–110 minutes (see Phase 1 notes in the ranking plan). Can run off-peak, no downtime if done against a copy.
- **Risk:** heading strings are mostly stable but a ~5% tail of cases will need a fallback; we may also discover new templates introduced by the Court after a given date that break the rules.

This is why Phase 1 (the merge) is shipping first — it unblocks users in one commit without any pipeline work, and Phase 2 can proceed without user-visible regressions because the merged bucket remains valid throughout.

---

## Files that will change in Phase 2

- `backend/build_db.py` — schema update, new column, new INSERT tuple.
- `backend/main.py` — FTS5 column routing, `/api/facets` section list.
- `scripts/resegment_sections.py` — **new**, runs the rule-based segmenter.
- `docs/assets/search-app.js` — `SECTION_ORDER`, `SECTION_LABELS`, `SECTION_COLORS`, `SECTION_DB_NAMES`, `normalizeSectionKey` aliases.
- `docs/index.html` — cache-buster bump.
- `CHANGES-FROM-ORIGINAL.md` — append a Phase 2 section.

---

## Definition of done

1. ≥0.85 macro-F1 on the hand-labelled evaluation set for `procedure` and `circumstances`.
2. Dashboard renders three distinct filter checkboxes with plausible counts.
3. A sample of 20 golden queries (Hirst, Selmouni, Handyside, …) returns paragraph snippets whose section classification matches a manual review.
4. `CHANGES-FROM-ORIGINAL.md` updated.
5. No regression on Phase 1 rank ordering (Hirst still top-1 for `Hirst`, torture still surfaces Selmouni/Ireland/Aksoy top-5).
