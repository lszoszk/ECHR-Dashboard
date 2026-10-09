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


if __name__ == "__main__":
    unittest.main()
