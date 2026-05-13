-- ============================================================
-- Faza 3 follow-up · auto-correct section drift using P38 roles.
--
-- Runs AFTER faza3_quality_gates.sql confirms drift counts are
-- non-zero but reasonable (< 5% of corpus).
--
-- Strategy: where P37's deterministic section assignment disagrees
-- with P38's triangulation role at HIGH OR MEDIUM confidence, trust
-- the multi-signal verdict.  Conservative: low-confidence rows are
-- left as P37 set them.
--
-- All three patches are wrapped in BEGIN/COMMIT so the whole pass
-- is atomic; if anything errors mid-way the DB stays consistent.
--
-- Run via:
--   ssh amuvmuser@150.254.115.204 \
--     'sqlite3 /home/amuvmuser/echr/data/echr_search.db' \
--     < scripts/faza3_section_drift_fix.sql
-- ============================================================

BEGIN;

-- ---------- Drift fix 1: separate opinions misfiled as Operative
-- DANILEŢ pattern: judges' concurring/dissenting opinion paragraphs
-- (sometimes 40-80 rows) get section='Operative part' because they
-- physically appear after the "FOR THESE REASONS, THE COURT" header
-- in the DOCX without a section boundary.  P38 catches them via the
-- "CONCURRING/DISSENTING OPINION OF JUDGE" header → all subsequent
-- rows score role_top='separate_opinion'.

UPDATE paragraphs
   SET section = 'Separate Opinion'
 WHERE section = 'Operative part'
   AND role_top = 'separate_opinion'
   AND confidence_band IN ('high', 'medium');

SELECT '1. sep-op drift fixed' AS step, changes() AS rows_changed;

-- ---------- Drift fix 2: applicant annex misfiled as Operative
-- ABBATE pattern: multi-applicant cases have an annex of applicants
-- after dispositif (sometimes 100-500 rows of names + dates + awards).
-- These get section='Operative part' but P38 scores them
-- role_top='table_cell' high-confidence (they live in tables).

UPDATE paragraphs
   SET section = 'Appendix'
 WHERE section = 'Operative part'
   AND role_top = 'table_cell'
   AND confidence_band IN ('high', 'medium');

SELECT '2. table->appendix drift fixed' AS step, changes() AS rows_changed;

-- ---------- Drift fix 3: TOC entries misfiled as main body
-- Some long judgments have a Table of Contents printed as part of the
-- "Facts" or front matter section.  P38 catches TOC entries by the
-- trailing-page-number pattern "\t<N>$".

UPDATE paragraphs
   SET section = 'Table of Contents'
 WHERE section IN ('Facts', 'Header', 'Merits')
   AND role_top = 'toc'
   AND confidence_band = 'high';

SELECT '3. toc drift fixed' AS step, changes() AS rows_changed;

-- ---------- Drift fix 4: separate opinions misfiled as Facts/Merits
-- Rare but happens when "PARTLY DISSENTING OPINION OF JUDGE X"
-- appears mid-judgment as a structural heading and the parser doesn't
-- pivot section.

UPDATE paragraphs
   SET section = 'Separate Opinion'
 WHERE section IN ('Facts', 'Merits', 'Just Satisfaction', 'Legal Framework')
   AND role_top = 'separate_opinion'
   AND confidence_band = 'high';

SELECT '4. mid-body sep-op drift fixed' AS step, changes() AS rows_changed;

-- ---------- Drift fix 5: signature/footer cleanup
-- Rows that are clearly footer/signature but got tagged as main_judgment
-- because they didn't have a recognized style class.

UPDATE paragraphs
   SET section = 'Operative part',
       numbering_block = COALESCE(numbering_block, 'judgment_footer')
 WHERE role_top IN ('footer', 'signature')
   AND confidence_band = 'high'
   AND section NOT IN ('Operative part', 'Separate Opinion');

SELECT '5. footer/signature reattach' AS step, changes() AS rows_changed;

COMMIT;

-- ---------- Verification: re-run distribution summary
SELECT '--- after drift fix ---' AS info;

SELECT section, COUNT(*) AS rows
  FROM paragraphs
 GROUP BY section
 ORDER BY rows DESC;
