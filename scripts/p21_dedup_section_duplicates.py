#!/usr/bin/env python3
"""
P21 — collapse Pop-C section-duplicate paragraph rows.

Background
----------
Population C (committee) judgments — and a smaller share of older Pop A/B —
ship in the corpus with the SAME paragraph text persisted under TWO section
labels.  L.P. v. Hungary (001-249494) carries 66 rows for a 37-paragraph
judgment; Kostyuchenko v. Russia 91 dup-groups out of 126.  The contamination
pattern is always FORWARD: Facts holds an extra copy of what is canonically
Merits / Just Satisfaction / Operative; Merits holds an extra copy of what
is canonically Just Satisfaction; etc.  Earlier passes (P14 v2, P16, P17)
INSERTed the corrected-section rows without DELETEing the originals, leaving
the doubles in place.

Detection key
-------------
``(case_id, hudoc_para_no, text[:100])``.  Tier-1 only — when hudoc_para_no
is present, that's the strongest signal of paragraph identity; the text
prefix tolerates the "JS row also carries the dispositif glued to its tail"
contamination pattern observed in L.P. ¶37.

Resolution rule
---------------
Keep the row whose section is LATER in the canonical SECTION_ORDER (Operative
> Just Satisfaction > Article 46 > Merits > Admissibility > Final Submissions
> Commission Proceedings > Legal Framework > Facts > Introduction > Header).
Move the dropped rows to ``_p21_backup`` for rollback.

Usage
-----
    python3 scripts/p21_dedup_section_duplicates.py [--db PATH] [--apply]
    python3 scripts/p21_dedup_section_duplicates.py --audit  # API-based sanity check

Without --apply, the script enumerates dup groups + prints stats.
With --apply, it backs up the affected rows then DELETEs them.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import urllib.request
import ssl
from collections import Counter, defaultdict
from pathlib import Path

# Canonical section ordering — later = winner.  Exact strings as used in the
# `paragraphs.section` column (mix of titlecase and lowercase legacy variants).
SECTION_ORDER = [
    "Header",
    "Introduction",
    "Facts Background", "Facts Proceedings", "Facts",
    "Legal Framework", "Legal Context", "Relevant legal framework",
    "Commission Proceedings",
    "Final Submissions",
    "Admissibility",
    "Merits",
    "Just Satisfaction",
    "Article 46",
    "Operative Part", "Operative part",
    "Separate Opinion",
    "Appendix",
]
SECTION_RANK = {s: i for i, s in enumerate(SECTION_ORDER)}


def text_key(text: str) -> str:
    return (text or "").strip()[:100]


def find_duplicate_groups(cur: sqlite3.Cursor) -> dict:
    """Return {(case_id, hudoc_para_no, text_prefix): [row_dicts]} for groups
    of size >= 2.  Excludes rows where hudoc_para_no is null (those are
    handled by P19-style text-merge passes, not section dedup)."""
    cur.execute(
        "SELECT rowid, case_id, section, para_idx, hudoc_para_no, "
        "       numbering_block, text "
        "FROM paragraphs WHERE hudoc_para_no IS NOT NULL"
    )
    groups = defaultdict(list)
    for r in cur.fetchall():
        d = dict(r)
        key = (d["case_id"], d["hudoc_para_no"], text_key(d["text"]))
        groups[key].append(d)
    return {k: v for k, v in groups.items() if len(v) >= 2}


def pick_keeper(rows: list[dict]) -> tuple[dict, list[dict]]:
    """Return (keeper, droppers).  Keeper = row in highest-ranked section.
    On tie, keep the row with the SHORTEST text (longer copies usually carry
    next-section contamination glued onto the tail)."""
    def rank(row):
        return SECTION_RANK.get(row["section"], -1)
    best = max(rows, key=lambda r: (rank(r), -len(r.get("text") or "")))
    keeper = best
    droppers = [r for r in rows if r["rowid"] != keeper["rowid"]]
    return keeper, droppers


def cmd_apply(db_path: Path, apply: bool) -> int:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    # Sanity: target schema must have hudoc_para_no.
    cols = {r[1] for r in cur.execute("PRAGMA table_info(paragraphs)").fetchall()}
    if "hudoc_para_no" not in cols:
        print(
            "ERROR: target DB has no `hudoc_para_no` column.  This script "
            "expects the post-P10 schema.",
            file=sys.stderr,
        )
        return 2

    print("scanning for section-duplicate paragraph rows…")
    groups = find_duplicate_groups(cur)
    print(f"  duplicate groups: {len(groups):,}")
    if not groups:
        print("  nothing to do.")
        return 0

    # Stats
    affected_cases = {k[0] for k in groups}
    total_rows = sum(len(v) for v in groups.values())
    drop_count = sum(len(v) - 1 for v in groups.values())
    print(f"  affected cases: {len(affected_cases):,}")
    print(f"  rows in dup groups: {total_rows:,}")
    print(f"  rows that would be dropped: {drop_count:,}")

    transition_counter = Counter()  # (loser_section, keeper_section) → n
    droppers_all: list[dict] = []
    for rows in groups.values():
        keeper, droppers = pick_keeper(rows)
        for d in droppers:
            transition_counter[(d["section"], keeper["section"])] += 1
            droppers_all.append(d)

    print("\n  top section-pair transitions (loser → keeper):")
    for (lo, kp), n in transition_counter.most_common(10):
        print(f"    {n:>6,}× {lo!r} → {kp!r}")

    if not apply:
        print("\n(dry run — pass --apply to actually delete)")
        return 0

    drop_rowids = [d["rowid"] for d in droppers_all]

    print(f"\napplying — deleting {len(drop_rowids):,} rows…")
    try:
        cur.execute("BEGIN")
        cur.execute("DROP TABLE IF EXISTS _p21_backup")
        cur.execute(
            "CREATE TABLE _p21_backup ("
            "rowid INTEGER PRIMARY KEY, case_id TEXT, section TEXT, "
            "para_idx INTEGER, hudoc_para_no INTEGER, numbering_block TEXT, "
            "text TEXT, keeper_section TEXT)"
        )
        for d, group in [(d, groups[(d["case_id"], d["hudoc_para_no"], text_key(d["text"]))]) for d in droppers_all]:
            keeper, _ = pick_keeper(group)
            cur.execute(
                "INSERT INTO _p21_backup (rowid, case_id, section, para_idx, "
                "hudoc_para_no, numbering_block, text, keeper_section) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (d["rowid"], d["case_id"], d["section"], d["para_idx"],
                 d["hudoc_para_no"], d["numbering_block"], d["text"],
                 keeper["section"]),
            )
        # Chunk the DELETE to avoid SQLite parameter limits.
        chunk = 500
        for i in range(0, len(drop_rowids), chunk):
            batch = drop_rowids[i:i+chunk]
            ph = ",".join("?" for _ in batch)
            cur.execute(f"DELETE FROM paragraphs WHERE rowid IN ({ph})", batch)
        con.commit()
    except Exception as exc:
        con.rollback()
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"done.  Backup retained as `_p21_backup` ({len(drop_rowids):,} rows).")
    return 0


def cmd_audit(api_base: str, sample_case_ids: list[str]) -> int:
    """API-based audit: fetch each case_id, count duplicate groups, summarise."""
    ctx = ssl._create_unverified_context()
    print(f"API audit against {api_base}\n")
    total_groups = 0
    for cid in sample_case_ids:
        try:
            with urllib.request.urlopen(
                f"{api_base}/cases/{cid}", context=ctx, timeout=10
            ) as resp:
                data = json.loads(resp.read())
        except Exception as exc:
            print(f"  {cid}: FETCH ERROR {exc}")
            continue
        paras = data.get("paragraphs", []) or data.get("paras", [])
        groups = defaultdict(list)
        for p in paras:
            if p.get("hudoc_para_no") is None:
                continue
            k = (p.get("hudoc_para_no"), text_key(p.get("text", "")))
            groups[k].append(p.get("section"))
        dup_groups = {k: v for k, v in groups.items() if len(v) >= 2}
        total_groups += len(dup_groups)
        print(f"  {cid}: {len(paras):>4} rows, {len(dup_groups):>3} dup groups "
              f"(would drop {sum(len(v)-1 for v in dup_groups.values()):>3} rows)")
    print(f"\n  total dup groups across sample: {total_groups}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="data/echr_search.db",
                    help="SQLite DB to operate on (default: data/echr_search.db).")
    ap.add_argument("--apply", action="store_true",
                    help="Apply the dedup.  Without this flag, dry-run only.")
    ap.add_argument("--audit", action="store_true",
                    help="API-based audit instead of DB inspection.  Useful "
                    "when the local DB doesn't carry hudoc_para_no.")
    ap.add_argument("--api", default="https://150.254.115.204/echr-api/api",
                    help="API base URL for --audit mode.")
    ap.add_argument("--sample", default="001-249494,001-194309,001-57619",
                    help="Comma-separated case_ids for --audit sample.")
    args = ap.parse_args()

    if args.audit:
        return cmd_audit(args.api, [s.strip() for s in args.sample.split(",") if s.strip()])

    db_path = Path(args.db).resolve()
    if not db_path.exists():
        print(f"ERROR: DB not found at {db_path}", file=sys.stderr)
        return 2
    return cmd_apply(db_path, args.apply)


if __name__ == "__main__":
    sys.exit(main())
