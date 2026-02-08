const fs = require('fs');
const { Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
        HeadingLevel, AlignmentType, BorderStyle, WidthType, ShadingType,
        Header, Footer, PageNumber, PageBreak } = require('docx');

// === CONSTANTS ===
const PAGE_WIDTH = 11906; // A4
const PAGE_HEIGHT = 16838;
const MARGIN = 1134; // ~0.8 inch
const CONTENT_WIDTH = PAGE_WIDTH - 2 * MARGIN;

const border = { style: BorderStyle.SINGLE, size: 1, color: "BBBBBB" };
const borders = { top: border, bottom: border, left: border, right: border };
const cellMargins = { top: 60, bottom: 60, left: 100, right: 100 };

function headerCell(text, width) {
  return new TableCell({
    borders,
    width: { size: width, type: WidthType.DXA },
    shading: { fill: "1a365d", type: ShadingType.CLEAR },
    margins: cellMargins,
    verticalAlign: "center",
    children: [new Paragraph({ children: [new TextRun({ text, bold: true, font: "Arial", size: 18, color: "FFFFFF" })] })]
  });
}

function cell(texts, width, opts = {}) {
  const children = texts.map(t => {
    if (typeof t === 'string') return new TextRun({ text: t, font: "Arial", size: 18, ...(opts.runOpts || {}) });
    return new TextRun({ font: "Arial", size: 18, ...t });
  });
  return new TableCell({
    borders,
    width: { size: width, type: WidthType.DXA },
    shading: opts.fill ? { fill: opts.fill, type: ShadingType.CLEAR } : undefined,
    margins: cellMargins,
    children: [new Paragraph({ children, spacing: { after: 0 } })]
  });
}

function heading(text, level) {
  return new Paragraph({ heading: level, children: [new TextRun({ text, font: "Arial" })] });
}

function para(text, opts = {}) {
  const runs = typeof text === 'string' 
    ? [new TextRun({ text, font: "Arial", size: 22, ...opts })]
    : text.map(t => typeof t === 'string' ? new TextRun({ text: t, font: "Arial", size: 22 }) : new TextRun({ font: "Arial", size: 22, ...t }));
  return new Paragraph({ 
    children: runs, 
    spacing: { after: 160 },
    ...(opts.paraOpts || {})
  });
}

// === BUILD DOCUMENT ===

const children = [];

// Title
children.push(new Paragraph({
  alignment: AlignmentType.CENTER,
  spacing: { after: 80 },
  children: [new TextRun({ text: "Comparative Analysis: Dashboard vs HUDOC", font: "Arial", size: 32, bold: true, color: "1a365d" })]
}));
children.push(new Paragraph({
  alignment: AlignmentType.CENTER,
  spacing: { after: 400 },
  children: [new TextRun({ text: "Selimi v. Albania (Application no. 37896/19) \u2014 Case ID: 001-246126", font: "Arial", size: 22, italics: true, color: "4a5568" })]
}));

// ── SECTION 1: OVERVIEW ──
children.push(heading("1. Overview of Differences", HeadingLevel.HEADING_1));
children.push(para("The comparison reveals three distinct categories of structural discrepancies between the dashboard rendering and the HUDOC original. These arise from two separate processing stages: (1) the upstream HUDOC scraper that produces the original JSONL, and (2) the Option B transformer that classifies paragraphs into structural sections."));

// Summary table
const col1 = 2400, col2 = 2000, col3 = 2500, col4 = 2738;
children.push(new Table({
  width: { size: CONTENT_WIDTH, type: WidthType.DXA },
  columnWidths: [col1, col2, col3, col4],
  rows: [
    new TableRow({ children: [
      headerCell("Issue Category", col1), headerCell("Occurrences", col2),
      headerCell("Origin", col3), headerCell("Impact", col4)
    ]}),
    new TableRow({ children: [
      cell(["Paragraph fragmentation"], col1),
      cell(["~12 instances"], col2),
      cell(["Upstream scraper"], col3),
      cell(["Text split mid-sentence; numbering broken"], col4)
    ]}),
    new TableRow({ children: [
      cell(["Section misclassification"], col1, { fill: "FFF5F5" }),
      cell(["~8 instances"], col2, { fill: "FFF5F5" }),
      cell(["Option B classifier"], col3, { fill: "FFF5F5" }),
      cell(["Wrong section label; content appears under wrong heading"], col4, { fill: "FFF5F5" })
    ]}),
    new TableRow({ children: [
      cell(["Facts sub-section bouncing"], col1),
      cell(["13 transitions"], col2),
      cell(["Option B classifier"], col3),
      cell(["Chaotic alternation between Background/Proceedings"], col4)
    ]}),
  ]
}));
children.push(new Paragraph({ spacing: { after: 200 }, children: [] }));

// ── SECTION 2: PARAGRAPH FRAGMENTATION ──
children.push(heading("2. Paragraph Fragmentation (Scraper-Level)", HeadingLevel.HEADING_1));
children.push(para("The upstream scraper incorrectly splits single HUDOC paragraphs into multiple fragments. This happens when paragraph text contains patterns that resemble paragraph numbering \u2014 such as legal section references, names starting with capital initials, or numbered sub-points."));
children.push(para([
  { text: "Root cause: ", bold: true },
  { text: "The scraper likely splits on regex patterns like " },
  { text: "/^\\d+\\.\\s/", italics: true, font: "Courier New", size: 20 },
  { text: " (number-dot-space at line start), which matches legal cross-references and sub-point numbering within quoted text." }
]));

// Fragmentation examples table
const fc1 = 1200, fc2 = 4219, fc3 = 4219;
children.push(para([{ text: "Specific instances in Selimi:", bold: true }]));
children.push(new Table({
  width: { size: CONTENT_WIDTH, type: WidthType.DXA },
  columnWidths: [fc1, fc2, fc3],
  rows: [
    new TableRow({ children: [
      headerCell("Dashboard \u00B6", fc1), headerCell("Fragmented text", fc2), headerCell("HUDOC original (single \u00B6)", fc3)
    ]}),
    new TableRow({ children: [
      cell(["[32]\u2013[33]"], fc1),
      cell([{text: "\"...pursuant to section\" ", size: 16}, {text: "then", size: 16, italics: true}, {text: " \"61. (2) and (3)...\"", size: 16}], fc2),
      cell([{text: "\u00B622: One paragraph containing \"section 61 (2) and (3)\"", size: 16}], fc3)
    ]}),
    new TableRow({ children: [
      cell(["[48]\u2013[50]"], fc1, {fill: "FFF5F5"}),
      cell([{text: "\"(a)\" then \"A. I. had been...\" then \"(1) of Law no. 10192...\"", size: 16}], fc2, {fill: "FFF5F5"}),
      cell([{text: "\u00B626(a): One sub-point about A.I.\u2019s prosecution", size: 16}], fc3, {fill: "FFF5F5"})
    ]}),
    new TableRow({ children: [
      cell(["[56]\u2013[57]"], fc1),
      cell([{text: "\"...composed of Judge\" then \"E. I. as chairperson...\"", size: 16}], fc2),
      cell([{text: "\u00B628: One paragraph about the extradition appeal panel", size: 16}], fc3)
    ]}),
    new TableRow({ children: [
      cell(["[76]\u2013[77]"], fc1, {fill: "FFF5F5"}),
      cell([{text: "\"...civil limb of Article\" then \"6. \u00A7 1 of the Convention...\"", size: 16}], fc2, {fill: "FFF5F5"}),
      cell([{text: "\u00B638: One paragraph about Article 6 \u00A7 1 applicability", size: 16}], fc3, {fill: "FFF5F5"})
    ]}),
    new TableRow({ children: [
      cell(["[60]\u2013[61]"], fc1),
      cell([{text: "\"...Thanza, \u00A7\u00A7\" then \"53. \u2011\" then \"73. The provisions...\"", size: 16}], fc2),
      cell([{text: "\u00B630: One paragraph with cross-reference to \u00A7\u00A7 53\u201173", size: 16}], fc3)
    ]}),
    new TableRow({ children: [
      cell(["[97]"], fc1, {fill: "FFF5F5"}),
      cell([{text: "\"1. The States have greater latitude...\"", size: 16}], fc2, {fill: "FFF5F5"}),
      cell([{text: "Continuation of \u00B655, split at \"Article 6 \u00A7 1.\"", size: 16}], fc3, {fill: "FFF5F5"})
    ]}),
    new TableRow({ children: [
      cell(["[103]\u2013[104]"], fc1),
      cell([{text: "\"6. \u00A7\" then \"1. For that to be the case...\"", size: 16}], fc2),
      cell([{text: "\u00B659: One paragraph about Article 6 \u00A7 1 limitations", size: 16}], fc3)
    ]}),
    new TableRow({ children: [
      cell(["[140]\u2013[141]"], fc1, {fill: "FFF5F5"}),
      cell([{text: "\"...(ii)\" then \"A. S. had been A.I.\u2019s personal driver...\"", size: 16}], fc2, {fill: "FFF5F5"}),
      cell([{text: "\u00B694: One paragraph about use of A.S.\u2019s vehicle", size: 16}], fc3, {fill: "FFF5F5"})
    ]}),
  ]
}));
children.push(new Paragraph({ spacing: { after: 200 }, children: [] }));

children.push(para([
  { text: "Pattern: ", bold: true },
  { text: "All fragmentations share the same trigger \u2014 the scraper encounters text like \"section 61.\", \"A. I.\", \"6. \u00A7 1\", or \"\u00A7\u00A7 53.\" and interprets the number-dot-space pattern as a new paragraph boundary. In HUDOC, these are mid-sentence references within a single paragraph." }
]));

// ── SECTION 3: SECTION MISCLASSIFICATION ──
children.push(new Paragraph({ children: [new PageBreak()] }));
children.push(heading("3. Section Misclassification (Classifier-Level)", HeadingLevel.HEADING_1));

children.push(heading("3.1 Legal Framework \u2192 Admissibility false transition", HeadingLevel.HEADING_2));
children.push(para("The most consequential misclassification occurs at paragraph index [66]. HUDOC paragraphs \u00B632\u201336 belong to the RELEVANT LEGAL FRAMEWORK AND PRACTICE section. However, the classifier transitions to \"Admissibility\" at [66] and absorbs the remaining legal framework paragraphs (\u00B632\u2013\u00B636) into the admissibility section."));
children.push(para([
  { text: "Root cause: ", bold: true },
  { text: "Paragraph [65] ends with the text \"b) Presents findings and opinions...in accordance with\" and paragraph [66] starts with \"; ...\". The classifier\u2019s default fallback for unrecognized text in the " },
  { text: "law", italics: true },
  { text: " field is to assign it to admissibility (line 275 of transform_optionB.py). Since these paragraphs come from the " },
  { text: "relevant_legal_framework_practice", italics: true, font: "Courier New", size: 20 },
  { text: " field, they should never enter the law classifier at all. But they don\u2019t \u2014 the real issue is that the " },
  { text: "original scraper", bold: true },
  { text: " misassigned several legal framework paragraphs to the wrong source field. The Option B transformer trusts field boundaries and sends " },
  { text: "relevant_legal_framework_practice", italics: true, font: "Courier New", size: 20 },
  { text: " directly to legal_framework. If the scraper puts these paragraphs in " },
  { text: "law", italics: true, font: "Courier New", size: 20 },
  { text: " instead, the classifier mishandles them." }
]));

children.push(heading("3.2 Merits \u2192 Admissibility false re-entry", HeadingLevel.HEADING_2));
children.push(para("At paragraph [149], the text reads: \"102. There has accordingly been a violation of Article 6 \u00A7 1 of the Convention. ALLEGED VIOLATION OF ARTICLE 8 OF THE CONVENTION\". This is the conclusion of the merits for Article 6 followed by a new article heading. The classifier correctly detects RE_ALLEGED_VIOLATION and resets sub_state to admissibility."));
children.push(para([
  { text: "The issue: ", bold: true },
  { text: "In HUDOC, \u00B6102 is the final sentence of the merits conclusion. The heading \"ALLEGED VIOLATION OF ARTICLE 8\" begins a new section. Because the scraper merged these into one paragraph, the classifier assigns the entire combined text to admissibility \u2014 losing the violation finding from the merits section." }
]));

children.push(heading("3.3 Article 8 complaint misplaced into Article 46", HeadingLevel.HEADING_2));
children.push(para("Paragraph [151] (\"104. The Government argued that the complaint was manifestly ill-founded. mutatis mutandis, \u00D6mer G\u00FCner v. Turkey...\") is classified as article_46. In HUDOC, this is \u00B6104\u2013105 about the Article 8 complaint, followed by the heading \"APPLICATION OF ARTICLEs 46 and 41\"."));
children.push(para([
  { text: "Root cause: ", bold: true },
  { text: "The scraper merged \u00B6104, \u00B6105, and the Art 46 heading into a single text blob. The classifier\u2019s RE_ARTICLE_46_HEADING pattern matches \"Article 46 of the Convention\" anywhere in the text, triggering article_46 classification for the entire paragraph \u2014 even though the Article 8 discussion precedes the heading." }
]));

// ── SECTION 4: FACTS SUB-SECTION BOUNCING ──
children.push(heading("4. Facts Sub-Section Bouncing", HeadingLevel.HEADING_1));
children.push(para("The dashboard shows 13 transitions between Facts (Background) and Facts (Proceedings) in the facts section. HUDOC organizes the same content into a stable hierarchy: THE FACTS \u2192 Background information \u2192 Vetting proceedings (with sub-headings: CISD report, IQC investigation, IQC report, IQC decision, SAC decision) \u2192 Other proceedings."));

children.push(para([
  { text: "Root cause: ", bold: true },
  { text: "The " },
  { text: "classify_facts_paragraphs()", italics: true, font: "Courier New", size: 20 },
  { text: " function uses a simple keyword-counting heuristic: if a paragraph contains \u22652 instances of words like \"proceedings\", \"court\", \"judgment\", \"decision\", \"hearing\", it is classified as facts_proceedings; otherwise as facts_background. This per-paragraph classification ignores context entirely." }
]));

children.push(para("Consider the IQC\u2019s decision (\u00B621\u201323 in HUDOC). \u00B621 describes the public hearing (\"decision\", \"hearing\" \u2192 proceedings), while \u00B622 describes the substantive findings (\"dismissed\", \"inappropriate contact\" \u2192 background). Both belong to the same sub-section (IQC\u2019s decision) but get split across sections. The same pattern repeats for the SAC\u2019s decision."));

children.push(para([
  { text: "The HUDOC structure has 6 sub-sections within THE FACTS: ", bold: true },
  { text: "Background information, Vetting proceedings in respect of the applicant, CISD report, IQC\u2019s investigation, IQC\u2019s decision, SAC\u2019s decision, Other proceedings. Option B\u2019s binary split (background vs proceedings) cannot represent this richness. The per-paragraph keyword heuristic further degrades the result by ignoring sequential context." }
]));

// ── SECTION 5: MISSING PARAGRAPH ──
children.push(new Paragraph({ children: [new PageBreak()] }));
children.push(heading("5. Missing Content", HeadingLevel.HEADING_1));
children.push(para("HUDOC \u00B666 (\"The Court will therefore apply the general principles...\") and \u00B693 (\"The Court considers in view of the above considerations...\") appear absent from the dashboard. \u00B666 was likely merged with adjacent text by the scraper, and \u00B693 may have been consumed by a paragraph split."));

// ── SECTION 6: REMEDIATION ──
children.push(heading("6. Remediation Strategy", HeadingLevel.HEADING_1));

children.push(heading("6.1 Scraper-level fixes (paragraph fragmentation)", HeadingLevel.HEADING_2));
children.push(para([
  { text: "Priority: HIGH. ", bold: true, color: "C53030" },
  { text: "This is the root cause of multiple downstream issues. Every fragment creates a false paragraph that can trigger false section transitions." }
]));
children.push(para("Approach: Add a paragraph-merging post-processing step to the scraper (or as a pre-processing step before Option B transformation). The merger should re-join fragments that were incorrectly split on legal cross-references:"));

children.push(para([
  { text: "(a) Detect fragments ", bold: true },
  { text: "that start with patterns like a bare number (\"61.\", \"6.\", \"1.\"), a single letter-dot (\"A.\", \"E.\"), a bare section marker (\"\u00A7\"), or a semi-colon/closing punctuation. These are never valid paragraph starts in ECHR judgments." }
]));
children.push(para([
  { text: "(b) Merge forward: ", bold: true },
  { text: "If a paragraph starts with such a pattern, prepend it to the previous paragraph. This is safe because ECHR paragraphs always start with a number followed by substantive text (e.g., \"22. The IQC dismissed...\"), never with a bare cross-reference." }
]));
children.push(para([
  { text: "(c) Validate: ", bold: true },
  { text: "After merging, verify that each paragraph starts with a valid ECHR paragraph pattern: /^(\\d+\\.\\s+[A-Z]|\\([a-z]\\)|RELEVANT|THE|FOR\\s+THESE|ALLEGED)/." }
]));

children.push(heading("6.2 Classifier-level fixes (section assignment)", HeadingLevel.HEADING_2));
children.push(para([
  { text: "Priority: MEDIUM. ", bold: true, color: "C05621" },
  { text: "Several fixes can significantly improve classification accuracy." }
]));

children.push(para([
  { text: "(a) Legal Framework boundary: ", bold: true },
  { text: "Paragraphs from the " },
  { text: "relevant_legal_framework_practice", font: "Courier New", size: 20 },
  { text: " field are already correctly routed to legal_framework. The issue occurs when the scraper puts legal framework text into the " },
  { text: "law", font: "Courier New", size: 20 },
  { text: " field. Add a heading-based detector in classify_law_paragraphs() that recognizes legal framework content (e.g., \"Article B of the Annex\", \"section 38 of the Vetting Act\", statutory quotes) and keeps them as legal_framework before entering the admissibility state machine." }
]));

children.push(para([
  { text: "(b) Combined paragraph handling: ", bold: true },
  { text: "When a paragraph contains both a conclusion (\"There has accordingly been a violation...\") AND a new section heading (\"ALLEGED VIOLATION OF...\"), split the text at the heading boundary and assign each part to its correct section." }
]));

children.push(para([
  { text: "(c) Facts classification: ", bold: true },
  { text: "Replace the per-paragraph keyword heuristic with a heading-based state machine. Detect HUDOC sub-headings within the facts (\"BACKGROUND INFORMATION\", \"VETTING PROCEEDINGS\", \"CISD report\", \"IQC\u2019s decision\", \"SAC\u2019s decision\", \"OTHER PROCEEDINGS\") and maintain state. Paragraphs within the same sub-section stay together regardless of keyword content." }
]));

children.push(para([
  { text: "(d) Article 8/46 disambiguation: ", bold: true },
  { text: "When detecting APPLICATION OF ARTICLE patterns, check whether preceding text belongs to a different complaint section and split accordingly." }
]));

children.push(heading("6.3 Implementation priority", HeadingLevel.HEADING_2));

const pc1 = 800, pc2 = 3200, pc3 = 2200, pc4 = 1600, pc5 = 1838;
children.push(new Table({
  width: { size: CONTENT_WIDTH, type: WidthType.DXA },
  columnWidths: [pc1, pc2, pc3, pc4, pc5],
  rows: [
    new TableRow({ children: [
      headerCell("#", pc1), headerCell("Fix", pc2), headerCell("Addresses", pc3),
      headerCell("Effort", pc4), headerCell("Impact", pc5)
    ]}),
    new TableRow({ children: [
      cell(["1"], pc1), cell(["Paragraph merger (pre-processing)"], pc2),
      cell(["Fragmentation + cascading misclassification"], pc3),
      cell(["Medium"], pc4), cell([{text: "Very High", bold: true, color: "C53030"}], pc5)
    ]}),
    new TableRow({ children: [
      cell(["2"], pc1, {fill: "F7FAFC"}), cell(["Facts heading-based state machine"], pc2, {fill: "F7FAFC"}),
      cell(["Facts section bouncing"], pc3, {fill: "F7FAFC"}),
      cell(["Medium"], pc4, {fill: "F7FAFC"}), cell([{text: "High", bold: true, color: "C05621"}], pc5, {fill: "F7FAFC"})
    ]}),
    new TableRow({ children: [
      cell(["3"], pc1), cell(["Combined-paragraph splitting"], pc2),
      cell(["Merits/Admissibility boundary"], pc3),
      cell(["Low"], pc4), cell([{text: "High", bold: true, color: "C05621"}], pc5)
    ]}),
    new TableRow({ children: [
      cell(["4"], pc1, {fill: "F7FAFC"}), cell(["Legal framework detector in law classifier"], pc2, {fill: "F7FAFC"}),
      cell(["Legal framework \u2192 admissibility leak"], pc3, {fill: "F7FAFC"}),
      cell(["Low"], pc4, {fill: "F7FAFC"}), cell([{text: "Medium", bold: true}], pc5, {fill: "F7FAFC"})
    ]}),
  ]
}));

children.push(new Paragraph({ spacing: { after: 300 }, children: [] }));

children.push(para([
  { text: "Fix #1 (paragraph merger) should be implemented first ", bold: true },
  { text: "because it eliminates the root cause of multiple downstream issues. Many section misclassifications (3.2, 3.3) would not occur if the paragraphs were properly formed. Fix #2 (facts state machine) would then address the most visually distracting issue \u2014 the chaotic bouncing between Background and Proceedings. Fixes #3 and #4 handle remaining edge cases." }
]));

// === CREATE DOCUMENT ===
const doc = new Document({
  styles: {
    default: { document: { run: { font: "Arial", size: 22 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 28, bold: true, font: "Arial", color: "1a365d" },
        paragraph: { spacing: { before: 360, after: 200 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 24, bold: true, font: "Arial", color: "2c5282" },
        paragraph: { spacing: { before: 240, after: 160 }, outlineLevel: 1 } },
    ]
  },
  sections: [{
    properties: {
      page: {
        size: { width: PAGE_WIDTH, height: PAGE_HEIGHT },
        margin: { top: MARGIN, right: MARGIN, bottom: MARGIN, left: MARGIN }
      }
    },
    headers: {
      default: new Header({ children: [new Paragraph({
        alignment: AlignmentType.RIGHT,
        children: [new TextRun({ text: "Dashboard vs HUDOC \u2014 Structural Analysis", font: "Arial", size: 16, color: "718096", italics: true })]
      })] })
    },
    footers: {
      default: new Footer({ children: [new Paragraph({
        alignment: AlignmentType.CENTER,
        children: [new TextRun({ text: "Page ", font: "Arial", size: 16, color: "718096" }), new TextRun({ children: [PageNumber.CURRENT], font: "Arial", size: 16, color: "718096" })]
      })] })
    },
    children
  }]
});

Packer.toBuffer(doc).then(buffer => {
  fs.writeFileSync("/sessions/admiring-ecstatic-fermi/mnt/ECHR/analysis_dashboard_vs_hudoc.docx", buffer);
  console.log("Document created successfully");
});
