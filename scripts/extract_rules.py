#!/usr/bin/env python3
"""Rule-based extraction to fill sparse metadata from section-tagged paragraphs.

Uses regex patterns on the right paragraph sections to extract structured
metadata without any LLM. High-precision, zero cost.

Targets:
  violation       ← operative_part: "Holds that there has been a violation of Article X"
  non-violation   ← operative_part: "Holds that there has been no violation of Article X"
  conclusion      ← operative_part: all "Holds...", "Decides...", "Awards..." clauses
  represented_by  ← introduction: "represented by X, lawyer/advocate/counsel"

Original non-empty values are NEVER overwritten.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Extraction patterns
# ---------------------------------------------------------------------------

# Article number patterns: "Article 6", "Article 6-1", "Article 8 § 1",
# "Art. 6", "Art. 14", "Article 1 of Protocol No. 1"
ARTICLE_RE = re.compile(
    r"(?:Article|Art\.?)\s+"
    r"(\d+(?:[‑\-]\d+)?)"
    r"(?:\s*§\s*\d+)?"
    r"(?:\s+of\s+(?:the\s+)?Protocol\s+(?:No\.?\s*)?(\d+))?",
    re.IGNORECASE,
)

# Violation patterns in operative part
VIOLATION_RE = re.compile(
    r"(?:holds|held|finds?)\s+(?:unanimously\s+)?(?:,?\s*by\s+\w+\s+votes?\s+to\s+\w+\s*,?\s*)?that\s+there\s+(?:has|had)\s+been\s+(?:a\s+)?violation\s+of\s+"
    r"((?:Article|Art\.?)\s+\d+(?:[‑\-]\d+)?(?:\s*§\s*\d+)?(?:\s+of\s+(?:the\s+)?Protocol\s+(?:No\.?\s*)?\d+)?)",
    re.IGNORECASE,
)

# Non-violation patterns
NON_VIOLATION_RE = re.compile(
    r"(?:holds|held|finds?)\s+(?:unanimously\s+)?(?:,?\s*by\s+\w+\s+votes?\s+to\s+\w+\s*,?\s*)?that\s+there\s+(?:has|had)\s+been\s+no\s+violation\s+of\s+"
    r"((?:Article|Art\.?)\s+\d+(?:[‑\-]\d+)?(?:\s*§\s*\d+)?(?:\s+of\s+(?:the\s+)?Protocol\s+(?:No\.?\s*)?\d+)?)",
    re.IGNORECASE,
)

# Represented by patterns in introduction
REPRESENTED_RE = re.compile(
    r"represented\s+by\s+"
    r"((?:Mr\.?|Mrs\.?|Ms\.?|Dr\.?|Prof\.?)?\s*[A-ZÀ-Ž][a-zà-ž]+(?:[‑\-'][A-ZÀ-Ž]?[a-zà-ž]+)*"  # first name
    r"(?:\s+[A-ZÀ-Ž][a-zà-ž]+(?:[‑\-'][A-ZÀ-Ž]?[a-zà-ž]+)*)*)"  # last name(s)
    r"(?:\s*,\s*(?:a\s+)?(?:lawyer|advocate|counsel|barrister|solicitor|attorney|avocat|Rechtsanwalt))?",
    re.IGNORECASE,
)

# Alternative simpler pattern: "represented by NAME, a lawyer practising in CITY"
REPRESENTED_SIMPLE_RE = re.compile(
    r"represented\s+by\s+([A-ZÀ-Ž][\w\s.'\-À-ž]+?)(?:\s*,\s*(?:a\s+)?(?:lawyer|advocate|counsel|barrister|solicitor|attorney|avocat))",
    re.IGNORECASE,
)

# Conclusion patterns: "Holds that...", "Decides that...", "Awards..."
CONCLUSION_CLAUSE_RE = re.compile(
    r"((?:Holds|Decides|Awards|Dismisses|Declares|Rules|Orders|Says)\b.+?)(?=\s*(?:Holds|Decides|Awards|Dismisses|Declares|Rules|Orders|Says)\b|\s*Done\s+in\s+|$)",
    re.IGNORECASE | re.DOTALL,
)


def extract_article_id(text: str) -> str | None:
    """Extract article ID from a text fragment like 'Article 6-1'."""
    m = ARTICLE_RE.search(text)
    if not m:
        return None
    article = m.group(1)
    protocol = m.group(2)
    if protocol:
        return f"P{protocol}-{article}"
    return article


def extract_violations(paragraphs: list[dict]) -> tuple[list[str], list[str]]:
    """Extract violation and non-violation article IDs from operative_part."""
    violations = []
    non_violations = []
    seen_v = set()
    seen_nv = set()

    for para in paragraphs:
        section = (para.get("section") or "").strip().lower()
        if section != "operative part":
            continue
        text = para.get("text", "")

        for m in VIOLATION_RE.finditer(text):
            art = extract_article_id(m.group(1))
            if art and art not in seen_v:
                violations.append(art)
                seen_v.add(art)

        for m in NON_VIOLATION_RE.finditer(text):
            art = extract_article_id(m.group(1))
            if art and art not in seen_nv:
                non_violations.append(art)
                seen_nv.add(art)

    return violations, non_violations


_NOISE_WORDS = {
    "the", "a", "an", "his", "her", "their", "its", "our",
    "counsel", "lawyer", "advocate", "agent", "solicitor",
    "mother", "father", "guardian", "abbot", "advisers", "tax",
}


def _is_valid_name(name: str) -> bool:
    """Check if extracted text looks like a real person name."""
    if not name or len(name) < 3:
        return False
    # Must start with uppercase letter
    if not name[0].isupper():
        return False
    # Must have at least one space (first + last name) OR be a single
    # surname with initial (e.g., "E. Proksch")
    words = name.split()
    if len(words) < 1:
        return False
    # Reject if any word is a noise word
    first_word_lower = words[0].lower()
    if first_word_lower in _NOISE_WORDS:
        return False
    # Reject if it contains common non-name phrases
    lower = name.lower()
    for phrase in ("officially assigned", "had designated", "on his own",
                   "acting on", "own behalf", "testamentary", "their agent"):
        if phrase in lower:
            return False
    return True


def extract_represented_by(paragraphs: list[dict]) -> str | None:
    """Extract lawyer name from introduction paragraphs."""
    for para in paragraphs:
        section = (para.get("section") or "").strip().lower()
        if section not in ("introduction", "header"):
            continue
        text = para.get("text", "")

        # Try the more specific pattern first
        m = REPRESENTED_SIMPLE_RE.search(text)
        if m:
            name = m.group(1).strip()
            # Clean up title prefixes
            name = re.sub(r"^(?:Mr\.?|Mrs\.?|Ms\.?|Dr\.?|Prof\.?)\s*", "", name).strip()
            if _is_valid_name(name):
                return name

        m = REPRESENTED_RE.search(text)
        if m:
            name = m.group(1).strip()
            name = re.sub(r"^(?:Mr\.?|Mrs\.?|Ms\.?|Dr\.?|Prof\.?)\s*", "", name).strip()
            if _is_valid_name(name):
                return name

    return None


def extract_conclusion(paragraphs: list[dict]) -> str | None:
    """Extract structured conclusion from operative_part."""
    operative_text = []
    for para in paragraphs:
        section = (para.get("section") or "").strip().lower()
        if section == "operative part":
            operative_text.append(para.get("text", ""))

    if not operative_text:
        return None

    full_text = " ".join(operative_text)
    clauses = CONCLUSION_CLAUSE_RE.findall(full_text)
    if not clauses:
        return None

    # Join clauses with semicolons (HUDOC conclusion format)
    cleaned = []
    for clause in clauses:
        c = re.sub(r"\s+", " ", clause).strip()
        if c and len(c) > 10:
            cleaned.append(c)

    return ";".join(cleaned) if cleaned else None


def is_empty(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict)):
        return len(value) == 0
    return False


def process(input_path: Path, output_path: Path):
    """Run rule-based extraction on all cases."""
    total = 0
    fills = {
        "violation": 0,
        "non-violation": 0,
        "represented_by": 0,
        "conclusion": 0,
    }
    skipped_press = 0

    with input_path.open("r", encoding="utf-8") as fin, \
         output_path.open("w", encoding="utf-8") as fout:

        for line in fin:
            line = line.strip()
            if not line:
                continue
            total += 1
            case = json.loads(line)
            paragraphs = case.get("paragraphs") or []

            doc_type = str(case.get("document_type") or "").lower()
            if "press release" in doc_type:
                skipped_press += 1
                fout.write(json.dumps(case, ensure_ascii=False) + "\n")
                continue

            # Extract violations
            if is_empty(case.get("violation")) or is_empty(case.get("non-violation")):
                v, nv = extract_violations(paragraphs)
                if is_empty(case.get("violation")) and v:
                    case["violation"] = v
                    fills["violation"] += 1
                if is_empty(case.get("non-violation")) and nv:
                    case["non-violation"] = nv
                    fills["non-violation"] += 1

            # Extract represented_by
            if is_empty(case.get("represented_by")):
                rep = extract_represented_by(paragraphs)
                if rep:
                    case["represented_by"] = rep
                    fills["represented_by"] += 1

            # Extract conclusion
            if is_empty(case.get("conclusion")):
                conc = extract_conclusion(paragraphs)
                if conc:
                    case["conclusion"] = conc
                    fills["conclusion"] += 1

            fout.write(json.dumps(case, ensure_ascii=False) + "\n")

    print()
    print("=" * 65)
    print(f"  Total records:          {total:>10,}")
    print(f"  Press releases skipped: {skipped_press:>10,}")
    print(f"  Judgments processed:    {total - skipped_press:>10,}")
    print(f"  ---")
    print(f"  Fields filled (rule-based):")
    for field, count in fills.items():
        print(f"    {field:<25s} {count:>8,}")
    print("=" * 65)
    print(f"\n  Output: {output_path}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", default="docs/data/echr_cases_enriched.jsonl")
    parser.add_argument("--output", default="docs/data/echr_cases_enriched.jsonl")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]

    def resolve(p):
        pp = Path(p).expanduser()
        return pp if pp.is_absolute() else (repo_root / pp).resolve()

    input_path = resolve(args.input)
    output_path = resolve(args.output)

    if not input_path.exists():
        print(f"ERROR: Input not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    process(input_path, output_path)


if __name__ == "__main__":
    main()
