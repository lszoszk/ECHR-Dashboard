# Data Quality TODO

**Saved:** 2026-04-28
**Status:** In progress — to be continued
**Current state:** P1–P9 applied (P8 rolled back), 8 backups in DB, 97.6% precision (LLM-audited + 7/7 expert-confirmed)

---

## Where we are now

```
Cumulative relabel total across P1, P2, P3, P4, P5, P6, P7, P9: 307,221 paragraphs (~15% of 2M corpus)
Audited precision (Sonnet 4.6, 490 samples): 97.6% [95% CI: 96.2%–98.6%]
Human-validated (M1, all 7 LLM-flagged errors): 7/7 confirmed
Backup tables: _p1_backup, _p2_backup, _p3_backup, _p4_backup, _p5_backup, _p6_backup, _p7_backup, _p9_backup
```

Section paragraph totals (current):

| Section | Paragraphs | Cases |
|---------|------------|-------|
| Merits | 564,788 | 18,993 |
| Facts Proceedings | 354,152 | 12,987 |
| Just Satisfaction | 159,921 | 12,838 |
| Introduction | 188,405 | 19,080 |
| Admissibility | 169,056 | 9,029 |
| Facts | 131,935 | 5,648 |
| Legal Framework | 108,244 | 9,501 |
| Header | 69,202 | 18,429 |
| Operative Part | 67,717 | 13,270 |
| Operative part | 60,851 | 6,232 |
| Appendix | 39,408 | (post-P9) |
| Facts Background | 36,463 | 13,095 |
| Separate Opinion | 31,575 | 2,635 |
| Relevant legal framework | 15,743 | 1,838 |
| Article 46 | 3,981 | 374 |
| Legal Context | 6 | 2 |

---

## Pending tasks (priority order)

### 🔴 P10 — Extract HUDOC paragraph numbers from text (~1–2h)

**Why:** Critical methodology gap discovered during expert manual review (M3, M4). Our `para_idx` is a sequential row counter from segmentation, NOT the canonical HUDOC paragraph number. Worked examples in our methodology cite paragraphs by `para_idx` ("¶76") which fails verification against HUDOC source documents.

**Fix:**
1. Add `hudoc_para_no INTEGER` column to `paragraphs` table:
   ```sql
   ALTER TABLE paragraphs ADD COLUMN hudoc_para_no INTEGER;
   ```
2. Extract leading "N. " pattern from each paragraph text:
   ```python
   import re
   m = re.match(r"^\s*(\d+)\.\s+", text)
   hudoc_para_no = int(m.group(1)) if m else None
   ```
3. Heading paragraphs (no number) get NULL.
4. Backup `_p10_backup` (rowid → original NULL state for completeness).
5. Update `paragraphs_fts` if it uses para_idx for ordering.
6. Frontend: display HUDOC numbering alongside or instead of `para_idx`.
7. Spot-check audit (50 samples by Sonnet) to verify extraction accuracy.

**Subtle issues to handle:**
- Operative Part dispositif clauses use "1.", "2.", "3." (separate numbering block from main judgment).
- Separate Opinions restart at "1." per opinion.
- Some paragraphs starting "X. " are sub-section labels ("A. Damage", "I. ALLEGED VIOLATION") not paragraph numbers — distinguish by length/content.
- Pop C cases without `para_idx` may also lack clear HUDOC numbering — accept NULL.

**Estimated coverage:** ~80% of paragraphs should yield an extractable HUDOC number. The remaining 20% (headings, operative part, fragments, Pop C unordered content) stay NULL.

---

### 🔴 P11 — Split Procedure / Relevant domestic law / Proceedings before Commission / Final Submissions out of Facts catch-all (~2–3h)

**Why:** M3 expert review identified that our schema collapses several HUDOC-canonical sub-sections into `Facts Background` / `Facts Proceedings` catch-all buckets. In Population A judgments specifically, the canonical sub-section structure is:

```
PROCEDURE                              ← currently in our "Introduction"
AS TO THE FACTS                         ← currently in our "Facts Background"
RELEVANT DOMESTIC LAW                   ← currently in our "Facts Proceedings"
PROCEEDINGS BEFORE THE COMMISSION       ← currently in our "Facts Proceedings"
FINAL SUBMISSIONS TO THE COURT          ← currently in our "Facts Proceedings"
AS TO THE LAW (Merits)                  ← currently in our "Merits" ✓
```

**Fix:**
1. Detect heading paragraphs containing canonical phrases (length<120, ALL CAPS or formatted as section headings):
   - `PROCEDURE` (start of Introduction in classical format) → already correctly in `Introduction`
   - `RELEVANT DOMESTIC LAW` (with optional roman numeral prefix) → relabel block as `Legal Framework`
   - `PROCEEDINGS BEFORE THE COMMISSION` → new label `Commission Proceedings`?
   - `FINAL SUBMISSIONS TO THE COURT` → new label `Final Submissions`?
   - `THE CASE-LAW OF THE COURT OF JUSTICE` → relabel as `International Law`?
2. Walk forward from each heading, relabel paragraphs in same source section until next heading or section boundary.
3. Conservative: skip paragraphs already correctly classified (e.g. `Legal Framework` from P3).

**Estimated impact:**
- "RELEVANT DOMESTIC LAW" headings outside Pop B already handled by P3 (~83k paragraphs moved). P11 would catch the residual in Pop A (a few thousand).
- "PROCEEDINGS BEFORE THE COMMISSION" — relevant for Pop A pre-1998 cases, ~1,500 cases × ~3 paras each = ~4,500 paragraphs.
- "FINAL SUBMISSIONS TO THE COURT" — ~500 cases × 1–3 paras = ~1,000 paragraphs.

**Decisions to make first:**
- Do we add new section labels (`Commission Proceedings`, `Final Submissions`, `International Law`) or fold these into existing buckets?
- Two new labels means more granularity for researchers but more frontend filter checkboxes.
- Recommendation: add `Commission Proceedings` and `Final Submissions` as standalone labels; fold international/EU case law references into `Legal Framework`.

---

### 🟡 P12 — Numbering blocks for Operative Part and Separate Opinions (~1h, after P10)

**Why:** Operative Part dispositif "1.", "2.", "3." restarts numbering. Each Separate Opinion also restarts at "1.". Without distinguishing numbering blocks, citing "paragraph 5" is ambiguous (main judgment ¶5? operative ¶5? which separate opinion's ¶5?).

**Fix:** Add `numbering_block TEXT` column:

| Value | Meaning |
|-------|---------|
| `main_judgment` | Body of the judgment (PROCEDURE through Operative Part dispositif heading) |
| `operative_part_dispositif` | Numbered ruling clauses ("1. Decides...", "2. Holds...") |
| `separate_opinion_N` | Paragraph M within the Nth separate opinion |
| `appendix` | Appendix tables (esp. Pop C mass cases) |
| NULL | Headings, fragments, unclassifiable |

Detection rules:
- Operative Part dispositif: paragraph in `Operative Part` section AND text starts with `\d+\.\s*(Decides|Declares|Holds|Dismisses)`.
- Separate Opinion: paragraph in `Separate Opinion` section; group by case_id + sequence break (when text starts with "1." after another opinion's text).
- Main judgment: everything else with `hudoc_para_no IS NOT NULL`.

Frontend: when displaying citation, format as "Wainwright v. UK, ¶57" for main judgment, "Wainwright v. UK, Operative ¶3" for operative, "Wainwright v. UK, Dissenting Opinion of Judge X, ¶3" for separate.

---

### 🟡 End-to-end recall audit (~1h, LLM)

**Why:** All audits so far measure precision (correctness of made relabels). None measure recall (how many paragraphs that SHOULD have been relabeled were missed).

**Method:** Stratified random sample of N=300 paragraphs from CURRENT state across all sections. Sonnet 4.6 evaluates each: "Does this paragraph have the correct section label given its content and surrounding context?" Output per pass:

- True positive rate per section
- False negatives (paragraphs that should have been moved but weren't)
- Specific error patterns (e.g. "5 cases of Article 41 reasoning still in Facts in Pop B chamber cases" → P10 candidate)

**Cost estimate:** ~$1–2 with Sonnet 4.6 (within rate limits if done in 2 batches of 150).

**Output:** `precision-audit.md` Section 7 with recall metrics. Tightens the methodology claim from "precision = 97.6%" to "precision = 97.6% AND recall ≥ X% on N=300 stratified samples."

---

### 🟡 Investigate PDF-extraction artefact in Fetisov v. Russia (~30 min)

**Why:** M2 review flagged rowid 1463491 as a paragraph the expert could not locate in HUDOC source. Possibly a fragment that was concatenated with a subsequent section heading during PDF extraction.

**Fix:**
1. Pull the full text of rowid 1463491 from DB.
2. Compare with HUDOC source for that case.
3. If artefact: flag and potentially split. If not: investigate why expert couldn't find it.
4. Search corpus for similar fragment patterns (e.g. paragraphs that start mid-sentence with no leading number) → quantify scope of PDF-extraction issues.

---

### 🟢 P13 (parked) — Narrow Merits sub-typing schema (TBD)

**Why:** B2 pilot was rejected by expert (1/10 agreement). The 7-category schema is too granular. A narrower binary tag — `violation_finding` vs `no_violation_finding` — has 99% structural reliability via "There has been a violation of Article X" pattern.

**Decision needed:** Is this analytical signal worth the work, or do we accept "Merits is Merits, no sub-typing"? Defer until downstream analytics need it.

---

### 🟢 Frontend updates after P10/P11/P12

After P10 + P11 + P12 land, the frontend needs:
1. Display `hudoc_para_no` on each paragraph card (alongside or instead of `para_idx`).
2. Add filter checkboxes for new sections (`Commission Proceedings`, `Final Submissions`) if introduced.
3. Update `SECTION_DB_NAMES` map.
4. Update CSV export columns.
5. Bump cache-buster version.

---

## Cleanup tasks (low priority)

- Remove `/home/amuvmuser/migration-backup-20260428/` after ~1 week stable (~250 MB free).
- Containerize `/home/amuvmuser/echr_rag/` (UHRI semantic search) — currently runs on host.
- Investigate `unhr_setfit_models/` and `unhr_setfit_runtime/` in `/home/amuvmuser/echr/data/` — UHRI artefacts that can probably move to `/home/amuvmuser/uhri/data/`.
- Audit residual `analyze_*.py` files in `/home/amuvmuser/echr/backend/` — some are ours (`analyze_sections.py`), some are old experiments.

---

## What was tried and rejected

- **P8 (fix audit findings)**: 30% precision, rolled back. Forward propagation from text triggers in Merits was too aggressive. See `precision-audit.md` Section 5.
- **B2 Merits sub-typing schema (7 categories)**: 1/10 expert agreement. Rejected. See `merits-subtyping-pilot.md` Section 8.

---

## Order of operations recommendation

When resuming:

1. **P10 first** (HUDOC para numbers) — unlocks proper citation format and is mechanically simple.
2. **End-to-end recall audit** — surfaces what other passes might be needed.
3. **P11** (sub-section split) — only after recall audit confirms the scope.
4. **P12** (numbering blocks) — depends on P10.
5. **Frontend updates** — last, after all DB-side work.

Estimated total time to complete all of the above: ~1 day (8h).

---

## Quick reference: how to work with the DB

```bash
# Connect to production DB (read-only):
ssh amuvmuser@150.254.115.204 "docker exec echr-api python3 -c \"
import sqlite3
conn = sqlite3.connect('file:/data/echr_search.db?mode=ro', uri=True)
cur = conn.cursor()
cur.execute('SELECT COUNT(*) FROM paragraphs')
print(cur.fetchone())
\""

# Or run a script (read-only or apply mode):
scp scripts/your_script.py amuvmuser@150.254.115.204:/home/amuvmuser/staging.py
ssh amuvmuser@150.254.115.204 "docker cp /home/amuvmuser/staging.py echr-api:/tmp/script.py && \
                                docker exec echr-api python /tmp/script.py [--apply]"
```

Backups in `/data/echr_search.db` table `_pN_backup`. Restore one pass:
```sql
UPDATE paragraphs
SET section = (SELECT section FROM _pN_backup b WHERE b.rowid = paragraphs.rowid)
WHERE rowid IN (SELECT rowid FROM _pN_backup);
```
