const SAMPLE_DATA_URL = "data/echr_cases_sample50.jsonl";
const PAGE_SIZE = 20;
const MAX_HITS = 5000;
const CLASSIFIER_SAMPLE_SIZE = 30;
const CLASSIFIER_STORAGE_PREFIX = "echr-classifier-v1:";
const CLASSIFIER_DEFAULT_THRESHOLD = 0.22;
const CLASSIFIER_MIN_LABELED_PARAGRAPHS = 6;
const CLASSIFIER_METHODS = {
  tfidf_centroid: {
    label: "TF-IDF Centroid (Balanced)",
    hint: "Balanced precision/recall using word TF-IDF centroids.",
    defaultThreshold: 0.22,
  },
  char_ngram_centroid: {
    label: "Char N-Gram Centroid (Short Text)",
    hint: "Robust on short/noisy text using character n-gram TF-IDF.",
    defaultThreshold: 0.18,
  },
  keyword_overlap: {
    label: "Keyword Overlap (Fast, Interpretable)",
    hint: "Fast rule-like scoring based on label-specific keywords.",
    defaultThreshold: 0.2,
  },
};

const SECTION_ORDER = [
  "introduction",
  "facts_background",
  "facts_proceedings",
  "legal_framework",
  "legal_context",
  "admissibility",
  "merits",
  "just_satisfaction",
  "article_46",
  "operative_part",
  "separate_opinion",
  "appendix",
];

const SECTION_LABELS = {
  header: "Header",
  introduction: "Introduction",
  facts_background: "Facts (Background)",
  facts_proceedings: "Facts (Proceedings)",
  legal_framework: "Legal Framework",
  legal_context: "Legal Context",
  admissibility: "Admissibility",
  merits: "Merits",
  just_satisfaction: "Just Satisfaction",
  article_46: "Article 46 (Execution)",
  operative_part: "Operative Part",
  separate_opinion: "Separate Opinion",
  appendix: "Appendix",
};

const SECTION_COLORS = {
  header: "#718096",
  introduction: "#4C72B0",
  facts_background: "#DD8452",
  facts_proceedings: "#C44E52",
  legal_framework: "#937860",
  legal_context: "#8B6A9C",
  admissibility: "#8172B3",
  merits: "#55A868",
  just_satisfaction: "#DA8BC3",
  article_46: "#CCB974",
  operative_part: "#64B5CD",
  separate_opinion: "#8C8C8C",
  appendix: "#A5A58D",
};

const COUNTRY_NAMES = {
  ALB: "Albania",
  AND: "Andorra",
  ARM: "Armenia",
  AUT: "Austria",
  AZE: "Azerbaijan",
  BEL: "Belgium",
  BIH: "Bosnia and Herzegovina",
  BGR: "Bulgaria",
  HRV: "Croatia",
  CYP: "Cyprus",
  CZE: "Czech Republic",
  DNK: "Denmark",
  EST: "Estonia",
  FIN: "Finland",
  FRA: "France",
  GEO: "Georgia",
  DEU: "Germany",
  GRC: "Greece",
  HUN: "Hungary",
  ISL: "Iceland",
  IRL: "Ireland",
  ITA: "Italy",
  LVA: "Latvia",
  LIE: "Liechtenstein",
  LTU: "Lithuania",
  LUX: "Luxembourg",
  MLT: "Malta",
  MDA: "Moldova",
  MCO: "Monaco",
  MNE: "Montenegro",
  NLD: "Netherlands",
  MKD: "North Macedonia",
  NOR: "Norway",
  POL: "Poland",
  PRT: "Portugal",
  ROU: "Romania",
  RUS: "Russia",
  SMR: "San Marino",
  SRB: "Serbia",
  SVK: "Slovakia",
  SVN: "Slovenia",
  ESP: "Spain",
  SWE: "Sweden",
  CHE: "Switzerland",
  TUR: "Turkey",
  UKR: "Ukraine",
  GBR: "United Kingdom",
};

const STOPWORDS = new Set([
  "the", "of", "and", "to", "in", "a", "that", "is", "was", "for", "it", "on", "with", "as", "by", "at", "an",
  "be", "this", "which", "or", "from", "had", "has", "have", "its", "not", "but", "are", "were", "been", "also",
  "they", "their", "would", "could", "should", "may", "can", "will", "shall", "any", "all", "each", "other", "such",
  "than", "more", "if", "there", "these", "those", "his", "her", "who", "him", "them", "did", "about", "between",
  "through", "after", "before", "under", "over", "into", "only", "see", "cited", "above", "paragraph", "paragraphs",
  "article", "articles", "no", "nos", "ibid", "v", "court", "applicant", "government", "case", "convention",
]);

const fmtInt = new Intl.NumberFormat("en-US");

const state = {
  loaded: false,
  datasetKey: "",
  sourceLabel: "",
  cases: [],
  caseById: new Map(),
  paragraphIndex: [],
  paragraphByKey: new Map(),
  sectionsInDataset: [],
  sortedCaseIdsByDate: [],
  articles: [],
  countries: [],
  bodies: [],
  importanceLevels: [],
  query: "",
  currentFilters: null,
  currentOrderedCaseIds: [],
  currentResultsById: new Map(),
  currentTerms: [],
  currentMode: "browse",
  currentPage: 1,
  totalHits: 0,
  limited: false,
  searchTimeMs: 0,
  classifierOpen: false,
  classifier: null,
};

const el = {};

function byId(id) {
  return document.getElementById(id);
}

function createEmptyClassifierState() {
  return {
    labels: [],
    trainingSections: new Set(),
    predictionSections: new Set(),
    sampleKeys: [],
    sampleCursor: 0,
    assignments: new Map(),
    method: "tfidf_centroid",
    threshold: CLASSIFIER_DEFAULT_THRESHOLD,
    model: null,
    modelInfo: "",
    lastSavedAt: null,
    loadedFromStorage: false,
  };
}

function cacheElements() {
  el.themeToggle = byId("themeToggle");

  el.loadSampleBtn = byId("loadSampleBtn");
  el.fileInput = byId("fileInput");
  el.dropZone = byId("dropZone");
  el.datasetStatus = byId("datasetStatus");
  el.datasetMeta = byId("datasetMeta");
  el.classifierResumeNote = byId("classifierResumeNote");
  el.openClassifierBtn = byId("openClassifierBtn");

  el.searchForm = byId("searchForm");
  el.searchInput = byId("searchInput");
  el.searchBtn = byId("searchBtn");
  el.filterToggleBtn = byId("filterToggleBtn");
  el.filtersPanel = byId("filtersPanel");

  el.sectionsFilters = byId("sectionsFilters");
  el.countriesFilters = byId("countriesFilters");
  el.articlesFilters = byId("articlesFilters");
  el.originatingBodyFilters = byId("originatingBodyFilters");
  el.importanceFilters = byId("importanceFilters");
  el.outcomeFilters = byId("outcomeFilters");
  el.separateOpinionFilters = byId("separateOpinionFilters");
  el.presenceFilters = byId("presenceFilters");
  el.keywordFilterInput = byId("keywordFilterInput");
  el.chamberFilters = byId("chamberFilters");
  el.dateFrom = byId("dateFrom");
  el.dateTo = byId("dateTo");

  el.statTotalCases = byId("statTotalCases");
  el.statTotalParagraphs = byId("statTotalParagraphs");
  el.statTotalCountries = byId("statTotalCountries");
  el.statDateRange = byId("statDateRange");

  el.resultsHeader = byId("resultsHeader");
  el.inlineSearchForm = byId("inlineSearchForm");
  el.inlineSearchInput = byId("inlineSearchInput");
  el.inlineSearchBtn = byId("inlineSearchBtn");
  el.resultsHits = byId("resultsHits");
  el.resultsCases = byId("resultsCases");
  el.resultsTime = byId("resultsTime");
  el.exportBtn = byId("exportBtn");
  el.classifierQuickOpenBtn = byId("classifierQuickOpenBtn");
  el.clearBtn = byId("clearBtn");
  el.activeFilters = byId("activeFilters");

  el.noResults = byId("noResults");
  el.backToSearch = byId("backToSearch");
  el.casesList = byId("casesList");
  el.pagination = byId("pagination");

  el.analyticsArticles = byId("analyticsArticles");
  el.analyticsCountries = byId("analyticsCountries");
  el.analyticsSections = byId("analyticsSections");
  el.analyticsBodies = byId("analyticsBodies");
  el.analyticsImportance = byId("analyticsImportance");
  el.analyticsOutcomes = byId("analyticsOutcomes");
  el.analyticsWords = byId("analyticsWords");

  el.caseModal = byId("caseModal");
  el.closeModal = byId("closeModal");
  el.modalBackdrop = document.querySelector(".modal-backdrop");
  el.modalTitle = byId("modalTitle");
  el.modalMeta = byId("modalMeta");
  el.modalQuery = byId("modalQuery");
  el.modalSectionFilter = byId("modalSectionFilter");
  el.modalCount = byId("modalCount");
  el.modalBody = byId("modalBody");

  el.classifierPane = byId("classifierPane");
  el.classifierBackdrop = byId("classifierBackdrop");
  el.closeClassifierBtn = byId("closeClassifierBtn");
  el.newClassifierLabelInput = byId("newClassifierLabelInput");
  el.addClassifierLabelBtn = byId("addClassifierLabelBtn");
  el.classifierLabelsList = byId("classifierLabelsList");
  el.classifierTrainingSections = byId("classifierTrainingSections");
  el.refreshClassifierSampleBtn = byId("refreshClassifierSampleBtn");
  el.classifierPrevSampleBtn = byId("classifierPrevSampleBtn");
  el.classifierNextSampleBtn = byId("classifierNextSampleBtn");
  el.classifierSampleCounter = byId("classifierSampleCounter");
  el.classifierSampleCard = byId("classifierSampleCard");
  el.classifierMethodSelect = byId("classifierMethod");
  el.classifierMethodHint = byId("classifierMethodHint");
  el.classifierThresholdRange = byId("classifierThresholdRange");
  el.classifierThresholdValue = byId("classifierThresholdValue");
  el.trainClassifierBtn = byId("trainClassifierBtn");
  el.classifierModelStatus = byId("classifierModelStatus");
  el.classifierPredictionSections = byId("classifierPredictionSections");
  el.applyClassifierModelBtn = byId("applyClassifierModelBtn");
  el.exportClassifierProgressBtn = byId("exportClassifierProgressBtn");
  el.importClassifierProgressInput = byId("importClassifierProgressInput");
  el.clearClassifierProgressBtn = byId("clearClassifierProgressBtn");
  el.classifierPersistStatus = byId("classifierPersistStatus");
}

function escapeHtml(text) {
  return String(text)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function escapeRegExp(text) {
  return String(text).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function parseDate(raw) {
  if (!raw) return null;
  const text = String(raw).trim();
  if (!text) return null;

  let match = text.match(/^(\d{2})\/(\d{2})\/(\d{4})$/);
  if (match) {
    const day = Number(match[1]);
    const month = Number(match[2]);
    const year = Number(match[3]);
    return new Date(Date.UTC(year, month - 1, day));
  }

  match = text.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (match) {
    const year = Number(match[1]);
    const month = Number(match[2]);
    const day = Number(match[3]);
    return new Date(Date.UTC(year, month - 1, day));
  }

  match = text.match(/^(\d{4})\/(\d{2})\/(\d{2})$/);
  if (match) {
    const year = Number(match[1]);
    const month = Number(match[2]);
    const day = Number(match[3]);
    return new Date(Date.UTC(year, month - 1, day));
  }

  return null;
}

function parseDateInput(raw) {
  const dt = parseDate(raw);
  return dt ? dt.getTime() : null;
}

function splitArticles(articleNo) {
  if (!articleNo) return [];
  return String(articleNo)
    .split(/[;,]/)
    .map((x) => x.trim())
    .filter(Boolean);
}

function parseQuery(query) {
  if (!query || !query.trim()) {
    return { andTerms: [], orGroups: [] };
  }

  const phrases = [...query.matchAll(/"([^"]+)"/g)]
    .map((m) => m[1].trim().toLowerCase())
    .filter(Boolean);

  const remaining = query.replace(/"[^"]*"/g, " ").trim();

  const andTerms = [];
  const orGroups = [];

  const orParts = remaining
    .split(/\s+[oO][rR]\s+/)
    .map((p) => p.trim())
    .filter(Boolean);

  if (orParts.length > 1) {
    orGroups.push(orParts.map((t) => t.toLowerCase()));
  } else {
    for (const token of remaining.split(/\s+/)) {
      const t = token.trim().toLowerCase();
      if (t) andTerms.push(t);
    }
  }

  for (const p of phrases) {
    andTerms.push(p);
  }

  return { andTerms, orGroups };
}

function highlightTerms(text, terms) {
  let html = escapeHtml(text);
  const sortedTerms = [...new Set(terms)].sort((a, b) => b.length - a.length);

  for (const term of sortedTerms) {
    if (!term) continue;
    const re = new RegExp(escapeRegExp(escapeHtml(term)), "gi");
    html = html.replace(re, (m) => `<mark class="hl">${m}</mark>`);
  }

  return html;
}

function setTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  try {
    localStorage.setItem("echr-theme", theme);
  } catch {
    // Ignore storage errors.
  }
}

function initTheme() {
  try {
    const saved = localStorage.getItem("echr-theme");
    if (saved === "dark" || saved === "light") {
      setTheme(saved);
      return;
    }
  } catch {
    // Ignore storage errors.
  }
  setTheme("light");
}

function toggleTheme() {
  const current = document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
  setTheme(current === "dark" ? "light" : "dark");
}

function setDatasetStatus(message, isError = false) {
  el.datasetStatus.textContent = message;
  el.datasetStatus.classList.toggle("dataset-error", isError);
}

function setDatasetMeta(message) {
  el.datasetMeta.textContent = message;
}

function setSearchEnabled(enabled) {
  el.searchInput.disabled = !enabled;
  el.searchBtn.disabled = !enabled;
  el.inlineSearchInput.disabled = !enabled;
  el.inlineSearchBtn.disabled = !enabled;
  el.filterToggleBtn.disabled = !enabled;
  el.dateFrom.disabled = !enabled;
  el.dateTo.disabled = !enabled;
  el.keywordFilterInput.disabled = !enabled;

  const dynamicInputs = document.querySelectorAll(
    "#sectionsFilters input, #countriesFilters input, #articlesFilters input, #originatingBodyFilters input, #importanceFilters input, #outcomeFilters input, #separateOpinionFilters input, #presenceFilters input, #chamberFilters input"
  );
  for (const input of dynamicInputs) {
    input.disabled = !enabled;
  }

  el.searchForm.classList.toggle("search-disabled", !enabled);

  el.exportBtn.disabled = !enabled || !state.currentOrderedCaseIds.length;
  el.clearBtn.disabled = !enabled;
  el.openClassifierBtn.disabled = !enabled;
  el.classifierQuickOpenBtn.disabled = !enabled;
}

function setDatasetLoading(loading) {
  el.loadSampleBtn.disabled = loading;
  el.fileInput.disabled = loading;
  if (!state.loaded) {
    el.openClassifierBtn.disabled = true;
    el.classifierQuickOpenBtn.disabled = true;
  }
  el.dropZone.classList.toggle("loading", loading);
}

function parseJsonlText(text) {
  const lines = String(text)
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);

  const rows = [];
  let invalidCount = 0;

  for (const line of lines) {
    try {
      const item = JSON.parse(line);
      if (item && typeof item === "object") {
        rows.push(item);
      } else {
        invalidCount += 1;
      }
    } catch {
      invalidCount += 1;
    }
  }

  return { rows, invalidCount, totalLines: lines.length };
}

function isPresentValue(value) {
  return !(value == null || value === "" || value === false || (Array.isArray(value) && value.length === 0));
}

function dedupeStrings(values) {
  return [...new Set(values.map((x) => String(x || "").trim()).filter(Boolean))];
}

function normalizeListField(value, splitPattern = /[;,]/) {
  if (Array.isArray(value)) {
    return dedupeStrings(value);
  }
  const text = String(value || "").trim();
  if (!text) return [];
  return dedupeStrings(text.split(splitPattern));
}

function normalizeSectionKey(rawSection) {
  const key = String(rawSection || "").trim().toLowerCase().replaceAll("-", " ");
  if (!key) return "unknown";

  const aliases = {
    header: "header",
    introduction: "introduction",
    "facts background": "facts_background",
    facts_background: "facts_background",
    "facts proceedings": "facts_proceedings",
    facts_proceedings: "facts_proceedings",
    "legal framework": "legal_framework",
    legal_framework: "legal_framework",
    "legal context": "legal_context",
    legal_context: "legal_context",
    admissibility: "admissibility",
    merits: "merits",
    "just satisfaction": "just_satisfaction",
    just_satisfaction: "just_satisfaction",
    "article 46": "article_46",
    article_46: "article_46",
    "operative part": "operative_part",
    operative_part: "operative_part",
    "separate opinion": "separate_opinion",
    separate_opinion: "separate_opinion",
    appendix: "appendix",
  };

  if (aliases[key]) {
    return aliases[key];
  }
  return key.replace(/\s+/g, "_");
}

function normalizeStateValues(caseObj) {
  const respondent = String(caseObj.respondent_state || "").trim();
  if (respondent) {
    return [respondent];
  }

  const defendantsRaw = normalizeListField(caseObj.defendants);
  if (!defendantsRaw.length) return [];
  return defendantsRaw.map((value) => COUNTRY_NAMES[value] || value);
}

function normalizeDocumentTypes(caseObj) {
  return normalizeListField(caseObj.document_type);
}

function deriveChamberCategory(documentTypes, originatingBody) {
  const docText = documentTypes.join(" ").toUpperCase();
  const bodyText = String(originatingBody || "").toUpperCase();

  if (docText.includes("GRANDCHAMBER") || docText.includes("GRAND CHAMBER") || bodyText.includes("GRAND CHAMBER")) {
    return "GRANDCHAMBER";
  }
  if (docText.includes("CHAMBER") || bodyText.includes("SECTION") || bodyText.includes("CHAMBER")) {
    return "CHAMBER";
  }
  return "OTHER";
}

function parseBoolLike(value) {
  if (value === true || value === false) return value;
  const text = String(value || "").trim().toLowerCase();
  if (["true", "1", "yes", "y"].includes(text)) return true;
  if (["false", "0", "no", "n"].includes(text)) return false;
  return false;
}

function deriveOutcomeBucket(violation, nonViolation) {
  const hasViolation = violation.length > 0;
  const hasNonViolation = nonViolation.length > 0;
  if (hasViolation && hasNonViolation) return "both";
  if (hasViolation) return "violation_only";
  if (hasNonViolation) return "non_violation_only";
  return "neither";
}

function normalizeCases(rawCases) {
  const usedIds = new Set();
  const normalized = [];

  for (let i = 0; i < rawCases.length; i += 1) {
    const source = rawCases[i] || {};
    const caseObj = { ...source };

    const baseId = String(caseObj.case_id || caseObj.caseId || `case-${i + 1}`).trim() || `case-${i + 1}`;
    let caseId = baseId;
    let suffix = 2;
    while (usedIds.has(caseId)) {
      caseId = `${baseId}-${suffix}`;
      suffix += 1;
    }
    usedIds.add(caseId);

    const defendants = normalizeListField(caseObj.defendants);
    const states = normalizeStateValues(caseObj);
    const documentType = normalizeDocumentTypes(caseObj);
    const originatingBody = String(caseObj.originating_body || "").trim();
    const importance = String(caseObj.importance || "").trim();
    const separateOpinion = parseBoolLike(caseObj.separate_opinion);
    const keywords = normalizeListField(caseObj.keywords);
    const violation = normalizeListField(caseObj.violation);
    const nonViolation = normalizeListField(caseObj["non-violation"]);
    const chamberComposedOf = normalizeListField(caseObj.chamber_composed_of);
    const strasbourgCaselaw = normalizeListField(caseObj.strasbourg_caselaw);
    const representedBy = String(caseObj.represented_by || "").trim();
    const ecli = String(caseObj.ecli || "").trim();
    const hudocUrl = String(caseObj.hudoc_url || "").trim();
    const chamberCategory = deriveChamberCategory(documentType, originatingBody);

    const rawParagraphs = Array.isArray(caseObj.paragraphs) ? caseObj.paragraphs : [];
    const parsedParagraphs = [];

    for (let p = 0; p < rawParagraphs.length; p += 1) {
      const para = rawParagraphs[p] || {};
      const section = normalizeSectionKey(para.section || "unknown");
      const text = String(para.text || "").trim();
      if (!text || section === "header") continue;

      const idx = Number(para.para_idx);
      const paraIdx = Number.isFinite(idx) ? idx : p;

      parsedParagraphs.push({
        section,
        paraIdx,
        localIdx: parsedParagraphs.length,
        text,
        textLower: text.toLowerCase(),
      });
    }

    const ts = parseDateInput(caseObj.judgment_date);

    normalized.push({
      ...caseObj,
      case_id: caseId,
      defendants,
      respondent_state: states[0] || "",
      represented_by: representedBy,
      document_type: documentType,
      originating_body: originatingBody,
      importance,
      separate_opinion: separateOpinion,
      keywords,
      violation,
      "non-violation": nonViolation,
      chamber_composed_of: chamberComposedOf,
      strasbourg_caselaw: strasbourgCaselaw,
      ecli,
      hudoc_url: hudocUrl,
      __articles: splitArticles(caseObj.article_no),
      __states: states,
      __originatingBody: originatingBody || "Unknown",
      __importance: importance || "Unspecified",
      __outcomeBucket: deriveOutcomeBucket(violation, nonViolation),
      __hasSeparateOpinion: separateOpinion,
      __hasStrasbourgCaselaw: strasbourgCaselaw.length > 0,
      __hasDomesticLaw: isPresentValue(caseObj.domestic_law),
      __hasInternationalLaw: isPresentValue(caseObj.international_law),
      __hasRulesOfCourt: isPresentValue(caseObj.rules_of_court),
      __keywordsNorm: keywords.map((k) => k.toLowerCase()),
      __keywordsText: keywords.join(" ").toLowerCase(),
      __chamberCategory: chamberCategory,
      __judgmentDateTs: ts,
      __sortTs: ts == null ? -Infinity : ts,
      __paragraphs: parsedParagraphs,
    });
  }

  return normalized;
}

function computeSimpleHash(text) {
  let hash = 5381;
  for (let i = 0; i < text.length; i += 1) {
    hash = ((hash << 5) + hash) ^ text.charCodeAt(i);
  }
  return (hash >>> 0).toString(36);
}

function computeDatasetKey(cases) {
  const head = cases.slice(0, 8);
  const tail = cases.slice(-8);
  const sig = [
    `cases:${cases.length}`,
    `head:${head.map((c) => `${c.case_id}|${c.__paragraphs.length}|${c.judgment_date || ""}`).join("~")}`,
    `tail:${tail.map((c) => `${c.case_id}|${c.__paragraphs.length}|${c.judgment_date || ""}`).join("~")}`,
  ].join("|");
  return computeSimpleHash(sig);
}

function preprocessDataset(cases) {
  const articles = new Set();
  const countries = new Set();
  const sections = new Set();
  const bodies = new Set();
  const importanceLevels = new Set();

  state.cases = cases;
  state.caseById = new Map();
  state.paragraphIndex = [];
  state.paragraphByKey = new Map();
  state.datasetKey = computeDatasetKey(cases);

  for (let caseIdx = 0; caseIdx < cases.length; caseIdx += 1) {
    const c = cases[caseIdx];
    state.caseById.set(c.case_id, c);

    for (const a of c.__articles) {
      articles.add(a);
    }
    for (const d of c.__states) {
      countries.add(d);
    }
    bodies.add(c.__originatingBody);
    importanceLevels.add(c.__importance);

    for (const para of c.__paragraphs) {
      sections.add(para.section);
      const paraKey = `${c.case_id}::${para.localIdx}`;
      para.key = paraKey;

      state.paragraphIndex.push({
        caseIdx,
        caseId: c.case_id,
        key: paraKey,
        section: para.section,
        paraIdx: para.paraIdx,
        text: para.text,
        textLower: para.textLower,
      });

      state.paragraphByKey.set(paraKey, {
        caseObj: c,
        caseId: c.case_id,
        caseTitle: c.title || "Untitled case",
        caseDate: c.judgment_date || "-",
        section: para.section,
        paraIdx: para.paraIdx,
        text: para.text,
        textLower: para.textLower,
      });
    }
  }

  state.sortedCaseIdsByDate = [...cases]
    .sort((a, b) => {
      if (b.__sortTs !== a.__sortTs) {
        return b.__sortTs - a.__sortTs;
      }
      return String(b.case_id).localeCompare(String(a.case_id));
    })
    .map((c) => c.case_id);

  state.articles = [...articles].sort((a, b) => (a.length - b.length) || a.localeCompare(b));
  state.countries = [...countries].sort((a, b) => (COUNTRY_NAMES[a] || a).localeCompare(COUNTRY_NAMES[b] || b));
  state.bodies = [...bodies].sort((a, b) => a.localeCompare(b));
  state.importanceLevels = [...importanceLevels].sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
  state.sectionsInDataset = [...sections].sort((a, b) => {
    const ai = SECTION_ORDER.indexOf(a);
    const bi = SECTION_ORDER.indexOf(b);
    if (ai !== -1 && bi !== -1) return ai - bi;
    if (ai !== -1) return -1;
    if (bi !== -1) return 1;
    return a.localeCompare(b);
  });
  state.loaded = true;
}

function makeCheckbox(label, value, name) {
  return `<label class="cb-label"><input type="checkbox" data-name="${name}" value="${escapeHtml(value)}"> <span>${escapeHtml(label)}</span></label>`;
}

function renderFilters() {
  el.sectionsFilters.innerHTML = state.sectionsInDataset
    .map((sec) => makeCheckbox(SECTION_LABELS[sec] || sec, sec, "sections"))
    .join("");

  el.countriesFilters.innerHTML = state.countries
    .map((code) => makeCheckbox(COUNTRY_NAMES[code] || code, code, "countries"))
    .join("");

  el.articlesFilters.innerHTML = state.articles
    .map((article) => makeCheckbox(`Art. ${article}`, article, "articles"))
    .join("");

  el.originatingBodyFilters.innerHTML = state.bodies
    .map((body) => makeCheckbox(body, body, "bodies"))
    .join("");

  el.importanceFilters.innerHTML = state.importanceLevels
    .map((level) => makeCheckbox(level, level, "importance"))
    .join("");

  el.outcomeFilters.innerHTML = [
    makeCheckbox("Violation only", "violation_only", "outcomes"),
    makeCheckbox("Non-violation only", "non_violation_only", "outcomes"),
    makeCheckbox("Both", "both", "outcomes"),
    makeCheckbox("Neither", "neither", "outcomes"),
  ].join("");

  el.separateOpinionFilters.innerHTML = [
    makeCheckbox("Yes", "yes", "separateOpinion"),
    makeCheckbox("No", "no", "separateOpinion"),
  ].join("");
}

function renderGlobalStats() {
  const dates = state.cases
    .map((c) => c.__judgmentDateTs)
    .filter((x) => Number.isFinite(x))
    .sort((a, b) => a - b);

  let dateRange = "n/a";
  if (dates.length) {
    const first = new Date(dates[0]).toISOString().slice(0, 10);
    const last = new Date(dates[dates.length - 1]).toISOString().slice(0, 10);
    dateRange = `${first} to ${last}`;
  }

  el.statTotalCases.textContent = fmtInt.format(state.cases.length);
  el.statTotalParagraphs.textContent = fmtInt.format(state.paragraphIndex.length);
  el.statTotalCountries.textContent = fmtInt.format(state.countries.length);
  el.statDateRange.textContent = dateRange;
}

function collectChecked(name) {
  return new Set(
    [...document.querySelectorAll(`input[data-name="${name}"]:checked`)].map((input) => input.value)
  );
}

function collectCheckedValuesIn(container) {
  return new Set(
    [...container.querySelectorAll("input[type='checkbox']:checked")].map((input) => input.value)
  );
}

function getCurrentFilters() {
  return {
    sections: collectChecked("sections"),
    countries: collectChecked("countries"),
    articles: collectChecked("articles"),
    bodies: collectChecked("bodies"),
    importance: collectChecked("importance"),
    outcomes: collectChecked("outcomes"),
    separateOpinion: collectChecked("separateOpinion"),
    presence: collectChecked("presence"),
    caseTypes: collectCheckedValuesIn(el.chamberFilters),
    keyword: String(el.keywordFilterInput.value || "").trim().toLowerCase(),
    dateFrom: parseDateInput(el.dateFrom.value),
    dateTo: parseDateInput(el.dateTo.value),
  };
}

function passesCaseFilters(c, filters) {
  if (filters.articles.size) {
    let ok = false;
    for (const a of c.__articles) {
      if (filters.articles.has(a)) {
        ok = true;
        break;
      }
    }
    if (!ok) return false;
  }

  if (filters.countries.size) {
    let ok = false;
    for (const d of c.__states) {
      if (filters.countries.has(d)) {
        ok = true;
        break;
      }
    }
    if (!ok) return false;
  }

  if (filters.caseTypes.size) {
    if (!filters.caseTypes.has(c.__chamberCategory)) return false;
  }

  if (filters.bodies.size && !filters.bodies.has(c.__originatingBody)) {
    return false;
  }

  if (filters.importance.size && !filters.importance.has(c.__importance)) {
    return false;
  }

  if (filters.outcomes.size && !filters.outcomes.has(c.__outcomeBucket)) {
    return false;
  }

  if (filters.separateOpinion.size) {
    const key = c.__hasSeparateOpinion ? "yes" : "no";
    if (!filters.separateOpinion.has(key)) return false;
  }

  if (filters.presence.has("has_strasbourg_caselaw") && !c.__hasStrasbourgCaselaw) {
    return false;
  }
  if (filters.presence.has("has_domestic_law") && !c.__hasDomesticLaw) {
    return false;
  }
  if (filters.presence.has("has_international_law") && !c.__hasInternationalLaw) {
    return false;
  }
  if (filters.presence.has("has_rules_of_court") && !c.__hasRulesOfCourt) {
    return false;
  }

  if (filters.keyword && !c.__keywordsText.includes(filters.keyword)) {
    return false;
  }

  if (filters.dateFrom != null && (c.__judgmentDateTs == null || c.__judgmentDateTs < filters.dateFrom)) {
    return false;
  }

  if (filters.dateTo != null && (c.__judgmentDateTs == null || c.__judgmentDateTs > filters.dateTo)) {
    return false;
  }

  return true;
}

function buildParagraphResult(para, terms) {
  return {
    key: para.key || "",
    section: para.section,
    sectionLabel: SECTION_LABELS[para.section] || para.section,
    sectionColor: SECTION_COLORS[para.section] || "#718096",
    paraIdx: para.paraIdx,
    rawText: para.text,
    textHtml: terms.length ? highlightTerms(para.text, terms) : escapeHtml(para.text),
  };
}

function buildBrowseResults(filters) {
  const resultsById = new Map();
  const orderedCaseIds = [];
  let totalHits = 0;

  for (const caseId of state.sortedCaseIdsByDate) {
    const c = state.caseById.get(caseId);
    if (!c) continue;
    if (!passesCaseFilters(c, filters)) continue;

    const selectedParagraphs = [];
    for (const para of c.__paragraphs) {
      if (filters.sections.size && !filters.sections.has(para.section)) {
        continue;
      }
      selectedParagraphs.push(buildParagraphResult(para, []));
    }

    if (filters.sections.size && selectedParagraphs.length === 0) {
      continue;
    }

    resultsById.set(caseId, {
      case: c,
      paragraphs: selectedParagraphs,
      hitCount: selectedParagraphs.length,
    });

    orderedCaseIds.push(caseId);
    totalHits += selectedParagraphs.length;
  }

  return {
    mode: "browse",
    orderedCaseIds,
    resultsById,
    totalHits,
    terms: [],
    limited: false,
  };
}

function buildQueryResults(query, filters) {
  const parsed = parseQuery(query);
  const allTerms = [...parsed.andTerms, ...parsed.orGroups.flat()];

  const resultsById = new Map();
  let totalHits = 0;
  let limited = false;

  for (const entry of state.paragraphIndex) {
    if (filters.sections.size && !filters.sections.has(entry.section)) {
      continue;
    }

    const c = state.cases[entry.caseIdx];
    if (!passesCaseFilters(c, filters)) {
      continue;
    }

    let andOk = true;
    for (const term of parsed.andTerms) {
      if (!entry.textLower.includes(term)) {
        andOk = false;
        break;
      }
    }
    if (!andOk) continue;

    let orOk = true;
    for (const group of parsed.orGroups) {
      let groupOk = false;
      for (const term of group) {
        if (entry.textLower.includes(term)) {
          groupOk = true;
          break;
        }
      }
      if (!groupOk) {
        orOk = false;
        break;
      }
    }
    if (!orOk) continue;

    if (!resultsById.has(c.case_id)) {
      resultsById.set(c.case_id, {
        case: c,
        paragraphs: [],
        hitCount: 0,
      });
    }

    const row = resultsById.get(c.case_id);
    row.paragraphs.push(
      buildParagraphResult(
        {
          key: entry.key,
          section: entry.section,
          paraIdx: entry.paraIdx,
          text: entry.text,
        },
        allTerms
      )
    );
    row.hitCount += 1;

    totalHits += 1;
    if (totalHits >= MAX_HITS) {
      limited = true;
      break;
    }
  }

  const orderedCaseIds = [...resultsById.entries()]
    .sort((a, b) => {
      if (b[1].hitCount !== a[1].hitCount) {
        return b[1].hitCount - a[1].hitCount;
      }
      return b[1].case.__sortTs - a[1].case.__sortTs;
    })
    .map((x) => x[0]);

  return {
    mode: "search",
    orderedCaseIds,
    resultsById,
    totalHits,
    terms: allTerms,
    limited,
  };
}

function renderActiveFilters(filters) {
  const chips = [];

  for (const s of filters.sections) {
    chips.push(`<span class="filter-chip">${escapeHtml(SECTION_LABELS[s] || s)}</span>`);
  }
  for (const a of filters.articles) {
    chips.push(`<span class="filter-chip">Art. ${escapeHtml(a)}</span>`);
  }
  for (const c of filters.countries) {
    chips.push(`<span class="filter-chip">${escapeHtml(COUNTRY_NAMES[c] || c)}</span>`);
  }
  for (const body of filters.bodies) {
    chips.push(`<span class="filter-chip">${escapeHtml(body)}</span>`);
  }
  for (const level of filters.importance) {
    chips.push(`<span class="filter-chip">Importance: ${escapeHtml(level)}</span>`);
  }
  for (const outcome of filters.outcomes) {
    const label = {
      violation_only: "Violation only",
      non_violation_only: "Non-violation only",
      both: "Both",
      neither: "Neither",
    }[outcome] || outcome;
    chips.push(`<span class="filter-chip">${escapeHtml(label)}</span>`);
  }
  for (const value of filters.separateOpinion) {
    chips.push(`<span class="filter-chip">Separate opinion: ${value === "yes" ? "Yes" : "No"}</span>`);
  }
  for (const key of filters.presence) {
    const label = {
      has_strasbourg_caselaw: "Has Strasbourg citations",
      has_domestic_law: "Has domestic law",
      has_international_law: "Has international law",
      has_rules_of_court: "Has rules of court",
    }[key] || key;
    chips.push(`<span class="filter-chip">${escapeHtml(label)}</span>`);
  }
  for (const t of filters.caseTypes) {
    const label = t === "GRANDCHAMBER" ? "Grand Chamber" : (t === "CHAMBER" ? "Chamber" : "Other");
    chips.push(`<span class="filter-chip">${escapeHtml(label)}</span>`);
  }
  if (filters.keyword) {
    chips.push(`<span class="filter-chip">Keyword: ${escapeHtml(filters.keyword)}</span>`);
  }
  if (el.dateFrom.value) {
    chips.push(`<span class="filter-chip">From: ${escapeHtml(el.dateFrom.value)}</span>`);
  }
  if (el.dateTo.value) {
    chips.push(`<span class="filter-chip">To: ${escapeHtml(el.dateTo.value)}</span>`);
  }

  el.activeFilters.innerHTML = chips.join("");
}

function getParagraphAssignment(paraKey) {
  if (!paraKey || !state.classifier) return null;
  return state.classifier.assignments.get(paraKey) || null;
}

function getCombinedParagraphLabels(paraKey) {
  const assignment = getParagraphAssignment(paraKey);
  if (!assignment) return [];
  if (assignment.excluded) return [];

  const labels = [];
  for (const label of assignment.manual) {
    labels.push({ label, kind: "manual" });
  }
  for (const label of assignment.predicted) {
    if (!assignment.manual.has(label)) {
      labels.push({ label, kind: "predicted" });
    }
  }
  return labels;
}

function buildParagraphLabelBadgesHtml(paraKey) {
  const labels = getCombinedParagraphLabels(paraKey);
  if (!labels.length) return "";
  return `
    <span class="para-label-badges">
      ${labels.map((item) => `<span class="para-label-chip ${item.kind}">${escapeHtml(item.label)}</span>`).join("")}
    </span>
  `;
}

function getClassifierStorageKey() {
  if (!state.datasetKey) return "";
  return `${CLASSIFIER_STORAGE_PREFIX}${state.datasetKey}`;
}

function normalizeClassifierLabel(rawLabel) {
  return String(rawLabel || "").trim().replace(/\s+/g, " ");
}

function classifierLabelKey(rawLabel) {
  return normalizeClassifierLabel(rawLabel).toLowerCase();
}

function sanitizeClassifierThreshold(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return CLASSIFIER_DEFAULT_THRESHOLD;
  }
  return Math.max(0.05, Math.min(0.8, numeric));
}

function createClassifierAssignment(manual = [], predicted = [], excluded = false) {
  return {
    manual: new Set(manual),
    predicted: new Set(predicted),
    excluded: !!excluded,
  };
}

function setsEqual(a, b) {
  if (a.size !== b.size) return false;
  for (const item of a) {
    if (!b.has(item)) return false;
  }
  return true;
}

function getInitialClassifierSections() {
  const preferred = ["merits", "admissibility"];
  const selected = preferred.filter((sec) => state.sectionsInDataset.includes(sec));
  if (selected.length) {
    return new Set(selected);
  }
  return new Set(state.sectionsInDataset);
}

function createDefaultClassifierState() {
  const classifier = createEmptyClassifierState();
  const defaults = getInitialClassifierSections();
  classifier.trainingSections = new Set(defaults);
  classifier.predictionSections = new Set(defaults);
  return classifier;
}

function sanitizeModelVector(rawVector) {
  const clean = {};
  if (!rawVector || typeof rawVector !== "object") return clean;

  for (const [token, value] of Object.entries(rawVector)) {
    const numeric = Number(value);
    if (!token || !Number.isFinite(numeric)) continue;
    clean[token] = numeric;
  }

  return clean;
}

function sanitizeClassifierModel(rawModel, validLabelsSet) {
  if (!rawModel || typeof rawModel !== "object") return null;
  const method = typeof rawModel.method === "string" && CLASSIFIER_METHODS[rawModel.method]
    ? rawModel.method
    : "tfidf_centroid";

  const trainingSize = Number(rawModel.trainingSize);
  if (method === "keyword_overlap") {
    const profiles = rawModel.keywordProfiles && typeof rawModel.keywordProfiles === "object"
      ? rawModel.keywordProfiles
      : {};
    const sanitizedProfiles = {};
    for (const [label, profile] of Object.entries(profiles)) {
      if (validLabelsSet.size && !validLabelsSet.has(label)) continue;
      const weights = profile?.weights && typeof profile.weights === "object" ? profile.weights : {};
      const totalWeight = Number(profile?.totalWeight) || 0;
      if (!Object.keys(weights).length || !totalWeight) continue;
      sanitizedProfiles[label] = { weights, totalWeight };
    }
    if (!Object.keys(sanitizedProfiles).length) return null;
    return {
      type: String(rawModel.type || "keyword-overlap-v1"),
      method,
      trainedAt: String(rawModel.trainedAt || new Date().toISOString()),
      trainingSize: Number.isFinite(trainingSize) && trainingSize > 0 ? trainingSize : 0,
      keywordProfiles: sanitizedProfiles,
    };
  }

  const idf = sanitizeModelVector(rawModel.idf);
  const centroids = {};
  const sourceCentroids = rawModel.centroids && typeof rawModel.centroids === "object"
    ? rawModel.centroids
    : {};

  for (const [label, vector] of Object.entries(sourceCentroids)) {
    if (validLabelsSet.size && !validLabelsSet.has(label)) continue;
    const cleanVector = sanitizeModelVector(vector);
    if (!Object.keys(cleanVector).length) continue;
    centroids[label] = cleanVector;
  }

  if (!Object.keys(centroids).length) return null;

  const labelCounts = {};
  if (rawModel.labelCounts && typeof rawModel.labelCounts === "object") {
    for (const [label, count] of Object.entries(rawModel.labelCounts)) {
      if (!centroids[label]) continue;
      const numeric = Number(count);
      if (!Number.isFinite(numeric) || numeric <= 0) continue;
      labelCounts[label] = numeric;
    }
  }

  return {
    type: String(rawModel.type || "tfidf-centroid-v1"),
    method,
    trainedAt: String(rawModel.trainedAt || new Date().toISOString()),
    trainingSize: Number.isFinite(trainingSize) && trainingSize > 0 ? trainingSize : 0,
    idf,
    centroids,
    labelCounts,
  };
}

function normalizeRawAssignmentRows(rawAssignments) {
  if (Array.isArray(rawAssignments)) {
    return rawAssignments;
  }
  if (rawAssignments && typeof rawAssignments === "object") {
    return Object.entries(rawAssignments).map(([key, value]) => ({
      key,
      ...(value && typeof value === "object" ? value : {}),
    }));
  }
  return [];
}

function hydrateClassifierPayload(payload, loadedFromStorage = false) {
  const classifier = createDefaultClassifierState();

  if (!payload || typeof payload !== "object") {
    classifier.loadedFromStorage = loadedFromStorage;
    return classifier;
  }

  const labels = [];
  const labelKeys = new Set();
  const pushLabel = (candidate) => {
    const normalized = normalizeClassifierLabel(candidate);
    if (!normalized) return;
    const key = classifierLabelKey(normalized);
    if (labelKeys.has(key)) return;
    labelKeys.add(key);
    labels.push(normalized);
  };

  if (Array.isArray(payload.labels)) {
    for (const label of payload.labels) {
      pushLabel(label);
    }
  }

  const rawAssignments = normalizeRawAssignmentRows(payload.assignments);
  for (const row of rawAssignments) {
    if (!row || typeof row !== "object") continue;
    if (Array.isArray(row.manual)) {
      for (const label of row.manual) {
        pushLabel(label);
      }
    }
    if (Array.isArray(row.predicted)) {
      for (const label of row.predicted) {
        pushLabel(label);
      }
    }
  }

  classifier.labels = labels;
  const validLabelsSet = new Set(classifier.labels);
  const validSectionsSet = new Set(state.sectionsInDataset);

  if (Array.isArray(payload.trainingSections)) {
    const selected = payload.trainingSections.filter((sec) => validSectionsSet.has(sec));
    classifier.trainingSections = selected.length ? new Set(selected) : getInitialClassifierSections();
  }

  if (Array.isArray(payload.predictionSections)) {
    const selected = payload.predictionSections.filter((sec) => validSectionsSet.has(sec));
    classifier.predictionSections = selected.length ? new Set(selected) : new Set(classifier.trainingSections);
  }

  const method = typeof payload.method === "string" && CLASSIFIER_METHODS[payload.method]
    ? payload.method
    : "tfidf_centroid";
  classifier.method = method;
  classifier.threshold = sanitizeClassifierThreshold(
    Number.isFinite(Number(payload.threshold))
      ? payload.threshold
      : (CLASSIFIER_METHODS[method]?.defaultThreshold ?? CLASSIFIER_DEFAULT_THRESHOLD)
  );
  classifier.model = sanitizeClassifierModel(payload.model, validLabelsSet);
  classifier.modelInfo = typeof payload.modelInfo === "string" ? payload.modelInfo : "";
  classifier.lastSavedAt = typeof payload.savedAt === "string" ? payload.savedAt : null;
  classifier.loadedFromStorage = loadedFromStorage;

  const assignments = new Map();
  for (const row of rawAssignments) {
    if (!row || typeof row !== "object") continue;
    const paraKey = String(row.key || "");
    if (!paraKey || !state.paragraphByKey.has(paraKey)) continue;

    const manual = Array.isArray(row.manual)
      ? row.manual.map((x) => normalizeClassifierLabel(x)).filter((label) => validLabelsSet.has(label))
      : [];
    const predicted = Array.isArray(row.predicted)
      ? row.predicted.map((x) => normalizeClassifierLabel(x)).filter((label) => validLabelsSet.has(label))
      : [];
    const excluded = !!row.excluded;

    if (!manual.length && !predicted.length && !excluded) continue;
    assignments.set(paraKey, createClassifierAssignment(manual, predicted, excluded));
  }
  classifier.assignments = assignments;

  const rawSampleKeys = Array.isArray(payload.sampleKeys) ? payload.sampleKeys : [];
  const sampleKeys = [];
  for (const key of rawSampleKeys) {
    const paraKey = String(key || "");
    if (!state.paragraphByKey.has(paraKey)) continue;
    const para = state.paragraphByKey.get(paraKey);
    if (!classifier.trainingSections.has(para.section)) continue;
    if (!sampleKeys.includes(paraKey)) {
      sampleKeys.push(paraKey);
    }
  }
  classifier.sampleKeys = sampleKeys;

  const rawCursor = Number(payload.sampleCursor);
  if (classifier.sampleKeys.length) {
    const maxCursor = classifier.sampleKeys.length - 1;
    classifier.sampleCursor = Number.isFinite(rawCursor)
      ? Math.max(0, Math.min(maxCursor, Math.floor(rawCursor)))
      : 0;
  } else {
    classifier.sampleCursor = 0;
  }

  return classifier;
}

function serializeClassifierState() {
  if (!state.classifier) return null;
  const classifier = state.classifier;
  const assignments = [];

  for (const [key, assignment] of classifier.assignments.entries()) {
    const manual = [...assignment.manual];
    const predicted = [...assignment.predicted];
    const excluded = !!assignment.excluded;
    if (!manual.length && !predicted.length && !excluded) continue;
    assignments.push({ key, manual, predicted, excluded });
  }

  return {
    version: 1,
    datasetKey: state.datasetKey,
    sourceLabel: state.sourceLabel,
    labels: [...classifier.labels],
    trainingSections: [...classifier.trainingSections],
    predictionSections: [...classifier.predictionSections],
    sampleKeys: [...classifier.sampleKeys],
    sampleCursor: classifier.sampleCursor,
    method: classifier.method,
    threshold: classifier.threshold,
    model: classifier.model,
    modelInfo: classifier.modelInfo,
    assignments,
    savedAt: new Date().toISOString(),
  };
}

function formatClassifierTimestamp(isoDate) {
  if (!isoDate) return "";
  const dt = new Date(isoDate);
  if (!Number.isFinite(dt.getTime())) return "";
  return dt.toLocaleString("en-US", { dateStyle: "medium", timeStyle: "short" });
}

function countClassifierManualAssignments() {
  if (!state.classifier) return 0;
  let total = 0;
  for (const assignment of state.classifier.assignments.values()) {
    if (assignment.excluded) continue;
    if (assignment.manual.size) total += 1;
  }
  return total;
}

function countClassifierPredictedAssignments() {
  if (!state.classifier) return 0;
  let total = 0;
  for (const assignment of state.classifier.assignments.values()) {
    if (assignment.excluded) continue;
    if (assignment.predicted.size) total += 1;
  }
  return total;
}

function countClassifierManualAssignmentsInSections(sectionSet) {
  if (!state.classifier) return 0;
  let total = 0;
  for (const [key, assignment] of state.classifier.assignments.entries()) {
    if (assignment.excluded) continue;
    if (!assignment.manual.size) continue;
    const paragraph = state.paragraphByKey.get(key);
    if (!paragraph) continue;
    if (!sectionSet.has(paragraph.section)) continue;
    total += 1;
  }
  return total;
}

function countClassifierExcludedAssignments() {
  if (!state.classifier) return 0;
  let total = 0;
  for (const assignment of state.classifier.assignments.values()) {
    if (assignment.excluded) total += 1;
  }
  return total;
}

function setClassifierPersistStatus(message) {
  el.classifierPersistStatus.textContent = message;
}

function setClassifierModelStatus(message) {
  el.classifierModelStatus.textContent = message;
}

function updateClassifierResumeNote() {
  if (!state.loaded || !state.classifier) {
    el.classifierResumeNote.classList.add("hidden");
    return;
  }

  const manualCount = countClassifierManualAssignments();
  const predictedCount = countClassifierPredictedAssignments();
  const excludedCount = countClassifierExcludedAssignments();
  const source = state.classifier.loadedFromStorage ? "resumed from browser storage" : "new session";
  const savedAt = formatClassifierTimestamp(state.classifier.lastSavedAt);
  const timePart = savedAt ? ` · last saved ${savedAt}` : "";

  el.classifierResumeNote.textContent =
    `Classifier progress: ${fmtInt.format(manualCount)} manual, ${fmtInt.format(predictedCount)} model-tagged, ${fmtInt.format(excludedCount)} excluded paragraphs (${source}${timePart}).`;
  el.classifierResumeNote.classList.remove("hidden");
}

function saveClassifierState(statusMessage = "") {
  if (!state.classifier || !state.datasetKey) return;
  const storageKey = getClassifierStorageKey();
  if (!storageKey) return;

  const payload = serializeClassifierState();
  if (!payload) return;

  try {
    localStorage.setItem(storageKey, JSON.stringify(payload));
    state.classifier.lastSavedAt = payload.savedAt;

    if (statusMessage) {
      const savedAt = formatClassifierTimestamp(payload.savedAt);
      setClassifierPersistStatus(`${statusMessage} Saved locally${savedAt ? ` (${savedAt})` : ""}.`);
    }
  } catch (err) {
    setClassifierPersistStatus(`Could not save classifier progress: ${err.message}`);
  }

  updateClassifierResumeNote();
}

function removeClassifierSavedState() {
  const storageKey = getClassifierStorageKey();
  if (!storageKey) return;
  try {
    localStorage.removeItem(storageKey);
  } catch {
    // Ignore storage errors.
  }
}

function pruneClassifierSampleKeysToTrainingSections() {
  if (!state.classifier) return;
  const classifier = state.classifier;

  classifier.sampleKeys = classifier.sampleKeys.filter((key) => {
    const paragraph = state.paragraphByKey.get(key);
    return paragraph && classifier.trainingSections.has(paragraph.section);
  });

  if (!classifier.sampleKeys.length) {
    classifier.sampleCursor = 0;
    return;
  }

  classifier.sampleCursor = Math.max(0, Math.min(classifier.sampleCursor, classifier.sampleKeys.length - 1));
}

function cleanupEmptyClassifierAssignment(paraKey) {
  if (!state.classifier) return;
  const assignment = state.classifier.assignments.get(paraKey);
  if (!assignment) return;
  if (!assignment.manual.size && !assignment.predicted.size && !assignment.excluded) {
    state.classifier.assignments.delete(paraKey);
  }
}

function markClassifierModelOutdated(reason) {
  if (!state.classifier) return;
  if (state.classifier.model) {
    state.classifier.model = null;
  }
  state.classifier.modelInfo = reason;
  setClassifierModelStatus(reason);
}

function renderClassifierLabels() {
  if (!state.classifier) {
    el.classifierLabelsList.innerHTML = "";
    return;
  }

  if (!state.classifier.labels.length) {
    el.classifierLabelsList.innerHTML = '<p class="classifier-empty">No labels yet.</p>';
    return;
  }

  el.classifierLabelsList.innerHTML = state.classifier.labels
    .map((label) => `
      <span class="classifier-chip">
        ${escapeHtml(label)}
        <button type="button" data-action="remove-label" data-label="${escapeHtml(label)}" aria-label="Remove label">×</button>
      </span>
    `)
    .join("");
}

function renderClassifierSectionGrid(container, kind, selectedSections) {
  if (!state.sectionsInDataset.length) {
    container.innerHTML = '<p class="classifier-empty">No sections available in this dataset.</p>';
    return;
  }

  container.innerHTML = state.sectionsInDataset
    .map((section) => {
      const checked = selectedSections.has(section) ? "checked" : "";
      return `
        <label>
          <input type="checkbox" data-kind="${escapeHtml(kind)}" value="${escapeHtml(section)}" ${checked}>
          <span>${escapeHtml(SECTION_LABELS[section] || section)}</span>
        </label>
      `;
    })
    .join("");
}

function renderClassifierSampleCard() {
  if (!state.classifier) return;
  const classifier = state.classifier;

  if (!classifier.sampleKeys.length) {
    el.classifierSampleCard.classList.remove("excluded");
    el.classifierSampleCounter.textContent = "No sample loaded";
    el.classifierSampleCard.innerHTML = classifier.trainingSections.size
      ? '<p class="classifier-empty">Generate sample first.</p>'
      : '<p class="classifier-empty">Select at least one section to generate a sample.</p>';
    el.classifierPrevSampleBtn.disabled = true;
    el.classifierNextSampleBtn.disabled = true;
    return;
  }

  const currentKey = classifier.sampleKeys[classifier.sampleCursor];
  const paragraph = state.paragraphByKey.get(currentKey);
  if (!paragraph) {
    el.classifierSampleCard.classList.remove("excluded");
    el.classifierSampleCounter.textContent = "Sample item unavailable";
    el.classifierSampleCard.innerHTML = '<p class="classifier-empty">Current sample paragraph is no longer available.</p>';
    el.classifierPrevSampleBtn.disabled = true;
    el.classifierNextSampleBtn.disabled = true;
    return;
  }

  const assignment = classifier.assignments.get(currentKey) || createClassifierAssignment();
  const manual = [...assignment.manual];
  const predictedOnly = [...assignment.predicted].filter((label) => !assignment.manual.has(label));
  const isExcluded = !!assignment.excluded;
  const labeledInSample = classifier.sampleKeys.filter((key) => {
    const row = classifier.assignments.get(key);
    return !!(row && row.manual.size && !row.excluded);
  }).length;
  const excludedInSample = classifier.sampleKeys.filter((key) => {
    const row = classifier.assignments.get(key);
    return !!(row && row.excluded);
  }).length;

  el.classifierSampleCounter.textContent =
    `Sample ${classifier.sampleCursor + 1}/${classifier.sampleKeys.length} · manual ${labeledInSample}/${classifier.sampleKeys.length} · excluded ${excludedInSample}`;

  el.classifierSampleCard.classList.toggle("excluded", isExcluded);

  const labelButtons = classifier.labels.length
    ? classifier.labels
      .map((label) => {
        const active = assignment.manual.has(label) ? "active" : "";
        return `
          <button
            type="button"
            class="classifier-label-toggle ${active}"
            data-action="toggle-sample-label"
            data-label="${escapeHtml(label)}"
            aria-pressed="${assignment.manual.has(label) ? "true" : "false"}"
            ${isExcluded ? "disabled" : ""}>
            ${escapeHtml(label)}
          </button>
        `;
      })
      .join("")
    : '<p class="classifier-empty">Add labels first.</p>';

  const modelSuggestion = predictedOnly.length
    ? `<p class="classifier-help">Model suggestions: ${predictedOnly.map((label) => escapeHtml(label)).join(", ")}</p>`
    : "";
  const excludedNote = isExcluded
    ? '<p class="classifier-exclude-note">This paragraph is excluded from training.</p>'
    : "";

  el.classifierSampleCard.innerHTML = `
    <div class="classifier-sample-meta">
      <span><strong>${escapeHtml(SECTION_LABELS[paragraph.section] || paragraph.section)}</strong></span>
      <span>¶ ${paragraph.paraIdx + 1}</span>
      <span>${escapeHtml(paragraph.caseId)}</span>
    </div>
    <p class="classifier-sample-text">${escapeHtml(paragraph.text)}</p>
    ${excludedNote}
    ${modelSuggestion}
    <div class="classifier-sample-labels">
      ${labelButtons}
    </div>
    <div class="classifier-sample-actions">
      <button
        type="button"
        class="classifier-btn ${isExcluded ? "danger exclude-active" : "secondary"}"
        data-action="toggle-sample-excluded">
        ${isExcluded ? "Include In Training" : "Exclude From Training"}
      </button>
      <button
        type="button"
        class="classifier-btn secondary"
        data-action="clear-current-sample-labels"
        ${manual.length && !isExcluded ? "" : "disabled"}>
        Clear Manual Labels
      </button>
    </div>
  `;

  el.classifierPrevSampleBtn.disabled = classifier.sampleCursor <= 0;
  el.classifierNextSampleBtn.disabled = classifier.sampleCursor >= classifier.sampleKeys.length - 1;
}

function renderClassifierPanel() {
  if (!state.classifier) return;
  const classifier = state.classifier;

  renderClassifierLabels();
  renderClassifierSectionGrid(el.classifierTrainingSections, "training", classifier.trainingSections);
  renderClassifierSectionGrid(el.classifierPredictionSections, "prediction", classifier.predictionSections);
  renderClassifierSampleCard();

  const method = CLASSIFIER_METHODS[classifier.method] ? classifier.method : "tfidf_centroid";
  classifier.method = method;
  if (el.classifierMethodSelect) {
    el.classifierMethodSelect.value = method;
  }
  if (el.classifierMethodHint) {
    el.classifierMethodHint.textContent = CLASSIFIER_METHODS[method]?.hint || "";
  }

  classifier.threshold = sanitizeClassifierThreshold(classifier.threshold);
  el.classifierThresholdRange.value = classifier.threshold.toFixed(2);
  el.classifierThresholdValue.textContent = classifier.threshold.toFixed(2);

  if (classifier.model) {
    const labelsCount = Object.keys(classifier.model.centroids || {}).length;
    const message = classifier.modelInfo
      || `Model ready (${fmtInt.format(classifier.model.trainingSize || 0)} training paragraphs, ${fmtInt.format(labelsCount)} labels).`;
    setClassifierModelStatus(message);
  } else if (classifier.modelInfo) {
    setClassifierModelStatus(classifier.modelInfo);
  } else {
    setClassifierModelStatus("Model not trained yet.");
  }

  const manualCount = countClassifierManualAssignmentsInSections(classifier.trainingSections);
  el.refreshClassifierSampleBtn.disabled = !classifier.trainingSections.size;
  el.trainClassifierBtn.disabled =
    !classifier.trainingSections.size
    || !classifier.labels.length
    || manualCount < CLASSIFIER_MIN_LABELED_PARAGRAPHS;
  el.applyClassifierModelBtn.disabled = !classifier.model || !classifier.predictionSections.size;
}

function openClassifierPane() {
  if (!state.loaded || !state.classifier) return;
  state.classifierOpen = true;
  el.classifierBackdrop.hidden = false;
  el.classifierPane.classList.add("open");
  renderClassifierPanel();
}

function closeClassifierPane() {
  state.classifierOpen = false;
  el.classifierBackdrop.hidden = true;
  el.classifierPane.classList.remove("open");
}

function getSampleParagraphKeysFromSections(sectionSet) {
  const candidateKeys = [];

  for (const row of state.paragraphIndex) {
    if (sectionSet.size && !sectionSet.has(row.section)) {
      continue;
    }
    candidateKeys.push(row.key);
  }

  return candidateKeys;
}

function shuffleArray(values) {
  const arr = [...values];
  for (let i = arr.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
  return arr;
}

function regenerateClassifierSample() {
  if (!state.classifier) return;
  const classifier = state.classifier;

  if (!classifier.trainingSections.size) {
    setClassifierPersistStatus("Select at least one section for training sample.");
    renderClassifierPanel();
    return;
  }

  const allKeys = getSampleParagraphKeysFromSections(classifier.trainingSections);
  if (!allKeys.length) {
    classifier.sampleKeys = [];
    classifier.sampleCursor = 0;
    setClassifierPersistStatus("No paragraphs available in selected training sections.");
    renderClassifierPanel();
    saveClassifierState();
    return;
  }

  const unlabeled = [];
  const labeled = [];
  for (const key of allKeys) {
    const assignment = classifier.assignments.get(key);
    if (assignment && (assignment.manual.size || assignment.excluded)) {
      labeled.push(key);
    } else {
      unlabeled.push(key);
    }
  }

  const prioritized = [...shuffleArray(unlabeled), ...shuffleArray(labeled)];
  const sampleSize = Math.min(CLASSIFIER_SAMPLE_SIZE, prioritized.length);
  classifier.sampleKeys = prioritized.slice(0, sampleSize);
  classifier.sampleCursor = 0;

  renderClassifierPanel();
  saveClassifierState(`Sample refreshed (${fmtInt.format(sampleSize)} paragraphs).`);
}

function moveClassifierSample(delta) {
  if (!state.classifier || !state.classifier.sampleKeys.length) return;
  const classifier = state.classifier;
  const maxCursor = classifier.sampleKeys.length - 1;
  classifier.sampleCursor = Math.max(0, Math.min(maxCursor, classifier.sampleCursor + delta));
  renderClassifierSampleCard();
  saveClassifierState();
}

function toggleCurrentSampleLabel(label) {
  if (!state.classifier) return;
  const classifier = state.classifier;
  const normalizedLabel = normalizeClassifierLabel(label);
  if (!normalizedLabel || !classifier.labels.includes(normalizedLabel)) return;

  const sampleKey = classifier.sampleKeys[classifier.sampleCursor];
  if (!sampleKey) return;

  const assignment = classifier.assignments.get(sampleKey) || createClassifierAssignment();
  if (assignment.excluded) {
    assignment.excluded = false;
  }
  if (assignment.manual.has(normalizedLabel)) {
    assignment.manual.delete(normalizedLabel);
  } else {
    assignment.manual.add(normalizedLabel);
  }

  classifier.assignments.set(sampleKey, assignment);
  cleanupEmptyClassifierAssignment(sampleKey);
  markClassifierModelOutdated("Labels changed. Train model again to refresh predictions.");

  renderClassifierPanel();
  renderResultsPage();
  saveClassifierState("Updated manual labels.");
}

function clearCurrentSampleManualLabels() {
  if (!state.classifier) return;
  const classifier = state.classifier;
  const sampleKey = classifier.sampleKeys[classifier.sampleCursor];
  if (!sampleKey) return;

  const assignment = classifier.assignments.get(sampleKey);
  if (!assignment || !assignment.manual.size) return;

  assignment.manual.clear();
  classifier.assignments.set(sampleKey, assignment);
  cleanupEmptyClassifierAssignment(sampleKey);
  markClassifierModelOutdated("Labels changed. Train model again to refresh predictions.");

  renderClassifierPanel();
  renderResultsPage();
  saveClassifierState("Cleared manual labels for current sample.");
}

function toggleExcludeCurrentSample() {
  if (!state.classifier) return;
  const classifier = state.classifier;
  const sampleKey = classifier.sampleKeys[classifier.sampleCursor];
  if (!sampleKey) return;

  const assignment = classifier.assignments.get(sampleKey) || createClassifierAssignment();
  assignment.excluded = !assignment.excluded;

  if (assignment.excluded) {
    assignment.manual.clear();
    assignment.predicted.clear();
  }

  classifier.assignments.set(sampleKey, assignment);
  cleanupEmptyClassifierAssignment(sampleKey);
  markClassifierModelOutdated("Training sample set changed. Train model again.");

  renderClassifierPanel();
  renderResultsPage();
  saveClassifierState(
    assignment.excluded
      ? "Sample excluded from training."
      : "Sample included in training again."
  );
}

function addClassifierLabel() {
  if (!state.classifier) return;
  const classifier = state.classifier;
  const label = normalizeClassifierLabel(el.newClassifierLabelInput.value);
  if (!label) return;

  const labelKey = classifierLabelKey(label);
  if (classifier.labels.some((item) => classifierLabelKey(item) === labelKey)) {
    setClassifierPersistStatus(`Label "${label}" already exists.`);
    return;
  }

  classifier.labels.push(label);
  el.newClassifierLabelInput.value = "";
  markClassifierModelOutdated("Label set changed. Train model again.");
  renderClassifierPanel();
  saveClassifierState(`Added label "${label}".`);
}

function removeClassifierLabel(label) {
  if (!state.classifier) return;
  const classifier = state.classifier;
  const normalized = normalizeClassifierLabel(label);
  if (!normalized) return;
  const targetKey = classifierLabelKey(normalized);

  const current = classifier.labels.find((item) => classifierLabelKey(item) === targetKey);
  if (!current) return;

  const shouldRemove = window.confirm(`Remove label "${current}" from classifier and all paragraph assignments?`);
  if (!shouldRemove) return;

  classifier.labels = classifier.labels.filter((item) => classifierLabelKey(item) !== targetKey);

  for (const [key, assignment] of classifier.assignments.entries()) {
    assignment.manual.delete(current);
    assignment.predicted.delete(current);
    if (!assignment.manual.size && !assignment.predicted.size) {
      classifier.assignments.delete(key);
    } else {
      classifier.assignments.set(key, assignment);
    }
  }

  markClassifierModelOutdated("Label set changed. Train model again.");
  renderClassifierPanel();
  renderResultsPage();
  saveClassifierState(`Removed label "${current}".`);
}

function handleClassifierSectionToggle(kind, section, checked) {
  if (!state.classifier) return;
  const classifier = state.classifier;
  if (!state.sectionsInDataset.includes(section)) return;

  const targetSet = kind === "prediction" ? classifier.predictionSections : classifier.trainingSections;
  if (checked) {
    targetSet.add(section);
  } else {
    targetSet.delete(section);
  }

  if (kind === "training") {
    pruneClassifierSampleKeysToTrainingSections();
    markClassifierModelOutdated("Training sections changed. Train model again.");
  }

  renderClassifierPanel();
  saveClassifierState(`Updated ${kind} sections.`);
}

function onClassifierThresholdInput() {
  if (!state.classifier) return;
  state.classifier.threshold = sanitizeClassifierThreshold(el.classifierThresholdRange.value);
  el.classifierThresholdValue.textContent = state.classifier.threshold.toFixed(2);
  saveClassifierState();
}

function setClassifierMethod(method) {
  if (!state.classifier) return;
  const nextMethod = CLASSIFIER_METHODS[method] ? method : "tfidf_centroid";
  if (state.classifier.method === nextMethod) return;

  state.classifier.method = nextMethod;
  state.classifier.model = null;
  state.classifier.modelInfo = `Method changed to ${CLASSIFIER_METHODS[nextMethod].label}. Train model again.`;
  state.classifier.threshold = sanitizeClassifierThreshold(
    CLASSIFIER_METHODS[nextMethod]?.defaultThreshold ?? CLASSIFIER_DEFAULT_THRESHOLD
  );

  renderClassifierPanel();
  saveClassifierState("Classifier method updated.");
}

function onClassifierMethodChange() {
  if (!el.classifierMethodSelect) return;
  setClassifierMethod(el.classifierMethodSelect.value);
}

function tokenizeClassifierText(text) {
  const tokens = String(text || "").toLowerCase().match(/[a-z0-9]{3,}/g) || [];
  return tokens.filter((token) => !STOPWORDS.has(token));
}

function tokenizeClassifierCharNgrams(text, minN = 3, maxN = 5) {
  const clean = String(text || "")
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  if (!clean) return [];
  const padded = ` ${clean} `;
  const grams = [];
  for (let n = minN; n <= maxN; n += 1) {
    for (let i = 0; i <= padded.length - n; i += 1) {
      const gram = padded.slice(i, i + n);
      if (gram.trim().length >= Math.max(2, n - 1)) {
        grams.push(gram);
      }
    }
  }
  return grams;
}

function getClassifierTokenizer(method) {
  if (method === "char_ngram_centroid") {
    return (text) => tokenizeClassifierCharNgrams(text, 3, 5);
  }
  return tokenizeClassifierText;
}

function computeClassifierTfIdf(texts, tokenizer = tokenizeClassifierText) {
  const docsTf = [];
  const df = new Map();

  for (const text of texts) {
    const tokens = tokenizer(text);
    const tf = new Map();
    const seen = new Set();

    for (const token of tokens) {
      tf.set(token, (tf.get(token) || 0) + 1);
      if (!seen.has(token)) {
        seen.add(token);
        df.set(token, (df.get(token) || 0) + 1);
      }
    }

    const total = tokens.length || 1;
    const normalizedTf = {};
    for (const [token, count] of tf.entries()) {
      normalizedTf[token] = count / total;
    }
    docsTf.push(normalizedTf);
  }

  const idf = {};
  const docCount = texts.length || 1;
  for (const [token, count] of df.entries()) {
    idf[token] = Math.log((docCount + 1) / (count + 1)) + 1;
  }

  const vectors = docsTf.map((docTf) => {
    const vec = {};
    for (const [token, tfVal] of Object.entries(docTf)) {
      vec[token] = tfVal * (idf[token] || 1);
    }
    return vec;
  });

  return { idf, vectors };
}

function buildClassifierCentroids(vectors, examples, labels) {
  const sumsByLabel = new Map();
  const countsByLabel = new Map();
  for (const label of labels) {
    sumsByLabel.set(label, {});
    countsByLabel.set(label, 0);
  }

  for (let i = 0; i < examples.length; i += 1) {
    const vector = vectors[i];
    const row = examples[i];
    for (const label of row.labels) {
      if (!sumsByLabel.has(label)) continue;
      const sums = sumsByLabel.get(label);
      countsByLabel.set(label, (countsByLabel.get(label) || 0) + 1);
      for (const [token, value] of Object.entries(vector)) {
        sums[token] = (sums[token] || 0) + value;
      }
    }
  }

  const centroids = {};
  const labelCounts = {};
  for (const label of labels) {
    const count = countsByLabel.get(label) || 0;
    if (!count) continue;
    labelCounts[label] = count;
    const centroid = {};
    const sums = sumsByLabel.get(label);
    for (const [token, value] of Object.entries(sums)) {
      centroid[token] = value / count;
    }
    centroids[label] = centroid;
  }

  return { centroids, labelCounts };
}

function textToClassifierVector(text, idf, tokenizer = tokenizeClassifierText) {
  const tokens = tokenizer(text);
  const counts = new Map();
  for (const token of tokens) {
    counts.set(token, (counts.get(token) || 0) + 1);
  }

  const total = tokens.length || 1;
  const vector = {};
  for (const [token, count] of counts.entries()) {
    vector[token] = (count / total) * (idf[token] || 1);
  }
  return vector;
}

function buildClassifierKeywordProfiles(texts, labelsByDoc, labels) {
  const tokenized = texts.map((t) => tokenizeClassifierText(t));
  const df = {};
  tokenized.forEach((tokens) => {
    const unique = new Set(tokens);
    unique.forEach((tok) => { df[tok] = (df[tok] || 0) + 1; });
  });
  const docCount = texts.length || 1;

  const labelTokenCounts = {};
  const labelTotals = {};
  labels.forEach((label) => {
    labelTokenCounts[label] = {};
    labelTotals[label] = 0;
  });

  tokenized.forEach((tokens, idx) => {
    const tf = {};
    tokens.forEach((tok) => { tf[tok] = (tf[tok] || 0) + 1; });
    (labelsByDoc[idx] || []).forEach((label) => {
      if (!labelTokenCounts[label]) return;
      Object.entries(tf).forEach(([tok, count]) => {
        labelTokenCounts[label][tok] = (labelTokenCounts[label][tok] || 0) + count;
        labelTotals[label] += count;
      });
    });
  });

  const profiles = {};
  labels.forEach((label) => {
    const counts = labelTokenCounts[label] || {};
    const total = labelTotals[label] || 1;
    const weighted = Object.entries(counts)
      .map(([tok, count]) => {
        const idf = Math.log((docCount + 1) / ((df[tok] || 0) + 1)) + 1;
        return [tok, (count / total) * idf];
      })
      .sort((a, b) => b[1] - a[1])
      .slice(0, 120);

    const weights = {};
    let totalWeight = 0;
    weighted.forEach(([tok, weight]) => {
      weights[tok] = weight;
      totalWeight += weight;
    });
    profiles[label] = { weights, totalWeight };
  });

  return profiles;
}

function predictLabelsWithKeywordProfiles(text, profiles, threshold) {
  const tokenSet = new Set(tokenizeClassifierText(text));
  const scored = [];

  for (const [label, profile] of Object.entries(profiles || {})) {
    const weights = profile?.weights || {};
    const totalWeight = profile?.totalWeight || 1;
    let overlap = 0;
    for (const [tok, weight] of Object.entries(weights)) {
      if (tokenSet.has(tok)) overlap += weight;
    }
    const score = overlap / totalWeight;
    if (score >= threshold) {
      scored.push([label, score]);
    }
  }

  scored.sort((a, b) => b[1] - a[1]);
  return scored.slice(0, 5).map(([label]) => label);
}

function cosineSimilarity(vecA, vecB) {
  let dot = 0;
  let normA = 0;
  let normB = 0;

  for (const value of Object.values(vecA)) {
    normA += value * value;
  }
  for (const value of Object.values(vecB)) {
    normB += value * value;
  }
  if (!normA || !normB) return 0;

  const [small, large] = Object.keys(vecA).length <= Object.keys(vecB).length
    ? [vecA, vecB]
    : [vecB, vecA];

  for (const [token, value] of Object.entries(small)) {
    dot += value * (large[token] || 0);
  }

  return dot / (Math.sqrt(normA) * Math.sqrt(normB));
}

function trainClassifierModel() {
  if (!state.classifier) return;
  const classifier = state.classifier;

  if (!classifier.trainingSections.size) {
    setClassifierModelStatus("Select at least one section for training.");
    return;
  }

  if (!classifier.labels.length) {
    setClassifierModelStatus("Add at least one label before training.");
    return;
  }

  const validLabelsSet = new Set(classifier.labels);
  const examples = [];

  for (const [paraKey, assignment] of classifier.assignments.entries()) {
    if (assignment.excluded) continue;
    if (!assignment.manual.size) continue;
    const paragraph = state.paragraphByKey.get(paraKey);
    if (!paragraph) continue;
    if (!classifier.trainingSections.has(paragraph.section)) continue;

    const labels = [...assignment.manual].filter((label) => validLabelsSet.has(label));
    if (!labels.length) continue;
    examples.push({
      text: paragraph.text,
      labels,
    });
  }

  if (examples.length < CLASSIFIER_MIN_LABELED_PARAGRAPHS) {
    setClassifierModelStatus(
      `Need at least ${CLASSIFIER_MIN_LABELED_PARAGRAPHS} manually labeled paragraphs in selected training sections (currently ${examples.length}).`
    );
    return;
  }

  const method = CLASSIFIER_METHODS[classifier.method] ? classifier.method : "tfidf_centroid";
  const labelsWithExamples = examples.map((row) => row.labels);

  let model = null;
  if (method === "keyword_overlap") {
    const profiles = buildClassifierKeywordProfiles(
      examples.map((row) => row.text),
      labelsWithExamples,
      classifier.labels
    );
    if (!Object.keys(profiles).length) {
      setClassifierModelStatus("Could not train model. Add more labeled examples for your labels.");
      return;
    }
    model = {
      type: "keyword-overlap-v1",
      method,
      trainedAt: new Date().toISOString(),
      trainingSize: examples.length,
      keywordProfiles: profiles,
    };
  } else {
    const tokenizer = getClassifierTokenizer(method);
    const { idf, vectors } = computeClassifierTfIdf(
      examples.map((row) => row.text),
      tokenizer
    );
    const { centroids, labelCounts } = buildClassifierCentroids(vectors, examples, classifier.labels);
    if (!Object.keys(centroids).length) {
      setClassifierModelStatus("Could not train model. Ensure labels are assigned in selected training sections.");
      return;
    }
    model = {
      type: method === "char_ngram_centroid" ? "char-ngram-centroid-v1" : "tfidf-centroid-v1",
      method,
      trainedAt: new Date().toISOString(),
      trainingSize: examples.length,
      idf,
      centroids,
      labelCounts,
    };
  }

  classifier.model = model;
  classifier.model.method = method;

  const labelsWithData = method === "keyword_overlap"
    ? Object.keys(classifier.model.keywordProfiles || {}).length
    : Object.keys(classifier.model.centroids || {}).length;
  classifier.modelInfo =
    `Model trained on ${fmtInt.format(examples.length)} labeled paragraphs (${fmtInt.format(labelsWithData)} labels with examples). Method: ${CLASSIFIER_METHODS[method].label}.`;
  setClassifierModelStatus(classifier.modelInfo);

  renderClassifierPanel();
  saveClassifierState("Model trained.");
}

function predictLabelsForTextWithClassifier(text, classifier) {
  if (!classifier.model) {
    return { labels: [], scores: {} };
  }

  const threshold = sanitizeClassifierThreshold(classifier.threshold);
  const method = classifier.model.method || classifier.method || "tfidf_centroid";

  if (method === "keyword_overlap") {
    return {
      labels: predictLabelsWithKeywordProfiles(text, classifier.model.keywordProfiles || {}, threshold),
      scores: {},
    };
  }

  const tokenizer = getClassifierTokenizer(method);
  const vector = textToClassifierVector(text, classifier.model.idf || {}, tokenizer);
  const scores = [];

  for (const [label, centroid] of Object.entries(classifier.model.centroids || {})) {
    const score = cosineSimilarity(vector, centroid);
    if (score >= threshold) {
      scores.push([label, score]);
    }
  }

  scores.sort((a, b) => b[1] - a[1]);
  const limitedScores = scores.slice(0, 5);
  return {
    labels: limitedScores.map(([label]) => label),
    scores: Object.fromEntries(limitedScores),
  };
}

function applyClassifierModelToSelectedSections() {
  if (!state.classifier) return;
  const classifier = state.classifier;

  if (!classifier.model) {
    setClassifierModelStatus("Train model before applying predictions.");
    return;
  }

  if (!classifier.predictionSections.size) {
    setClassifierModelStatus("Select at least one section for model tagging.");
    return;
  }

  let evaluatedParagraphs = 0;
  let taggedParagraphs = 0;
  let assignedLabels = 0;
  let changedParagraphs = 0;

  for (const row of state.paragraphIndex) {
    if (!classifier.predictionSections.has(row.section)) {
      continue;
    }

    const existing = classifier.assignments.get(row.key) || createClassifierAssignment();
    if (existing.excluded) {
      classifier.assignments.set(row.key, existing);
      continue;
    }

    evaluatedParagraphs += 1;
    const previousPredicted = new Set(existing.predicted);

    const prediction = predictLabelsForTextWithClassifier(row.text, classifier);
    const nextPredicted = new Set(prediction.labels.filter((label) => !existing.manual.has(label)));
    existing.predicted = nextPredicted;

    if (!setsEqual(previousPredicted, nextPredicted)) {
      changedParagraphs += 1;
    }

    if (nextPredicted.size) {
      taggedParagraphs += 1;
      assignedLabels += nextPredicted.size;
    }

    if (existing.manual.size || existing.predicted.size) {
      classifier.assignments.set(row.key, existing);
    } else {
      classifier.assignments.delete(row.key);
    }
  }

  const sectionCount = classifier.predictionSections.size;
  const sectionWord = sectionCount === 1 ? "section" : "sections";
  const summary =
    `Model applied to ${fmtInt.format(evaluatedParagraphs)} paragraphs in ${fmtInt.format(sectionCount)} ${sectionWord}. ` +
    `Tagged ${fmtInt.format(taggedParagraphs)} paragraphs (${fmtInt.format(assignedLabels)} labels, ${fmtInt.format(changedParagraphs)} changes).`;

  setClassifierModelStatus(summary);
  renderClassifierPanel();
  renderResultsPage();
  saveClassifierState("Model predictions applied.");
}

function exportClassifierProgress() {
  const payload = serializeClassifierState();
  if (!payload) return;
  payload.exportedAt = new Date().toISOString();

  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `echr_classifier_progress_${state.datasetKey || "dataset"}.json`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);

  setClassifierPersistStatus("Classifier progress exported.");
}

async function importClassifierProgress(file) {
  if (!file) return;
  try {
    const text = await file.text();
    const payload = JSON.parse(text);
    if (!payload || typeof payload !== "object") {
      throw new Error("Invalid JSON structure.");
    }

    if (payload.datasetKey && payload.datasetKey !== state.datasetKey) {
      const proceed = window.confirm(
        "This progress file belongs to a different dataset signature. Import anyway?"
      );
      if (!proceed) {
        return;
      }
    }

    state.classifier = hydrateClassifierPayload(payload, true);
    renderClassifierPanel();
    renderResultsPage();
    saveClassifierState("Classifier progress imported.");
  } catch (err) {
    setClassifierPersistStatus(`Could not import progress file: ${err.message}`);
  } finally {
    el.importClassifierProgressInput.value = "";
  }
}

function clearClassifierProgress() {
  if (!state.classifier) return;
  const shouldClear = window.confirm("Clear all classifier labels, assignments, and model for this dataset?");
  if (!shouldClear) return;

  removeClassifierSavedState();
  state.classifier = createDefaultClassifierState();
  state.classifier.loadedFromStorage = false;
  state.classifier.modelInfo = "Model not trained yet.";
  setClassifierPersistStatus("Classifier progress cleared for this dataset.");
  setClassifierModelStatus("Model not trained yet.");
  renderClassifierPanel();
  renderResultsPage();
  updateClassifierResumeNote();
}

function loadClassifierStateForDataset() {
  const storageKey = getClassifierStorageKey();
  let classifier = null;

  if (storageKey) {
    try {
      const raw = localStorage.getItem(storageKey);
      if (raw) {
        classifier = hydrateClassifierPayload(JSON.parse(raw), true);
      }
    } catch (err) {
      console.error("Could not load classifier state:", err);
    }
  }

  if (!classifier) {
    classifier = createDefaultClassifierState();
    classifier.loadedFromStorage = false;
    classifier.modelInfo = "Model not trained yet.";
    setClassifierPersistStatus("No saved state loaded for this dataset yet.");
  } else {
    const savedAt = formatClassifierTimestamp(classifier.lastSavedAt);
    setClassifierPersistStatus(
      `Loaded saved classifier progress${savedAt ? ` (${savedAt})` : ""}.`
    );
  }

  state.classifier = classifier;
  if (!CLASSIFIER_METHODS[state.classifier.method]) {
    state.classifier.method = "tfidf_centroid";
  }
  renderClassifierPanel();
  updateClassifierResumeNote();
}

function buildCaseCard(caseId, row) {
  const c = row.case;
  const defendantLabel = (c.__states || []).map((d) => COUNTRY_NAMES[d] || d).join(", ");

  const paraBlocks = row.paragraphs
    .map((p) => {
      return `
        <div class="paragraph-item">
          <div class="para-header">
            <span class="para-section">${escapeHtml(p.sectionLabel)}</span>
            <span class="para-num">¶ ${p.paraIdx + 1}</span>
            ${buildParagraphLabelBadgesHtml(p.key)}
            <button class="copy-btn" data-action="copy-paragraph" data-text="${escapeHtml(p.rawText)}">Copy</button>
          </div>
          <p class="para-text">${p.textHtml}</p>
        </div>
      `;
    })
    .join("");

  const hitLabel = state.currentMode === "browse"
    ? (row.hitCount === 1 ? "para" : "paras")
    : (row.hitCount === 1 ? "hit" : "hits");

  return `
    <div class="case-card" id="case-${escapeHtml(caseId)}">
      <div class="case-header" data-action="toggle-case" data-case-id="${escapeHtml(caseId)}">
        <div class="case-info">
          <h2 class="case-title">${escapeHtml(c.title || "Untitled case")}</h2>
          <div class="case-actions-inline">
            <button type="button" class="case-open-link" data-action="open-case" data-case-id="${escapeHtml(caseId)}">View full judgment</button>
            ${c.hudoc_url ? `<a href="${escapeHtml(c.hudoc_url)}" class="case-open-link" data-action="open-hudoc" target="_blank" rel="noopener noreferrer">Open in HUDOC ↗</a>` : ""}
          </div>
          <div class="case-meta">
            <span class="meta-item">📋 ${escapeHtml(c.case_no || "-")}</span>
            <span class="meta-item">📅 ${escapeHtml(c.judgment_date || "-")}</span>
            <span class="meta-item">🏳️ ${escapeHtml(defendantLabel || "-")}</span>
            <span class="meta-item">🏛️ ${escapeHtml(c.__originatingBody || "-")}</span>
            <span class="meta-item">📜 ${escapeHtml(c.article_no || "-")}</span>
            <span class="meta-item">⭐ ${escapeHtml(c.__importance || "-")}</span>
          </div>
        </div>
        <div class="case-badge">
          <span class="hit-count">${fmtInt.format(row.hitCount)}</span>
          <span class="hit-label">${hitLabel}</span>
          <span class="toggle-icon" id="icon-${escapeHtml(caseId)}">▶</span>
        </div>
      </div>
      <div class="case-body" id="body-${escapeHtml(caseId)}">
        ${paraBlocks || '<div class="paragraph-item"><p class="para-text">No paragraphs for current filters.</p></div>'}
        <div class="case-footer">
          <a href="#" class="view-full" data-action="open-case" data-case-id="${escapeHtml(caseId)}">View full judgment →</a>
          ${c.hudoc_url ? `<a href="${escapeHtml(c.hudoc_url)}" class="view-full" target="_blank" rel="noopener noreferrer">Open in HUDOC ↗</a>` : ""}
        </div>
      </div>
    </div>
  `;
}

function buildPageWindow(totalPages, currentPage) {
  if (totalPages <= 9) {
    return Array.from({ length: totalPages }, (_, i) => i + 1);
  }

  const pages = [1];
  const start = Math.max(2, currentPage - 1);
  const end = Math.min(totalPages - 1, currentPage + 1);

  if (start > 2) {
    pages.push("...");
  }

  for (let p = start; p <= end; p += 1) {
    pages.push(p);
  }

  if (end < totalPages - 1) {
    pages.push("...");
  }

  pages.push(totalPages);
  return pages;
}

function renderPagination() {
  const totalCases = state.currentOrderedCaseIds.length;
  const totalPages = Math.ceil(totalCases / PAGE_SIZE);

  if (totalPages <= 1) {
    el.pagination.hidden = true;
    el.pagination.innerHTML = "";
    return;
  }

  const pageItems = buildPageWindow(totalPages, state.currentPage)
    .map((item) => {
      if (item === "...") {
        return `<span class="pagination-gap">…</span>`;
      }
      const activeClass = item === state.currentPage ? "active" : "";
      return `<button type="button" class="pagination-btn ${activeClass}" data-page="${item}">${item}</button>`;
    })
    .join("");

  const prevDisabled = state.currentPage <= 1 ? "disabled" : "";
  const nextDisabled = state.currentPage >= totalPages ? "disabled" : "";

  el.pagination.hidden = false;
  el.pagination.innerHTML = `
    <button type="button" class="pagination-btn" data-page="prev" ${prevDisabled}>Prev</button>
    ${pageItems}
    <button type="button" class="pagination-btn" data-page="next" ${nextDisabled}>Next</button>
  `;
}

function renderResultsPage() {
  const totalCases = state.currentOrderedCaseIds.length;

  if (totalCases === 0) {
    el.casesList.innerHTML = "";
    el.noResults.hidden = false;
    el.pagination.hidden = true;
    el.exportBtn.disabled = true;
    return;
  }

  el.noResults.hidden = true;

  const totalPages = Math.ceil(totalCases / PAGE_SIZE);
  if (state.currentPage > totalPages) {
    state.currentPage = totalPages;
  }

  const start = (state.currentPage - 1) * PAGE_SIZE;
  const end = Math.min(start + PAGE_SIZE, totalCases);
  const pageCaseIds = state.currentOrderedCaseIds.slice(start, end);

  el.casesList.innerHTML = pageCaseIds
    .map((caseId) => buildCaseCard(caseId, state.currentResultsById.get(caseId)))
    .join("");

  renderPagination();
}

function computeAnalytics() {
  const countryCounts = new Map();
  const articleCounts = new Map();
  const sectionCounts = new Map();
  const bodyCounts = new Map();
  const importanceCounts = new Map();
  const outcomeCounts = new Map();
  const wordCounts = new Map();

  for (const caseId of state.currentOrderedCaseIds) {
    const data = state.currentResultsById.get(caseId);
    if (!data) continue;

    for (const d of data.case.__states || []) {
      countryCounts.set(d, (countryCounts.get(d) || 0) + data.hitCount);
    }

    bodyCounts.set(data.case.__originatingBody, (bodyCounts.get(data.case.__originatingBody) || 0) + data.hitCount);
    importanceCounts.set(data.case.__importance, (importanceCounts.get(data.case.__importance) || 0) + data.hitCount);
    outcomeCounts.set(data.case.__outcomeBucket, (outcomeCounts.get(data.case.__outcomeBucket) || 0) + data.hitCount);

    for (const a of data.case.__articles || []) {
      articleCounts.set(a, (articleCounts.get(a) || 0) + data.hitCount);
    }

    for (const para of data.paragraphs) {
      sectionCounts.set(para.sectionLabel, (sectionCounts.get(para.sectionLabel) || 0) + 1);

      const words = para.rawText.toLowerCase().match(/\b[a-z]{4,}\b/g) || [];
      for (const w of words) {
        if (STOPWORDS.has(w)) continue;
        wordCounts.set(w, (wordCounts.get(w) || 0) + 1);
      }
    }
  }

  const sortDesc = (a, b) => b[1] - a[1];

  return {
    countries: [...countryCounts.entries()].sort(sortDesc).slice(0, 10),
    articles: [...articleCounts.entries()].sort(sortDesc).slice(0, 10),
    sections: [...sectionCounts.entries()].sort(sortDesc).slice(0, 10),
    bodies: [...bodyCounts.entries()].sort(sortDesc).slice(0, 10),
    importance: [...importanceCounts.entries()].sort(sortDesc).slice(0, 10),
    outcomes: [...outcomeCounts.entries()].sort(sortDesc).slice(0, 10),
    words: [...wordCounts.entries()].sort(sortDesc).slice(0, 25),
  };
}

function renderBarList(container, rows, labelFn, fillClass = "") {
  if (!rows.length) {
    container.className = "bar-list empty";
    container.textContent = "No data";
    return;
  }

  const max = rows[0][1] || 1;
  const html = rows
    .map(([label, value]) => {
      const width = Math.max(2, Math.round((value / max) * 100));
      return `
        <div class="bar-item">
          <span class="bar-label">${escapeHtml(labelFn(label))}</span>
          <div class="bar-track"><div class="bar-fill ${fillClass}" style="width:${width}%"></div></div>
          <span class="bar-value">${fmtInt.format(value)}</span>
        </div>
      `;
    })
    .join("");

  container.className = "bar-list";
  container.innerHTML = html;
}

function renderWordCloud(rows) {
  if (!rows.length) {
    el.analyticsWords.className = "word-cloud empty";
    el.analyticsWords.textContent = "No data";
    return;
  }

  const max = rows[0][1] || 1;
  const html = rows
    .map(([word, count]) => {
      const ratio = count / max;
      const size = 0.74 + ratio * 0.74;
      const opacity = 0.5 + ratio * 0.45;
      return `<span class="word-tag" style="font-size:${size.toFixed(2)}rem;opacity:${opacity.toFixed(2)}">${escapeHtml(word)}</span>`;
    })
    .join("");

  el.analyticsWords.className = "word-cloud";
  el.analyticsWords.innerHTML = html;
}

function renderAnalytics() {
  const a = computeAnalytics();

  renderBarList(
    el.analyticsArticles,
    a.articles,
    (label) => `Art. ${label}`,
    ""
  );

  renderBarList(
    el.analyticsCountries,
    a.countries,
    (label) => COUNTRY_NAMES[label] || label,
    "country"
  );

  renderBarList(
    el.analyticsSections,
    a.sections,
    (label) => label,
    "section"
  );

  renderBarList(
    el.analyticsBodies,
    a.bodies,
    (label) => label,
    "section"
  );

  renderBarList(
    el.analyticsImportance,
    a.importance,
    (label) => `Importance ${label}`,
    ""
  );

  renderBarList(
    el.analyticsOutcomes,
    a.outcomes,
    (label) => ({
      violation_only: "Violation only",
      non_violation_only: "Non-violation only",
      both: "Both",
      neither: "Neither",
    })[label] || label,
    "country"
  );

  renderWordCloud(a.words);
}

function updateResultsHeader() {
  const totalCases = state.currentOrderedCaseIds.length;
  const totalPages = Math.ceil(totalCases / PAGE_SIZE) || 1;
  const modeLabel = state.currentMode === "browse" ? "browse" : "search";
  const limitedNote = state.limited ? ` · limited to ${MAX_HITS} hits` : "";

  el.resultsHeader.hidden = false;
  el.resultsHits.textContent = fmtInt.format(state.totalHits);
  el.resultsCases.textContent = fmtInt.format(totalCases);
  el.resultsTime.textContent = `(${(state.searchTimeMs / 1000).toFixed(3)}s · page ${state.currentPage}/${totalPages} · ${modeLabel}${limitedNote})`;

  el.exportBtn.disabled = !totalCases;
  el.clearBtn.disabled = !state.loaded;
}

function applySearch(resetPage = true) {
  if (!state.loaded) {
    return;
  }

  const query = el.searchInput.value.trim();
  state.query = query;
  el.inlineSearchInput.value = query;

  const filters = getCurrentFilters();
  state.currentFilters = filters;

  const t0 = performance.now();
  const result = query
    ? buildQueryResults(query, filters)
    : buildBrowseResults(filters);
  const t1 = performance.now();

  state.currentMode = result.mode;
  state.currentOrderedCaseIds = result.orderedCaseIds;
  state.currentResultsById = result.resultsById;
  state.currentTerms = result.terms;
  state.totalHits = result.totalHits;
  state.limited = result.limited;
  state.searchTimeMs = t1 - t0;

  if (resetPage) {
    state.currentPage = 1;
  }

  renderActiveFilters(filters);
  renderResultsPage();
  renderAnalytics();
  updateResultsHeader();
}

function resetFiltersAndQuery() {
  el.searchInput.value = "";
  el.inlineSearchInput.value = "";
  el.dateFrom.value = "";
  el.dateTo.value = "";
  el.keywordFilterInput.value = "";

  const checks = document.querySelectorAll("#filtersPanel input[type='checkbox']");
  for (const c of checks) {
    c.checked = false;
  }

  applySearch(true);
}

function exportCsv() {
  if (!state.currentOrderedCaseIds.length) return;

  const rows = [
    [
      "Case ID",
      "Case No",
      "Title",
      "Judgment Date",
      "Defendants",
      "Articles",
      "Respondent State",
      "Originating Body",
      "Importance",
      "Outcome",
      "Separate Opinion",
      "ECLI",
      "HUDOC URL",
      "Violation",
      "Non-violation",
      "Keywords",
      "Section",
      "Paragraph",
      "Assigned Labels",
      "Text",
    ],
  ];

  for (const caseId of state.currentOrderedCaseIds) {
    const data = state.currentResultsById.get(caseId);
    if (!data) continue;

    for (const p of data.paragraphs) {
      rows.push([
        caseId,
        data.case.case_no || "",
        data.case.title || "",
        data.case.judgment_date || "",
        (data.case.defendants || []).join(", "),
        data.case.article_no || "",
        (data.case.__states || []).join(", "),
        data.case.__originatingBody || "",
        data.case.__importance || "",
        data.case.__outcomeBucket || "",
        data.case.__hasSeparateOpinion ? "yes" : "no",
        data.case.ecli || "",
        data.case.hudoc_url || "",
        (data.case.violation || []).join("; "),
        (data.case["non-violation"] || []).join("; "),
        (data.case.keywords || []).join("; "),
        p.sectionLabel,
        String(p.paraIdx + 1),
        getCombinedParagraphLabels(p.key).map((x) => x.label).join("; "),
        p.rawText,
      ]);
    }
  }

  const csv = rows
    .map((row) =>
      row
        .map((cell) => `"${String(cell ?? "").replaceAll('"', '""')}"`)
        .join(",")
    )
    .join("\n");

  const blob = new Blob([`\uFEFF${csv}`], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  const suffix = state.query ? state.query.slice(0, 24).replace(/\s+/g, "_") : "all_cases";
  link.href = url;
  link.download = `echr_search_${suffix}.csv`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function toggleCase(caseId) {
  const body = byId(`body-${caseId}`);
  const icon = byId(`icon-${caseId}`);
  if (!body || !icon) return;

  const isOpen = body.classList.toggle("open");
  icon.textContent = isOpen ? "▼" : "▶";
}

function buildCaseMeta(caseObj) {
  const parts = [];
  parts.push(`Case no: ${escapeHtml(caseObj.case_no || "-")}`);
  parts.push(`Judgment: ${escapeHtml(caseObj.judgment_date || "-")}`);

  const states = (caseObj.__states || []).map((d) => COUNTRY_NAMES[d] || d).join(", ") || "-";
  parts.push(`Respondent State: ${escapeHtml(states)}`);
  parts.push(`Originating Body: ${escapeHtml(caseObj.__originatingBody || "-")}`);
  parts.push(`Importance: ${escapeHtml(caseObj.__importance || "-")}`);
  parts.push(`Separate Opinion: ${caseObj.__hasSeparateOpinion ? "Yes" : "No"}`);
  parts.push(`Articles: ${escapeHtml(caseObj.article_no || "-")}`);
  if (caseObj.represented_by) {
    parts.push(`Represented by: ${escapeHtml(caseObj.represented_by)}`);
  }
  if (caseObj.ecli) {
    parts.push(`ECLI: ${escapeHtml(caseObj.ecli)}`);
  }

  if (Array.isArray(caseObj.violation) && caseObj.violation.length) {
    parts.push(`Violation: ${escapeHtml(caseObj.violation.join("; "))}`);
  }

  if (Array.isArray(caseObj["non-violation"]) && caseObj["non-violation"].length) {
    parts.push(`No violation: ${escapeHtml(caseObj["non-violation"].join("; "))}`);
  }

  if (caseObj.hudoc_url) {
    parts.push(`<a href="${escapeHtml(caseObj.hudoc_url)}" target="_blank" rel="noopener noreferrer">Open in HUDOC ↗</a>`);
  }

  return parts.join(" · ");
}

function renderModalSection(sectionKey, paragraphs) {
  const label = SECTION_LABELS[sectionKey] || sectionKey;
  const color = SECTION_COLORS[sectionKey] || "#4C72B0";

  const paragraphsHtml = paragraphs
    .map((p) => {
      return `
        <p class="modal-para" data-section="${escapeHtml(sectionKey)}" data-text="${escapeHtml(p.textLower)}">
          <span class="modal-para-num">¶ ${p.paraIdx + 1}</span>
          <span>${escapeHtml(p.text)}</span>
        </p>
      `;
    })
    .join("");

  return `
    <section class="modal-section" data-section="${escapeHtml(sectionKey)}">
      <h3 style="border-bottom-color:${escapeHtml(color)}66">${escapeHtml(label)}</h3>
      ${paragraphsHtml}
    </section>
  `;
}

function openCaseModal(caseId) {
  const c = state.caseById.get(caseId);
  if (!c) return;

  el.modalTitle.textContent = c.title || "Untitled case";
  el.modalMeta.innerHTML = buildCaseMeta(c);

  const grouped = new Map();
  for (const para of c.__paragraphs) {
    if (!grouped.has(para.section)) {
      grouped.set(para.section, []);
    }
    grouped.get(para.section).push(para);
  }

  const availableSections = [...grouped.keys()];
  el.modalSectionFilter.innerHTML = `<option value="all">All sections</option>`;

  for (const sec of SECTION_ORDER) {
    if (!grouped.has(sec)) continue;
    el.modalSectionFilter.insertAdjacentHTML(
      "beforeend",
      `<option value="${escapeHtml(sec)}">${escapeHtml(SECTION_LABELS[sec] || sec)}</option>`
    );
  }
  for (const sec of availableSections.sort()) {
    if (SECTION_ORDER.includes(sec)) continue;
    el.modalSectionFilter.insertAdjacentHTML(
      "beforeend",
      `<option value="${escapeHtml(sec)}">${escapeHtml(SECTION_LABELS[sec] || sec)}</option>`
    );
  }

  const parts = [];
  for (const sec of SECTION_ORDER) {
    if (!grouped.has(sec)) continue;
    parts.push(renderModalSection(sec, grouped.get(sec)));
  }
  for (const sec of availableSections.sort()) {
    if (SECTION_ORDER.includes(sec)) continue;
    parts.push(renderModalSection(sec, grouped.get(sec)));
  }

  el.modalBody.innerHTML = parts.join("");
  el.modalQuery.value = "";
  el.modalCount.textContent = `${fmtInt.format(c.__paragraphs.length)} paragraphs`;

  el.caseModal.hidden = false;
  document.body.style.overflow = "hidden";
}

function closeCaseModal() {
  el.caseModal.hidden = true;
  document.body.style.overflow = "";
}

function filterModalParagraphs() {
  const query = el.modalQuery.value.trim().toLowerCase();
  const section = el.modalSectionFilter.value;

  let visibleCount = 0;

  for (const para of el.modalBody.querySelectorAll(".modal-para")) {
    const text = para.getAttribute("data-text") || "";
    const paraSection = para.getAttribute("data-section") || "";

    const matchesQuery = !query || text.includes(query);
    const matchesSection = section === "all" || paraSection === section;

    const visible = matchesQuery && matchesSection;
    para.classList.toggle("hidden", !visible);
    para.classList.toggle("visible-hit", !!query && visible);

    if (visible) visibleCount += 1;
  }

  for (const sec of el.modalBody.querySelectorAll(".modal-section")) {
    const hasVisible = sec.querySelector(".modal-para:not(.hidden)");
    sec.classList.toggle("hidden", !hasVisible);
  }

  el.modalCount.textContent = query
    ? `${fmtInt.format(visibleCount)} matching paragraphs`
    : `${fmtInt.format(visibleCount)} paragraphs`;
}

async function activateDataset(rawRows, sourceLabel, metaLine, invalidCount = 0) {
  const normalized = normalizeCases(rawRows);
  if (!normalized.length) {
    throw new Error("Dataset contains no valid decisions.");
  }

  preprocessDataset(normalized);
  renderFilters();
  renderGlobalStats();

  state.sourceLabel = sourceLabel;

  setDatasetStatus(
    `Loaded ${fmtInt.format(state.cases.length)} cases and ${fmtInt.format(state.paragraphIndex.length)} indexed paragraphs.` +
    (invalidCount ? ` Skipped ${fmtInt.format(invalidCount)} invalid lines.` : "")
  );
  setDatasetMeta(metaLine);

  closeClassifierPane();
  loadClassifierStateForDataset();
  setSearchEnabled(true);

  resetFiltersAndQuery();
}

async function loadSampleDataset() {
  setDatasetLoading(true);
  setDatasetStatus("Loading sample dataset...");

  try {
    const res = await fetch(SAMPLE_DATA_URL, { cache: "no-store" });
    if (!res.ok) {
      throw new Error(`Failed to load sample (${res.status})`);
    }
    const text = await res.text();
    const parsed = parseJsonlText(text);

    await activateDataset(
      parsed.rows,
      "Sample (50 decisions)",
      `Dataset: Sample (50) · source ${SAMPLE_DATA_URL}`,
      parsed.invalidCount
    );
  } catch (err) {
    console.error(err);
    setDatasetStatus(`Could not load sample dataset: ${err.message}`, true);
    setDatasetMeta("Dataset: load failed");
  } finally {
    setDatasetLoading(false);
  }
}

async function loadUploadedFile(file) {
  if (!file) return;

  setDatasetLoading(true);
  setDatasetStatus(`Loading ${file.name}...`);

  try {
    const text = await file.text();
    const parsed = parseJsonlText(text);
    if (!parsed.rows.length) {
      throw new Error("No valid JSONL records found in the uploaded file.");
    }

    await activateDataset(
      parsed.rows,
      `Upload (${file.name})`,
      `Dataset: Uploaded file ${file.name}`,
      parsed.invalidCount
    );
  } catch (err) {
    console.error(err);
    setDatasetStatus(`Could not load uploaded file: ${err.message}`, true);
    setDatasetMeta("Dataset: upload failed");
  } finally {
    setDatasetLoading(false);
    el.fileInput.value = "";
  }
}

function bindEvents() {
  el.themeToggle.addEventListener("click", toggleTheme);

  el.filterToggleBtn.addEventListener("click", () => {
    if (el.filterToggleBtn.disabled) return;
    const open = el.filtersPanel.classList.toggle("open");
    el.filterToggleBtn.setAttribute("aria-expanded", open ? "true" : "false");
  });

  el.searchForm.addEventListener("submit", (e) => {
    e.preventDefault();
    applySearch(true);
  });

  el.inlineSearchForm.addEventListener("submit", (e) => {
    e.preventDefault();
    el.searchInput.value = el.inlineSearchInput.value;
    applySearch(true);
  });

  el.filtersPanel.addEventListener("change", () => {
    if (!state.loaded) return;
    applySearch(true);
  });

  el.keywordFilterInput.addEventListener("change", () => {
    if (!state.loaded) return;
    applySearch(true);
  });

  el.clearBtn.addEventListener("click", () => {
    if (!state.loaded) return;
    resetFiltersAndQuery();
  });

  el.exportBtn.addEventListener("click", exportCsv);

  el.backToSearch.addEventListener("click", (e) => {
    e.preventDefault();
    resetFiltersAndQuery();
  });

  el.loadSampleBtn.addEventListener("click", loadSampleDataset);
  el.openClassifierBtn.addEventListener("click", openClassifierPane);
  el.classifierQuickOpenBtn.addEventListener("click", openClassifierPane);
  el.closeClassifierBtn.addEventListener("click", closeClassifierPane);
  el.classifierBackdrop.addEventListener("click", closeClassifierPane);

  el.addClassifierLabelBtn.addEventListener("click", addClassifierLabel);
  el.newClassifierLabelInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      addClassifierLabel();
    }
  });

  el.classifierLabelsList.addEventListener("click", (e) => {
    const target = e.target.closest("button[data-action='remove-label']");
    if (!target) return;
    const label = target.getAttribute("data-label") || "";
    removeClassifierLabel(label);
  });

  el.classifierTrainingSections.addEventListener("change", (e) => {
    const input = e.target.closest("input[type='checkbox'][data-kind='training']");
    if (!input) return;
    handleClassifierSectionToggle("training", input.value, input.checked);
  });

  el.classifierPredictionSections.addEventListener("change", (e) => {
    const input = e.target.closest("input[type='checkbox'][data-kind='prediction']");
    if (!input) return;
    handleClassifierSectionToggle("prediction", input.value, input.checked);
  });

  el.refreshClassifierSampleBtn.addEventListener("click", regenerateClassifierSample);
  el.classifierPrevSampleBtn.addEventListener("click", () => moveClassifierSample(-1));
  el.classifierNextSampleBtn.addEventListener("click", () => moveClassifierSample(1));

  el.classifierSampleCard.addEventListener("click", (e) => {
    const button = e.target.closest("button[data-action]");
    if (!button) return;
    const action = button.getAttribute("data-action");
    if (action === "toggle-sample-label") {
      toggleCurrentSampleLabel(button.getAttribute("data-label") || "");
      return;
    }
    if (action === "toggle-sample-excluded") {
      toggleExcludeCurrentSample();
      return;
    }
    if (action === "clear-current-sample-labels") {
      clearCurrentSampleManualLabels();
    }
  });

  el.classifierThresholdRange.addEventListener("input", onClassifierThresholdInput);
  el.classifierMethodSelect?.addEventListener("change", onClassifierMethodChange);
  el.trainClassifierBtn.addEventListener("click", trainClassifierModel);
  el.applyClassifierModelBtn.addEventListener("click", applyClassifierModelToSelectedSections);

  el.exportClassifierProgressBtn.addEventListener("click", exportClassifierProgress);
  el.importClassifierProgressInput.addEventListener("change", () => {
    const file = el.importClassifierProgressInput.files && el.importClassifierProgressInput.files[0];
    if (file) {
      importClassifierProgress(file);
    }
  });
  el.clearClassifierProgressBtn.addEventListener("click", clearClassifierProgress);

  el.fileInput.addEventListener("change", () => {
    const file = el.fileInput.files && el.fileInput.files[0];
    if (file) {
      loadUploadedFile(file);
    }
  });

  el.dropZone.addEventListener("click", () => {
    if (el.fileInput.disabled) return;
    el.fileInput.click();
  });

  el.dropZone.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      if (!el.fileInput.disabled) {
        el.fileInput.click();
      }
    }
  });

  el.dropZone.addEventListener("dragenter", (e) => {
    e.preventDefault();
    if (!el.fileInput.disabled) {
      el.dropZone.classList.add("drag-over");
    }
  });

  el.dropZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    if (!el.fileInput.disabled) {
      el.dropZone.classList.add("drag-over");
    }
  });

  el.dropZone.addEventListener("dragleave", () => {
    el.dropZone.classList.remove("drag-over");
  });

  el.dropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    el.dropZone.classList.remove("drag-over");
    if (el.fileInput.disabled) return;

    const file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
    if (file) {
      loadUploadedFile(file);
    }
  });

  el.casesList.addEventListener("click", (e) => {
    const clickable = e.target.closest("[data-action]");
    if (!clickable) return;

    const action = clickable.getAttribute("data-action");
    const caseId = clickable.getAttribute("data-case-id");

    if (action === "toggle-case" && caseId) {
      toggleCase(caseId);
      return;
    }

    if (action === "copy-paragraph") {
      const text = clickable.getAttribute("data-text") || "";
      navigator.clipboard?.writeText(text).then(() => {
        const original = clickable.textContent;
        clickable.textContent = "Copied";
        clickable.classList.add("copied");
        setTimeout(() => {
          clickable.textContent = original;
          clickable.classList.remove("copied");
        }, 1200);
      });
      return;
    }

    if (action === "open-case" && caseId) {
      e.preventDefault();
      openCaseModal(caseId);
    }
  });

  el.pagination.addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-page]");
    if (!btn) return;

    const totalPages = Math.ceil(state.currentOrderedCaseIds.length / PAGE_SIZE);
    const page = btn.getAttribute("data-page");

    if (page === "prev") {
      if (state.currentPage > 1) {
        state.currentPage -= 1;
      }
    } else if (page === "next") {
      if (state.currentPage < totalPages) {
        state.currentPage += 1;
      }
    } else {
      const numericPage = Number(page);
      if (Number.isFinite(numericPage) && numericPage >= 1 && numericPage <= totalPages) {
        state.currentPage = numericPage;
      }
    }

    renderResultsPage();
    updateResultsHeader();
    window.scrollTo({ top: 0, behavior: "smooth" });
  });

  el.closeModal.addEventListener("click", closeCaseModal);
  el.modalBackdrop.addEventListener("click", closeCaseModal);
  el.modalQuery.addEventListener("input", filterModalParagraphs);
  el.modalSectionFilter.addEventListener("change", filterModalParagraphs);

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      if (state.classifierOpen) {
        closeClassifierPane();
        return;
      }

      if (!el.caseModal.hidden) {
        closeCaseModal();
        return;
      }
    }

    if (e.key === "/" && !["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName)) {
      if (!el.searchInput.disabled) {
        e.preventDefault();
        el.searchInput.focus();
      }
    }
  });
}

function init() {
  cacheElements();
  initTheme();
  bindEvents();

  setSearchEnabled(false);
  setDatasetMeta("Dataset: not selected");
  setDatasetStatus("No dataset loaded yet. Choose sample dataset or upload your JSONL file.");
  el.classifierResumeNote.classList.add("hidden");
  setClassifierPersistStatus("No saved state loaded.");
  setClassifierModelStatus("Model not trained yet.");

  el.resultsHeader.hidden = true;
  el.noResults.hidden = true;
  el.pagination.hidden = true;

  renderBarList(el.analyticsArticles, [], (x) => x);
  renderBarList(el.analyticsCountries, [], (x) => x);
  renderBarList(el.analyticsSections, [], (x) => x);
  renderBarList(el.analyticsBodies, [], (x) => x);
  renderBarList(el.analyticsImportance, [], (x) => x);
  renderBarList(el.analyticsOutcomes, [], (x) => x);
  renderWordCloud([]);
}

init();
