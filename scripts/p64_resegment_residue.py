#!/usr/bin/env python3
"""P64 — segment the 564-case residue that P63 left labelled plain `Facts`.

P63 split the Facts family for the 97.2% of cases carrying a structural
heading *within their Facts-family rows*. The probe over the remaining 564
cases (7,000 paragraphs) showed the residue is four self-explaining template
families, not a classification problem:

  1. Modern committee judgments whose `SUBJECT-MATTER OF THE CASE` heading is
     (a) HYPHENATED — P62's normaliser collapsed whitespace but not hyphens —
     and (b) often mislabelled into the `Header` section, outside P62's
     Facts-family-only scan.
  2. `PROCEDURE AND FACTS` — previously classed as a PROCEDURE marker, but it
     is the Court's merged committee block, i.e. a Subject Matter start.
  3. Just Satisfaction / Revision / Interpretation / Struck-out judgments,
     which by design have NO circumstances section: PROCEDURE → THE LAW →
     operative. Their Facts rows sit between the PROCEDURE heading and the
     first LAW-family heading, and are procedure content.
  4. French-language judgments: PROCÉDURE → EN FAIT → …CIRCONSTANCES DE
     L'ESPÈCE… → EN DROIT, committee variant OBJET DE L'AFFAIRE, revision
     variant SUR LA DEMANDE EN RÉVISION.

Method: per-case boundary rules, extended vocabulary, markers searched in
heading rows of ANY section (not just the Facts family):

  rule S  a SUBJ marker at s      -> Facts rows >= s: Subject Matter,
                                     Facts rows <  s: Procedure
  rule F  a facts-start at f      -> Facts rows >= f: Circumstances,
                                     Facts rows <  f: Procedure
  rule P  a PROC marker at p and the first LAW/operative heading L > p
                                  -> Facts rows in [p, L): Procedure;
                                     rows outside [p, L) are LEFT untouched
                                     and reported (partial-coverage cases)
  else                            -> case left untouched (true residue)

Matched SUBJ / FACTS_START / PROC heading rows that sit in `Header` or
`Introduction` for a resolved case are re-homed into the section they
introduce, so the block does not render headless (same principle as P63's
Introduction re-homing; the handful of body headings misfiled into `Header`
are moved, the 294k genuine Header metadata rows are untouched).

Safety: same conventions as P63 — dry-run by default, --apply to write,
backup table section_backup_p64, --restore to undo, chunked writes with a
long busy timeout (the live API holds a write connection), idempotent (the
pool is section='Facts', which shrinks as rules apply).

Usage (inside the echr-api container):
  python3 p64_resegment_residue.py            # dry-run + report
  python3 p64_resegment_residue.py --apply
  python3 p64_resegment_residue.py --restore
"""
from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
import time
from collections import Counter, defaultdict

DB = os.environ.get("ECHR_DB_PATH", "/data/echr_search.db")
BACKUP = "section_backup_p64"
CHUNK = 20_000
BUSY_TIMEOUT_S = 180

PROCEDURE = "Procedure"
CIRCUMSTANCES = "Circumstances"
SUBJECT_MATTER = "Subject Matter"

# --------------------------------------------------------------- normalising

_WS = re.compile(r"\s+")
_LEAD_NUM = re.compile(r"^\s*(?:[IVXLC]+|[0-9]+|[A-Z])\s*[.)]\s*", re.I)


def norm(text: str) -> str:
    """Upper-case, collapse whitespace AND hyphens, strip leading numbering.

    Hyphen folding is the P64 addition: the Court's modern committee template
    writes `SUBJECT-MATTER OF THE CASE`, which P62/P63 failed to match.
    """
    t = _WS.sub(" ", (text or "")).strip().upper()
    t = t.replace("’", "'").replace("‘", "'").replace("-", " ")
    t = _WS.sub(" ", t)
    prev = None
    while prev != t:                      # "I. A. FOO" -> "FOO"
        prev = t
        t = _LEAD_NUM.sub("", t)
    return t.strip(" .:")


# ------------------------------------------------------------------ markers

FACTS_START_EXACT = {"THE FACTS", "AS TO THE FACTS", "FACTS", "EN FAIT"}
PROC_EXACT = {"PROCEDURE", "PROCÉDURE", "AS TO THE PROCEDURE"}
LAW_EXACT = {"THE LAW", "AS TO THE LAW", "EN DROIT"}


def marker_class(h: str) -> str | None:
    """'SUBJ' | 'FACTS_START' | 'PROC' | 'LAW' | None for a normalised heading.

    SUBJ is tested first: "FACTS AND PROCEDURE" / "PROCEDURE AND FACTS" would
    otherwise match PROC. LAW doubles as the end boundary for rule P; the
    operative formula is included as a fallback end-stop.
    """
    if ("SUBJECT MATTER OF THE CASE" in h
            or h.startswith("FACTS AND PROCEDURE")
            or h.startswith("PROCEDURE AND FACTS")
            or "OBJET DE L'AFFAIRE" in h):
        return "SUBJ"
    if (h in FACTS_START_EXACT
            or "CIRCUMSTANCES OF THE CASE" in h
            or "CIRCONSTANCES DE L'ESPÈCE" in h):
        return "FACTS_START"
    if h in PROC_EXACT or "PROCEEDINGS BEFORE THE COMMISSION" in h:
        return "PROC"
    if (h in LAW_EXACT
            or "COURT'S ASSESSMENT" in h
            or "APPRÉCIATION DE LA COUR" in h
            or h.startswith("APPLICATION OF ARTICLE 41")
            or h.startswith("SUR L'APPLICATION DE L'ARTICLE 41")
            or "REQUEST FOR REVISION" in h
            or "DEMANDE EN RÉVISION" in h
            or "REQUEST FOR INTERPRETATION" in h
            or "DEMANDE EN INTERPRÉTATION" in h
            or h.startswith("FOR THESE REASONS")
            or h.startswith("PAR CES MOTIFS")):
        return "LAW"
    return None


# --------------------------------------------------------------------- plan


def build_plan(conn):
    cur = conn.cursor()

    # Residue pool: cases still holding plain 'Facts' rows after P63.
    cur.execute("SELECT DISTINCT case_id FROM paragraphs WHERE section='Facts'")
    residue = [r[0] for r in cur.fetchall()]
    if not residue:
        return [], Counter(), {}, {}

    ph = ",".join("?" * len(residue))

    # Markers from heading rows in ANY section, plus each row's section so we
    # can re-home misfiled headings.
    marks: dict[str, list[tuple[int, str, int, str]]] = defaultdict(list)
    cur.execute(
        f"""SELECT case_id, para_idx, rowid, section, text FROM paragraphs
            WHERE case_id IN ({ph}) AND row_role LIKE 'heading%'
            ORDER BY case_id, para_idx""",
        residue,
    )
    for case_id, para_idx, rowid, section, text in cur:
        cls = marker_class(norm(text))
        if cls:
            marks[case_id].append((para_idx, cls, rowid, section))

    # The Facts rows to relabel.
    facts: dict[str, list[tuple[int, int]]] = defaultdict(list)
    cur.execute(
        f"SELECT case_id, para_idx, rowid FROM paragraphs "
        f"WHERE case_id IN ({ph}) AND section='Facts'",
        residue,
    )
    for case_id, para_idx, rowid in cur:
        facts[case_id].append((para_idx, rowid))

    changes: list[tuple[int, str, str, str]] = []
    stats = Counter()
    rule_of: dict[str, str] = {}
    new_label: dict[int, str] = {}

    for case_id in residue:
        ms = marks.get(case_id, [])
        rows = sorted(facts[case_id])
        first = {}
        for para_idx, cls, rowid, section in ms:
            if cls not in first:
                first[cls] = (para_idx, rowid, section)

        rehome: list[tuple[int, str, str]] = []   # (rowid, old_section, new_section)

        if "SUBJ" in first:
            cut, mrowid, msec = first["SUBJ"]
            rule, tail = "S", SUBJECT_MATTER
        elif "FACTS_START" in first:
            cut, mrowid, msec = first["FACTS_START"]
            rule, tail = "F", CIRCUMSTANCES
        elif "PROC" in first:
            p, prowid, psec = first["PROC"]
            law = next((pi for pi, cls, _, _ in ms if cls == "LAW" and pi > p), None)
            if law is None:
                stats["cases_left_no_law_boundary"] += 1
                stats["paras_left_no_law_boundary"] += len(rows)
                rule_of[case_id] = "left:no-law"
                continue
            rule_of[case_id] = "P"
            stats["cases_rule_P"] += 1
            inside = outside = 0
            for para_idx, rowid in rows:
                if p <= para_idx < law:
                    new_label[rowid] = PROCEDURE
                    changes.append((rowid, "Facts", PROCEDURE, "P"))
                    inside += 1
                else:
                    outside += 1
            stats["paras_rule_P"] += inside
            if outside:
                stats["cases_rule_P_partial"] += 1
                stats["paras_left_outside_proc_law"] += outside
            if psec in ("Header", "Introduction"):
                rehome.append((prowid, psec, PROCEDURE))
            for rowid, old, new in rehome:
                changes.append((rowid, old, new, "H"))
                stats["headings_rehomed"] += 1
            continue
        else:
            stats["cases_left_no_marker"] += 1
            stats["paras_left_no_marker"] += len(rows)
            rule_of[case_id] = "left:no-marker"
            continue

        # Rules S and F: split at `cut`.
        rule_of[case_id] = rule
        stats[f"cases_rule_{rule}"] += 1
        for para_idx, rowid in rows:
            new = PROCEDURE if para_idx < cut else tail
            new_label[rowid] = new
            changes.append((rowid, "Facts", new, rule))
            stats[f"paras_rule_{rule}"] += 1
        if msec in ("Header", "Introduction"):
            rehome.append((mrowid, msec, tail))
        # A PROC heading before the cut, misfiled in Header/Introduction,
        # introduces the procedure block — re-home it too.
        if "PROC" in first:
            pp, prowid, psec = first["PROC"]
            if pp < cut and psec in ("Header", "Introduction"):
                rehome.append((prowid, psec, PROCEDURE))
        for rowid, old, new in rehome:
            changes.append((rowid, old, new, "H"))
            stats["headings_rehomed"] += 1

    return changes, stats, facts, new_label


# --------------------------------------------------------------- invariants


def check_invariants(conn, facts, new_label):
    failures = []

    # 1. contiguity among relabelled Facts rows per case (untouched rows are
    #    allowed at the edges for partial rule-P cases; among CHANGED rows the
    #    sequence must be Procedure* then at most one tail label).
    bad = []
    for case_id, rows in facts.items():
        seq = [new_label[r] for _, r in sorted(rows) if r in new_label]
        if not seq:
            continue
        transitions = sum(1 for a, b in zip(seq, seq[1:]) if a != b)
        tails = {s for s in seq if s != PROCEDURE}
        if transitions > 1 or len(tails) > 1:
            bad.append(case_id)
    if bad:
        failures.append(f"contiguity: {len(bad)} case(s) interleave labels "
                        f"(e.g. {bad[:5]})")

    # 2. row count unchanged (plan is UPDATE-only).
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM paragraphs")
    failures.append(("_rowcount", cur.fetchone()[0]))
    return failures


# ------------------------------------------------------------------- report


def report(changes, stats, invariant_failures, rowcount):
    print("P64 — residue segmentation (post-P63 `Facts` cases)")
    print("=" * 72)
    for rule, label in (("S", "subject-matter marker"),
                        ("F", "facts-start marker"),
                        ("P", "PROC..LAW all-procedure")):
        print(f"rule {rule} ({label:26s}): {stats[f'cases_rule_{rule}']:>5,} cases  "
              f"{stats[f'paras_rule_{rule}']:>6,} paras")
    print(f"headings re-homed (Header/Intro) : {stats['headings_rehomed']:>5,}")
    print()
    print(f"left: rule-P partial coverage    : {stats['cases_rule_P_partial']:>5,} cases  "
          f"{stats['paras_left_outside_proc_law']:>6,} paras stay `Facts`")
    print(f"left: PROC but no LAW boundary   : {stats['cases_left_no_law_boundary']:>5,} cases  "
          f"{stats['paras_left_no_law_boundary']:>6,} paras")
    print(f"left: no usable marker           : {stats['cases_left_no_marker']:>5,} cases  "
          f"{stats['paras_left_no_marker']:>6,} paras")
    print()
    print(f"TOTAL ROW UPDATES PLANNED        : {len(changes):>7,}")
    print(f"corpus row count (unchanged)     : {rowcount:,}")

    print()
    print("--- transition matrix ---")
    tm = Counter((old, new) for _, old, new, _ in changes)
    for (old, new), n in tm.most_common():
        print(f"  {old:16s} -> {new:16s} {n:>7,}")

    print()
    print("--- invariants ---")
    real = [f for f in invariant_failures if not isinstance(f, tuple)]
    if real:
        for f in real:
            print(f"  FAIL  {f}")
    else:
        print("  PASS  1. contiguity  — changed rows form Procedure* then one tail")
        print("  PASS  2. row count   — plan is UPDATE-only")
    return not real


# -------------------------------------------------------------------- apply


def warm_facets_cache():
    """Recompute /api/facets so the first real user does not pay for it.

    MANDATORY after a chunked apply, alongside checkpoint_wal(). api/main.py
    keys _FACETS_CACHE on the DB file's (mtime, size), so ANY write — including
    the WAL checkpoint, which rewrites the file — invalidates it. The next
    request then does a whole-corpus aggregation that takes >45 s and simply
    times out for whoever made it, while the server quietly finishes and caches
    the result. Firing it here means that unlucky first request is us.
    """
    import urllib.request

    # BOTH endpoints. /api/stats is called by the Search page itself
    # (search-app.js:7038) and costs ~76 s cold, so warming only /api/facets
    # leaves the site's own front door hanging for the first visitor.
    for path in ("/api/facets", "/api/stats"):
        t0 = time.time()
        try:
            with urllib.request.urlopen("http://127.0.0.1:8000" + path, timeout=900) as r:
                n = len(r.read())
            print(f"warmed {path:14s} {n:,} bytes in {time.time() - t0:.1f}s")
        except Exception as e:                               # noqa: BLE001
            print(f"  WARNING: could not warm {path} ({e}). The first load "
                  f"after this pass will hang — run "
                  f"`curl -s localhost:8000{path} >/dev/null` on the VM.")


def checkpoint_wal(conn):
    """Fold the WAL back into the main DB and truncate it.

    MANDATORY after a chunked apply. Each committed chunk appends frames to the
    WAL, and because the live echr-api holds a connection open SQLite never
    gets a quiet moment to checkpoint on its own. P63 + P64 left a 1.16 GB WAL:
    every reader then had to traverse it, which pushed /api/search from ~0.3 s
    to 8.8 s and made /api/facets time out entirely, until this was run by hand.
    PASSIVE first (never blocks readers), then TRUNCATE to shrink the file.
    """
    try:
        busy, pages, done = conn.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
        print(f"WAL checkpoint PASSIVE : busy={busy} pages={pages:,} written={done:,}")
        busy, pages, done = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        print(f"WAL checkpoint TRUNCATE: busy={busy} pages={pages:,} written={done:,}")
        if busy:
            print("  WARNING: readers still active, WAL not fully truncated — "
                  "re-run the checkpoint when the API is idle.")
    except sqlite3.Error as e:
        print(f"  WARNING: WAL checkpoint failed ({e}). Run it manually or "
              f"reads will stay slow.")


def apply_changes(conn, changes):
    cur = conn.cursor()
    cur.execute(
        f"""CREATE TABLE IF NOT EXISTS {BACKUP} (
              rowid_ref   INTEGER,
              old_section TEXT,
              new_section TEXT,
              rule        TEXT
            )"""
    )
    conn.commit()
    done = 0
    for i in range(0, len(changes), CHUNK):
        batch = changes[i:i + CHUNK]
        cur.execute("BEGIN IMMEDIATE")
        cur.executemany(
            f"INSERT INTO {BACKUP} (rowid_ref, old_section, new_section, rule) "
            f"VALUES (?,?,?,?)",
            batch,
        )
        cur.executemany(
            "UPDATE paragraphs SET section = ? WHERE rowid = ?",
            [(new, rowid) for rowid, _, new, _ in batch],
        )
        conn.commit()
        done += len(batch)
        print(f"  ... {done:>6,} / {len(changes):,}", flush=True)
    print(f"\nAPPLIED {done:,} updates. Backup: {BACKUP} ({done:,} rows this run).")
    checkpoint_wal(conn)
    warm_facets_cache()


def restore(conn):
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='{BACKUP}'")
    if not cur.fetchone()[0]:
        sys.exit(f"No backup table {BACKUP} — nothing to restore.")
    cur.execute(f"SELECT rowid_ref, old_section FROM {BACKUP}")
    pairs = cur.fetchall()
    cur.executemany("UPDATE paragraphs SET section = ? WHERE rowid = ?",
                    [(old, rid) for rid, old in pairs])
    cur.execute(f"DROP TABLE {BACKUP}")
    conn.commit()
    print(f"Restored {len(pairs):,} rows and dropped {BACKUP}.")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="write changes")
    ap.add_argument("--restore", action="store_true", help="undo everything")
    args = ap.parse_args()

    if args.restore:
        conn = sqlite3.connect(DB, timeout=BUSY_TIMEOUT_S)
        conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_S * 1000}")
        restore(conn)
        return

    mode = "rw" if args.apply else "ro"
    conn = sqlite3.connect(f"file:{DB}?mode={mode}", uri=True,
                           timeout=BUSY_TIMEOUT_S)
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_S * 1000}")

    changes, stats, facts, new_label = build_plan(conn)
    failures = check_invariants(conn, facts, new_label)
    rowcount = next(f[1] for f in failures if isinstance(f, tuple))

    ok = report(changes, stats, failures, rowcount)
    if not ok:
        sys.exit("\nInvariants FAILED — refusing to apply.")
    if args.apply:
        apply_changes(conn, changes)
    else:
        print("\nDry run. Re-run with --apply to write.")


if __name__ == "__main__":
    main()
