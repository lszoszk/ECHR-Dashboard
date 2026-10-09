# Statistics snapshot: scope and rebuild

Statistics counts **HUDOC judgment records only** from the Grand Chamber,
Chambers and Committees. Decisions, Commission reports and press releases are
excluded. The counting unit is a judgment record, not an application, applicant
or language version. Multiple respondent states each receive one contribution.

## October 2026 snapshot

- Verified catalog: 29,343 English-flagged judgment metadata records, cut off
  on 9 October 2026. Latest judgment date: 8 October 2026.
- English metadata is used for outcomes and thesaurus labels, independently
  of whether the available source text is English or French.
- Text inventory: 20,060 catalog-matching production records plus 9,283 local
  French source bundles, selected once per judgment. Production takes precedence
  where a nonempty curated text exists; local and deployed versions are never
  added together.
- 4,400,091 nonempty text rows, including headers, headings and applicant tables.
  This is not a count of numbered judicial paragraphs.
- The downloaded batch also contains 56 English bundles. At inventory time,
  matching text already existed in production for those records, so it was not
  added a second time. The production database does not record confirmed source
  language; those selected texts remain `Unknown` rather than guessed English.
- Eight translation-title records remain included in the literal official
  English catalog scope. One metadata record lacks ECLI. The snapshot is not
  a certified bilingual ECLI union: French originals serve as text fallbacks
  with exact ECLI/date/collection checks, not extra counted judgments.
- Local French bundles have not been deployed by this statistics refresh.
  Paragraph segmentation and French section assignment still require separate
  source-exact QA before publication as certified paragraph-level search data.

## Rebuild

Run from the repository root. No production database is written or copied.
The exporter uses a single read-only SQLite transaction, aggregating paragraph
rows per case/section/role on the server rather than transferring all text.

```bash
mkdir -p output/statistics
ssh -o BatchMode=yes -o ConnectTimeout=15 amuvmuser@150.254.115.204 \
  'docker exec -i echr-api python3 - --export-inventory /data/echr_search.db' \
  < scripts/refresh_statistics.py \
  > output/statistics/production-inventory.json.tmp && \
  mv output/statistics/production-inventory.json.tmp \
     output/statistics/production-inventory.json

python3 scripts/refresh_statistics.py \
  --catalog output/hudoc-reconciliation/catalog.json \
  --inventory output/statistics/production-inventory.json \
  --downloads output/hudoc-reconciliation/missing-judgments \
  --output docs/data/stats.json \
  --citations-output docs/data/judgment-citations.json \
  --citations-audit output/citation-reconciliation/audit.sqlite

python3 -m unittest discover -s tests -v
node --check docs/assets/pages-dashboard.js
python3 -m http.server 8766 --bind 127.0.0.1 --directory docs
```

To include the HUDOC fields that the catalog query does not select (separate-opinion flag, representation,
application numbers HUDOC extracted from the text), fetch the records once and add `--hudoc-metadata`:

```bash
python3 scripts/p69_sync_hudoc_metadata.py fetch --db echr_search.db --out metadata.json \
  --ids french_source_ids.txt            # the French source records of the French-only judgments
python3 scripts/refresh_statistics.py ... --hudoc-metadata metadata.json
```

Where a judgment's own record lacks a field, its French source record supplies it. This populates the
separate-opinion statistics (Grand Chamber 81.9%, Chamber 16.5%, Committee 0%; 29,279 of 29,343 records
carry the flag) and adds three coverage rows: citation metadata in either language (12,536), application
numbers extracted by HUDOC (29,272) and the separate-opinion flag. Without the option the output is what the
catalog alone supports. Equal counts in `top_violated_articles` are ordered by set iteration, so a rebuild can
reorder ties without any data change.

Preview `http://127.0.0.1:8766/analytics.html`. The build validates the catalog
coverage/checksum, scope, bundle identities/provenance and French fallback
identity, then writes the JSON atomically. A refresh of the inventory alone
does not extend the catalog cut-off; harvest and reconcile a new verified
catalog when the date scope changes. Network access is needed only for the
read-only SSH inventory; the build itself is offline and needs Python stdlib.

The citation options build the separate `Most Cited Judgments` asset from
ENG/FRE registry metadata and a local audit database. This ranking is not the
old raw-reference chart or production Search's application-number graph.
See [judgment-citations.md](judgment-citations.md) for matching policy, measured
coverage, partial-ranking limits and separate publication/API rollout.

Do not use `rebuild_stats.sh` for this combined snapshot: its old enrichment
pipeline builds from deployed text only and cannot account for local French
source bundles. Do not reuse `p66` to patch totals into this full snapshot;
that would mix scopes. Publishing remains a separate approved operation.

## UI and analytical changes

The old 22-tile overview is replaced by a four-metric ledger: judgment records,
respondent states, at-least-one-violation share and text rows. Scope, provenance,
language limits and the partial final year are visible at the beginning.

The new judicial-collection time series uses official collection labels,
including Committees rather than putting them in `Other`. Metadata coverage
uses exact populated-record counts; an absent field is not treated as a legal
finding. Protocol article tags are included. Country names come from the
official respondent codes, eliminating the previous split-name/alias inflation.

Empty chart wrappers and their navigation links are removed after loading.
Case duration has no lodging-date data and its placeholder is removed. The
stale citation network/PageRank blocks are removed rather than copied into the
new catalog. Citation-string frequencies and concentration are retained with
explicit denominators and metadata coverage, without pretending strings are
resolved precedents. Unpopulated keyword and separate-opinion charts disappear.
The real coverage table replaces the old coverage placeholder.

## Next useful additions

### Article comparison methodology

`Outcomes by Article` replaces the misleading raw-tag rate ranking (which
favoured combinations with very small samples). The new `article_analytics`
payload collapses subparagraphs to main articles, preserving Protocol identity
(`6-1` and `6-3-d` become `6`; `P1-1-2` becomes `P1-1`). Each judgment record
counts once per article in a mutually exclusive violation-only, mixed,
non-violation-only or no-outcome bucket. The rate is `(violation-only + mixed)
/ (violation-only + mixed + non-violation-only)`. No-outcome records are shown
separately in the exact-count table and excluded from the denominator.

Conjunction components (`14+8`) contribute to both article families, following
article-related HUDOC metadata. This must not be interpreted as independent
standalone violations of both articles. The HUDOC outcome fields themselves
may also repeat component tags. Results are a descriptive comparison, not a
claim-level success probability; no legal outcome is inferred from the text.
See the [official HUDOC manual](https://www.echr.coe.int/documents/d/echr/hudoc_manual_eng).

The default view orders all qualifying articles by sample volume and requires
at least 100 judgments with an outcome tag. Controls allow descending/ascending
violation share, numeric article order and thresholds of 1, 50, 100 or 500.
Highest/lowest highlights use the same threshold, not small-sample outliers.
The adjacent count chart uses the 15 largest primary-article samples and the
same three disjoint outcome buckets. Raw tags remain in the legacy payload
for compatibility but no longer power these two charts. English/French text
versions use the existing single-record catalog scope, without double counting.

### Further analytics

Citation-axis labels now show compact case names without application numbers,
paragraph references, dates or report-series metadata. Decision and just-
satisfaction qualifiers are retained to avoid confusing document stages.
This is display-only: reference entries are not merged; tooltips, CSV and
accessible data tables retain the complete original reference. Coverage and
counting notes are available in a collapsed disclosure. Run the label regression
checks with `node tests/test_citation_labels.cjs`.

1. Shared year, collection, state and article filters across all charts, with
   the active denominator and filtered CSV export. This requires a compact
   record-level metadata file, not just aggregate `stats.json`.
2. Text-length and section-composition comparisons by language/collection,
   after verifying section mapping and separating table cells from prose.
   Otherwise mass-applicant tables and Committee formats bias the results.
3. A rebuilt citation network using judgment/ECLI identity, not the first
   application number. One application can have several judgments. Mark
   ambiguous links and coverage, and do not describe recent judgments as
   less influential without accounting for their shorter citation exposure.
4. Article/outcome trends by collection with minimum sample sizes. The dataset
   already has date, judicial collection, respondent and article/outcome tags;
   this would distinguish Committee volume from Grand Chamber jurisprudence.

Case duration, applicant demographics and exact monetary-award distributions
should not be added from this catalog alone: the needed fields are absent or
not reliably structured. No values should be invented or inferred from titles.
