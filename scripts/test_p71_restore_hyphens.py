import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import p71_restore_hyphens as p71  # noqa: E402


class RestoreTests(unittest.TestCase):
    def test_only_added_hyphens_count(self):
        self.assertTrue(p71.restored("EUR 5,000 in respect of nonpecuniary damage", "EUR 5,000 in respect of non-pecuniary damage"))
        self.assertTrue(p71.restored("manifestly illfounded; the coaccused", "manifestly ill-founded; the co-accused"))

    def test_anything_else_is_left_alone(self):
        self.assertFalse(p71.restored("non-pecuniary damage", "non-pecuniary damage"))           # nothing to do
        self.assertFalse(p71.restored("nonpecuniary damage", "non-pecuniary damages"))           # other change
        self.assertFalse(p71.restored("non-pecuniary", "nonpecuniary"))                          # would remove one


if __name__ == "__main__":
    unittest.main()
