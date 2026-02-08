#!/usr/bin/env python3
"""
ECHR Dataset Transformer — Option B (Structural Division)

Transforms the flat JSONL dataset into a paragraph-level dataset with
fine-grained structural section labels based on the formal judgment template.

Sections:
  header              — composition, parties, representatives
  introduction        — case summary (§1)
  facts_background    — factual background
  facts_proceedings   — domestic proceedings history
  legal_framework     — relevant domestic/international law & practice
  admissibility       — admissibility assessment
  merits              — merits assessment (general principles + application)
  just_satisfaction   — Art. 41 damages, costs
  article_46          — execution guidance (Art. 46)
  operative_part      — "FOR THESE REASONS" / dispositif
  separate_opinion    — concurring/dissenting opinions
"""

import json
import re
import sys
import os
from collections import Counter, defaultdict

# ── Input / Output ───────────────────────────────────────────────────────────

INPUT_FILE = os.path.join(os.path.dirname(__file__), '..', 'echr_cases_scraped.jsonl')
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), '..', 'echr_cases_optionB.jsonl')

# ── Section classification for the `law` field ──────────────────────────────
# The `law` field contains admissibility, merits, just_satisfaction, art46,
# and sometimes separate opinions all mixed together as a flat list.
# We classify using heading patterns and state machine logic.

# Patterns that signal section transitions within `law`
RE_ALLEGED_VIOLATION = re.compile(
    r'ALLEGED\s+VIOLATION\s+OF\s+ARTICLE',
    re.IGNORECASE
)
RE_APPLICATION_ART41 = re.compile(
    r'APPLICATION\s+OF\s+ARTICLE\s*4[16]',
    re.IGNORECASE
)
RE_APPLICATION_ART46 = re.compile(
    r'Article\s+46\s+of\s+the\s+Convention',
    re.IGNORECASE
)
RE_ARTICLE_46_HEADING = re.compile(
    r'(APPLICATION\s+OF\s+ARTICLE.*46|Article\s+46\s+of\s+the\s+Convention)',
    re.IGNORECASE
)
RE_ADMISSIBILITY = re.compile(
    r'^(\d+\.\s+)?(Admissibility|ADMISSIBILITY)',
)
RE_MERITS = re.compile(
    r'^(\d+\.\s+)?(Merits|MERITS)',
)
RE_JUST_SAT_HEADING = re.compile(
    r'(APPLICATION\s+OF\s+ARTICLE\s*41|Just\s+satisfaction|JUST\s+SATISFACTION)',
    re.IGNORECASE
)
RE_DAMAGE = re.compile(
    r'^(\d+\.\s+)?(Damage|NON-PECUNIARY|PECUNIARY|Costs\s+and\s+expenses)',
    re.IGNORECASE
)
RE_SEPARATE_OPINION = re.compile(
    r'(CONCURRING|DISSENTING|SEPARATE)\s+OPINION',
    re.IGNORECASE
)
RE_JOINDER = re.compile(
    r'JOINDER\s+OF\s+THE\s+APPLICATION',
    re.IGNORECASE
)
RE_COURT_ASSESSMENT = re.compile(
    r"The\s+Court[''\u2019]s\s+assessment",
    re.IGNORECASE
)
RE_PARTY_SUBMISSIONS = re.compile(
    r"(The\s+parties[''\u2019]\s+submissions|The\s+applicant[s']?\s+(complain|submitt|argu|maintain)|The\s+Government\s+(submitt|argu|contest|maintain))",
    re.IGNORECASE
)
RE_GENERAL_PRINCIPLES = re.compile(
    r'General\s+principles',
    re.IGNORECASE
)
RE_FOR_THESE_REASONS = re.compile(
    r'FOR\s+THESE\s+REASONS',
    re.IGNORECASE
)
RE_PRELIMINARY_OBJECTION = re.compile(
    r'PRELIMINARY\s+OBJECTION',
    re.IGNORECASE
)

# Patterns for sub-classification of 'facts'
RE_FACTS_PROCEEDINGS = re.compile(
    r'(proceedings|lodged|appealed|judgment|court|tribunal|decision|hearing|complaint|sentenced|convicted|acquitted|remand|detention|arrested|charged)',
    re.IGNORECASE
)


def classify_law_paragraphs(paragraphs):
    """
    Classify paragraphs from the 'law' section into sub-sections.
    Returns list of (section_label, text) tuples.

    State machine with improved transition detection:
    - Detects "declared admissible" as trigger for admissibility → merits
    - Handles "(a) Admissibility" / "(b) Merits" mid-paragraph headings
    - Detects separate opinions, Art 46, just satisfaction
    - Filters out header fragments that leak into law section
    """
    results = []
    sub_state = None  # 'admissibility' or 'merits'
    in_just_sat = False
    in_art46 = False
    in_separate_opinion = False

    # Additional patterns for improved classification
    RE_DECLARED_ADMISSIBLE = re.compile(
        r'(declared\s+admissible|must\s+therefore\s+be\s+declared\s+admissible|'
        r'not\s+inadmissible\s+on\s+any\s+other\s+grounds)',
        re.IGNORECASE
    )
    RE_MERITS_ANYWHERE = re.compile(
        r'(\(b\)\s*Merits|\bMerits\b\s*(The\s+parties|$))',
        re.IGNORECASE | re.MULTILINE
    )
    RE_ADMISSIBILITY_ANYWHERE = re.compile(
        r'(\(a\)\s*Admissibility|^\d+\.\s*Admissibility|^Admissibility)',
        re.IGNORECASE | re.MULTILINE
    )
    RE_HEADER_FRAGMENT = re.compile(
        r'^(Prepared\s+by\s+the\s+Registry|STRASBOURG$|^\d{1,2}\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+20|^This\s+judgment\s+will\s+become\s+final|^In\s+the\s+case\s+of\s+|^The\s+European\s+Court\s+of\s+Human\s+Rights\s+\(|^Having\s+regard\s+to:|^the\s+application|^the\s+decision\s+to\s+give|^the\s+parties[\'\u2019]\s+observations;?$|^Having\s+deliberated|^Delivers\s+the\s+following)',
        re.IGNORECASE
    )
    RE_JUDGE_NAME_ONLY = re.compile(
        r'^[A-ZÁÀÂÃÉÈÊÍÏÓÔÕÖÚÇÑ][a-záàâãéèêíïóôõöúçñ]+\s*,?\s*(President|Registrar|judge|ad\s+hoc)?$'
    )

    for para in paragraphs:
        text = para.strip()
        if not text:
            continue

        # --- Skip header fragments that leaked into law ---
        if RE_HEADER_FRAGMENT.search(text):
            # Very short fragments or clear header lines → skip
            if len(text) < 200:
                results.append(('header', text))
                continue
        if RE_JUDGE_NAME_ONLY.match(text) and len(text) < 60:
            results.append(('header', text))
            continue
        # Single word/comma lines
        if len(text.strip()) <= 3:
            results.append(('header', text))
            continue

        # --- Check for separate opinion (highest priority, sticky) ---
        if RE_SEPARATE_OPINION.search(text):
            in_separate_opinion = True
            # If this paragraph also has earlier content (e.g., conclusion + opinion heading)
            results.append(('separate_opinion', text))
            continue

        if in_separate_opinion:
            results.append(('separate_opinion', text))
            continue

        # --- Check for APPLICATION OF ARTICLE 41/46 headings ---
        has_art41 = bool(re.search(r'APPLICATION\s+OF\s+ARTICLE\s*41', text, re.IGNORECASE))
        has_art46 = bool(re.search(r'(APPLICATION\s+OF\s+ARTICLE.*46|Article\s+46\s+of\s+the\s+Convention)', text, re.IGNORECASE))

        if has_art41 or has_art46:
            # Determine which comes first / which is primary
            if has_art46 and has_art41:
                # Combined heading: "APPLICATION OF ARTICLEs 41 and 46"
                # Art 46 section typically comes first
                if re.search(r'46\s+(and|&)\s+41', text, re.IGNORECASE):
                    in_art46 = True
                    in_just_sat = False
                else:
                    in_just_sat = True
                    in_art46 = False
            elif has_art46:
                in_art46 = True
                in_just_sat = False
            elif has_art41:
                in_just_sat = True
                in_art46 = False
            sub_state = None

            # If the paragraph also contains a violation finding, tag as merits
            if re.search(r'(violation|no\s+violation)\s+of\s+Article', text, re.IGNORECASE):
                results.append(('merits', text))
            elif in_art46:
                results.append(('article_46', text))
            else:
                results.append(('just_satisfaction', text))
            continue

        # --- If already in just_satisfaction or article_46, stay there ---
        if in_art46:
            # Check for transition to Art 41
            if re.search(r'Article\s+41\s+of\s+the\s+Convention', text, re.IGNORECASE):
                in_art46 = False
                in_just_sat = True
                results.append(('just_satisfaction', text))
            else:
                results.append(('article_46', text))
            continue

        if in_just_sat:
            # Check for transition to Art 46
            if re.search(r'Article\s+46\s+of\s+the\s+Convention', text, re.IGNORECASE):
                in_just_sat = False
                in_art46 = True
                results.append(('article_46', text))
            else:
                results.append(('just_satisfaction', text))
            continue

        # --- Detect admissibility / merits transitions ---

        # Explicit heading: "Admissibility" or "(a) Admissibility"
        if RE_ADMISSIBILITY_ANYWHERE.search(text):
            sub_state = 'admissibility'

        # Explicit heading: "Merits" or "(b) Merits"
        if RE_MERITS_ANYWHERE.search(text):
            sub_state = 'merits'

        # "General principles" heading → merits (Court's substantive analysis)
        if RE_GENERAL_PRINCIPLES.search(text) and sub_state in ('admissibility', 'merits_pending', None):
            sub_state = 'merits'

        # "The Court's assessment" after admissibility → merits
        if RE_COURT_ASSESSMENT.search(text) and sub_state in ('admissibility', 'merits_pending', None):
            sub_state = 'merits'

        # "The parties' submissions" after admissibility is often the start of merits
        # (when no explicit admissibility/merits headings exist)
        if RE_PARTY_SUBMISSIONS.search(text) and sub_state in ('admissibility', None):
            # Only transition if this is the second occurrence (first = admissibility subs)
            pass  # Keep current state

        # Transition trigger: "declared admissible" → next section is merits
        if sub_state == 'admissibility' and RE_DECLARED_ADMISSIBLE.search(text):
            results.append(('admissibility', text))
            # Check if "Merits" appears in the same paragraph after "admissible"
            if re.search(r'admissible.*Merits', text, re.IGNORECASE | re.DOTALL):
                sub_state = 'merits'
            else:
                # The NEXT paragraph will be merits (transition happens after this one)
                sub_state = 'merits_pending'
            continue

        # Transition: violation finding → this is the last merits paragraph
        if sub_state in ('admissibility', 'merits') and re.search(
            r'(there\s+has(\s+accordingly)?\s+been\s+(a\s+)?violation|'
            r'there\s+has\s+been\s+no\s+violation|'
            r'finds?\s+that\s+there\s+(has\s+been|was)\s+(a\s+)?violation)',
            text, re.IGNORECASE
        ):
            # If still in admissibility, this was actually merits all along
            if sub_state == 'admissibility' and not RE_ADMISSIBILITY_ANYWHERE.search(text):
                results.append(('merits', text))
            else:
                results.append((sub_state, text))
            # After a violation finding, the next ALLEGED VIOLATION resets to admissibility
            continue

        # Handle the pending merits transition
        if sub_state == 'merits_pending':
            sub_state = 'merits'

        # --- ALLEGED VIOLATION heading starts a new article assessment ---
        if RE_ALLEGED_VIOLATION.search(text):
            sub_state = 'admissibility'  # Each new article starts with admissibility
            results.append(('admissibility', text))
            continue

        # --- Classify based on current sub_state ---
        if sub_state == 'admissibility':
            results.append(('admissibility', text))
        elif sub_state == 'merits':
            results.append(('merits', text))
        else:
            # No sub_state yet — try to infer
            if RE_JOINDER.search(text):
                results.append(('admissibility', text))
            elif RE_PRELIMINARY_OBJECTION.search(text):
                results.append(('admissibility', text))
            elif RE_ADMISSIBILITY.search(text) or re.search(r'admissibl', text, re.IGNORECASE):
                results.append(('admissibility', text))
                sub_state = 'admissibility'
            else:
                # Default: if we haven't seen any structure yet, assume admissibility
                # (most judgments start law section with admissibility)
                results.append(('admissibility', text))

    return results


RE_FACTS_PROCEEDINGS_HEADING = re.compile(
    r'(proceedings|appeal|judicial|court|tribunal|constitutional|supreme|'
    r'cassation|disciplinary|criminal\s+(investigation|case)|'
    r'detention|remand|arrest|investigat)',
    re.IGNORECASE
)
RE_FACTS_BACKGROUND_HEADING = re.compile(
    r'(background|context|circumstances|events|facts|history|incident|'
    r'report|assessment|information|declaration|vetting|inspection|'
    r'applicant.{0,20}posts?|legislation|reform|domestic\s+law)',
    re.IGNORECASE
)
RE_FACTS_SUB_HEADING = re.compile(
    r'^(\d+\.\s+)?([A-Z]\.?\s+)?[A-Z][A-Za-z\s,]+$'
)


def classify_facts_paragraphs(paragraphs):
    """
    Split 'facts' into facts_background vs facts_proceedings.
    Uses heading-based state machine: detects sub-headings within facts
    (e.g. "A. Background", "B. Domestic proceedings") and assigns all
    following paragraphs to that sub-section until the next heading.
    Falls back to keyword heuristic only when no headings are found.
    """
    results = []
    if not paragraphs:
        return results

    # First pass: identify heading paragraphs and their types
    heading_indices = []
    for i, para in enumerate(paragraphs):
        text = para.strip()
        if not text:
            continue
        # Short lines that look like headings
        if len(text) < 100 and not text.endswith('.'):
            clean = re.sub(r'^\d+\.\s*', '', text).strip()
            if len(clean) > 2 and clean[0].isupper():
                if RE_FACTS_PROCEEDINGS_HEADING.search(clean):
                    heading_indices.append((i, 'facts_proceedings'))
                elif RE_FACTS_BACKGROUND_HEADING.search(clean):
                    heading_indices.append((i, 'facts_background'))
        # Also detect Roman numeral headings: "I. ...", "II. ..."
        if re.match(r'^[IVX]+\.\s+[A-Z]', text) and len(text) < 120:
            clean = re.sub(r'^[IVX]+\.\s*', '', text).strip()
            if RE_FACTS_PROCEEDINGS_HEADING.search(clean):
                heading_indices.append((i, 'facts_proceedings'))
            elif RE_FACTS_BACKGROUND_HEADING.search(clean):
                heading_indices.append((i, 'facts_background'))

    # If we found headings, use them as state transitions
    if heading_indices:
        current_state = 'facts_background'  # default before first heading
        heading_map = dict(heading_indices)

        for i, para in enumerate(paragraphs):
            text = para.strip()
            if not text:
                continue
            if i in heading_map:
                current_state = heading_map[i]
            results.append((current_state, text))
    else:
        # Fallback: keyword heuristic with sequential context
        # Start as background; once we see substantial proceedings language,
        # switch and stay (proceedings typically come after background)
        current_state = 'facts_background'
        for para in paragraphs:
            text = para.strip()
            if not text:
                continue
            proc_words = len(RE_FACTS_PROCEEDINGS.findall(text))
            if proc_words >= 2 and current_state == 'facts_background':
                current_state = 'facts_proceedings'
            results.append((current_state, text))

    return results


def transform_case(case):
    """
    Transform a single case from the flat schema to Option B paragraph-level schema.
    """
    paragraphs = []

    # 1. Header — from metadata fields
    header_text = []
    if case.get('chamber_composed_of'):
        header_text.append(f"Composed of: {', '.join(case['chamber_composed_of'])}")
    if case.get('originating_body'):
        header_text.append(f"Originating body: {', '.join(case['originating_body'])}")
    if case.get('document_type'):
        header_text.append(f"Document type: {', '.join(case['document_type'])}")

    for ht in header_text:
        paragraphs.append({
            'section': 'header',
            'text': ht,
        })

    # 2. Introduction
    for pi, para in enumerate(case.get('introduction', [])):
        if para.strip():
            paragraphs.append({
                'section': 'introduction',
                'text': para.strip(),
            })

    # 3. Legal context (if present — rare, treat as introduction/background)
    for pi, para in enumerate(case.get('legal_context', [])):
        if para.strip():
            paragraphs.append({
                'section': 'introduction',
                'text': para.strip(),
            })

    # 4. Facts → split into background vs proceedings
    for section, text in classify_facts_paragraphs(case.get('facts', [])):
        paragraphs.append({
            'section': section,
            'text': text,
        })

    # 5. Relevant legal framework
    for para in case.get('relevant_legal_framework_practice', []):
        if para.strip():
            paragraphs.append({
                'section': 'legal_framework',
                'text': para.strip(),
            })

    # 6. Law → split into admissibility, merits, just_satisfaction, art46, separate_opinion
    for section, text in classify_law_paragraphs(case.get('law', [])):
        paragraphs.append({
            'section': section,
            'text': text,
        })

    # 7. Operative part (reasons_the_court_unanimously)
    for para in case.get('reasons_the_court_unanimously', []):
        if para.strip():
            paragraphs.append({
                'section': 'operative_part',
                'text': para.strip(),
            })

    # 7b. Separate opinions (from new scraper, or from law classifier)
    for para in case.get('separate_opinions', []):
        if para.strip():
            paragraphs.append({
                'section': 'separate_opinion',
                'text': para.strip(),
            })

    # 8. Violations / Non-violations → tag as operative_part metadata
    for v in case.get('violation', []):
        if v.strip():
            paragraphs.append({
                'section': 'operative_part',
                'text': f"Violation: {v.strip()}",
            })
    for nv in case.get('non-violation', []):
        if nv.strip():
            paragraphs.append({
                'section': 'operative_part',
                'text': f"No violation: {nv.strip()}",
            })

    # Number paragraphs
    for i, p in enumerate(paragraphs):
        p['para_idx'] = i

    # Build transformed case
    transformed = {
        'case_id': case['case_id'],
        'case_no': case.get('case_no', ''),
        'title': case.get('title', ''),
        'judgment_date': case.get('judgment_date', ''),
        'article_no': case.get('article_no', ''),
        'defendants': case.get('defendants', []),
        'court': case.get('court', []),
        'originating_body': case.get('originating_body', []),
        'chamber_composed_of': case.get('chamber_composed_of', []),
        'document_type': case.get('document_type', []),
        'organisation': case.get('organisation', []),
        'violation': case.get('violation', []),
        'non-violation': case.get('non-violation', []),
        'court_assessment_references': case.get('court_assessment_references', {}),
        'paragraphs': paragraphs,
    }

    return transformed


def main():
    print("=" * 60)
    print("ECHR Dataset Transformer — Option B (Structural Division)")
    print("=" * 60)

    # Load
    cases = []
    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                cases.append(json.loads(line))
    print(f"\nLoaded {len(cases)} cases from {INPUT_FILE}")

    # Transform
    transformed = []
    section_stats = Counter()
    total_paras = 0

    for case in cases:
        t = transform_case(case)
        transformed.append(t)
        for p in t['paragraphs']:
            section_stats[p['section']] += 1
            total_paras += 1

    # Write output
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        for t in transformed:
            f.write(json.dumps(t, ensure_ascii=False) + '\n')

    print(f"Wrote {len(transformed)} cases to {OUTPUT_FILE}")
    print(f"\nTotal paragraphs: {total_paras}")
    print(f"\n{'Section':<25} {'Count':>8} {'%':>7}")
    print("-" * 42)
    for section, count in section_stats.most_common():
        pct = count / total_paras * 100
        print(f"  {section:<23} {count:>8} {pct:>6.1f}%")

    # Detailed per-case breakdown
    print(f"\n{'Case':<50} {'Total':>6} {'adm':>5} {'mer':>5} {'js':>4} {'a46':>4} {'sep':>4}")
    print("-" * 80)
    for t in transformed[:10]:
        sec_count = Counter(p['section'] for p in t['paragraphs'])
        title = t['title'][:48]
        print(f"  {title:<48} {len(t['paragraphs']):>6} "
              f"{sec_count.get('admissibility',0):>5} "
              f"{sec_count.get('merits',0):>5} "
              f"{sec_count.get('just_satisfaction',0):>5} "
              f"{sec_count.get('article_46',0):>4} "
              f"{sec_count.get('separate_opinion',0):>4}")

    # Sanity check: cases where admissibility = 0 (might be misclassified)
    no_adm = sum(1 for t in transformed
                 if not any(p['section'] == 'admissibility' for p in t['paragraphs']))
    no_mer = sum(1 for t in transformed
                 if not any(p['section'] == 'merits' for p in t['paragraphs']))
    no_js = sum(1 for t in transformed
                if not any(p['section'] == 'just_satisfaction' for p in t['paragraphs']))

    print(f"\n=== SANITY CHECKS ===")
    print(f"  Cases with 0 admissibility paras: {no_adm}")
    print(f"  Cases with 0 merits paras:        {no_mer}")
    print(f"  Cases with 0 just_satisfaction:    {no_js}")

    return transformed


if __name__ == '__main__':
    main()
