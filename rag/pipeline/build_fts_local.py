#!/usr/bin/env python3
"""Build a local BM25 (FTS5) index over the SAME Option-C corpus that was embedded,
so the BM25 arm shares the dense arm's exact rowid space and (case_id, section_no)
keys — no VM round-trip, no regex section recovery.

Reads data/corpus_textsC.jsonl.gz, writes data/corpus_fts.db with:
  para(rid INTEGER PRIMARY KEY, case_id TEXT, section_no INT, text TEXT)
  para_fts  FTS5(text, content='para', content_rowid='rid')   # porter stemmer

  python3 build_fts_local.py
"""
import gzip, json, sqlite3, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "data" / "corpus_textsC.jsonl.gz"
DB = HERE / "data" / "corpus_fts.db"

def main():
    if DB.exists(): DB.unlink()
    con = sqlite3.connect(DB)
    con.execute("PRAGMA journal_mode=OFF"); con.execute("PRAGMA synchronous=OFF")
    con.execute("CREATE TABLE para(rid INTEGER PRIMARY KEY, case_id TEXT, section_no INT, text TEXT)")
    t0 = time.time(); n = 0; batch = []
    def flush():
        con.executemany("INSERT INTO para(rid,case_id,section_no,text) VALUES(?,?,?,?)", batch)
        batch.clear()
    for line in gzip.open(SRC, "rt", encoding="utf-8"):
        r = json.loads(line)
        batch.append((r["rowid"], r["case_id"], r["section_no"], r["text"]))
        n += 1
        if len(batch) >= 5000: flush()
        if n % 200000 == 0: print(f"  loaded {n:,}", flush=True)
    if batch: flush()
    con.commit()
    print(f"[para] {n:,} rows in {time.time()-t0:.0f}s; building FTS5 ...")
    t1 = time.time()
    con.execute("CREATE VIRTUAL TABLE para_fts USING fts5(text, content='para', content_rowid='rid', tokenize='porter unicode61')")
    con.execute("INSERT INTO para_fts(para_fts) VALUES('rebuild')")
    con.commit()
    print(f"[fts] built in {time.time()-t1:.0f}s -> {DB} ({DB.stat().st_size/1e6:.0f} MB)")
    con.close()

if __name__ == "__main__":
    main()
