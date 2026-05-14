"""Backfill the legacy ``row_role='heading'`` rows (no explicit level)
with proper ``heading_h0..h4`` levels inferred from the leading-prefix
pattern of the row's own text.

Pre-P39 P34 produced row_role='heading' for any text matching the
section-header text rules.  P39's level extraction happened only for
cases re-parsed via the extract-from-DOCX-cache pipeline, so ~210 k
heading rows (mostly 1990-2005 cases not re-parsed since) still carry
the bare 'heading' role.  In the v1 UI this matters because the
heading-exclusion filter relies on ``row_role.startsWith('heading')``
which already catches them, but the breadcrumb logic (v1.1) and
analytics need a level.

Mapping from text prefix:
  PROCEDURE / THE FACTS / THE LAW / FOR THESE REASONS …   →  h0
  I. / II. / III. / IV. …                                  →  h1
  A. / B. / C. …                                            →  h2
  1. / 2. / 3. …                                            →  h3
  (a) / (b) / (i) / (ii) / (α) …                            →  h4

Top-level (h0) is recognised by the ALL-CAPS short text pattern that
the P34 section_for_header rules use.  Anything that doesn't fit any
rule keeps the bare 'heading' role.
"""
import re
import sqlite3

DB = "/data/echr_search.db"

H0_TEXT_PATTERNS = [
    r"^\s*PROCEDURE\b",
    r"^\s*THE FACTS\b",
    r"^\s*THE LAW\b",
    r"^\s*AS TO THE FACTS\b",
    r"^\s*AS TO THE LAW\b",
    r"^\s*FOR THESE REASONS\b",
    r"^\s*APPLICATION OF ARTICLE\b",
    r"^\s*RELEVANT (?:DOMESTIC )?(?:LEGAL FRAMEWORK|INTERNATIONAL)\b",
    r"^\s*PROCEEDINGS BEFORE THE COMMISSION\b",
    r"^\s*FINAL SUBMISSIONS TO THE COURT\b",
    r"^\s*JOINT (?:CONCURRING|DISSENTING|PARTLY)\b",
    r"^\s*(?:CONCURRING|DISSENTING|SEPARATE) OPINION\b",
    r"^\s*APPENDIX|^\s*ANNEX\b",
]
H0_RE = re.compile("|".join(H0_TEXT_PATTERNS), re.IGNORECASE)
ROMAN_RE = re.compile(r"^\s*([IVX]+)\.\s")
LETTER_UPPER_RE = re.compile(r"^\s*([A-Z])\.\s")
DIGIT_RE = re.compile(r"^\s*(\d+)\.\s")
PAREN_LOWER_RE = re.compile(r"^\s*\(([a-z]|[ivx]+|[α-ω])\)\s")


def infer_level(text):
    if not text:
        return None
    if H0_RE.search(text):
        return "h0"
    if ROMAN_RE.match(text):
        return "h1"
    if LETTER_UPPER_RE.match(text):
        return "h2"
    if DIGIT_RE.match(text):
        return "h3"
    if PAREN_LOWER_RE.match(text):
        return "h4"
    return None


def main():
    con = sqlite3.connect(DB)
    con.execute("PRAGMA journal_mode = WAL")

    n_seen = 0
    n_promoted = 0
    by_level = {"h0": 0, "h1": 0, "h2": 0, "h3": 0, "h4": 0}
    updates = []
    for rowid, text in con.execute(
        "SELECT rowid, text FROM paragraphs WHERE row_role = 'heading'"
    ):
        n_seen += 1
        level = infer_level(text)
        if level is None:
            continue
        updates.append((f"heading_{level}", rowid))
        n_promoted += 1
        by_level[level] += 1

    print(f"scanned {n_seen:,} legacy heading rows", flush=True)
    print(f"will promote {n_promoted:,}", flush=True)
    print(f"  by level: {by_level}", flush=True)

    batch = 20000
    for i in range(0, len(updates), batch):
        con.executemany(
            "UPDATE paragraphs SET row_role = ? WHERE rowid = ?",
            updates[i:i + batch],
        )
        con.commit()
    print(f"applied {len(updates):,} updates")

    rem = con.execute(
        "SELECT COUNT(*) FROM paragraphs WHERE row_role = 'heading'"
    ).fetchone()[0]
    print(f"remaining bare 'heading' rows (no detectable level): {rem:,}")


if __name__ == "__main__":
    main()
