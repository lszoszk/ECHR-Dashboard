#!/usr/bin/env python3
"""p77 — importance levels as HUDOC shows them, in the main database and the French originals.

HUDOC's API codes importance 1-4 and its search shows them as Key cases, 1, 2 and 3. The monthly update
(p60) stored the code itself until 11 October 2026, so its judgments, the decisions (p66), the machine
translations and the French originals (p75) sat one level too low (a Key case as "1"), and code 4 became
"Unspecified"; part of the original corpus also has "Unspecified" for code 4. This script sets every
document to HUDOC's level:

  * the code comes from hudoc_metadata (p69) where it is there, otherwise from HUDOC by item id;
  * a document HUDOC does not return keeps its value;
  * it writes SQL, it never changes a database itself.

    python3 p77_fix_importance.py --main echr_search.db --fr echr_fr.db --out-dir DIR

DIR receives p77_main.sql and p77_fr.sql. Each first copies (case_id, importance) of every case into
importance_backup_p77 (kept if it exists), then sets the new values in one transaction; the matching
*.rollback.sql puts the backup back.
"""
from __future__ import annotations

import argparse
import importlib.util
import sqlite3
import time
from collections import Counter
from pathlib import Path

_spec = importlib.util.spec_from_file_location("p60", Path(__file__).with_name("p60_monthly_update.py"))
p60 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(p60)

BATCH = 25


def fetch_codes(ids: list[str], delay: float) -> dict[str, str]:
    """HUDOC's importance code of each item id it returns (HUDOC matches itemid by tokens, so the
    answer is filtered to the ids asked for)."""
    out: dict[str, str] = {}
    for s in range(0, len(ids), BATCH):
        chunk = ids[s:s + BATCH]
        q = "contentsitename:ECHR AND (" + " OR ".join(f'itemid:"{i}"' for i in chunk) + ")"
        data = p60.hudoc_get({"query": q, "select": p60.META_SELECT, "sort": "itemid Ascending",
                              "start": "0", "length": "500"})
        want = set(chunk)
        for r in data.get("results", []):
            c = r.get("columns", {})
            if c.get("itemid") in want:
                out[c["itemid"]] = str(c.get("importance") or "").strip()
        if (s // BATCH) % 40 == 0:
            print(f"  HUDOC {min(s + BATCH, len(ids)):,}/{len(ids):,}", flush=True)
        time.sleep(delay)
    return out


def sql_str(v: str) -> str:
    return "'" + str(v).replace("'", "''") + "'"


def write_sql(path: Path, levels: dict[str, str]) -> None:
    """Every case with a known level is set to it (not only those that differ here), so that the file
    is right for the production copy too, whatever its current values."""
    lines = ["BEGIN;",
             "CREATE TABLE IF NOT EXISTS importance_backup_p77 AS SELECT case_id, importance FROM cases;"]
    lines += [f"UPDATE cases SET importance = {sql_str(v)} WHERE case_id = {sql_str(k)} "
              f"AND importance IS NOT {sql_str(v)};" for k, v in sorted(levels.items())]
    lines.append("COMMIT;")
    path.write_text("\n".join(lines) + "\n")
    path.with_suffix(".rollback.sql").write_text(
        "UPDATE cases SET importance = (SELECT b.importance FROM importance_backup_p77 b "
        "WHERE b.case_id = cases.case_id) WHERE case_id IN (SELECT case_id FROM importance_backup_p77);\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--main", required=True)
    ap.add_argument("--fr", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--fetch-delay", type=float, default=0.3)
    args = ap.parse_args()
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    m = sqlite3.connect(f"file:{args.main}?mode=ro", uri=True)
    f = sqlite3.connect(f"file:{args.fr}?mode=ro", uri=True)
    main_cases = dict(m.execute("SELECT case_id, importance FROM cases WHERE document_type NOT LIKE '%Press Release%'"))
    fr_cases = dict(f.execute("SELECT case_id, importance FROM cases"))
    codes = {k: str(v).strip() for k, v in m.execute(
        "SELECT case_id, importance FROM hudoc_metadata WHERE importance IS NOT NULL AND importance <> ''")}
    missing = sorted((set(main_cases) | set(fr_cases)) - set(codes))
    print(f"main {len(main_cases):,} cases, French {len(fr_cases):,}; code in hudoc_metadata for "
          f"{len(set(codes) & (set(main_cases) | set(fr_cases))):,}; fetching {len(missing):,} from HUDOC")
    codes.update(fetch_codes(missing, args.fetch_delay))

    for name, cases, path in (("main", main_cases, out / "p77_main.sql"), ("French", fr_cases, out / "p77_fr.sql")):
        levels, moves, unknown = {}, Counter(), 0
        for cid, old in cases.items():
            code = codes.get(cid)
            if code is None:
                unknown += 1
                continue
            levels[cid] = new = p60._importance(code)
            if new != (old or ""):
                moves[(old, new)] += 1
        write_sql(path, levels)
        print(f"\n{name}: {sum(moves.values()):,} of {len(cases):,} change here; {unknown:,} not returned by HUDOC (kept) -> {path}")
        for (a, b), n in moves.most_common():
            print(f"   {a!s:>12} -> {b:<10} {n:6,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
