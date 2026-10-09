#!/usr/bin/env python3
"""Tests for scripts/p69_sync_hudoc_metadata.py (apply step).

    python3 scripts/test_p69_sync_hudoc_metadata.py
"""
import contextlib
import importlib.util
import io
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("p69", Path(__file__).with_name("p69_sync_hudoc_metadata.py"))
p69 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p69)


def setup(tmp):
    db = Path(tmp) / "t.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE cases (case_id TEXT PRIMARY KEY, violation TEXT, non_violation TEXT, "
                "violation_inferred TEXT, non_violation_inferred TEXT)")
    con.executemany("INSERT INTO cases VALUES (?,?,?,?,?)", [
        ("001-1", '["8-1","8","9","9-1"]', "[]", '["9"]', "[]"),   # HUDOC says 8;8-1
        ("001-2", '["3"]', "[]", "[]", "[]"),                       # HUDOC has no outcome fields
        ("001-3", "[]", "[]", "[]", "[]"),                          # not returned by HUDOC
    ])
    con.commit()
    con.close()
    meta = Path(tmp) / "m.json"
    meta.write_text(json.dumps({
        "001-1": {"violation": "8;8-1", "nonviolation": "13+8-1", "scl": "A v. B, no. 1/01;C v. D, no. 2/02",
                  "issue": "Child Welfare Act", "externalsources": "", "rulesofcourt": "39"},
        "001-2": {"violation": "", "nonviolation": None, "scl": ""},
    }))
    return db, meta


def run(argv):
    old = sys.argv
    sys.argv = ["p69", *argv]
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            return p69.main()
    finally:
        sys.argv = old


class ApplyTests(unittest.TestCase):
    def test_apply_replaces_outcomes_keeps_empty_and_backs_up_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            db, meta = setup(tmp)
            self.assertEqual(run(["apply", "--db", str(db), "--meta", str(meta)]), 0)      # dry run
            con = sqlite3.connect(db)
            self.assertEqual(con.execute("SELECT violation FROM cases WHERE case_id='001-1'").fetchone()[0],
                             '["8-1","8","9","9-1"]')
            con.close()
            self.assertEqual(run(["apply", "--db", str(db), "--meta", str(meta), "--apply"]), 0)
            con = sqlite3.connect(db)
            row = con.execute("SELECT violation, non_violation, violation_inferred, strasbourg_caselaw, domestic_law, "
                              "rules_of_court FROM cases WHERE case_id='001-1'").fetchone()
            self.assertEqual(json.loads(row[0]), ["8", "8-1"])
            self.assertEqual(json.loads(row[1]), ["13+8-1"])
            self.assertEqual(row[2], "[]")
            self.assertEqual(json.loads(row[3]), ["A v. B, no. 1/01", "C v. D, no. 2/02"])
            self.assertEqual(json.loads(row[4]), ["Child Welfare Act"])
            self.assertEqual(json.loads(row[5]), ["39"])
            self.assertEqual(con.execute("SELECT violation FROM cases WHERE case_id='001-2'").fetchone()[0], '["3"]')
            self.assertEqual(con.execute("SELECT violation FROM cases WHERE case_id='001-3'").fetchone()[0], "[]")
            con.close()
            # a second run must not overwrite the original backup
            self.assertEqual(run(["apply", "--db", str(db), "--meta", str(meta), "--apply"]), 0)
            con = sqlite3.connect(db)
            self.assertEqual(con.execute("SELECT violation FROM outcome_backup_p69 WHERE case_id='001-1'").fetchone()[0],
                             '["8-1","8","9","9-1"]')
            self.assertEqual(con.execute("SELECT count(*) FROM hudoc_metadata").fetchone()[0], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
