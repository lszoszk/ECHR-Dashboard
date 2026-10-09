#!/usr/bin/env python3
"""Tests for scripts/apply_sql_batched.py and scripts/dedupe_loaded_paragraphs.py.

    python3 scripts/test_sql_loading.py
"""
import contextlib
import importlib.util
import io
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).parent


def load(name):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


loader, dedupe = load("apply_sql_batched"), load("dedupe_loaded_paragraphs")

SQL = """BEGIN;
INSERT OR IGNORE INTO cases (case_id, title) VALUES ('001-1', 'A v. X');
INSERT INTO paragraphs (case_id, para_idx, section, hudoc_para_no, numbering_block, row_role, logical_para_idx, display_para_no, title, keywords_text, text) VALUES ('001-1', 1, 'Facts', '1', NULL, 'paragraph', 1, '1', '', '', 'first; with a semicolon
and a second line');
INSERT INTO paragraphs (case_id, para_idx, section, hudoc_para_no, numbering_block, row_role, logical_para_idx, display_para_no, title, keywords_text, text) VALUES ('001-1', 2, 'Facts', '2', NULL, 'paragraph', 2, '2', '', '', 'second');
INSERT OR IGNORE INTO cases (case_id, title) VALUES ('001-2', 'B v. Y');
INSERT INTO paragraphs (case_id, para_idx, section, hudoc_para_no, numbering_block, row_role, logical_para_idx, display_para_no, title, keywords_text, text) VALUES ('001-2', 1, 'Facts', '1', NULL, 'paragraph', 1, '1', '', '', 'third');
COMMIT;
"""


def make_db(tmp):
    db = Path(tmp) / "t.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE cases (case_id TEXT PRIMARY KEY, title TEXT)")
    con.execute("CREATE TABLE paragraphs (case_id TEXT, para_idx INT, section TEXT, hudoc_para_no TEXT, "
                "numbering_block TEXT, row_role TEXT, logical_para_idx INT, display_para_no TEXT, "
                "title TEXT, keywords_text TEXT, text TEXT)")
    con.commit()
    con.close()
    sql = Path(tmp) / "load.sql"
    sql.write_text(SQL, encoding="utf-8")
    return db, sql


def run(mod, argv):
    old = sys.argv
    sys.argv = ["x", *argv]
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return mod.main()
    finally:
        sys.argv = old


def count(db, table="paragraphs"):
    con = sqlite3.connect(db)
    try:
        return con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    finally:
        con.close()


class LoaderTests(unittest.TestCase):
    def test_loading_twice_changes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            db, sql = make_db(tmp)
            self.assertEqual(run(loader, ["--db", str(db), "--sql", str(sql), "--min-free-gb", "0"]), 0)
            self.assertEqual((count(db, "cases"), count(db)), (2, 3))
            self.assertEqual(run(loader, ["--db", str(db), "--sql", str(sql), "--min-free-gb", "0"]), 0)
            self.assertEqual((count(db, "cases"), count(db)), (2, 3))

    def test_a_statement_with_semicolon_and_newline_survives(self):
        with tempfile.TemporaryDirectory() as tmp:
            db, sql = make_db(tmp)
            run(loader, ["--db", str(db), "--sql", str(sql), "--min-free-gb", "0"])
            text = sqlite3.connect(db).execute("SELECT text FROM paragraphs WHERE para_idx=1 AND case_id='001-1'").fetchone()[0]
            self.assertEqual(text, "first; with a semicolon\nand a second line")


class DedupeTests(unittest.TestCase):
    def test_repairs_a_double_load_and_leaves_a_clean_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            db, sql = make_db(tmp)
            con = sqlite3.connect(db)
            con.executescript(SQL)
            con.executescript(SQL)                       # the accident: a plain double load
            con.close()
            self.assertEqual(count(db), 6)
            self.assertEqual(run(dedupe, ["--db", str(db), "--sql", str(sql)]), 0)       # report only
            self.assertEqual(count(db), 6)
            self.assertEqual(run(dedupe, ["--db", str(db), "--sql", str(sql), "--apply"]), 0)
            self.assertEqual(count(db), 3)
            self.assertEqual(run(dedupe, ["--db", str(db), "--sql", str(sql), "--apply"]), 0)
            self.assertEqual(count(db), 3)

    def test_a_row_that_is_not_a_copy_rolls_the_repair_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            db, sql = make_db(tmp)
            con = sqlite3.connect(db)
            con.executescript(SQL)
            con.execute("INSERT INTO paragraphs (case_id, para_idx, text) VALUES ('001-2', 9, 'stray')")
            con.commit()
            con.close()
            # 001-2 now holds 2 rows for a file that has 1: looks doubled, but the extra row is no copy
            self.assertEqual(run(dedupe, ["--db", str(db), "--sql", str(sql), "--apply"]), 1)
            self.assertEqual(count(db), 4)

    def test_stops_when_counts_are_neither_one_nor_two_times(self):
        with tempfile.TemporaryDirectory() as tmp:
            db, sql = make_db(tmp)
            con = sqlite3.connect(db)
            con.executescript(SQL)
            con.executemany("INSERT INTO paragraphs (case_id, para_idx, text) VALUES ('001-2', ?, 'stray')", [(8,), (9,)])
            con.commit()
            con.close()
            self.assertEqual(run(dedupe, ["--db", str(db), "--sql", str(sql), "--apply"]), 3)
            self.assertEqual(count(db), 5)


class RepairUpdateTests(unittest.TestCase):
    def test_updates_are_applied_in_batches_and_guarded_by_the_old_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            db, sql = make_db(tmp)
            self.assertEqual(run(loader, ["--db", str(db), "--sql", str(sql), "--min-free-gb", "0"]), 0)
            fix = Path(tmp) / "fix.sql"
            fix.write_text("\n".join(
                [f"UPDATE paragraphs SET text = 'fixed {i}' WHERE case_id = '001-1' AND para_idx = 2 AND text = '{t}';"
                 for i, t in enumerate(["second", "fixed 0", "no longer there"])]) + "\n", encoding="utf-8")
            self.assertEqual(run(loader, ["--db", str(db), "--sql", str(fix), "--min-free-gb", "0", "--batch-updates", "2"]), 0)
            con = sqlite3.connect(db)
            self.assertEqual(con.execute("SELECT text FROM paragraphs WHERE case_id='001-1' AND para_idx=2").fetchone()[0], "fixed 1")
            self.assertEqual(con.execute("SELECT count(*) FROM paragraphs").fetchone()[0], 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
