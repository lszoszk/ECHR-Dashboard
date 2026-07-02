#!/usr/bin/env python3
"""P60 — relabel boilerplate rows mislabelled as body paragraphs.

Problem (UX audit, lawyer perspective): ~85k rows carry row_role='paragraph'
but are procedural boilerplate (court-composition formulae, signature lines,
appearance lists, elision rows) or sub-headings / quoted-instrument lines.
They surface as search hits and, lacking a HUDOC ¶ number, cannot be cited.

Method (established P5x pattern):
  Stage-1  curated template families (this file, RULES) — precision by
           construction, calibrated by eyeball on samples;
  Stage-2  LLM-judge (Sonnet subagents) verdicts over the remaining DISTINCT
           texts — supplied via --verdicts (a JSON {text: category} map built from
           the judges' TSV outputs).

Safety:
  * Pool is narrow: row_role='paragraph' AND hudoc_para_no IS NULL AND
    3 ≤ len(text) ≤ 130.  Numbered paragraphs are NEVER touched.
  * Dry-run by default; --apply required to write.
  * Every change is recorded first in backup table role_backup_p60
    (rowid, old_role, new_role, batch) — restore with --restore.
  * Verdict category 'paragraph' (= keep) is ignored, never written.

Usage (inside the echr-api container):
  python3 p60_heal_boilerplate.py                    # dry-run, rule stats
  python3 p60_heal_boilerplate.py --verdicts map.json
  python3 p60_heal_boilerplate.py --verdicts map.json --apply
  python3 p60_heal_boilerplate.py --restore          # undo everything
"""
from __future__ import annotations
import argparse, json, os, re, sqlite3, sys
from datetime import datetime, timezone

DB = os.environ.get("ECHR_DB_PATH", "/data/echr_search.db")

RULES: list[tuple[str, str]] = [
    ("metadata", r"^Delivers the following judgment"),
    ("metadata", r"^This judgment (is final|may be|will become)"),
    ("metadata", r"^The European Court of Human Rights \((First|Second|Third|Fourth|Fifth|Grand)"),
    ("metadata", r"^Having regard to:?$"),
    ("metadata", r"^Having deliberated in private on .{4,40},?$"),
    ("metadata", r"^(the )?parties[’'] observations;?$"),
    ("metadata", r"^Prepared by the Registry"),
    ("metadata", r"^\(Translation\)$"),
    ("metadata", r"^(Judgment|Strasbourg|FINAL|final)$"),
    ("metadata", r"^\.{2,}[”\"']?$|^[“\"']\.{2,}$|^…[”\"']?$|^[“\"']…$"),
    ("metadata", r"^[-–—]?\s*\(?[a-e]?\)?\s*for the (Government|Commission|applicants?|Delegate of the Commission|third[- ]party)\b[.:;]?$"),
    ("metadata", r"^(and )?the (decision|observations|documents|letters?) (of|submitted|lodged)\b.{0,60};$"),
    ("signature", r"^(Signed:\s.*|President|Registrar|Deputy Registrar|Section Registrar)$"),
    ("heading_h4", r"^List of (applicants|applications|cases|appendices):?$"),
    ("heading_h4", r"^(Pecuniary damage|Non-pecuniary damage|Costs and expenses|Default interest)$"),
    ("heading_h4", r"^The (parties[’']|Government[’']s|applicants?[’']s?) (submissions?|arguments?)$"),
    ("heading_h4", r"^The Court[’']s (assessment|considerations?)$"),
    ("quote", r"^Everyone charged with a criminal offence"),
    ("quote", r"^Article \d+.{0,40}of the Convention provides"),
    ("quote", r"^[“\"]"),
]
# LLM-judge 'heading' verdicts map onto heading_h4 (lowest heading tier).
VERDICT_TO_ROLE = {"metadata": "metadata", "signature": "signature",
                   "heading": "heading_h4", "quote": "quote"}

POOL_WHERE = ("row_role='paragraph' AND hudoc_para_no IS NULL "
              "AND length(text) BETWEEN 3 AND 130")


def classify(text: str, rules, verdicts) -> str | None:
    for role, rx in rules:
        if rx.search(text):
            return role
    v = verdicts.get(text)
    if v and v != "paragraph":
        return VERDICT_TO_ROLE.get(v)
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verdicts", help="JSON file: {text: category} from the LLM judge")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--restore", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect(DB)
    cur = con.cursor()

    if a.restore:
        n = 0
        for rowid, old in cur.execute("SELECT rowid_ref, old_role FROM role_backup_p60").fetchall():
            cur.execute("UPDATE paragraphs SET row_role=? WHERE rowid=?", (old, rowid))
            n += 1
        con.commit()
        print(f"[restore] reverted {n:,} rows from role_backup_p60")
        return

    verdicts = {}
    if a.verdicts:
        verdicts = json.load(open(a.verdicts, encoding="utf-8"))
        print(f"[verdicts] loaded {len(verdicts):,} text verdicts")

    rules = [(role, re.compile(rx)) for role, rx in RULES]

    plan: dict[str, list[int]] = {}
    samples: dict[str, list[str]] = {}
    for rowid, text in cur.execute(f"SELECT rowid, text FROM paragraphs WHERE {POOL_WHERE}"):
        role = classify(text or "", rules, verdicts)
        if role:
            plan.setdefault(role, []).append(rowid)
            s = samples.setdefault(role, [])
            if len(s) < 8 and (text or "") not in s:
                s.append(text or "")

    total = sum(len(v) for v in plan.values())
    print(f"[plan] {total:,} rows to relabel")
    for role, ids in sorted(plan.items()):
        print(f"  -> {role:<11} {len(ids):>7,} rows")
        for s in samples[role]:
            print(f"       «{s[:78]}»")

    if not a.apply:
        print("\nDRY-RUN — nothing written. Re-run with --apply to execute.")
        return

    cur.execute("""CREATE TABLE IF NOT EXISTS role_backup_p60(
        rowid_ref INTEGER PRIMARY KEY, old_role TEXT, new_role TEXT, batch TEXT)""")
    batch = datetime.now(timezone.utc).isoformat(timespec="seconds")
    n = 0
    for role, ids in plan.items():
        for rowid in ids:
            cur.execute("INSERT OR IGNORE INTO role_backup_p60 "
                        "SELECT rowid, row_role, ?, ? FROM paragraphs WHERE rowid=?",
                        (role, batch, rowid))
            cur.execute("UPDATE paragraphs SET row_role=? WHERE rowid=?", (role, rowid))
            n += 1
    con.commit()
    print(f"[apply] relabelled {n:,} rows (backup in role_backup_p60, batch {batch})")


if __name__ == "__main__":
    main()
