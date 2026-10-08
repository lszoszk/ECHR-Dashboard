#!/usr/bin/env python3
"""P65 — validate the P63/P64 boundary placement on a seeded stratified sample.

Read-only. Produces the accuracy number for Phase 2.

WHY NOT macro-F1 over paragraphs. Every paragraph label is *derived* from one
per-case boundary, so 725k paragraph judgements would measure ~19.8k independent
decisions with false precision, and would flatter the result: a case with a
400-paragraph narrative and a 4-paragraph procedure block scores 99% just by
getting the tail right. The unit of accuracy is therefore **the case boundary**.

WHY NOT "did we cut at the Court's heading". That is true by construction — it
is what the segmenter did. Checking it would be circular.

THE INDEPENDENT SIGNAL. What the headings cannot tell us is whether the
resulting blocks *contain* what they claim. ECtHR procedure blocks have a
highly stereotyped vocabulary ("The case originated in an application…",
"was represented by…", "the Government were given notice…") that is nearly
absent from the circumstances narrative, and vice versa. So for each sampled
case we measure:

    procedure_purity   fraction of Procedure rows carrying procedure vocabulary
    circ_contamination fraction of the FIRST rows of Circumstances that are
                       still procedure vocabulary (i.e. the cut came too early)
    narrative_in_proc  Procedure rows carrying narrative vocabulary
                       (i.e. the cut came too late)

A case is AUTO-OK when the blocks look like themselves, and FLAGGED otherwise.
Flagged cases are written to a review file for adjudication — they are not
counted as errors, only as "needs a human/judge".

Sampling is seeded and stratified by era × rule, so the run is reproducible and
the number is publishable.

Usage (inside the echr-api container):
  python3 p65_boundary_validation.py               # n=150, seed 2026
  python3 p65_boundary_validation.py --n 300
  python3 p65_boundary_validation.py --out /tmp/p65_review.json
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sqlite3
from collections import Counter, defaultdict

DB = os.environ.get("ECHR_DB_PATH", "/data/echr_search.db")

PROCEDURE = "Procedure"
CIRCUMSTANCES = "Circumstances"
SUBJECT_MATTER = "Subject Matter"

# --------------------------------------------------------------- vocabularies
# Deliberately high-precision. These are the Court's own formulae; they are
# frozen here so the metric cannot be tuned after seeing the result.

PROC_VOCAB = [
    # -- post-Protocol-11 (v1) -------------------------------------------------
    r"case originated in .{0,40}applications?",       # v2: quantifier is optional
    r"lodged with the Court under Article 34",
    r"w(as|ere) represented by",
    r"Government.{0,30}(were|was) (represented|given notice)",   # v2: tolerate "(the Government)"
    r"decided to (communicate|give notice)",
    r"declared the application (partly |wholly )?(in)?admissible",
    r"Having deliberated in private",
    r"friendly[- ]settlement",
    r"leave to intervene|third[- ]party intervention|written comments",
    r"a hearing took place|public hearing",
    r"relinquished jurisdiction",
    r"referral (to|of the case to) the Grand Chamber|panel of (five judges|the Grand Chamber)",
    r"the applicants?'? (details|names) (are|is) set out in the appended table",
    r"(notice of the application|the application) was given to the .{0,30}Government",
    r"PROCÉDURE|requête a été introduite|représenté par",
    # -- v2 additions: pre-Protocol-11 (Court A / Commission) formulae ---------
    # The 1959-1998 Court had an entirely different procedural vocabulary; v1
    # encoded only the modern formula and therefore scored these blocks at 0.
    # Added from the Court's own pre-1998 templates, not from the flagged set.
    r"(referred to|brought before) the Court by the (European Commission|Government)",
    r"in response to the enquiry made in accordance with Rule",
    r"Chamber .{0,30}(to be constituted|constituted to examine)",
    r"elected judge of .{0,25}nationality",
    r"within the three[- ]month period",
    r"(Rules|Rule \d+) of (the )?Rules? of Court|Rules of Court",
    r"the Commission('s)? (report|request|delegate)",
    r"drew by lot.{0,40}names of the .{0,20}judges|President of the Court",
]

# The Court's modern one-line opener ("The application concerns X"). It sits in
# the procedure position but reads as a case summary, so it scores 0 on both
# vocabularies. It is neither a pass nor a failure — it is a definitional
# question about what `procedure` should contain, so it gets its own verdict
# instead of being silently counted either way.
SUMMARY_OPENER = re.compile(
    r"^\s*\d*\.?\s*(the )?(present )?(application|case|applications)\s+concerns?\b", re.I)

NARRATIVE_VOCAB = [
    r"was born in \d{4}",
    r"lives in|resides in|is currently detained",
    r"(District|Regional|Supreme|Constitutional|Court of Appeal|County|City) Court",
    r"(convicted|sentenced|acquitted|arrested|detained|dismissed the (claim|appeal))",
    r"criminal proceedings (were|was) (instituted|brought)",
    r"the facts .{0,40}may be summarised as follows",
    r"on \d{1,2} \w+ \d{4},? the applicant",
    r"né en \d{4}|réside à|tribunal (de|d')",
]

PROC_RE = [re.compile(p, re.I) for p in PROC_VOCAB]
NARR_RE = [re.compile(p, re.I) for p in NARRATIVE_VOCAB]

# Rows that carry no vocabulary signal either way — excluded from the ratios so
# short structural rows do not drag purity down.
MIN_LEN = 60


def hits(text, pats):
    return any(p.search(text or "") for p in pats)


def era_of(jd):
    m = re.search(r"(\d{4})\s*$", jd or "")          # DD/MM/YYYY -> year is LAST
    if not m:
        return "unknown"
    y = m.group(1)
    if y < "1995":
        return "pre1995"
    if y < "2011":
        return "1995-2010"
    if y < "2022":
        return "2011-2021"
    return "2022+"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=150, help="sample size (cases)")
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--out", default="/tmp/p65_review.json")
    args = ap.parse_args()

    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Every case that P63/P64 segmented, with its era and which shape it got.
    cur.execute(
        """SELECT p.case_id,
                  SUM(p.section = 'Procedure')      AS n_proc,
                  SUM(p.section = 'Circumstances')  AS n_circ,
                  SUM(p.section = 'Subject Matter') AS n_subj
           FROM paragraphs p
           WHERE p.section IN ('Procedure','Circumstances','Subject Matter')
           GROUP BY p.case_id"""
    )
    shape = {r["case_id"]: (r["n_proc"], r["n_circ"], r["n_subj"]) for r in cur}

    cur.execute("SELECT case_id, judgment_date, title FROM cases")
    meta = {r["case_id"]: (era_of(r["judgment_date"]), r["title"]) for r in cur}

    # Stratify by era × shape. Only cases with a real Procedure/tail split are
    # informative: a case that is 100% Subject Matter has no boundary to check.
    strata = defaultdict(list)
    for cid, (npr, ncirc, nsubj) in shape.items():
        if cid not in meta:
            continue
        era, _ = meta[cid]
        kind = "subject_matter" if nsubj else "circumstances"
        if npr == 0:
            kind += "_noproc"                       # tail-only, boundary at row 0
        strata[(era, kind)].append(cid)

    rng = random.Random(args.seed)
    per = max(1, args.n // max(1, len(strata)))
    sample = []
    for key in sorted(strata):
        pool = sorted(strata[key])
        rng.shuffle(pool)
        sample += [(key, cid) for cid in pool[:per]]
    rng.shuffle(sample)
    sample = sample[:args.n]

    results, flagged = [], []
    for (era, kind), cid in sample:
        rows = list(cur.execute(
            """SELECT section, row_role, text FROM paragraphs
               WHERE case_id = ? AND section IN ('Procedure','Circumstances','Subject Matter')
               ORDER BY para_idx""", (cid,)))
        proc = [r["text"] for r in rows
                if r["section"] == PROCEDURE and not (r["row_role"] or "").startswith("heading")
                and len(r["text"] or "") >= MIN_LEN]
        tail = [r["text"] for r in rows
                if r["section"] in (CIRCUMSTANCES, SUBJECT_MATTER)
                and not (r["row_role"] or "").startswith("heading")
                and len(r["text"] or "") >= MIN_LEN]

        p_hit = sum(hits(t, PROC_RE) for t in proc)
        p_narr = sum(hits(t, NARR_RE) and not hits(t, PROC_RE) for t in proc)
        head = tail[:3]
        c_contam = sum(hits(t, PROC_RE) and not hits(t, NARR_RE) for t in head)

        purity = p_hit / len(proc) if proc else None
        contam = c_contam / len(head) if head else None

        # A procedure block that is *only* the Court's modern one-line opener is
        # a definitional question, not an error — see SUMMARY_OPENER.
        opener_only = bool(proc) and all(SUMMARY_OPENER.match(t or "") for t in proc)

        verdict, why = "OK", []
        if opener_only:
            verdict, _ = "DEFINITIONAL", why.append(
                "procedure block is only the 'application concerns…' opener")
        else:
            if proc and purity is not None and purity < 0.34:
                verdict, _ = "FLAG", why.append("procedure block lacks procedure vocabulary")
            if proc and p_narr / len(proc) > 0.5:
                verdict, _ = "FLAG", why.append("procedure block reads as narrative (cut too late)")
        if head and contam is not None and contam >= 0.67:
            verdict, _ = "FLAG", why.append("tail opens with procedure content (cut too early)")
        if not proc and not tail:
            verdict, _ = "FLAG", why.append("no scoreable rows")

        rec = {
            "case_id": cid, "era": era, "kind": kind,
            "title": (meta[cid][1] or "")[:70],
            "n_proc": len(proc), "n_tail": len(tail),
            "procedure_purity": round(purity, 3) if purity is not None else None,
            "narrative_in_proc": round(p_narr / len(proc), 3) if proc else None,
            "tail_contamination": round(contam, 3) if contam is not None else None,
            "verdict": verdict, "why": why,
        }
        results.append(rec)
        if verdict == "FLAG":
            rec = dict(rec)
            rec["procedure_sample"] = [(t or "")[:220] for t in proc[:3]]
            rec["tail_sample"] = [(t or "")[:220] for t in head]
            flagged.append(rec)

    # ------------------------------------------------------------------ report
    n = len(results)
    ok = sum(r["verdict"] == "OK" for r in results)
    defi = sum(r["verdict"] == "DEFINITIONAL" for r in results)
    flag = sum(r["verdict"] == "FLAG" for r in results)
    print("P65 — boundary validation (seed %d, n=%d cases)" % (args.seed, n))
    print("=" * 72)
    print("AUTO-OK       : %3d/%d = %5.1f%%" % (ok, n, 100.0 * ok / n))
    print("DEFINITIONAL  : %3d/%d = %5.1f%%  (opener-only procedure block)" %
          (defi, n, 100.0 * defi / n))
    print("FLAGGED       : %3d/%d = %5.1f%%  (needs adjudication)" %
          (flag, n, 100.0 * flag / n))
    print()
    print("--- by era ---")
    by = defaultdict(lambda: [0, 0])
    for r in results:
        by[r["era"]][0] += r["verdict"] == "OK"
        by[r["era"]][1] += 1
    for era in sorted(by):
        o, t = by[era]
        print("  %-12s %3d/%3d  %5.1f%%" % (era, o, t, 100.0 * o / t))
    print()
    print("--- by shape ---")
    by = defaultdict(lambda: [0, 0])
    for r in results:
        by[r["kind"]][0] += r["verdict"] == "OK"
        by[r["kind"]][1] += 1
    for k in sorted(by):
        o, t = by[k]
        print("  %-26s %3d/%3d  %5.1f%%" % (k, o, t, 100.0 * o / t))

    pur = [r["procedure_purity"] for r in results if r["procedure_purity"] is not None]
    if pur:
        pur.sort()
        print()
        print("--- procedure_purity distribution (n=%d cases with a Procedure block) ---" % len(pur))
        for lab, q in (("p10", .10), ("median", .50), ("p90", .90)):
            print("  %-7s %.2f" % (lab, pur[min(len(pur) - 1, int(q * len(pur)))]))

    print()
    print("--- flag reasons ---")
    for why, c in Counter(w for r in results for w in r["why"]).most_common():
        print("  %-52s %3d" % (why, c))

    # ------------------------------------------- corpus-wide absorption scan
    # The one real error class the sample surfaced: cases with NO Procedure
    # block whose Circumstances opens with procedure vocabulary — i.e. the
    # procedure block was absorbed into the narrative. Counted over the whole
    # corpus rather than estimated from the sample, since it is cheap.
    # Two very different things look alike here, so they are counted apart:
    #
    #   ABSORPTION (a real defect) — the Circumstances block opens with
    #     case-origination / referral / notice formulae, i.e. an actual
    #     PROCEDURE block ended up inside the narrative.
    #
    #   REPRESENTATION (not a defect) — it opens with "the applicant was born
    #     in… and was represented by…" / "the Government were represented by…".
    #     Since ~2019 the Court itself places these AFTER `THE FACTS`, so the
    #     segmenter is faithfully following the document. Counting these as
    #     errors would penalise it for being right; they are the population
    #     affected by the open definitional question instead.
    CORE_ABSORPTION = [re.compile(p, re.I) for p in [
        r"case originated in .{0,40}applications?",
        r"(referred to|brought before) the Court by the (European Commission|Government)",
        r"lodged with the Court under Article 34",
        r"relinquished jurisdiction",
        r"Government.{0,30}(were|was) given notice",
        r"declared the application (partly |wholly )?(in)?admissible",
    ]]
    REPRESENTATION = [re.compile(p, re.I) for p in [
        r"w(as|ere) represented by", r"Government.{0,30}(were|was) represented",
        r"was born in \d{4}", r"a été représentée? par|est née? en \d{4}",
    ]]

    print()
    print("--- corpus-wide: cases with NO Procedure block, by what opens the tail ---")
    absorbed, representation, checked = [], [], 0
    for cid, (npr, ncirc, nsubj) in shape.items():
        if npr or not ncirc:
            continue
        checked += 1
        first = list(cur.execute(
            """SELECT text FROM paragraphs
               WHERE case_id = ? AND section = 'Circumstances'
                 AND row_role NOT LIKE 'heading%' AND length(text) >= 60
               ORDER BY para_idx LIMIT 2""", (cid,)))
        if not first:
            continue
        t = first[0]["text"]
        if hits(t, CORE_ABSORPTION):
            absorbed.append(cid)
        elif hits(t, REPRESENTATION):
            representation.append(cid)
    print("  cases with no Procedure block            : %6d" % checked)
    print("  ...opening with representation/identity  : %6d   <- Court's own placement, NOT an error"
          % len(representation))
    print("  ...opening with origination/referral     : %6d   <- genuine absorption"
          % len(absorbed))
    era_ct = Counter(meta[c][0] for c in absorbed if c in meta)
    for e, c in sorted(era_ct.items()):
        print("      %-12s %5d" % (e, c))

    with open(args.out, "w") as f:
        json.dump({"seed": args.seed, "n": n, "auto_ok": ok,
                   "definitional": defi, "flagged_n": flag,
                   "absorbed_case_ids": absorbed,
                   "results": results, "flagged": flagged}, f, indent=1)
    print("\nreview file: %s  (%d flagged cases with text samples)" % (args.out, len(flagged)))


if __name__ == "__main__":
    main()
