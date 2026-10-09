import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import p73_fill_paragraph_numbers as p73  # noqa: E402


def row(i, no, text, role="paragraph", section="Facts"):
    return {"para_idx": i, "hudoc_para_no": no, "numbering_block": "main_judgment" if no else None,
            "row_role": role, "section": section, "text": text}


class NumberTests(unittest.TestCase):
    def test_marker_and_heading_rows_get_their_number(self):
        rows = [row(0, 5, "5.  The parties filed observations."),
                row(1, None, "ITMarkFactsComplaintsStart 6.  The applicant was born in 1977.", "paragraph"),
                row(2, None, "7.  The Refugee Act", "heading_h3"),
                row(3, 8, "8.  On 2 May 2005 the Court communicated the application.")]
        plan = p73.plan_case(rows, None)
        self.assertEqual([(r["para_idx"], g, new) for r, g, _, new in plan],
                         [(1, 6, "6.  The applicant was born in 1977."), (2, 7, "7.  The Refugee Act")])

    def test_text_matched_to_hudoc_gets_number_prefix(self):
        rows = [row(0, 107, "107.  The applicant complained."),
                row(1, None, "Article 41 of the Convention provides:"),
                row(2, 109, "109.  The applicant claimed EUR 10,000.")]
        plan = p73.plan_case(rows, {108: "Article 41 of the Convention provides:"})
        self.assertEqual([(g, new) for _, g, _, new in plan], [(108, "108.\u00a0\u00a0Article 41 of the Convention provides:")])

    def test_a_numbered_quotation_that_is_not_the_paragraph_is_left_alone(self):
        rows = [row(0, 49, "49.  The report reads:"),
                row(1, None, "50. Falun Gong practitioners were detained.", "quote"),
                row(2, None, "The Court notes the following submissions of the parties."),
                row(3, 51, "51.  The applicant submitted ...")]
        plan = p73.plan_case(rows, {50: "The Court notes the following submissions of the parties."})
        self.assertEqual([(r["para_idx"], g) for r, g, _, _ in plan], [(2, 50)])

    def test_large_jumps_are_not_gaps(self):
        rows = [row(0, 10, "10.  A"), row(1, None, "11.  B"), row(2, 40, "40.  C")]
        self.assertEqual(p73.plan_case(rows, None), [])


if __name__ == "__main__":
    unittest.main()
