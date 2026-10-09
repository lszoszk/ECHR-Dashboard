import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import p70_french_only_metadata as p70


class MergeTests(unittest.TestCase):
    def test_scl_is_the_union_without_duplicates(self):
        row = p70.merge({"scl": "A v. B, no. 1/01;C v. D, no. 2/02"}, {"scl": "C v. D, no. 2/02;E c. F, no 3/03"})
        self.assertEqual(row["scl"], "A v. B, no. 1/01;C v. D, no. 2/02;E c. F, no 3/03")

    def test_extractedappno_comes_from_the_french_record(self):
        row = p70.merge({"scl": "", "extractedappno": ""}, {"extractedappno": "10/01;11/02"})
        self.assertEqual(row["extractedappno"], "10/01;11/02")

    def test_catalogue_fields_win_and_empty_ones_fall_back(self):
        row = p70.merge({"conclusion": "Violation of Art. 6-1", "issue": "", "violation": "6-1"},
                        {"conclusion": "Violation de l'art. 6-1", "issue": "x;y"})
        self.assertEqual(row["conclusion"], "Violation of Art. 6-1")
        self.assertEqual(row["issue"], "x;y")

    def test_missing_french_record_keeps_the_catalogue_values(self):
        row = p70.merge({"scl": "A v. B, no. 1/01", "ecli": "ECLI:X"}, None)
        self.assertEqual((row["scl"], row["ecli"], row["extractedappno"]), ("A v. B, no. 1/01", "ECLI:X", ""))

    def test_citing_doc_reads_date_and_application_numbers(self):
        doc = p70.citing_doc("001-1", {"docname": "CASE OF LUNARI v. ITALY", "judgementdate": "11/01/2001 00:00:00",
                                       "appno": "21463/93;21464/93"})
        self.assertEqual((doc.date, doc.date_str), ((2001, 1, 11), "11/01/2001"))
        self.assertEqual(doc.appnos, frozenset({"21463/93", "21464/93"}))

    def test_display_row_names_states_and_links_the_french_text(self):
        row = p70.display_row("001-1", "001-2", {"docname": "CASE OF A v. B", "appno": "1/01;2/02",
                                               "judgementdate": "11/01/2001 00:00:00", "respondent": "GRC;ITA"})
        self.assertEqual(row, ("001-1", "001-2", "CASE OF A v. B", "1/01; 2/02", "11/01/2001", "Greece, Italy",
                               "https://hudoc.echr.coe.int/fre?i=001-2"))

    def test_tables_sql_loads_into_sqlite_and_escapes_quotes(self):
        import sqlite3
        sql = p70.tables_sql([("001-1", "001-2", "CASE OF O'BRIEN v. IRELAND", "1/01", "11/01/2001", "Ireland", "u")],
                             [("001-1", "001-9", "hudoc_caselaw"), ("001-1", "001-9", "hudoc_caselaw")])
        con = sqlite3.connect(":memory:")
        con.executescript(sql)
        con.executescript(sql)                       # loading twice replaces, never doubles
        self.assertEqual(con.execute("SELECT title FROM french_only_cases").fetchall(), [("CASE OF O'BRIEN v. IRELAND",)])
        self.assertEqual(con.execute("SELECT count(*) FROM french_only_citations").fetchone(), (1,))


if __name__ == "__main__":
    unittest.main()
