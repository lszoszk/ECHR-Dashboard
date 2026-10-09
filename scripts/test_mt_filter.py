"""Machine translations are left out of search unless asked for or named (api/main.py _doc_type_clause)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ["ECHR_DB_PATH"] = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import main  # noqa: E402


class MtFilterTests(unittest.TestCase):
    def setUp(self):
        main._MT_COLUMN[:] = [True]          # as on a database with text_origin

    def tearDown(self):
        main._MT_COLUMN[:] = []

    def test_left_out_by_default(self):
        self.assertIn("machine_translation", main._doc_type_clause([]))
        self.assertIn("machine_translation", main._doc_type_clause(["chamber"]))

    def test_included_on_request_or_when_named(self):
        self.assertNotIn("machine_translation", main._doc_type_clause([], include_mt=True))
        self.assertNotIn("machine_translation", main._doc_type_clause(["committee"], include_mt=True))
        self.assertEqual(main._doc_type_clause([], explicit_lookup=True), "1=1")

    def test_database_without_the_column_is_unchanged(self):
        main._MT_COLUMN[:] = [False]
        self.assertEqual(main._doc_type_clause([]), "c.document_type NOT LIKE 'Decision%' AND 1=1".join(["(", ")"]))

    def test_years_facet_counts_judgments_of_the_default_search(self):
        import sqlite3
        con = sqlite3.connect(main.DB_PATH)
        con.execute("PRAGMA journal_mode = wal")     # the API opens it read-only, already in WAL
        con.executescript("""
            DROP TABLE IF EXISTS cases; DROP TABLE IF EXISTS case_articles; DROP TABLE IF EXISTS paragraphs;
            CREATE TABLE cases (case_id TEXT, respondent_state TEXT, importance TEXT, originating_body TEXT,
                                document_type TEXT, keywords TEXT, judgment_date TEXT, text_origin TEXT);
            CREATE TABLE case_articles (case_id TEXT, article TEXT);
            CREATE TABLE paragraphs (case_id TEXT, section TEXT);
            INSERT INTO cases VALUES ('a', 'Poland', '2', '25', 'Judgment (Merits)', '[]', '01/02/2010', NULL),
                                     ('b', 'Poland', '2', '25', 'Judgment (Merits)', '[]', '05/06/2010', NULL),
                                     ('c', 'Italy', '3', '25', 'Judgment (Merits)', '[]', '07/08/2012', NULL),
                                     ('d', 'Italy', '3', '25', 'Decision', '[]', '07/08/2012', NULL),
                                     ('e', 'France', '3', '25', 'Judgment (Merits)', '[]', '07/08/2012',
                                      'machine_translation');
        """)
        con.commit()
        con.close()
        main._FACETS_CACHE.clear()
        years = {r["year"]: r["count"] for r in main.facets(q=None, date_from=None, date_to=None)["years"]}
        self.assertEqual(years, {"2010": 2, "2012": 1})


if __name__ == "__main__":
    unittest.main()
