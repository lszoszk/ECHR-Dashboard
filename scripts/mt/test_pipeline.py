#!/usr/bin/env python3
"""Tests for the row-level merge (assemble.py) and repair list (judge.py).   python3 scripts/mt/test_pipeline.py"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import judge  # noqa: E402
from assemble import merged_translation  # noqa: E402


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False))


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        case = self.dir / "001-1"
        case.mkdir()
        self.chunk = case / "chunk_000.json"
        write(self.chunk, {"rows": [{"id": "r1", "fr": "Le requérant est né en 1950."},
                                    {"id": "r2", "fr": "Il réside à Paris."},
                                    {"id": "r3", "fr": "Voir Kudła c. Pologne [GC], no 30210/96, § 156."}]})
        write(case / "chunk_000.haiku.json", {"r1": "The applicant was born in 1950.", "r2": "He lives in Paris.",
                                               "r3": "See Kudła v. Poland [GC], § 156."})       # lost the application number

    def test_a_repair_file_replaces_only_its_rows(self):
        write(self.chunk.with_name("chunk_000.fix.json"), {"r3": "See Kudła v. Poland [GC], no. 30210/96, § 156."})
        merged = merged_translation(self.chunk, ["fix", "haiku"])
        self.assertEqual(merged["r1"], "The applicant was born in 1950.")
        self.assertIn("30210/96", merged["r3"])

    def test_rule_flagged_rows_are_listed_by_paragraph(self):
        chunks, fix, stats = judge.collect_chunks(str(self.dir), ["haiku"], None)
        self.assertEqual(fix, {"001-1__000 r3"})
        self.assertEqual(stats["rule_flagged_rows"], 1)

    def test_after_repair_nothing_is_flagged(self):
        write(self.chunk.with_name("chunk_000.fix.json"), {"r3": "See Kudła v. Poland [GC], no. 30210/96, § 156."})
        _, fix, _ = judge.collect_chunks(str(self.dir), ["fix", "haiku"], None)
        self.assertEqual(fix, set())


if __name__ == "__main__":
    unittest.main()
