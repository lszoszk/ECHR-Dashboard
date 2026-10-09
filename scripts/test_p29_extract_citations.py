#!/usr/bin/env python3
"""Tests for scripts/p29_extract_citations.py on a small synthetic database.

    python3 scripts/test_p29_extract_citations.py
"""
import importlib.util
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "p29", Path(__file__).with_name("p29_extract_citations.py"))
p29 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(p29)

CASES = [
    # case_id, case_no, title, judgment_date, document_type
    ("handyside", "5493/72", "CASE OF HANDYSIDE v. THE UNITED KINGDOM", "07/12/1976", "Judgment (Merits)"),
    ("golder", "4451/70", "CASE OF GOLDER v. THE UNITED KINGDOM", "21/02/1975", "Judgment (Merits)"),
    ("young", "7601/76", "CASE OF YOUNG, JAMES AND WEBSTER v. THE UNITED KINGDOM", "13/08/1981", "Judgment (Merits)"),
    ("kudla", "30210/96", "CASE OF KUDLA v. POLAND", "26/10/2000", "Judgment (Merits and Just Satisfaction)"),
    ("kudla-tr", "30210/96", "CASE OF KUDLA v. POLAND - [Armenian translation] by the Ministry", "26/10/2000", "Judgment (Merits and Just Satisfaction)"),
    ("lawless-m", "1234/57", "CASE OF LAWLESS v. IRELAND (No. 3)", "01/07/1961", "Judgment (Merits)"),
    ("lawless-js", "1234/57", "CASE OF LAWLESS v. IRELAND (No. 3)", "14/11/1962", "Judgment (Just Satisfaction)"),
    ("alpha-dec", "5000/01", "ALPHA v. ITALY", "01/01/2003", "Decision"),
    ("alpha-j", "5000/01", "CASE OF ALPHA v. ITALY", "01/01/2005", "Judgment (Merits)"),
    ("bankovic", "52207/99", "BANKOVIĆ AND OTHERS v. BELGIUM AND OTHERS", "12/12/2001", "Decision"),
    ("twin-a", "7001/80", "CASE OF TWIN v. SPAIN", "03/03/1990", "Judgment (Merits)"),
    ("twin-b", "7002/80", "CASE OF TWIN v. SPAIN", "03/03/1990", "Judgment (Merits)"),
    ("old", "100/60", "CASE OF OLD v. SPAIN", "01/01/1970", "Judgment (Merits)"),
    ("modern", "9999/15", "CASE OF SMITH v. FRANCE", "05/05/2015", "Judgment (Chamber)"),
    ("zfi", "9811/91", "CASE OF Z v. FINLAND", "25/02/1997", "Judgment (Merits)"),
    ("rh", "7336/03", "CASE OF R. H. v. AUSTRIA", "19/01/2006", "Judgment (Merits)"),
    ("nadtoka2", "5566/18", "CASE OF NADTOKA v. RUSSIA (No. 2)", "08/10/2014", "Judgment (Merits)"),
    ("gaf-ch", "22978/05", "CASE OF GAF v. GERMANY", "30/06/2008", "Judgment (Merits and Just Satisfaction)"),
    ("gaf-gc", "22978/05", "CASE OF GAF v. GERMANY", "01/06/2010", "Judgment (Merits and Just Satisfaction)"),
]
GC_BODY = {"gaf-gc"}
PARAS = {
    "modern": [
        "In Handyside v. the United Kingdom, 7 December 1976, § 49, Series A no. 24, the Court held",
        "See Golder v. the United Kingdom, judgment of 21 February 1975, Series A no. 18; and Young, James and "
        "Webster v. the United Kingdom, 13 August 1981, § 52",
        "Handyside v. France, 7 December 1976, is another matter",              # wrong State
        "Kudla v. Poland [GC], no. 30210/96, § 152, ECHR 2000-XI",
        "Lawless v. Ireland (no. 3), no. 1234/57, 1 July 1961, § 1",
        "Lawless v. Ireland (no. 3), no. 1234/57, § 1",
        "Lawless v. Ireland (no. 3), no. 1234/57, 14 November 1962, § 1",
        "Alpha v. Italy (dec.), no. 5000/01, 1 January 2003",
        "Alpha v. Italy, no. 5000/01, 1 January 2005",
        "Kudla v. Poland (dec.), no. 30210/96",                                  # decision not in corpus
        "Banković and Others v. Belgium and Others, no. 52207/99, ECHR 2001-XII",
        "Twin v. Spain, 3 March 1990, § 4",                                      # two candidates: ambiguous
        "The year 2026/01 and the date 7 December 1976 mean nothing here",
        "Charzy\u0144ski v.\u00a0Poland (no. 5000/01 (dec.), \u00a7 12), and Kudla v.\u00a0Poland (no. 30210/96, \u00a7 4)",
        "See Handyside v.\u00a0the United Kingdom, 7\u00a0December 1976, \u00a7 49",
        "Gaf v. Germany [GC], no. 22978/05, \u00a7 142, ECHR 2010",
        "Gaf v. Germany, no. 22978/05, \u00a7 10, ECHR 2008",
        "Gaf v. Germany, no. 22978/05, \u00a7 10",
        "Gaf v. Germany [GC], no. 22978/05, \u00a7 11",
        "H v. Austria (no. 46389/99, 19 January 2006)",
        "Z v. Finland, 25 February 1997",
        "H v. Austria, 19 January 2006",
        "R. H. v. Austria, 19 January 2006",
        "Nadtoka v. Russia (no. 2) (request for revision of the judgment of 8 October 2014)",
        "Nadtoka v. Russia (no. 2), 8 October 2014",
    ],
    "lawless-js": ["(Application no. 1234/57)"],
    "old": ["The Court recalls Handyside v. the United Kingdom, 7 December 1976, a later judgment"],
    "kudla-tr": ["See Handyside v. the United Kingdom, 7 December 1976"],
    "handyside": ["See Handyside v. the United Kingdom, 7 December 1976, itself"],
}


def run_extraction():
    tmp = tempfile.mkdtemp()
    db = Path(tmp) / "t.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE cases (case_id TEXT, case_no TEXT, title TEXT, judgment_date TEXT, "
                "document_type TEXT, originating_body TEXT)")
    con.executemany("INSERT INTO cases VALUES (?,?,?,?,?,?)",
                    [c + ("Court (Grand Chamber)" if c[0] in GC_BODY else "Court (Chamber)",) for c in CASES])
    con.execute("CREATE TABLE paragraphs (case_id TEXT, text TEXT)")
    for cid, texts in PARAS.items():
        con.executemany("INSERT INTO paragraphs VALUES (?,?)", [(cid, t) for t in texts])
    con.commit()
    con.close()
    old_argv = sys.argv
    sys.argv = ["p29", "--db", str(db), "--apply"]
    try:
        assert p29.main() == 0
    finally:
        sys.argv = old_argv
    con = sqlite3.connect(db)
    rows = con.execute(
        "SELECT p.text, c.cited_case_id, c.extraction_method FROM case_citations c "
        "JOIN paragraphs p ON p.rowid = c.citing_paragraph_rowid WHERE c.citing_case_id = 'modern' "
        "ORDER BY c.citing_paragraph_rowid").fetchall()
    allrows = con.execute("SELECT citing_case_id, cited_case_id FROM case_citations").fetchall()
    excerpts = con.execute("SELECT cited_case_id, raw_text FROM case_citations "
                           "WHERE extraction_method = 'name_date'").fetchall()
    con.close()
    return rows, allrows, excerpts


class P29Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows, cls.allrows, cls.excerpts = run_extraction()

    def cited(self, prefix):
        return sorted(c for t, c, _ in self.rows if t.startswith(prefix))

    def test_name_and_date_without_application_number(self):
        self.assertEqual(self.cited("In Handyside v. the United Kingdom"), ["handyside"])
        self.assertEqual(self.cited("See Golder"), ["golder", "young"])

    def test_name_date_method_is_recorded(self):
        m = {c: meth for t, c, meth in self.rows if t.startswith("In Handyside")}
        self.assertEqual(m["handyside"], "name_date")

    def test_stored_excerpt_runs_from_the_name_to_the_date(self):
        raws = [raw for c, raw in self.excerpts if c == "handyside"]
        self.assertTrue(raws)
        for raw in raws:
            self.assertTrue(raw.endswith("Handyside v. the United Kingdom, 7 December 1976"), raw)
            self.assertLess(len(raw), 70)

    def test_wrong_state_is_not_resolved(self):
        self.assertEqual(self.cited("Handyside v. France"), [])

    def test_application_number_ignores_the_translation(self):
        self.assertEqual(self.cited("Kudla v. Poland [GC]"), ["kudla"])

    def test_several_documents_one_number(self):
        self.assertEqual(self.cited("Lawless v. Ireland (no. 3), no. 1234/57, 1 July 1961"), ["lawless-m"])
        self.assertEqual(self.cited("Lawless v. Ireland (no. 3), no. 1234/57, §"), ["lawless-m"])   # principal judgment
        self.assertEqual(self.cited("Lawless v. Ireland (no. 3), no. 1234/57, 14 November 1962"), ["lawless-js"])

    def test_decision_marker_picks_the_decision(self):
        self.assertEqual(self.cited("Alpha v. Italy (dec.)"), ["alpha-dec"])
        self.assertEqual(self.cited("Alpha v. Italy, no. 5000/01"), ["alpha-j"])

    def test_decision_missing_from_corpus_is_dropped_not_credited_to_the_judgment(self):
        self.assertEqual(self.cited("Kudla v. Poland (dec.)"), [])

    def test_decision_cited_without_marker_when_it_is_the_only_document(self):
        self.assertEqual(self.cited("Banković"), ["bankovic"])

    def test_ambiguous_date_is_skipped(self):
        self.assertEqual(self.cited("Twin v. Spain"), [])

    def test_bare_year_code_is_not_a_citation(self):
        self.assertEqual(self.cited("The year 2026/01"), [])

    def test_a_judgment_cannot_cite_a_later_one(self):
        self.assertNotIn(("old", "handyside"), self.allrows)

    def test_translations_do_not_cite(self):
        self.assertFalse([r for r in self.allrows if r[0] == "kudla-tr"])

    def test_decision_marker_after_the_number(self):
        self.assertEqual(self.cited("Charzy"), ["alpha-dec", "kudla"])

    def test_no_break_spaces_do_not_hide_a_reference(self):
        self.assertEqual(self.cited("See Handyside v.\u00a0the United"), ["handyside"])

    def test_header_application_number_is_not_a_citation_of_a_sibling_document(self):
        self.assertFalse([r for r in self.allrows if r[0] == "lawless-js"])

    def test_grand_chamber_marker_and_report_year_choose_between_chamber_and_gc(self):
        self.assertEqual(self.cited("Gaf v. Germany [GC], no. 22978/05, \u00a7 142"), ["gaf-gc"])
        self.assertEqual(self.cited("Gaf v. Germany, no. 22978/05, \u00a7 10, ECHR 2008"), ["gaf-ch"])
        self.assertEqual(set(self.cited("Gaf v. Germany, no. 22978/05, \u00a7 10")), {"gaf-ch"})
        self.assertEqual(self.cited("Gaf v. Germany [GC], no. 22978/05, \u00a7 11"), ["gaf-gc"])

    def test_initials_a_foreign_number_and_revision_requests_are_not_resolved(self):
        self.assertEqual(self.cited("H v. Austria"), [])                 # other application number
        self.assertEqual(self.cited("R. H. v. Austria"), ["rh"])         # exact initials
        self.assertEqual(self.cited("Z v. Finland"), ["zfi"])
        self.assertEqual(self.cited("Nadtoka v. Russia (no. 2) (request"), [])
        self.assertEqual(self.cited("Nadtoka v. Russia (no. 2), 8 October"), ["nadtoka2"])

    def test_self_citation_dropped(self):
        self.assertNotIn(("handyside", "handyside"), self.allrows)


class GraphJsonTests(unittest.TestCase):
    def test_graph_matches_case_citations(self):
        spec = importlib.util.spec_from_file_location(
            "rag_graph", Path(__file__).with_name("build_rag_citations_json.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE cases (case_id TEXT, case_no TEXT, title TEXT, judgment_date TEXT)")
        con.executemany("INSERT INTO cases VALUES (?,?,?,?)", [
            ("a", "1/01", "CASE OF A v. X", "01/01/2001"),
            ("b", "2/02", "CASE OF B v. X", "02/02/2002"),
            ("c", "3/03", "CASE OF C v. X", "03/03/2003")])
        con.execute("CREATE TABLE case_citations (citing_case_id TEXT, cited_case_id TEXT)")
        con.executemany("INSERT INTO case_citations VALUES (?,?)",
                        [("b", "a"), ("b", "a"), ("c", "a"), ("c", "b")])
        g = mod.build_graph(con)
        self.assertEqual(g["a"]["cited_by"], ["b", "c"])
        self.assertEqual(g["c"]["cites"], ["a", "b"])
        self.assertEqual(g["b"]["cites"], ["a"])
        self.assertEqual(set(g), {"a", "b", "c"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
