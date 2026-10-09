import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import p72_fix_sections as p72  # noqa: E402


def rows(*spec):
    return [{"para_idx": i, "section": s, "row_role": r, "text": t} for i, (s, r, t) in enumerate(spec)]


class SectionTests(unittest.TestCase):
    def test_stray_heading_takes_the_next_section_and_a_paragraph_the_previous(self):
        doc = rows(("Merits", "heading_h0", "THE LAW"),
                   ("Operative part", "heading_h1", "I. JOINDER OF THE APPLICATIONS"),
                   ("Merits", "paragraph", "12. Having regard to the similar subject matter ..."),
                   ("Just Satisfaction", "paragraph", "40. Article 41 of the Convention provides:"),
                   ("Operative part", "operative_list", "(i) EUR 14,500 to the applicant in application no. 1/01;"),
                   ("Operative part", "heading_h0", "FOR THESE REASONS, THE COURT, UNANIMOUSLY,"),
                   ("Operative part", "operative_list", "1. Holds that there has been a violation of Article 6 § 1;"))
        self.assertEqual(p72.stray_operative(doc), [(1, "Operative part", "Merits"), (4, "Operative part", "Just Satisfaction")])

    def test_no_dispositif_no_change(self):
        doc = rows(("Merits", "paragraph", "1. Text"), ("Operative part", "paragraph", "2. Holds"))
        self.assertEqual(p72.stray_operative(doc), [])

    def test_a_quotation_is_not_the_start_of_the_dispositif(self):
        doc = rows(("Operative part", "quote", "For these reasons, I ask the court to reinstate the proceedings"),
                   ("Facts", "paragraph", "64. On 27 March 2009 the applicant complained ..."))
        self.assertEqual(p72.stray_operative(doc), [])

    def test_opinion_after_the_dispositif_until_the_appendix(self):
        doc = rows(("Operative part", "heading_h0", "FOR THESE REASONS, THE COURT"),
                   ("Operative part", "operative_list", "1. Holds that there has been no violation;"),
                   ("Appendix", "paragraph", "(a) concurring opinion of Mr Lorenzen;"),
                   ("Operative part", "heading_h0", "DISSENTING OPINION OF MR. A. ROSS"),
                   ("Just Satisfaction", "paragraph", "I cannot agree with the majority ..."),
                   ("Appendix", "heading", "APPENDIX"),
                   ("Appendix", "table_cell", "Application no. 1/01"))
        self.assertEqual(p72.opinions_outside(doc), [(3, "Operative part", "Separate Opinion"),
                                                     (4, "Just Satisfaction", "Separate Opinion")])


if __name__ == "__main__":
    unittest.main()
