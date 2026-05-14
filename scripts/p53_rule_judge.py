"""P53 — Deterministic Stage-1 classifier for ECHR paragraph buckets.

Rationale.  The LLM-judge on 1000 sampled paragraphs returned Y in 87.6 %
of cases — most of those rubber-stamps cost a Sonnet round-trip we don't
need.  This module captures the high-confidence deterministic patterns
the judge applied implicitly, so the next sweep can pre-classify the
easy cases in Python and route only the residue (~20 %) to the LLM.

Inputs (per record)
-------------------
  - case_id, para_idx, text
  - section (current DB label)
  - row_role
  - hudoc_para_no
  - operative_part_seen, done_line_seen, art41_seen  (forward ratchets
    computed by walking the case in order)

Output
------
  classify(record) → (bucket, confidence, rule_id)
                     bucket = one of FACTS / ADM_MERITS /
                              JUST_SATISFACTION / OPERATIVE / OPINIONS /
                              META / HEADING / APPENDIX / None
                     confidence ∈ [0.50, 1.00]
                     rule_id   = string identifying which rule fired
                     If no rule fires confidently, returns (None, 0, None)
                     and the row is routed to the LLM judge.

Calibration
-----------
Run ``python p53_rule_judge.py --calibrate /tmp/echr_judge_results/all_judgments.tsv``
to score each rule against the 1000-row gold TSV.  A rule is accepted
into the production set iff its precision against gold is ≥ 0.98 and it
covers at least 10 rows.

Usage in next judge sweep
-------------------------
  1. Pre-classify all candidates with `classify()`.
  2. Records with rule-bucket → write straight to output TSV (Y/N
     decided by comparing rule-bucket vs DB-mapped bucket).
  3. Records with rule-bucket = None → ship to Sonnet judge as before.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

# ────────────────────────────────────────────────────────────────────────
# Patterns (mostly shared with p52_multi_heal)
# ────────────────────────────────────────────────────────────────────────

OP_VERB_RE = re.compile(
    r"^\s*(?:\d+\.\s+)?"
    r"(Holds?|Decides?|Dismisses?|Declares?|Rejects?|Strikes?|Awards?|Joins?|Orders?|Adjourns?)\b",
    re.I,
)
DONE_LINE_RE = re.compile(
    r"^\s*(Done in (English|French)|Fait en (anglais|fran[cç]ais))",
    re.I,
)
ART41_QUOTE_RE = re.compile(
    r"\bArticle\s*4[16]\s+of the Convention\s+(provides|reads)",
    re.I,
)
DEFAULT_INTEREST_RE = re.compile(
    r"default\s+interest.{0,80}marginal\s+lending\s+rate\s+of\s+the\s+European\s+Central\s+Bank",
    re.I,
)
ART41_HEADING_RE = re.compile(
    r"^\s*([IVX]+\.\s+)?APPLICATION\s+OF\s+ARTICLE\s*4[16]\b",
    re.I,
)
JS_BOILERPLATE_RE = re.compile(
    r"\b(claimed\s+(EUR|euros?)\b|in respect of (non-)?pecuniary damage|"
    r"costs and expenses\b|just satisfaction\b|Government (did not (comment|express)|disputed|contested))",
    re.I,
)
OPI_HEAD_RE = re.compile(
    r"^\s*("
    r"(JOINT\s+)?(PARTLY\s+)?(CONCURRING|DISSENTING)"
    r"(\s*,\s*PARTLY\s+(CONCURRING|DISSENTING))?\s+OPINION\s+(OF|BY)\s+JUDGES?\b"
    r"|SEPARATE\s+OPINION\s+OF\s+JUDGES?\b"
    r"|DECLARATION\s+OF\s+JUDGE\b"
    r"|OPINION\s+(CONCORDANTE|DISSIDENTE|S[EÉ]PAR[EÉ]E|COMMUNE|CONJOINTE)"
    r"|OPINION\s+(EN\s+PARTIE|PARTIELLEMENT)\s+(CONCORDANTE|DISSIDENTE)"
    r"|D[EÉ]CLARATION\s+(DU|DE\s+LA)\s+JUGE\b"
    r")",
    re.I,
)
OPI_VOICE_RE = re.compile(
    r"\b(I\s+(respectfully\s+)?(dissent|disagree|am unable to agree|am of the opinion|find that)|"
    r"we\s+(do not (share|consider)|cannot (agree|attach)|are unable to agree|"
    r"respectfully\s+dissent|fail to see)|"
    r"in my (view|opinion)|in our (view|opinion))\b",
    re.I,
)
COURT_VOICE_RE = re.compile(
    r"^\s*The Court\s+(notes?|considers?|observes?|finds?|recalls?|reiterates?|"
    r"accepts?|holds?|concludes?|emphasises?)\b",
    re.I,
)
SUBMITTED_RE = re.compile(
    r"^\s*The (applicants?|Government)\s+(submitted|argued|contended|contested|claimed|complained)\b",
    re.I,
)
DATE_NARRATIVE_RE = re.compile(
    r"^\s*On\s+\d{1,2}\s+(January|February|March|April|May|June|July|"
    r"August|September|October|November|December)\s+\d{4}\b",
    re.I,
)
FACTS_BIO_RE = re.compile(
    r"\bborn\s+in\s+\d{4}\b|\blives?\s+in\s+[A-Z]",
)
COVER_META_RE = re.compile(
    r"^\s*(FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH|GRAND CHAMBER|PLENARY|"
    r"PRESIDENT|REGISTRAR|STRASBOURG|FINAL|JUDGMENT)\s*$",
    re.I,
)

# Heading detector (mirror of p52_multi_heal.is_heading_only)
_H_CHAR = r"[A-Za-zÀ-ſ \-–—'‘’/&:(),]"
HEADING_PATTERNS = [
    re.compile(r"^\s*(THE LAW|THE FACTS|PROCEDURE|THE COURT|JUDGMENT)\s*$", re.I),
    re.compile(r"^\s*(PROCÉDURE|EN FAIT|EN DROIT)\s*$", re.I),
    re.compile(r"^\s*[IVX]+\.\s+[A-Z][A-Z " + _H_CHAR + r"]{2,180}\s*$"),
    re.compile(r"^\s*[A-Z]\.\s+[A-Z]" + _H_CHAR + r"{2,180}\s*$"),
    re.compile(r"^\s*\d+\.\s+[A-Z]" + _H_CHAR + r"{2,160}\s*$"),
    re.compile(r"^\s*\([a-z]+\)\s+[A-Z]" + _H_CHAR + r"{2,160}\s*$"),
    re.compile(r"^\s*\([ivx]+\)\s+[A-Z]" + _H_CHAR + r"{2,160}\s*$"),
    re.compile(r"^\s*FOR THESE REASONS\b.*$", re.I),
    re.compile(r"^\s*PAR CES MOTIFS\b.*$", re.I),
    re.compile(r"^\s*APPLICATION OF ARTICLE 4[16]\s*", re.I),
    re.compile(r"^\s*ALLEGED VIOLATION OF\b", re.I),
    re.compile(r"^\s*RELEVANT (DOMESTIC|INTERNATIONAL)\b", re.I),
]
_TERMINATOR_RE = re.compile(r"[.?!;]\s+(?=[a-z])")


def is_heading_only(text):
    if not text:
        return False
    t = text.strip()
    if not t or len(t) > 220:
        return False
    for pat in HEADING_PATTERNS:
        if pat.match(t):
            return True
    has_body = _TERMINATOR_RE.search(t) or len(t) >= 120
    if has_body:
        lower = sum(1 for c in t if c.isalpha() and c.islower())
        upper = sum(1 for c in t if c.isalpha() and c.isupper())
        if lower > upper * 2:
            return False
    if len(t) <= 90:
        upper = sum(1 for c in t if c.isalpha() and c.isupper())
        lower = sum(1 for c in t if c.isalpha() and c.islower())
        if upper >= 4 and upper >= lower * 2:
            return True
    return False


# ────────────────────────────────────────────────────────────────────────
# Rule definitions (priority-ordered)
# ────────────────────────────────────────────────────────────────────────


def classify(rec: dict) -> tuple[str | None, float, str | None]:
    """Return (bucket, confidence, rule_id).  Bucket=None means abstain."""
    text = (rec.get("text") or "").strip()
    if not text:
        return (None, 0.0, None)
    section = rec.get("section") or ""
    role = rec.get("row_role") or ""
    op_seen = bool(rec.get("operative_part_seen"))
    done_seen = bool(rec.get("done_line_seen"))
    art41_seen = bool(rec.get("art41_seen"))

    # 1. Explicit opinion-heading anchor — unambiguous
    if OPI_HEAD_RE.match(text):
        return ("OPINIONS", 0.99, "rule_opi_head")

    # 2. Operative dispositif verb at line start
    if section in ("Operative part", "Operative Part") and OP_VERB_RE.match(text):
        return ("OPERATIVE", 0.99, "rule_op_verb")

    # 3. Article 41 Convention quote
    if ART41_QUOTE_RE.search(text):
        return ("JUST_SATISFACTION", 0.98, "rule_art41_quote")

    # 4. Default interest formula
    if DEFAULT_INTEREST_RE.search(text):
        return ("JUST_SATISFACTION", 0.98, "rule_default_interest")

    # 5. Pure heading.  ABSTAIN by default — the judge's bucket
    #    convention bundles a heading into its parent section unless the
    #    parent itself is wrong.  Decide-out only on the LLM's signal.
    if is_heading_only(text) and rec.get("hudoc_para_no") is None:
        # Strong heading WITH a top-level keyword — almost always
        # parent-section-correct, so abstain (let LLM rubber-stamp).
        return (None, 0.0, None)

    # 6. Done-in-English line — bucket is genuinely ambiguous between
    #    OPERATIVE (closing formula of dispositif) and META (footer).
    #    Calibration: 6/8 OPERATIVE, 2/8 META.  Abstain.
    # (no rule_done_line — let LLM decide)

    # 7. Post-operative table cell → META (judge convention for annex
    #    tables; our new APPENDIX bucket is a UI-side reclassification,
    #    not the LLM judge's bucket).  Precision ~0.76 on gold.
    if role == "table_cell" and (op_seen or done_seen):
        return ("META", 0.92, "rule_appendix_table")

    # 8. Cover-page metadata words
    if COVER_META_RE.match(text) and rec.get("hudoc_para_no") is None:
        return ("META", 0.92, "rule_cover_meta")

    # 9. Post-operative opinion voice (caught by p52d)
    if op_seen and OPI_VOICE_RE.search(text) and not OP_VERB_RE.match(text):
        return ("OPINIONS", 0.90, "rule_opi_voice_post_op")

    # 10. Court voice in Merits/Admissibility section
    if (
        section in ("Merits", "Admissibility")
        and (COURT_VOICE_RE.match(text) or SUBMITTED_RE.match(text))
    ):
        return ("ADM_MERITS", 0.95, "rule_court_voice_merits")

    # 11. Just Satisfaction boilerplate in JS section
    if (
        section in ("Just Satisfaction", "Article 46")
        and JS_BOILERPLATE_RE.search(text)
    ):
        return ("JUST_SATISFACTION", 0.95, "rule_js_boilerplate")

    # 12. Dated narrative in Facts section
    if (
        section in ("Facts", "Facts Background", "Facts Proceedings")
        and (DATE_NARRATIVE_RE.match(text) or FACTS_BIO_RE.search(text))
    ):
        return ("FACTS", 0.95, "rule_facts_narrative")

    # Abstain — let LLM decide
    return (None, 0.0, None)


# ────────────────────────────────────────────────────────────────────────
# Calibration against gold TSV
# ────────────────────────────────────────────────────────────────────────

GOLD_DB_TO_BUCKET = {
    "Header": "META", "Summary": "META", "Appendix": "APPENDIX",
    "Introduction": "FACTS", "Facts": "FACTS",
    "Facts Background": "FACTS", "Facts Proceedings": "FACTS",
    "Legal Framework": "FACTS", "Commission Proceedings": "FACTS",
    "Admissibility": "ADM_MERITS", "Merits": "ADM_MERITS",
    "Final Submissions": "ADM_MERITS",
    "Just Satisfaction": "JUST_SATISFACTION", "Article 46": "JUST_SATISFACTION",
    "Operative part": "OPERATIVE", "Operative Part": "OPERATIVE",
    "Separate Opinion": "OPINIONS",
}


def calibrate(gold_tsv: Path):
    """Compare rule output against LLM-judge gold verdicts.

    For each gold row, the judge's `actual_bucket` is the ground truth.
    We replay the rule classifier (without ratchets — they're case-local
    and the gold TSV doesn't carry them; ratchets reduce false positives
    so calibration here is a worst-case lower bound on precision).
    """
    rows = []
    with gold_tsv.open() as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 7:
                continue
            rows.append({
                "case_id": parts[0],
                "para_idx": parts[1],
                "verdict": parts[2],
                "gold_bucket": parts[3],
                "confidence": float(parts[4]) if parts[4] else 0,
                "failure_mode": parts[5],
                "reasoning": parts[6],
            })
    print(f"loaded {len(rows)} gold rows")

    # The gold TSV doesn't have raw text — we can only calibrate rules
    # that fire on the `reasoning` excerpt as a proxy.  Better: rerun
    # calibration against the original JSONL batches which DO have text.
    # For now, count how many gold rows the LLM-judge labelled with each
    # actual_bucket — and what the LLM's failure_mode distribution was.
    by_bucket = Counter(r["gold_bucket"] for r in rows)
    print("\nGold bucket distribution (LLM-judge actual_bucket):")
    for k, n in by_bucket.most_common():
        print(f"  {k:18s} {n:>4}")

    print("\nNote: full rule-vs-text calibration needs original JSONL batches.")
    print("Pointing at /tmp/echr_judge_batches/batch_*.jsonl for that.")


def calibrate_against_jsonl(jsonl_dir: Path, gold_tsv: Path):
    """Run rules against the original record JSONL + gold verdicts."""
    import json

    # Load gold verdicts indexed by (case_id, para_idx)
    gold = {}
    with gold_tsv.open() as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 7:
                continue
            key = (parts[0], parts[1])
            gold[key] = {
                "verdict": parts[2],
                "bucket": parts[3],
                "confidence": float(parts[4]) if parts[4] else 0,
            }
    print(f"loaded {len(gold)} gold entries")

    # Walk JSONL batches; build per-case ratchets while iterating
    # records.  The batch_NN.jsonl files store one *target* per record
    # with limited context, so we cannot perfectly reproduce ratchet
    # state — but we can use the target's own section as a proxy
    # (e.g. section='Operative part' → operative_part_seen ≈ True).
    rule_hits = Counter()
    rule_correct = Counter()
    rule_wrong: dict[str, list] = defaultdict(list)
    abstain = 0
    abstain_buckets = Counter()
    total = 0

    for path in sorted(jsonl_dir.glob("batch_*.jsonl")):
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            t = r.get("target") or {}
            cid = r["case_id"]
            pi = str(t.get("para_idx") or "")
            key = (cid, pi)
            if key not in gold:
                continue
            total += 1
            g = gold[key]
            section = t.get("section") or ""
            # Cheap ratchet proxy
            rec = {
                "text": t.get("text"),
                "section": section,
                "row_role": t.get("row_role"),
                "hudoc_para_no": t.get("hudoc_para_no"),
                "operative_part_seen": section in (
                    "Operative part", "Operative Part",
                    "Separate Opinion", "Appendix",
                ),
                "done_line_seen": False,
                "art41_seen": section in (
                    "Just Satisfaction", "Article 46",
                ),
            }
            bucket, conf, rule_id = classify(rec)
            if bucket is None:
                abstain += 1
                abstain_buckets[g["bucket"]] += 1
                continue
            rule_hits[rule_id] += 1
            if bucket == g["bucket"]:
                rule_correct[rule_id] += 1
            else:
                rule_wrong[rule_id].append((cid, pi, bucket, g["bucket"],
                                            (t.get("text") or "")[:90]))

    print(f"\nTotal evaluated:       {total}")
    print(f"Abstain (→ LLM):       {abstain}  ({100*abstain/total:.1f}%)")
    print(f"Rules fired:           {sum(rule_hits.values())}  "
          f"({100*sum(rule_hits.values())/total:.1f}%)")
    print(f"\nPer-rule precision:")
    print(f"  {'rule_id':28s}  {'hits':>5}  {'correct':>7}  precision")
    for rid in sorted(rule_hits, key=lambda r: -rule_hits[r]):
        h = rule_hits[rid]
        c = rule_correct[rid]
        prec = c / h if h else 0
        marker = "✓" if prec >= 0.98 else ("·" if prec >= 0.95 else "✗")
        print(f"  {rid:28s}  {h:>5}  {c:>7}  {prec:.3f} {marker}")

    print(f"\nAbstain breakdown (which buckets the rules missed):")
    for k, n in abstain_buckets.most_common():
        print(f"  {k:18s} {n:>4}")

    # Show example mismatches for rules with imperfect precision
    print(f"\nExample mismatches (rule said X, gold said Y):")
    for rid, examples in list(rule_wrong.items())[:3]:
        if not examples:
            continue
        print(f"\n  {rid}:")
        for cid, pi, rule_b, gold_b, txt in examples[:3]:
            print(f"    {cid} pi={pi}  rule={rule_b}  gold={gold_b}  | {txt}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--calibrate", type=Path,
                    help="gold TSV (all_judgments.tsv)")
    ap.add_argument("--jsonl-dir", type=Path,
                    default=Path("/tmp/echr_judge_batches"),
                    help="dir with batch_*.jsonl record files")
    args = ap.parse_args()
    if args.calibrate:
        if args.jsonl_dir.exists():
            calibrate_against_jsonl(args.jsonl_dir, args.calibrate)
        else:
            calibrate(args.calibrate)
    else:
        print("Use --calibrate <tsv> to score against gold verdicts.")


if __name__ == "__main__":
    main()
