#!/usr/bin/env python3
"""p79 — HUDOC's translations of judgments in the English corpus (12 October 2026).

HUDOC publishes a judgment as its official English and/or French text plus translations by
governments and NGOs, each with its own item id. 21 of those translations were in the English corpus:

  * 13 translations into other languages (Ukrainian, Turkish, Armenian, Lithuanian, Czech), loaded by the
    2026 monthly updates before p60 checked the item's language. The Court's own text of each is already
    here (English, in the main database) or in the French originals (Mavrakis, Topuz, Tožičková).
    -> removed from the main database (copied into p79_removed_* first);
  * 3 correct texts under a translation's title (Svilengaćanin; the machine translations of Contrada (no. 3)
    and Ghibusi): HUDOC flags those translation items "ENG", and the title came with it -> title fixed,
    also title_en of the French originals (with Argunhan v. Turkey there);
  * 5 English translations by the European Roma Rights Centre of judgments HUDOC has only in French
    (Wallová and Walla, Sampanis, Paraskeva Todorova, Sampani, Lavida) -> kept, marked
    text_origin = 'third_party_translation' with the French original as source_case_id, the
    translation note dropped from the title (the UI labels them as unofficial).

    python3 p79_translation_items.py --main /data/echr_search.db --fr /data/echr_fr.db           # report
    python3 p79_translation_items.py --main /data/echr_search.db --fr /data/echr_fr.db --apply   # repair

Rollback: re-insert from p79_removed_* into the main database; put back title, text_origin,
source_case_id and source_language from p79_title_backup (main) and title_en from p79_title_backup (French).
Afterwards: rebuild the citations (deploy/rebuild_citations.sh --apply, then p76 for the French ones),
the Semantic Search metadata (rag/pipeline/build_cases_meta.py) and the statistics.
"""
from __future__ import annotations

import argparse
import re
import sqlite3

REMOVE = [
    "001-250131", "001-250132", "001-251104", "001-251105", "001-251106",   # Ukrainian
    "001-250281", "001-251706", "001-251716",                               # Turkish
    "001-250173", "001-250174",                                             # Armenian
    "001-250822", "001-251603",                                             # Lithuanian
    "001-251492",                                                           # Czech
]
TITLES = {
    "001-207123": "CASE OF SVILENGAĆANIN AND OTHERS v. SERBIA",
    "001-154006": "CASE OF CONTRADA v. ITALY (No. 3)",
    "001-69474": "CASE OF GHIBUSI v. ROMANIA",
}
TITLES_EN_FR = {**{k: v for k, v in TITLES.items() if k != "001-207123"}, "001-91549": "CASE OF ARGUNHAN v. TURKEY"}
ERRC = {   # English translation -> the French original on HUDOC
    "001-77715": "001-77713", "001-86798": "001-86797", "001-98210": "001-97954",
    "001-115493": "001-115169", "001-120188": "001-119974",
}
NOTE = re.compile(r"\s*-?\s*\[[^\]]*translation\].*$", re.I)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--main", required=True)
    ap.add_argument("--fr", required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    ro = not args.apply
    m = sqlite3.connect(f"file:{args.main}?mode=ro" if ro else args.main, uri=ro, timeout=600)
    f = sqlite3.connect(f"file:{args.fr}?mode=ro" if ro else args.fr, uri=ro, timeout=600)
    ph = ",".join("?" * len(REMOVE))
    present = [r[0] for r in m.execute(f"SELECT case_id FROM cases WHERE case_id IN ({ph})", REMOVE)]
    n_par = m.execute(f"SELECT count(*) FROM paragraphs WHERE case_id IN ({ph})", REMOVE).fetchone()[0]
    print(f"remove: {len(present)} of {len(REMOVE)} present ({n_par} paragraphs)")
    retitle = {cid: t for cid, t in TITLES.items() if m.execute("SELECT 1 FROM cases WHERE case_id=?", (cid,)).fetchone()}
    errc = {cid: src for cid, src in ERRC.items() if m.execute("SELECT 1 FROM cases WHERE case_id=?", (cid,)).fetchone()}
    print(f"retitle: {len(retitle)}; ERRC translations: {len(errc)}")
    left = m.execute("SELECT count(*) FROM cases WHERE lower(title) LIKE '%translation]%'").fetchone()[0]
    print(f"titles with a translation note now: {left} (after: {left - len(present) - len(retitle) - len(errc)})")
    if not args.apply:
        print("dry run: nothing written (use --apply)")
        return 0

    changed = list(retitle) + list(errc)
    cph = ",".join("?" * len(changed))
    with m:
        m.execute("DROP TABLE IF EXISTS p79_title_backup")
        m.execute(f"CREATE TABLE p79_title_backup AS SELECT case_id, title, text_origin, source_case_id, source_language "
                  f"FROM cases WHERE case_id IN ({cph})", changed)
        for t, b in (("cases", "p79_removed_cases"), ("paragraphs", "p79_removed_paragraphs"),
                     ("case_articles", "p79_removed_case_articles"), ("hudoc_metadata", "p79_removed_hudoc_metadata")):
            m.execute(f"DROP TABLE IF EXISTS {b}")
            m.execute(f"CREATE TABLE {b} AS SELECT * FROM {t} WHERE case_id IN ({ph})", REMOVE)
        for t in ("paragraphs", "case_articles", "hudoc_metadata", "cases"):
            m.execute(f"DELETE FROM {t} WHERE case_id IN ({ph})", REMOVE)
        for cid, title in retitle.items():
            m.execute("UPDATE cases SET title=? WHERE case_id=?", (title, cid))
            m.execute("UPDATE paragraphs SET title=? WHERE case_id=? AND title<>''", (title, cid))
        for cid, src in errc.items():
            title = NOTE.sub("", m.execute("SELECT title FROM cases WHERE case_id=?", (cid,)).fetchone()[0])
            m.execute("UPDATE cases SET title=?, text_origin='third_party_translation', source_case_id=?, "
                      "source_language='FRE' WHERE case_id=?", (title, src, cid))
            m.execute("UPDATE paragraphs SET title=? WHERE case_id=? AND title<>''", (title, cid))
    fids = [cid for cid in TITLES_EN_FR if f.execute("SELECT 1 FROM cases WHERE case_id=?", (cid,)).fetchone()]
    with f:
        f.execute("DROP TABLE IF EXISTS p79_title_backup")
        f.execute(f"CREATE TABLE p79_title_backup AS SELECT case_id, title_en FROM cases "
                  f"WHERE case_id IN ({','.join('?' * len(fids))})", fids)
        for cid in fids:
            f.execute("UPDATE cases SET title_en=? WHERE case_id=?", (TITLES_EN_FR[cid], cid))
    for con in (m, f):
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    print("done:", m.execute("SELECT count(*) FROM cases WHERE lower(title) LIKE '%translation]%'").fetchone()[0],
          "translation titles left in the main database;",
          f.execute("SELECT count(*) FROM cases WHERE lower(title_en) LIKE '%translation]%'").fetchone()[0], "in the French one;",
          m.execute("SELECT count(*) FROM cases WHERE text_origin='third_party_translation'").fetchone()[0], "ERRC marked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
