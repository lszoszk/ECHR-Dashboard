"""The API counts French-only citing judgments until they are loaded into `cases`, and never twice."""
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ["ECHR_DB_PATH"] = DB
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import main  # noqa: E402
import p70_french_only_metadata as p70  # noqa: E402


def database():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE cases (case_id TEXT PRIMARY KEY)")
    con.executemany("INSERT INTO cases VALUES (?)", [("001-1",), ("001-2",)])
    con.executescript(p70.tables_sql(
        [("001-9", "001-90", "CASE OF A v. B", "1/01", "01/01/2001", "Greece", "u"),
         ("001-8", "001-80", "CASE OF C v. D", "2/02", "01/01/2002", "Italy", "u")],
        [("001-9", "001-1", "hudoc_caselaw"), ("001-8", "001-1", "hudoc_extracted"),
         ("001-8", "001-2", "hudoc_extracted")]))
    return con


class FrenchOnlyCitedByTests(unittest.TestCase):
    def test_counts_distinct_french_only_citers(self):
        cur = database().cursor()
        self.assertEqual(main._french_only_cited_by(cur, ["001-1", "001-2", "001-3"]), {"001-1": 2, "001-2": 1})

    def test_a_judgment_loaded_into_cases_is_not_counted_again(self):
        con = database()
        con.execute("INSERT INTO cases VALUES ('001-9')")          # translated and loaded: case_citations has its links
        self.assertEqual(main._french_only_cited_by(con.cursor(), ["001-1"]), {"001-1": 1})

    def test_missing_tables_mean_no_french_only_citers(self):
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        self.assertEqual(main._french_only_cited_by(con.cursor(), ["001-1"]), {})

    def test_no_ids(self):
        self.assertEqual(main._french_only_cited_by(database().cursor(), []), {})


if __name__ == "__main__":
    unittest.main()
