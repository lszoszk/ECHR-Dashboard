"""Outcome filter of the API (api/main.py _outcome_clause): the four rail options, incl. inadmissible / struck out."""
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

os.environ["ECHR_DB_PATH"] = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import main  # noqa: E402

ROWS = [  # case_id, violation, non_violation, conclusion
    ("v", '["6"]', "[]", "Violation of Article 6"),
    ("m", '["6"]', '["8"]', "Violation of Article 6;No violation of Article 8"),
    ("n", "[]", '["8"]', "No violation of Article 8"),
    ("i", '["3"]', "[]", "Remainder inadmissible;Violation of Article 3"),
    ("s", "[]", "[]", "Struck out of the list"),
]


def matching(outcomes):
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE cases (case_id, violation, non_violation, conclusion, document_type)")
    con.executemany("INSERT INTO cases VALUES (?, ?, ?, ?, 'Judgment (Merits)')", ROWS)
    clause = main._outcome_clause(outcomes)
    return {r[0] for r in con.execute(f"SELECT case_id FROM cases c WHERE {clause or '1=1'}")}


class OutcomeFilterTests(unittest.TestCase):
    def test_violation_found_covers_mixed(self):
        self.assertEqual(matching(["violation_only", "both"]), {"v", "m", "i"})

    def test_no_violation(self):
        self.assertEqual(matching(["non_violation_only"]), {"n"})

    def test_inadmissible_and_struck_out_from_conclusion(self):
        self.assertEqual(matching(["has_inadmissibility"]), {"i"})
        self.assertEqual(matching(["is_struck_out"]), {"s"})
        self.assertEqual(matching(["has_inadmissibility", "is_struck_out"]), {"i", "s"})

    def test_unknown_values_are_ignored(self):
        self.assertIsNone(main._outcome_clause(["nonsense"]))
        self.assertIsNone(main._outcome_clause([]))


if __name__ == "__main__":
    unittest.main()
