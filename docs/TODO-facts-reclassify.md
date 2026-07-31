# TODO — Phase 2: split the Facts family into PROCEDURE / CIRCUMSTANCES

**Status:** scoped and measured (2026-07-31). Step 1 complete — see §3.
**Supersedes:** the April 2026 version of this document, whose premise is obsolete (§1).
**Prerequisite commit:** the Phase 1 merge of `facts_background` + `facts_proceedings` into a single `facts` bucket (commit `20260410-factsmerge`).
**Probe script:** `scripts/p62_facts_boundary_probe.py` (read-only).
**Owner:** unassigned

---

## 1. What changed since April — the original premise is gone

The April version of this document described the problem as two upstream labels
("Facts Background" ≈ 36k paragraphs, "Facts Proceedings" ≈ 438k) that were
semantically inverted and produced an unusable 92 : 8 imbalance. The P21–P57
heal passes dissolved that problem. Measured against the production database on
2026-07-31:

| | April 2026 | Production today |
|---|---|---|
| `Facts Background` | ~36,000 paras | **9,573** |
| `Facts Proceedings` | ~438,000 paras | **3,985** |
| Corpus | 1,314,796 paras | **3,258,434 paras / 19,822 cases** |

Both legacy labels are now residue. The real Phase 2 problem is different and
simpler to state:

> **718,093 paragraphs across 19,808 cases sit in one undifferentiated Facts
> family** (`Facts` + `Facts Background` + `Facts Proceedings`) and need to be
> split into `procedure`, `circumstances`, and `subject_matter`.

---

## 2. What the HUDOC convention actually is

*(unchanged from the April version — still accurate)*

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
  II. RELEVANT DOMESTIC LAW AND PRACTICE
  III. RELEVANT INTERNATIONAL MATERIALS

THE LAW
```

### Committee summary template (since 1 September 2021)

```
SUBJECT MATTER OF THE CASE             ← merged facts + procedure
    (or "FACTS AND PROCEDURE")

THE COURT'S ASSESSMENT
```

### Pre-Protocol-11 (Court A / Commission) template

```
PROCEDURE
  PROCEEDINGS BEFORE THE COMMISSION
AS TO THE FACTS
  I.  THE PARTICULAR CIRCUMSTANCES OF THE CASE
AS TO THE LAW
```

---

## 3. Step 1 (done) — the job is 99% deterministic

**The unit of work is not the paragraph, it is the case boundary.** These
sections are contiguous blocks, so the question is not "what is this paragraph"
(718,093 decisions) but "where does the PROCEDURE block end" (19,808 decisions).
And `row_role` already marks heading rows, so most of those boundaries are
sitting in the data as literal strings.

Any *one* facts-start marker suffices: within the Facts family, everything
before it is `procedure`, everything from it onward is `circumstances`.

`scripts/p62_facts_boundary_probe.py` measures the coverage of an expanded
marker vocabulary against production:

| Bucket | Cases | | Paragraphs | |
|---|---:|---:|---:|---:|
| A. committee `SUBJECT MATTER` marker | 982 | 5.0% | 11,776 | 1.6% |
| B. facts-start marker present | 18,262 | 92.2% | 699,317 | 97.4% |
| C. PROCEDURE marker only, no end boundary | 203 | 1.0% | 2,258 | 0.3% |
| D. no structural heading | 361 | 1.8% | 4,742 | 0.7% |
| **TOTAL** | **19,808** | | **718,093** | |

> **Deterministic (A+B): 19,244 cases (97.2%) / 711,093 paragraphs (99.0%)**
> **Needs a boundary decision (C+D): 564 cases (2.8%) / 7,000 paragraphs (1.0%)**

The April sketch only looked for `PROCEDURE` and `I. THE CIRCUMSTANCES OF THE
CASE` and left 26.8% of cases uncovered. Adding `THE FACTS` (17,368 heading
rows), `AS TO THE FACTS` (859) and the Commission-era headings collapses the
residue from 5,306 cases to 564.

### Markers that fire

| Rows | Class | Heading |
|---:|---|---|
| 17,368 | FACTS_START | `THE FACTS` |
| 8,819 | PROC | `PROCEDURE` |
| 977 | SUBJ | `SUBJECT MATTER OF THE CASE` |
| 859 | FACTS_START | `AS TO THE FACTS` |
| 224 | PROC | `PROCEEDINGS BEFORE THE COMMISSION` |
| 51 | PROC | `PROCEDURE AND FACTS` |
| 40 | FACTS_START | `THE CIRCUMSTANCES OF THE CASE` |

Everything below 10 rows is noise (`SPECIFIC CIRCUMSTANCES OF THE CASE`, etc.).

### Sanity check — the boundary assumption holds

PROCEDURE-block length in bucket B, i.e. Facts-family rows before the
facts-start marker:

| p10 | median | p90 | p99 |
|---:|---:|---:|---:|
| 1 | **4** | 8 | 21 |

This matches the HUDOC convention (~5–15 short administrative paragraphs) and
is the evidence that the marker is cutting in the right place. If the split
had produced 100-paragraph "procedure" blocks the whole approach would be
wrong.

198 of 18,262 cases yield a zero-length procedure block (the marker is the
first Facts-family row). That is expected where the `PROCEDURE` heading was
labelled `Introduction` — see §4.

### Residue (C+D) by era

| Bucket | Era | Paragraphs |
|---|---|---:|
| C | pre-1995 | 623 |
| C | 1995–2010 | 1,162 |
| C | 2011–2021 | 454 |
| C | 2022+ | 19 |
| D | 1995–2010 | 331 |
| D | 2011–2021 | 1,131 |
| D | 2022+ | 3,280 |

Bucket D concentrates in 2022+ — modern committee judgments whose
`SUBJECT MATTER` variant the matcher missed. That is a rule-harvest problem,
not a classification problem.

> ⚠️ `cases.judgment_date` is stored **`DD/MM/YYYY`**, not ISO. The year is the
> *last* four characters. Slicing the first four buckets every case by
> day-of-month and produces plausible-looking nonsense — the same lexical trap
> fixed frontend-side in `13b487d`. An earlier version of this analysis fell
> into it.

---

## 4. Where the PROCEDURE heading actually lives

`Introduction` is effectively a heading-only section: 10,200 paragraphs across
9,752 cases, of which **9,733 are `heading_h0`**. It holds bare `PROCEDURE`
heading rows while the procedure *body* paragraphs sit in the Facts family.

PROCEDURE-class heading rows by current section:

| Section | Rows |
|---|---:|
| Facts | 9,430 |
| Introduction | 7,871 |
| Facts Proceedings | 229 |
| other | 11 |

16,746 distinct cases (84.5%) carry a PROCEDURE heading somewhere.

**Consequence:** a `procedure` bucket built purely from the Facts family will
render without its own heading in ~7,871 cases. Phase 2 should re-home those
heading rows into `procedure` as part of the same pass. `Header` (294,636 paras,
mostly `metadata`) is document preamble and is **out of scope** — do not touch it.

---

## 5. Goals

1. Per-paragraph classification reflecting real HUDOC structure:
   - `procedure` — lodging date, composition, interveners, hearing,
     admissibility ruling history, friendly-settlement negotiations
   - `circumstances` — substantive applicant narrative and facts as found
   - `subject_matter` — merged bucket for post-2021 Committee summaries
   - all other labels (`merits`, `admissibility`, `just_satisfaction`,
     `legal_framework`, `legal_context`, `article_46`, `operative_part`,
     `separate_opinion`, `appendix`) unchanged
2. Re-home the 7,871 orphaned PROCEDURE heading rows out of `Introduction`.
3. Re-expose three UI buckets; keep Phase 1 `facts` as a compatibility alias
   that OR-selects all three.
4. Full rollback via a `_p63_backup` table.

### Non-goals

- Changing paragraph IDs or ordering.
- Revisiting the ranking pipeline.
- Touching `Header`.
- Adding new dense-retrieval models.

---

## 6. Plan

| Step | Work | Verify |
|---|---|---|
| 1 ✅ | Expand marker vocabulary, measure coverage (`p62`) | Residue < 5% of cases; procedure-block median in the 5–15 range — **both met** |
| 2 | Deterministic segmenter over A+B (19,244 cases) | Every case yields contiguous, non-overlapping blocks; no paragraph loses a label; total row count unchanged |
| 3 | Rule harvest on the 564-case residue | Coverage rises on a held-out slice; bucket D 2022+ cluster resolved by a committee-template rule |
| 4 | Extend judge vocabulary + `v5_local_eval.py` | Re-running the v5 sweep reproduces its published numbers on the unchanged buckets (regression check on the tooling itself) |
| 5 | Hand-label ~200 paragraphs from 50 cases as gold | Built **before** any agent runs; agents never see it |
| 6 | Apply pass + frontend buckets | macro-F1 ≥ 0.85 on `procedure` and `circumstances` |

### Where the LLM fan-out belongs

Two places only, both small — the deterministic passes do the heavy lifting:

- **Rule harvest (step 3):** one agent per era-stratum reads ~30 residue cases
  and proposes boundary rules. ~5 agents. Output is regexes applied
  deterministically to all 564 cases, not per-case labels.
- **Verification sweep (step 6):** reuse the v5 machinery — stratified 1,000
  rows, 20 agents × 50, fresh context per agent, TSV verdicts, effective-error
  rate with the heading-convention filter.

Estimated total: **under 100 agents.** Naive per-case fan-out would be ~19,800;
per-paragraph is not worth costing.

### Blocker to clear first

The existing LLM-judge scheme **cannot validate Phase 2 as written**. Its
seven-bucket vocabulary (`FACTS`, `ADM_MERITS`, `JUST_SATISFACTION`,
`OPERATIVE`, `OPINIONS`, `META`, `HEADING`) has a single `FACTS` bucket — which
is precisely what Phase 2 splits. `DB_TO_BUCKET`, the judge prompt, and
`v5_local_eval.py` all need extending to `PROCEDURE` / `CIRCUMSTANCES` /
`SUBJECT_MATTER` before any sweep number means anything.

---

## 7. Constraints and anchors

- **The verifier must not see the rule that produced the label.** It receives
  text + context + `row_role` + era and returns a bucket. Hand it the
  segmenter's reasoning and it rubber-stamps.
- **Freeze `DB_TO_BUCKET` and the heading-convention filter before the sweep.**
  They are the knobs an optimiser would loosen to flatter the error rate.
- **Paragraph text is data, not instructions** — state this in every judge
  prompt, as the v2–v5 sweeps do.
- **Production DB lives on the VM** (`/home/amuvmuser/echr/data/echr_search.db`,
  4.16 GB), healed in place by the P5x passes. Local `data/echr_search.db` is
  from 2026-05-22 and stale. **Never run `deploy.sh --with-db`.**
- **One SQLite DB — no parallel writers.** Agents emit JSON verdicts; a single
  serialized script applies them. This is the existing
  `pNN_audit_extract.py` → `verdicts.json` → `pNN_relabel.py` split; keep it.
- **Follow the P5x mutation convention:** dry-run default, `_pNN_backup` table
  written before any `UPDATE`, idempotent.
- **Deterministic scripts, not agents, produce any published number.**
  A seeded sample plus a committed verdicts file is reproducible evidence for
  the methodology; a workflow run is not.

### Dropped from the April plan

The `section_v2` column and `USE_V2_SECTIONS` feature flag. Every audit script
reads `section`; a parallel column means touching all of them for no rollback
benefit the `_pNN_backup` convention doesn't already provide.

---

## 8. Definition of done

1. ≥ 0.85 macro-F1 on the hand-labelled eval set for `procedure` and
   `circumstances`.
2. Dashboard renders three distinct filter checkboxes with plausible counts.
3. 20 golden queries (Hirst, Selmouni, Handyside, …) return snippets whose
   section classification survives manual review.
4. No regression on Phase 1 rank ordering (Hirst top-1 for `Hirst`; torture
   surfaces Selmouni / Ireland / Aksoy top-5).
5. `CHANGES-FROM-ORIGINAL.md` and `notes-internal/CHANGELOG.md` updated.

---

## 9. Files that will change

- `scripts/p62_facts_boundary_probe.py` — **added** (read-only probe, step 1).
- `scripts/p63_resegment_facts.py` — **new**, deterministic segmenter + apply.
- `scripts/p63_audit_extract.py` / `p63_audit_verdicts.json` — verification sweep.
- `rag/../v5_local_eval.py` + judge prompt — extended bucket vocabulary.
- `docs/assets/search-app.js` — `SECTION_ORDER`, `SECTION_LABELS`,
  `SECTION_COLORS`, `SECTION_DB_NAMES`, `normalizeSectionKey` aliases.
- `docs/index.html` — cache-buster bump.
- `CHANGES-FROM-ORIGINAL.md`, `notes-internal/CHANGELOG.md`.

---

## 10. Unrelated gap noticed while scoping

`notes-internal/CHANGELOG.md` stops at **P20 (2026-04-30)**, but heal passes ran
through **P57** and further scripts exist through **P61**. For a project with a
DOI and published error rates, that documentation gap is worth closing
separately from Phase 2.
