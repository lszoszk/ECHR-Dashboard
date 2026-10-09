"""Offline scope, denominator and source-language regression tests."""
import copy
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from build_pages_dashboard import build_payload, primary_articles
from refresh_statistics import attach_bundle, build_statistics, catalog_case, export_inventory
from hudoc_fixtures import document, fixture


def metadata(cid="001-1", **extra):
    row = document(cid)
    row.update(respondent="POL", importance="1", article="6;6-1;P1-1", violation="6-1",
               nonviolation="", conclusion="Violation of Art. 6", kpthesaurus="445", scl="", rulesofcourt="")
    row.update(extra)
    return row


class StatisticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        with sqlite3.connect(self.directory / "downloads.sqlite") as c:
            c.execute("CREATE TABLE jobs (case_id TEXT,active INTEGER,status TEXT)")

    def tearDown(self):
        self.temp.cleanup()

    def test_primary_articles_collapse_subparagraphs_and_preserve_protocols(self):
        self.assertEqual(primary_articles(["6;6-1", "6-3-d", "P1-1-2", "14+8", "13+6-1", "nonsense"]),
                         {"6", "P1-1", "14", "8", "13"})
        self.assertEqual(primary_articles(["1", "P1-1", "P12-1", "P7-4-1"]),
                         {"1", "P1-1", "P12-1", "P7-4"})

    def test_primary_article_denominator_excludes_untagged_and_deduplicates(self):
        cases = [catalog_case(metadata()),
                 catalog_case(metadata("001-2", violation="6;6-1;6-3-d", nonviolation="6-2")),
                 catalog_case(metadata("001-3", violation="", nonviolation="6-1;6")),
                 catalog_case(metadata("001-4", violation="", nonviolation=""))]
        rows = {r["article"]: r for r in build_payload(cases, "fixture")["article_analytics"]["rows"]}
        six = rows["6"]
        self.assertEqual((six["referenced"], six["with_outcome"], six["without_outcome"]), (4, 3, 1))
        self.assertEqual((six["violation_only"], six["mixed"], six["non_violation_only"]), (1, 1, 1))
        self.assertEqual(six["with_violation"], 2)
        self.assertAlmostEqual(six["violation_share"], 2 / 3)
        self.assertIsNone(rows["P1-1"]["violation_share"])

    def test_linked_outcome_tags_are_article_related_not_independent_findings(self):
        cases = [catalog_case(metadata(article="14+8;14;8", violation="14+8;14;8")),
                 catalog_case(metadata("001-2", article="", violation="14+P1-1", nonviolation="14+8"))]
        result = build_payload(cases, "fixture")["article_analytics"]
        rows = {r["article"]: r for r in result["rows"]}
        self.assertEqual(rows["14"]["with_outcome"], 2)
        self.assertEqual(rows["14"]["mixed"], 1)
        self.assertEqual(rows["8"]["violation_share"], .5)
        self.assertEqual(rows["P1-1"]["with_outcome"], 1)
        self.assertIn("not necessarily standalone findings", result["method"])
        self.assertEqual(result["default_minimum"], 100)

    def test_primary_article_order_is_numeric_and_protocols_follow_convention(self):
        case = catalog_case(metadata(article="P12-1;P1-2;P1-1;10;2;6", violation="", nonviolation=""))
        rows = build_payload([case], "fixture")["article_analytics"]["rows"]
        self.assertEqual([r["article"] for r in rows], ["2", "6", "10", "P1-1", "P1-2", "P12-1"])

    def test_committee_and_protocols_are_not_dropped(self):
        case = catalog_case(metadata(doctypebranch="COMMITTEE"))
        result = build_payload([case], "fixture")
        self.assertEqual(result["summary"]["committee_cases"], 1)
        self.assertEqual(result["summary"]["other_cases"], 0)
        self.assertIn("P1-1", dict(result["rankings"]["articles_top"]))

    def test_country_names_and_outcome_are_counted_once(self):
        case = catalog_case(metadata(respondent="MDA;RUS"))
        result = build_payload([case], "fixture")
        self.assertEqual(result["summary"]["total_cases"], 1)
        self.assertEqual(dict(result["rankings"]["countries_top"]), {"Moldova": 1, "Russia": 1})
        self.assertEqual(result["summary"]["violation_cases"], 1)

    def test_compact_inventory_equals_paragraph_input(self):
        case = catalog_case(metadata())
        paragraphs = [{"text": "x", "section": "Merits"}, {"text": "y", "section": "Merits"}, {"text": "z", "section": "Header"}]
        compact = build_payload([dict(case, paragraph_section_counts={"Merits": 2, "Header": 1})], "fixture")
        full = dict(case, paragraphs=paragraphs)
        del full["paragraph_section_counts"]
        original = build_payload([full], "fixture")
        self.assertEqual(compact["summary"], original["summary"])
        self.assertEqual(compact["rankings"]["sections"], original["rankings"]["sections"])

    def test_scope_excludes_decisions_and_french_duplicate(self):
        eng, fre = metadata(), metadata("001-2", languageisocode="FRE", doctype="HFJUD")
        dec = metadata("001-3", doctype="HEDEC")
        data = fixture([eng, fre, dec], ("ENG", "FRE"))
        result = build_statistics(data, {"exported_at": "2026-10-09", "cases": {}}, self.directory)
        self.assertEqual(result["summary"]["total_cases"], 1)
        self.assertEqual(result["text_coverage"]["by_origin"], {"Unavailable": 1})
        self.assertNotIn("citation_network", result)

    def test_missing_ecli_has_exact_count_not_rounded_presence(self):
        rows = [metadata(), metadata("001-2", ecli="")]
        result = build_statistics(fixture(rows, ("ENG", "FRE")),
                                  {"exported_at": "today", "cases": {}}, self.directory)
        self.assertEqual(result["quality"]["field_counts"]["ecli"], 1)
        self.assertEqual(result["quality"]["field_completeness"]["ecli"], .5)

    def test_unrecorded_production_language_is_not_guessed(self):
        inventory = {"exported_at": "today", "cases": {"001-1": {
            "paragraph_section_counts": {"Merits": 3}, "paragraph_role_counts": {"paragraph": 3}}}}
        result = build_statistics(fixture([metadata()], ("ENG", "FRE")), inventory, self.directory)
        self.assertEqual(result["text_coverage"]["by_language"], {"Unknown": 1})
        self.assertEqual(result["summary"]["total_paragraphs"], 3)

    def test_unknown_dates_rejected(self):
        data = fixture([metadata(judgementdate="invalid")], ("ENG", "FRE"))
        with self.assertRaisesRegex(ValueError, "Invalid judgment date"):
            build_statistics(data, {"exported_at": "today", "cases": {}}, self.directory)

    def test_export_is_read_only_and_excludes_blank_rows(self):
        db = self.directory / "production.db"
        with sqlite3.connect(db) as c:
            c.executescript("CREATE TABLE cases (case_id TEXT); CREATE TABLE paragraphs (case_id TEXT,section TEXT,row_role TEXT,text TEXT);")
            c.execute("INSERT INTO cases VALUES ('001-1')")
            c.executemany("INSERT INTO paragraphs VALUES ('001-1','Merits','paragraph',?)", [("abc",), ("",), ("   ",)])
        before = db.read_bytes()
        inventory = export_inventory(db)
        self.assertEqual(inventory["cases"]["001-1"]["paragraph_section_counts"], {"Merits": 1})
        self.assertEqual(db.read_bytes(), before)

    def test_french_fallback_checks_ecli_date_count_and_hash(self):
        eng = metadata()
        fre = metadata("001-2", languageisocode="FRE", doctype="HFJUD")
        bundle = {"case_id": eng["itemid"], "official_metadata": eng, "source_metadata": fre,
                  "source_language": "FRE",
                  "source_sha256": "abc", "paragraphs": [{"section": "Merits", "text": "texte", "row_role": "paragraph"}]}
        path = self.directory / "parsed.json"
        job = {"parsed_file": "parsed.json", "source_case_id": "001-2", "source_language": "FRE",
               "source_sha256": "abc", "paragraph_count": 1}
        path.write_text(json.dumps(bundle))
        case = catalog_case(eng)
        attach_bundle(case, job, self.directory)
        self.assertEqual(case["paragraph_section_counts"], {"Merits": 1})
        for field, value in [("ecli", "different"), ("kpdate", "1960-01-01"), ("doctypebranch", "COMMITTEE")]:
            bad = copy.deepcopy(bundle)
            bad["source_metadata"][field] = value
            path.write_text(json.dumps(bad))
            with self.assertRaises(ValueError): attach_bundle(case, job, self.directory)
        path.write_text(json.dumps(bundle))
        with self.assertRaises(ValueError): attach_bundle(case, dict(job, paragraph_count=2), self.directory)
        with self.assertRaises(ValueError): attach_bundle(case, dict(job, source_sha256="bad"), self.directory)

    def test_award_trend_does_not_require_a_numeric_eur_amount(self):
        case = catalog_case(metadata(conclusion="Non-pecuniary damage awarded (Article 41)"))
        result = build_payload([case], "fixture")
        self.assertEqual(result["conclusion_analytics"]["conclusion_outcomes_by_year"][0][3], 1)

    def test_topic_trends_use_actual_top_terms_and_pairs_are_not_truncated(self):
        case = catalog_case(metadata(kpthesaurus=";".join(str(n) for n in range(20000, 20009)) + ";20000"))
        result = build_payload([case], "fixture")["thesaurus_analytics"]
        self.assertEqual(result["unique_terms"], 9)
        self.assertEqual(result["terms_by_year_labels"], [row[0] for row in result["top_terms"][:5]])
        self.assertTrue(all(n == 1 for _, n in result["top_terms"]))
        # The ninth topic must participate even though the old build truncated at eight.
        self.assertTrue(any("#20008" in pair for pair, _ in result["top_cooccurrences"]))


if __name__ == "__main__":
    unittest.main()
