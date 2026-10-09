# Judgment-level citation ranking

## Scope and limits

`Most Cited Judgments` counts distinct directed pairs of judgment identities,
not paragraphs, raw citation strings, applications or language versions.
Both ends must be judgments in the audited English-flagged catalog (Grand
Chamber, Chamber or Committee). French metadata aliases join through the same
ECLI, judgment date and judicial collection; French sources can contribute
edges even when English citation metadata is empty. An unpaired French record
is held for review, not counted as another judgment. Separate ECLIs remain
separate judgments even when application numbers match.

This first release uses registry citation metadata (`scl`) in ENG and FRE.
It does **not** scan the downloaded French texts or production paragraph text.
Missing metadata is not zero citations. Resolved counts are lower bounds and
unresolved references can change the ordering. This is not a complete ranking
of citations in all HUDOC judgments and is not a legal-influence score.

## Matching policy

1. An explicit HUDOC ID / ECLI must resolve consistently. Unknown identifiers
   do not fall back to application/name guessing.
2. Otherwise use all cited application numbers with the exact judgment date,
   or application numbers with an exact normalized English/French case name.
   A case name and exact date can resolve legacy references without appnos.
3. Dates, document-stage hints and known conflicting case names constrain the
   candidates. Several candidates stay ambiguous; future citations and
   self-references are not edges. A report-series year is not a judgment date
   and must not be used to pick between merits and just-satisfaction judgments.
4. Explicit decisions / Commission decisions / advisory opinions are excluded.
   Unknown external references stay unresolved rather than being labelled
   definitely outside the corpus.
5. If application metadata differs between ENG/FRE, only the common application
   aliases support secondary matching; direct document IDs remain available.

Every observation retains raw reference, language, source HUDOC ID, resolution
status, method and candidate IDs. `edges` has a unique `(citing_id,cited_id)`
primary key. The existing production `case_citations` table and API are **not**
reused or overwritten: their old application-number matching needs a separate
migration and audit before replacing Search's cites/cited-by results.

## Application numbers extracted by HUDOC (second evidence type)

HUDOC records, for almost every judgment, the application numbers it found in the full text
(`extractedappno`; 29,272 of 29,343 judgment identities, French originals included). The catalog query
does not select the field; `p69_sync_hudoc_metadata.py fetch` does, and `--hudoc-metadata` (statistics
refresh) or `--extracted-appno` (citation builder) passes it in. The snapshot then carries a separate
`with_extracted_appno` block; the top-level `ranking`, `citing_by_target`, `citing_judgments` and
`coverage` are unchanged and remain the curated-list result. The dashboard lets the reader choose.

A number resolves only when exactly one other judgment in the catalog has that application and is not
later than the citing judgment. A number belonging to the citing judgment's own application is skipped,
several judgments of one application (Chamber and Grand Chamber, merits and just satisfaction) stay
ambiguous, and a number without a judgment in the catalog (for example a decision) is unresolved. The
numbers carry no date, name or citation context, so this is weaker evidence than the curated lists.

Measured on the 9 October 2026 catalog (452,837 extracted numbers):

| | curated lists | + extracted numbers |
|---|---|---|
| Resolved pairs | 140,085 | 280,448 (232,920 from the numbers, 92,557 in both) |
| Judgments citing at least one judgment | 12,194 | 27,706 of 29,343 |
| Frydlender v. France, cited by | 1,215 | 3,584 |

Of the extracted numbers: 256,384 resolved, 53,752 ambiguous, 73,441 the judgment's own application,
67,911 without a judgment in the catalog, 1,349 only later judgments.

Validation against the text of English judgments in the Search corpus (167,300 + 6,524 pairs where both
ends are in the corpus): 96.2% of the resolved pairs are also found by the text extraction, 1.9% point to a
different document of the same application in the corpus (typically a decision cited under that number),
and 1.8% are not found in the text (footnotes, or no citation context). Treat the extended counts as
approximate lower bounds.

## Rebuild

Run from the repository root. Python stdlib only; no downloads or DB writes on
the production server. The input catalog must pass its completeness/checksum
validation. Audit SQLite is a new local artifact, never the production DB.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/refresh_statistics.py \
  --catalog output/hudoc-reconciliation/catalog.json \
  --inventory output/statistics/production-inventory.json \
  --downloads output/hudoc-reconciliation/missing-judgments \
  --output docs/data/stats.json \
  --citations-output docs/data/judgment-citations.json \
  --citations-audit output/citation-reconciliation/audit.sqlite

PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
node tests/test_citation_labels.cjs
node --check docs/assets/pages-dashboard.js
git diff --check
```

To refresh citations alone use `scripts/build_judgment_citations.py` with
`--catalog`, `--output` and `--audit` as above. The browser checks catalog
scope, metadata checksum and cut-off against `stats.json` before drawing the
ranking. Publish both JSON snapshots and the matching HTML/JS/CSS together.
The compact public snapshot contains Top 20, distinct citing lists, IDs and
coverage. Raw references and unresolved candidates remain in the local audit.
Ranking CSV includes HUDOC ID/ECLI; each Top 20 item also exports its complete
distinct citing list, not only the first 25 displayed rows.

## Acceptance and rollout

- Check all Top 20 identities/dates and at least one ENG and FRE evidence
  reference per target against catalog metadata; audit additional resolved
  samples and inspect ambiguous / conflict / excluded categories.
- Assert every edge has existing nodes, dates are chronological, no self-edge,
  and all public citing lists match the distinct edge counts exactly.
- Test merit/Article 41 separation, bilingual duplicates, joined applications,
  disagreement/absence of identity metadata and conflicting identifiers.
- Check list selection, pagination, links, both CSV exports, desktop/mobile,
  dark mode and the stale-snapshot failure path.
- First release is local/staged. Do not modify the production corpus or graph.
  Public publication and Search/API migration require a separate explicit
  approval. Keep the old reference-entry chart as an audit aid.

Rollback: restore the previous HTML/JS/CSS snapshots and omit the new citation
asset. No production migration must be reversed. For a future full-text phase,
retain the same identity model, record text-source/language provenance, reject
applicant-table application numbers as citations without citation context, and
deduplicate metadata/text evidence into the same distinct edges. Publish its
measured coverage separately rather than silently mixing extraction methods.
