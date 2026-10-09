#!/usr/bin/env python3
"""Tests for scripts/mt/citations.py.   python3 scripts/mt/test_citations.py"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import citations as c  # noqa: E402


class ConvertTests(unittest.TestCase):
    def test_court_citation_note_examples(self):
        self.assertEqual(c.convert("M.S.S. c. Belgique et Grèce [GC], no 30696/09, §§ 216-222, CEDH 2011"),
                         "M.S.S. v. Belgium and Greece [GC], no. 30696/09, §§ 216-222, ECHR 2011")
        self.assertEqual(c.convert("Handyside c. Royaume-Uni, 7 décembre 1976, § 49, série A no 24"),
                         "Handyside v. the United Kingdom, 7 December 1976, § 49, Series A no. 24")
        self.assertEqual(c.convert("Brusco c. Italie (déc.), no 69789/01, CEDH 2001-IX"),
                         "Brusco v. Italy (dec.), no. 69789/01, ECHR 2001-IX")
        self.assertEqual(c.convert("Ahmed c. Autriche, 17 décembre 1996, Recueil des arrêts et décisions 1996-VI"),
                         "Ahmed v. Austria, 17 December 1996, Reports of Judgments and Decisions 1996-VI")
        self.assertEqual(c.convert("nos 123/05 et 2 autres, 1er mars 2010"), "nos. 123/05 and 2 others, 1 March 2010")

    def test_states_with_article(self):
        self.assertEqual(c.convert("X c. Pays-Bas"), "X v. the Netherlands")
        self.assertEqual(c.convert("Y c. République tchèque"), "Y v. the Czech Republic")

    def test_plain_text_untouched(self):
        s = "The applicant, Mr A. c., complained of the decision."
        self.assertEqual(c.convert(s), s)


class CheckTests(unittest.TestCase):
    def test_complete_translation_passes(self):
        fr = "Voir Brusco c. Italie (déc.), no 69789/01, § 12, 6 septembre 2001."
        en = "See Brusco v. Italy (dec.), no. 69789/01, § 12, 6 September 2001."
        self.assertEqual(c.check(fr, en), [])

    def test_lost_number_pinpoint_and_date_are_reported(self):
        fr = "Voir Brusco c. Italie (déc.), no 69789/01, § 12, 6 septembre 2001."
        en = "See Brusco v. Italy (déc.), no. 69789/02, 6 Sept. 2001."
        problems = " | ".join(c.check(fr, en))
        for word in ("69789/01", "§ 12", "6 September 2001", "(déc.)"):
            self.assertIn(word, problems)


if __name__ == "__main__":
    unittest.main(verbosity=2)
