"""The full-text query builder: Boolean NOT and trailing-* prefix queries (api/main.py)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
import main  # noqa: E402

q = main._build_fts_query


class FtsQueryTests(unittest.TestCase):
    def test_not_excludes_from_everything_before_it(self):
        self.assertEqual(q("surveillance OR interception NOT terrorism"),
                         "{text} : ((surveillance OR interception) NOT terrorism)")
        self.assertEqual(q("expulsion NOT asylum"), "{text} : (expulsion NOT asylum)")

    def test_leading_not_drops_its_word(self):
        self.assertEqual(q("NOT torture prison"), "{text} : (prison)")

    def test_prefix_matches_stems_too(self):
        self.assertEqual(q("discriminat* Roma"),
                         "{text} : ((discriminat* OR discrimin OR discriminati) AND Roma)")

    def test_short_prefix_and_plain_words_unchanged(self):
        self.assertEqual(q("ab* x"), "{text} : (ab AND x)")
        self.assertEqual(q('"margin of appreciation" data NEAR retention'),
                         '{text} : ("margin of appreciation" AND NEAR(data retention, 10))')


if __name__ == "__main__":
    unittest.main()
