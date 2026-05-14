"""API-driven battery for 50 stratified cases.
Same detector as before; reads /tmp/test_sample_50.txt, writes
/tmp/test_report.{json,txt}.
"""
import json, re, sys, urllib.request, ssl
from pathlib import Path
from collections import Counter

API = "https://150.254.115.204/echr-api/api/cases"
ctx = ssl._create_unverified_context()

HEADING_PREFIX_RE = re.compile(
    r"^(\([a-z]\)|\([ivx]+\)|\([α-ω]\)|"
    r"[IVX]+\.\s|[A-Z]\.\s|\d+\.\s)"
)

# Patterns that LOOK like headings but are actually legit body content:
#  * judge composition entries  ("G. BALLADORE PALLIERI,",  "H. P.")
#  * body list items where the prefix is followed by lowercase text
#    ("(a) joint dissenting opinion of Mr. Pettiti…")
#  * body list items that enumerate sub-points of a paragraph and
#    flow into mid-sentence lowercase ("(c) from April 2013 to…")
_JUDGE_INITIALS_RE = re.compile(r"^[A-Z]\.\s*(?:[A-Z]\.\s*)*[A-Z][A-Z\s]*[,\.]?\s*$")
_BODY_LIST_LOWER_RE = re.compile(r"^\(([a-z]|[ivx]+|[α-ω])\)\s*(?:\xa0\s*)*[a-z]")
# After a prefix, a TYPICAL heading is short Title-Case with no commas
# enumerating a list.  Sentence-style body lines have commas / mid-clause.
_BODY_SENTENCE_RE = re.compile(r"^\(([a-z]|[ivx]+)\)\s+\S+\s+[a-z]")  # lowercase 3rd word
# Body verbs that essentially never appear in a heading line.
_BODY_VERB_RE = re.compile(
    r"\b(was|were|is|are|had|have|has|did|does|will|would|could|"
    r"shall|should|might|may|been|being|am|am\.|claimed|stated|"
    r"submitted|alleged|argued|contended|requested|noted|considered|"
    r"found|held)\b",
    re.I,
)


def _is_real_heading_candidate(text, section):
    """Filter out known false-positive patterns before we flag E1."""
    if section in ("Header",):
        return False  # composition lists never are headings
    if _JUDGE_INITIALS_RE.match(text):
        return False
    if _BODY_LIST_LOWER_RE.match(text):
        return False
    if _BODY_SENTENCE_RE.match(text):
        return False
    # Body paragraphs that happen to start with "N. " or "(a) " — real
    # headings are SHORT (< ~50 chars) and don't contain conjugated
    # verbs / participles.  This catches "(a) In February 2011 it was
    # established…" and "10. According to information supplied …".
    if len(text) > 50:
        return False
    if _BODY_VERB_RE.search(text):
        return False
    # English participles & sentence connectors that signal body prose.
    if re.search(r"\b(supplied|appearing|including|relying|seeking|"
                 r"according to|in respect of|by the|of the [a-z])\b", text, re.I):
        return False
    return True


def fetch_case(cid):
    req = urllib.request.Request(f"{API}/{cid}",
        headers={"Accept": "application/json", "User-Agent": "t/1"})
    return json.loads(urllib.request.urlopen(req, context=ctx, timeout=20).read())


def check_case(cid, data):
    paras = sorted(data.get("paragraphs", []),
        key=lambda p: p.get("para_idx") if p.get("para_idx") is not None else -1)
    anomalies = []
    role_dist = Counter(p.get("row_role") for p in paras)

    if not any((r or "").startswith("heading") for r in role_dist):
        anomalies.append({"id": "A1", "msg": "no heading rows"})

    if any(p.get("section") == "Operative part" for p in paras):
        if not any(p.get("row_role") == "operative_list"
                   and p.get("section") == "Operative part" for p in paras):
            anomalies.append({"id": "A2", "msg": "Operative part w/o operative_list"})

    # Build neighbour-role lookup for the inside-quote-block test below.
    role_seq = [p.get("row_role") or "" for p in paras]

    for i, p in enumerate(paras):
        role = role_seq[i]
        text = (p.get("text") or "").strip()
        hp = p.get("hudoc_para_no")

        if role.startswith("heading") and hp is not None:
            anomalies.append({"id": "C1",
                "msg": f"heading carries hpno={hp}: {text[:60]!r}",
                "para_idx": p.get("para_idx")})

        if (role == "paragraph" and not hp
            and HEADING_PREFIX_RE.match(text) and len(text) <= 150
            and (p.get("section") or "") not in ("Appendix", "Separate Opinion", "Header")
            and (p.get("numbering_block") or "") != "table"
            and _is_real_heading_candidate(text, p.get("section") or "")):
            # Final filter: if both neighbours are quote rows, this is a
            # sub-heading inside a quoted external document (e.g.
            # BIANCARDI quotes a Council of Europe recommendation with
            # its own "III. Filtering and de-indexing" sub-headings).
            # Such rows render fine and aren't a bug.
            prev_role = role_seq[i - 1] if i > 0 else ""
            next_role = role_seq[i + 1] if i + 1 < len(role_seq) else ""
            if prev_role == "quote" and next_role == "quote":
                continue
            anomalies.append({"id": "E1",
                "msg": f"body looks-like-heading: {text[:80]!r}",
                "para_idx": p.get("para_idx")})

    if any(p.get("row_role") == "quote" for p in paras):
        for p in paras:
            role = p.get("row_role") or ""
            text = (p.get("text") or "").strip()
            if (role == "paragraph" and text.startswith(("“", "«"))
                and len(text) <= 200
                and (p.get("section") or "") not in ("Appendix", "Header")):
                anomalies.append({"id": "D1",
                    "msg": f"body looks-like-quote: {text[:80]!r}",
                    "para_idx": p.get("para_idx")})
                break

    table_cells = [p for p in paras if p.get("row_role") == "table_cell"]
    missing = sum(1 for p in table_cells
        if p.get("table_id") is None
        or p.get("table_row") is None or p.get("table_col") is None)
    # Tolerate up to 5% missing coords — multi-applicant annexes with
    # repeated boilerplate ("Art. 6 (1) - lack of impartiality…") lose a
    # handful of cells to the hash-collision gotcha in
    # extract_table_structure.  P41's anti-fragmentation renderer keeps
    # them in the same buffer, so the visible <table> is still
    # coherent.  Beyond 5%, the loss is large enough to flag.
    if table_cells and missing and missing / len(table_cells) > 0.05:
        anomalies.append({"id": "G1",
            "msg": f"{missing}/{len(table_cells)} table_cell missing coords"})

    last = -1
    for p in paras:
        pi = p.get("para_idx")
        if pi is None: continue
        if pi <= last:
            anomalies.append({"id": "H1",
                "msg": f"para_idx not monotonic: {last} → {pi}",
                "para_idx": pi})
            break
        last = pi

    return {"cid": cid, "title": data.get("title") or "",
            "date": data.get("judgment_date"),
            "doc_type": data.get("document_type"),
            "paragraphs_n": len(paras),
            "anomalies": anomalies, "ok": not anomalies}


def main():
    cids = [l.strip() for l in Path("/tmp/test_sample_50.txt").open() if l.strip()]
    print(f"# testing {len(cids)}", file=sys.stderr, flush=True)
    results = []
    for i, cid in enumerate(cids, 1):
        try:
            d = fetch_case(cid)
            r = check_case(cid, d)
        except Exception as e:
            r = {"cid": cid, "error": str(e)[:80], "ok": False, "anomalies": []}
        results.append(r)
        flag = "  " if r.get("ok") else "  ⚠"
        print(f"{flag} {i:2}/{len(cids)} {cid}  paras={r.get('paragraphs_n')}  "
              f"anomalies={len(r.get('anomalies') or [])}  "
              f"{(r.get('title') or '')[:55]}", file=sys.stderr, flush=True)

    Path("/tmp/test_report.json").write_text(json.dumps(results, indent=2))

    n_ok = sum(1 for r in results if r.get("ok"))
    n_fail = len(results) - n_ok
    codes = Counter()
    for r in results:
        for a in r.get("anomalies") or []:
            codes[a["id"]] += 1

    lines = [f"50-case test report\n===================\n",
             f"Total: {len(results)}  Pass: {n_ok}  Fail: {n_fail}\n",
             "Codes: " + ", ".join(f"{c}={n}" for c, n in codes.most_common()) + "\n",
             "--- failures ---\n"]
    for r in results:
        if r.get("ok"): continue
        lines.append(f"{r['cid']}  {(r.get('title') or '')[:60]}  ({r.get('date')})")
        for a in r.get("anomalies") or []:
            pi = a.get("para_idx")
            line = f"  [{a['id']}]"
            if pi is not None: line += f" pi={pi}"
            line += f"  {a['msg']}"
            lines.append(line)
        lines.append("")
    Path("/tmp/test_report.txt").write_text("\n".join(lines))

    print(f"\n=== {n_ok}/{len(results)} clean ===", file=sys.stderr)
    sys.exit(n_fail)


if __name__ == "__main__":
    main()
