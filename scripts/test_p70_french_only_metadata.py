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


if __name__ == "__main__":
    unittest.main()
