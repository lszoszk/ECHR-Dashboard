"""Citation resolution for the Check page (api/citation_check.py)."""
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import citation_check as cc  # noqa: E402

CASES = [  # case_id, case_no, title, date, document_type, originating_body
    ("001-58920", "30210/96", "CASE OF KUDLA v. POLAND", "26/10/2000", "Judgment (Merits and Just Satisfaction)", "Court (Grand Chamber)"),
    ("001-59686", "36022/97", "CASE OF HATTON AND OTHERS v. THE UNITED KINGDOM", "02/10/2001", "Judgment (Merits and Just Satisfaction)", "Court (Third Section)"),
    ("001-61188", "36022/97", "CASE OF HATTON AND OTHERS v. THE UNITED KINGDOM", "08/07/2003", "Judgment (Merits and Just Satisfaction)", "Court (Grand Chamber)"),
    ("001-57499", "5493/72", "CASE OF HANDYSIDE v. THE UNITED KINGDOM", "07/12/1976", "Judgment (Merits)", "Court (Plenary)"),
    ("001-57500", "5493/72", "CASE OF HANDYSIDE v. THE UNITED KINGDOM (ARTICLE 50)", "01/01/1978", "Judgment (Just Satisfaction)", "Court (Plenary)"),
    ("001-22099", "52207/99", "BANKOVIC AND OTHERS v. BELGIUM AND OTHERS", "12/12/2001", "Decision", "Court (Grand Chamber)"),
    ("001-90000", "1111/10", "CASE OF NOWAK v. TURKEY", "01/02/2012", "Judgment (Committee)", "25"),
    ("001-90001", "2222/10", "CASE OF NOWAK v. TURKEY (No. 2)", "01/02/2013", "Judgment (Committee)", "25"),
]
FRENCH = [("001-59122", "001-59122", "CASE OF LUNARI v. ITALY", "21463/93", "11/01/2001", "Italy", "https://hudoc.echr.coe.int/fre?i=001-59122")]


def index():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE cases (case_id, case_no, title, judgment_date, document_type, originating_body, "
                "importance, hudoc_url)")
    con.executemany("INSERT INTO cases VALUES (?, ?, ?, ?, ?, ?, '1', '')", CASES)
    con.execute("CREATE TABLE french_only_cases (case_id, source_id, title, case_no, judgment_date, respondent_state, hudoc_url)")
    con.executemany("INSERT INTO french_only_cases VALUES (?, ?, ?, ?, ?, ?, ?)", FRENCH)
    return cc.CitationIndex.from_db(con)


IDX = index()


def resolve(**item):
    return cc.resolve_item(IDX, cc.clean_item({"key": "k", **item}))


class CitationCheckTests(unittest.TestCase):
    def test_found_by_application_number(self):
        r = resolve(appnos=["30210/96"], name="Kudła v. Poland", gc=True)
        self.assertEqual((r["status"], r["match"]["case_id"]), ("found", "001-58920"))

    def test_real_number_wrong_name(self):
        r = resolve(appnos=["30210/96"], name="Smith v. Poland")
        self.assertEqual(r["status"], "check")
        self.assertIn("KUDLA v. POLAND", r["notes"][0])

    def test_gc_marker_picks_the_grand_chamber_judgment(self):
        r = resolve(appnos=["36022/97"], name="Hatton and Others v. the United Kingdom", gc=True)
        self.assertEqual((r["status"], r["match"]["case_id"]), ("found", "001-61188"))

    def test_chamber_judgment_later_referred_to_the_grand_chamber(self):
        r = resolve(appnos=["36022/97"], name="Hatton and Others v. the United Kingdom", date="2001-10-02")
        self.assertEqual((r["status"], r["match"]["case_id"]), ("check", "001-59686"))
        self.assertTrue(any("referred to the Grand Chamber" in n for n in r["notes"]))

    def test_gc_marker_on_a_chamber_judgment(self):
        r = resolve(appnos=["1111/10"], name="Nowak v. Türkiye", gc=True)
        self.assertEqual(r["status"], "check")
        self.assertTrue(any("Cited as [GC]" in n for n in r["notes"]))

    def test_wrong_date(self):
        r = resolve(appnos=["30210/96"], name="Kudła v. Poland", gc=True, date="2001-10-26")
        self.assertEqual(r["status"], "check")

    def test_old_judgment_by_name_and_date_principal_not_article_50(self):
        r = resolve(name="Handyside v. the United Kingdom", date="1976-12-07")
        self.assertEqual((r["status"], r["match"]["case_id"]), ("found", "001-57499"))
        r = resolve(name="Handyside v. the United Kingdom")
        self.assertEqual(r["match"]["case_id"], "001-57499")

    def test_french_only(self):
        r = resolve(appnos=["21463/93"], name="Lunari v. Italy")
        self.assertEqual(r["status"], "outside")
        self.assertTrue(r["match"]["french_only"])
        self.assertEqual(resolve(appnos=["21463/93"], name="Rossi v. Italy")["status"], "check")

    def test_invented(self):
        self.assertEqual(resolve(appnos=["99999/19"], name="Kowalski v. Poland")["status"], "not_found")
        self.assertEqual(resolve(name="Kowalski v. Poland")["status"], "not_found")

    def test_decision(self):
        self.assertEqual(resolve(appnos=["52207/99"], dec=True, gc=True)["status"], "found")
        self.assertEqual(resolve(appnos=["12345/06"], dec=True)["status"], "outside")

    def test_name_without_number_suffix_is_ambiguous(self):
        r = resolve(name="Nowak v. Turkey")
        self.assertEqual(r["status"], "found")          # "Nowak v. Turkey" exists exactly
        r = resolve(name="Nowak v. Turkey (no. 2)")
        self.assertEqual(r["match"]["case_id"], "001-90001")

    def test_name_key(self):
        self.assertEqual(cc.name_key("CASE OF KUDLA v. POLAND (No. 2)"), cc.name_key("Kudła v. Poland (no. 2) [GC]"))
        self.assertEqual(cc.name_key("X v. Türkiye"), cc.name_key("X v. TURKEY"))


if __name__ == "__main__":
    unittest.main()
