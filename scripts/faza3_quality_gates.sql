-- ============================================================
-- Faza 3 quality gates — run after P37 rebuild + P38 enrichment.
-- Compares deterministic P37 section/numbering_block assignments
-- against P38's triangulation role_top, surfacing rows that need
-- attention.
--
-- Run via:
--   ssh amuvmuser@150.254.115.204 \
--     'sqlite3 /home/amuvmuser/echr/data/echr_search.db' \
--     < scripts/faza3_quality_gates.sql
-- ============================================================

.headers on
.mode column
.width 28 12

-- ---------- 3a. Cases without ANY high-confidence main_paragraph -----
SELECT
  '3a · cases lacking high-conf main_paragraph' AS gate,
  COUNT(*) AS n
FROM (
  SELECT case_id
    FROM paragraphs
   GROUP BY case_id
  HAVING SUM(role_top = 'main_paragraph'
          AND confidence_band = 'high') = 0
);

-- ---------- 3b. Operative-part coverage: P37 vs P38 ---------------
SELECT
  '3b · operative coverage P37 vs P38' AS gate,
  (SELECT COUNT(DISTINCT case_id) FROM paragraphs
    WHERE numbering_block = 'operative_dispositif') AS p37_cases,
  (SELECT COUNT(DISTINCT case_id) FROM paragraphs
    WHERE role_top = 'operative'
      AND confidence_band IN ('high','medium')) AS p38_cases,
  ABS(
    (SELECT COUNT(DISTINCT case_id) FROM paragraphs
      WHERE role_top = 'operative'
        AND confidence_band IN ('high','medium')) -
    (SELECT COUNT(DISTINCT case_id) FROM paragraphs
      WHERE numbering_block = 'operative_dispositif')
  ) AS delta;

-- ---------- 3c. Section drift: P37 says "Operative part" but P38
--                says "separate_opinion" (high conf) ---------------
SELECT
  '3c · section drift (op->sep_op)' AS gate,
  COUNT(*) AS rows_to_reassign,
  COUNT(DISTINCT case_id) AS cases_affected
FROM paragraphs
WHERE section = 'Operative part'
  AND role_top = 'separate_opinion'
  AND confidence_band IN ('high', 'medium');

-- ---------- 3d. Section drift: P37 says "Operative part" but P38
--                says "table_cell" (annex appendix) ---------------
SELECT
  '3d · section drift (op->appendix)' AS gate,
  COUNT(*) AS rows_to_reassign,
  COUNT(DISTINCT case_id) AS cases_affected
FROM paragraphs
WHERE section = 'Operative part'
  AND role_top = 'table_cell'
  AND confidence_band IN ('high', 'medium');

-- ---------- 3e. Confidence-band distribution overall --------------
SELECT
  '3e · band distribution' AS gate,
  confidence_band,
  COUNT(*) AS n,
  ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM paragraphs WHERE role_top IS NOT NULL), 1) AS pct
FROM paragraphs
WHERE role_top IS NOT NULL
GROUP BY confidence_band
ORDER BY n DESC;

-- ---------- 3f. Role distribution overall --------------------------
SELECT
  '3f · role distribution' AS gate,
  role_top,
  COUNT(*) AS n,
  ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM paragraphs WHERE role_top IS NOT NULL), 1) AS pct
FROM paragraphs
WHERE role_top IS NOT NULL
GROUP BY role_top
ORDER BY n DESC;

-- ---------- 3g. Panel-10 spot-check ------------------------------
SELECT
  '3g · panel 10' AS gate,
  case_id,
  COUNT(*) AS total,
  SUM(role_top = 'main_paragraph' AND confidence_band = 'high') AS main_hi,
  SUM(role_top = 'operative' AND confidence_band IN ('high','medium')) AS op,
  SUM(role_top = 'separate_opinion' AND confidence_band IN ('high','medium')) AS sep_op,
  SUM(role_top = 'heading') AS heading,
  SUM(role_top = 'quote') AS quote,
  SUM(role_top = 'table_cell') AS table_cell,
  SUM(confidence_band IN ('low','unknown')) AS low_or_unknown
FROM paragraphs
WHERE case_id IN (
  '001-247839',   -- DANILEŢ
  '001-249494',   -- L.P.
  '001-216400',   -- GRZĘDA
  '001-238843',   -- ABBATE
  '001-57506',    -- IRELAND v UK
  '001-57468',    -- DEUMELAND
  '001-58336',    -- ESCOUBET
  '001-78219',    -- KRASNOSHAPKA
  '001-102672',   -- SILVA BARREIRA
  '001-100655'    -- ŽIROVNICKÝ (legacy .doc)
)
GROUP BY case_id
ORDER BY case_id;

-- ---------- 3h. Sample 30 high-confidence P37↔P38 disagreements --
.print
.print "-- 3h · sample disagreements (P37 numbering vs P38 role, high conf)"
SELECT
  case_id,
  para_idx,
  section,
  numbering_block,
  role_top,
  confidence_band,
  substr(text, 1, 70) AS preview
FROM paragraphs
WHERE confidence_band = 'high'
  AND (
       (numbering_block = 'main_judgment'         AND role_top NOT IN ('main_paragraph','quote','heading'))
    OR (numbering_block = 'operative_dispositif'  AND role_top != 'operative')
    OR (numbering_block = 'separate_opinion'      AND role_top NOT IN ('separate_opinion','main_paragraph','heading'))
    OR (numbering_block = 'metadata'              AND role_top NOT IN ('metadata','heading'))
    OR (numbering_block = 'signature'             AND role_top != 'signature')
    OR (numbering_block = 'judgment_footer'       AND role_top != 'footer')
  )
ORDER BY RANDOM()
LIMIT 30;
