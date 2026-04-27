"""
Phase 2 / Step 1 — empirical heading-string inventory.

Read-only. Produces a JSON report we use to decide whether the rule-based
segmenter from docs/TODO-facts-reclassify.md will actually cover >90% of
the corpus, and which exact strings to put in HEADING_PATTERNS.

Run inside the echr-search-api container:
    docker exec -i echr-search-api python /tmp/harvest_headings.py > harvest.json
"""

import json
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict

DB_PATH = os.environ.get("ECHR_DB_PATH", "/data/echr_search.db")

HEADING_ONLY_RE = re.compile(
    r"^[A-ZÉÀÈÙÂÊÎÔÛÇ0-9\s.()\"'/:,“”‘’–—-]+$"
)
NUMBERED_PARA_RE = re.compile(r"^\d+\s*[.)]\s+\S")

CANONICAL_PATTERNS = [
    ("procedure_classical",   re.compile(r"^\s*PROCEDURE\s*$")),
    ("the_facts",             re.compile(r"^\s*THE FACTS\s*$")),
    ("circumstances",         re.compile(r"^\s*I\.?\s+THE CIRCUMSTANCES OF THE CASE")),
    ("relevant_domestic",     re.compile(r"^\s*II\.?\s+RELEVANT (DOMESTIC|LEGAL) ")),
    ("relevant_international", re.compile(r"^\s*III\.?\s+RELEVANT INTERNATIONAL")),
    ("the_law",               re.compile(r"^\s*THE LAW\s*$")),
    ("alleged_violation",     re.compile(r"^\s*I\.?\s+ALLEGED VIOLATION OF ARTICLE")),
    ("subject_matter",        re.compile(r"^\s*SUBJECT MATTER OF THE CASE")),
    ("facts_and_procedure",   re.compile(r"^\s*FACTS AND PROCEDURE")),
    ("courts_assessment",     re.compile(r"^\s*THE COURT[’']S ASSESSMENT")),
    ("for_these_reasons",     re.compile(r"^\s*FOR THESE REASONS")),
    ("just_satisfaction",     re.compile(r"^\s*(II|III|IV|V|VI)\.?\s+APPLICATION OF ARTICLE 41")),
    ("article_50_old",        re.compile(r"^\s*APPLICATION OF ARTICLE 50")),
    ("dissenting_opinion",    re.compile(r"DISSENTING OPINION")),
    ("concurring_opinion",    re.compile(r"CONCURRING OPINION")),
]


def is_heading_text(text: str) -> bool:
    if not text:
        return False
    t = text.strip()
    if not t or len(t) > 220:
        return False
    if NUMBERED_PARA_RE.match(t):
        return False
    return bool(HEADING_ONLY_RE.match(t))


def main():
    if not os.path.exists(DB_PATH):
        print(f"ERROR: DB not found at {DB_PATH}", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    report = {"db_path": DB_PATH}

    # 0. Corpus size
    cur.execute("SELECT COUNT(*) FROM cases")
    report["total_cases"] = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM paragraphs")
    report["total_paragraphs"] = cur.fetchone()[0]

    # 1. Distribution of section values currently stored
    cur.execute("""
        SELECT section, COUNT(*) AS n
        FROM paragraphs
        GROUP BY section
        ORDER BY n DESC
    """)
    report["section_counts"] = [dict(r) for r in cur.fetchall()]

    # 2. Heading-only paragraphs by current section label.
    #    We pull short paragraphs (<220 chars) and filter in Python with the
    #    same regex the frontend uses, so the inventory is a strict superset
    #    of what the dashboard already treats as a heading.
    cur.execute("""
        SELECT case_id, para_idx, section, text
        FROM paragraphs
        WHERE length(text) BETWEEN 3 AND 220
    """)

    heading_counter = Counter()                    # text -> count
    heading_by_section = defaultdict(Counter)      # text -> section -> count
    case_canonical = defaultdict(set)              # case_id -> {pattern_name}
    canonical_per_pattern = Counter()              # pattern_name -> count

    rows_seen = 0
    headings_seen = 0
    for r in cur.fetchall():
        rows_seen += 1
        text = (r["text"] or "").strip()
        if not is_heading_text(text):
            continue
        headings_seen += 1
        norm = re.sub(r"\s+", " ", text)
        heading_counter[norm] += 1
        heading_by_section[norm][r["section"] or ""] += 1
        for name, pat in CANONICAL_PATTERNS:
            if pat.search(text):
                case_canonical[r["case_id"]].add(name)
                canonical_per_pattern[name] += 1
                break  # one canonical match per heading line is enough

    report["short_paragraphs_scanned"] = rows_seen
    report["headings_detected"] = headings_seen

    # 3. Top heading strings — the long head we need to handle
    top_n = 80
    report["top_headings"] = [
        {
            "text": h,
            "count": c,
            "by_section": dict(heading_by_section[h].most_common(5)),
        }
        for h, c in heading_counter.most_common(top_n)
    ]

    # 4. Per-pattern coverage at the case level
    total_cases = report["total_cases"]
    cases_with_any = len(case_canonical)
    report["case_coverage"] = {
        "cases_with_at_least_one_canonical_heading": cases_with_any,
        "pct": round(100 * cases_with_any / total_cases, 2) if total_cases else 0,
        "by_pattern_case_count": {
            name: sum(1 for s in case_canonical.values() if name in s)
            for name, _ in CANONICAL_PATTERNS
        },
    }
    report["headings_matched_per_pattern"] = dict(canonical_per_pattern)

    # 5. Template inference per case (classical / committee / hybrid / none)
    classical_markers = {"procedure_classical", "the_facts", "circumstances", "the_law"}
    committee_markers = {"subject_matter", "facts_and_procedure", "courts_assessment"}
    template_counter = Counter()
    for cid, names in case_canonical.items():
        has_classical = bool(names & classical_markers)
        has_committee = bool(names & committee_markers)
        if has_classical and has_committee:
            template_counter["hybrid"] += 1
        elif has_classical:
            template_counter["classical"] += 1
        elif has_committee:
            template_counter["committee"] += 1
        else:
            template_counter["other_canonical"] += 1
    template_counter["no_canonical_heading"] = total_cases - cases_with_any
    report["template_distribution"] = dict(template_counter)

    # 6. Misclassification spotlight: count cases where short paragraphs
    #    starting with PROCEDURE / THE FACTS / etc. live under the wrong
    #    current section label. This is the smoking gun for Phase 2.
    misclass = []
    spot_patterns = [
        ("PROCEDURE",                "procedure"),
        ("THE FACTS",                "facts"),
        ("THE LAW",                  "merits"),
        ("SUBJECT MATTER OF THE CASE", "subject_matter"),
        ("FACTS AND PROCEDURE",      "subject_matter"),
        ("FOR THESE REASONS",        "operative_part"),
    ]
    for needle, expected in spot_patterns:
        cur.execute("""
            SELECT section, COUNT(*) AS n
            FROM paragraphs
            WHERE length(text) < 80 AND UPPER(text) LIKE ?
            GROUP BY section
            ORDER BY n DESC
        """, (f"%{needle}%",))
        misclass.append({
            "needle": needle,
            "expected_phase2_label": expected,
            "current_distribution": [dict(r) for r in cur.fetchall()],
        })
    report["misclassification_spotlight"] = misclass

    # 7. Year coverage of canonical headings (lightweight version)
    year_coverage = {}
    cur.execute("""
        SELECT substr(judgment_date, 7, 4) AS year, COUNT(*) AS total
        FROM cases
        WHERE judgment_date IS NOT NULL AND length(judgment_date) >= 10
        GROUP BY year
        ORDER BY year
    """)
    year_totals = {r["year"]: r["total"] for r in cur.fetchall()}

    cur.execute("""
        SELECT substr(c.judgment_date, 7, 4) AS year,
               COUNT(DISTINCT p.case_id) AS hits
        FROM paragraphs p
        JOIN cases c ON c.case_id = p.case_id
        WHERE length(p.text) < 80
          AND (UPPER(p.text) LIKE '%PROCEDURE%'
            OR UPPER(p.text) LIKE '%THE FACTS%'
            OR UPPER(p.text) LIKE '%SUBJECT MATTER%'
            OR UPPER(p.text) LIKE '%FACTS AND PROCEDURE%')
        GROUP BY year
    """)
    canonical_per_year = {r["year"]: r["hits"] for r in cur.fetchall()}

    for year, total in sorted(year_totals.items()):
        hits = canonical_per_year.get(year, 0)
        year_coverage[year] = {
            "total_cases": total,
            "with_canonical_heading": hits,
            "pct": round(100 * hits / total, 1) if total else 0,
        }
    report["year_coverage"] = year_coverage

    json.dump(report, sys.stdout, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
