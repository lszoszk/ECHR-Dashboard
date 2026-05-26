#!/usr/bin/env python3
"""Phase B — extract the to-embed corpus (Option C) from the canonical DB.

Option C = row_role='paragraph', non-empty text, EXCLUDING boilerplate/annex
sections (Header, Appendix, Summary). Verified on the benchmark: 100% of gold
sections live in role=paragraph, and ZERO gold lives in the excluded sections,
so this loses no recall. ~1.31M rows / ~147M tokens / 19,821 cases.

Runs READ-ONLY inside the echr-api container (DB at /data/echr_search.db).
Emits JSONL to stdout, one row per line:
  {"rowid":int, "case_id":str, "section_no":int|null, "section":str, "text":str}

section_no (= hudoc_para_no) is the key paraHit is scored against; keep it.
para_idx ordering is preserved so neighbouring rows stay contiguous.

Usage (on VM):
  docker exec echr-api python3 /tmp/extract_corpus.py | gzip > /tmp/corpus_textsC.jsonl.gz
"""
import sqlite3, json, sys

DB = "file:/data/echr_search.db?mode=ro"

def main():
    con = sqlite3.connect(DB, uri=True)
    cur = con.cursor()
    q = ("SELECT rowid, case_id, hudoc_para_no, section, text "
         "FROM paragraphs "
         "WHERE row_role='paragraph' AND text IS NOT NULL AND TRIM(text)<>'' "
         "AND COALESCE(section,'') NOT IN ('Header','Appendix','Summary') "
         "ORDER BY case_id,(para_idx IS NULL),para_idx,rowid")
    n = 0
    w = sys.stdout
    for rid, cid, hpno, sec, text in cur.execute(q):
        w.write(json.dumps({
            "rowid": rid,
            "case_id": cid,
            "section_no": hpno,
            "section": sec or "",
            "text": text,
        }, ensure_ascii=False))
        w.write("\n")
        n += 1
        if n % 100000 == 0:
            print(f"  ...{n:,} rows", file=sys.stderr, flush=True)
    print(f"[done] emitted {n:,} rows", file=sys.stderr)

if __name__ == "__main__":
    main()
