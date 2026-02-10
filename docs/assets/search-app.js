const SAMPLE_DATA_URL = "data/echr_cases_sample50.jsonl";
const PAGE_SIZE = 20;
const MAX_HITS = 5000;

const SECTION_ORDER = [
  "introduction",
  "facts_background",
  "facts_proceedings",
  "legal_framework",
  "admissibility",
  "merits",
  "just_satisfaction",
  "article_46",
  "operative_part",
  "separate_opinion",
];

const SECTION_LABELS = {
  header: "Header",
  introduction: "Introduction",
  facts_background: "Facts (Background)",
  facts_proceedings: "Facts (Proceedings)",
  legal_framework: "Legal Framework",
  admissibility: "Admissibility",
  merits: "Merits",
  just_satisfaction: "Just Satisfaction",
  article_46: "Article 46 (Execution)",
  operative_part: "Operative Part",
  separate_opinion: "Separate Opinion",
};

const SECTION_COLORS = {
  header: "#718096",
  introduction: "#4C72B0",
  facts_background: "#DD8452",
  facts_proceedings: "#C44E52",
  legal_framework: "#937860",
  admissibility: "#8172B3",
  merits: "#55A868",
  just_satisfaction: "#DA8BC3",
  article_46: "#CCB974",
  operative_part: "#64B5CD",
  separate_opinion: "#8C8C8C",
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
  sourceLabel: "",
  cases: [],
  caseById: new Map(),
  paragraphIndex: [],
  sortedCaseIdsByDate: [],
  articles: [],
  countries: [],
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
};

const el = {};

function byId(id) {
  return document.getElementById(id);
}

function cacheElements() {
  el.themeToggle = byId("themeToggle");

  el.loadSampleBtn = byId("loadSampleBtn");
  el.fileInput = byId("fileInput");
  el.dropZone = byId("dropZone");
  el.datasetStatus = byId("datasetStatus");
  el.datasetMeta = byId("datasetMeta");

  el.searchForm = byId("searchForm");
  el.searchInput = byId("searchInput");
  el.searchBtn = byId("searchBtn");
  el.filterToggleBtn = byId("filterToggleBtn");
  el.filtersPanel = byId("filtersPanel");

  el.sectionsFilters = byId("sectionsFilters");
  el.countriesFilters = byId("countriesFilters");
  el.articlesFilters = byId("articlesFilters");
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
  el.clearBtn = byId("clearBtn");
  el.activeFilters = byId("activeFilters");

  el.noResults = byId("noResults");
  el.backToSearch = byId("backToSearch");
  el.casesList = byId("casesList");
  el.pagination = byId("pagination");

  el.analyticsArticles = byId("analyticsArticles");
  el.analyticsCountries = byId("analyticsCountries");
  el.analyticsSections = byId("analyticsSections");
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

  const dynamicInputs = document.querySelectorAll(
    "#sectionsFilters input, #countriesFilters input, #articlesFilters input, #chamberFilters input"
  );
  for (const input of dynamicInputs) {
    input.disabled = !enabled;
  }

  el.searchForm.classList.toggle("search-disabled", !enabled);

  el.exportBtn.disabled = !enabled || !state.currentOrderedCaseIds.length;
  el.clearBtn.disabled = !enabled;
}

function setDatasetLoading(loading) {
  el.loadSampleBtn.disabled = loading;
  el.fileInput.disabled = loading;
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

    const defendants = Array.isArray(caseObj.defendants)
      ? caseObj.defendants.map((d) => String(d).trim()).filter(Boolean)
      : [];

    const documentType = Array.isArray(caseObj.document_type)
      ? caseObj.document_type.map((d) => String(d).trim()).filter(Boolean)
      : [];

    const rawParagraphs = Array.isArray(caseObj.paragraphs) ? caseObj.paragraphs : [];
    const parsedParagraphs = [];

    for (let p = 0; p < rawParagraphs.length; p += 1) {
      const para = rawParagraphs[p] || {};
      const section = String(para.section || "unknown").trim() || "unknown";
      const text = String(para.text || "").trim();
      if (!text || section === "header") continue;

      const idx = Number(para.para_idx);
      const paraIdx = Number.isFinite(idx) ? idx : p;

      parsedParagraphs.push({
        section,
        paraIdx,
        text,
        textLower: text.toLowerCase(),
      });
    }

    const ts = parseDateInput(caseObj.judgment_date);

    normalized.push({
      ...caseObj,
      case_id: caseId,
      defendants,
      document_type: documentType,
      __articles: splitArticles(caseObj.article_no),
      __judgmentDateTs: ts,
      __sortTs: ts == null ? -Infinity : ts,
      __paragraphs: parsedParagraphs,
    });
  }

  return normalized;
}

function preprocessDataset(cases) {
  const articles = new Set();
  const countries = new Set();

  state.cases = cases;
  state.caseById = new Map();
  state.paragraphIndex = [];

  for (let caseIdx = 0; caseIdx < cases.length; caseIdx += 1) {
    const c = cases[caseIdx];
    state.caseById.set(c.case_id, c);

    for (const a of c.__articles) {
      articles.add(a);
    }
    for (const d of c.defendants) {
      countries.add(d);
    }

    for (const para of c.__paragraphs) {
      state.paragraphIndex.push({
        caseIdx,
        caseId: c.case_id,
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
  state.loaded = true;
}

function makeCheckbox(label, value, name) {
  return `<label class="cb-label"><input type="checkbox" data-name="${name}" value="${escapeHtml(value)}"> <span>${escapeHtml(label)}</span></label>`;
}

function renderFilters() {
  el.sectionsFilters.innerHTML = SECTION_ORDER
    .map((sec) => makeCheckbox(SECTION_LABELS[sec] || sec, sec, "sections"))
    .join("");

  el.countriesFilters.innerHTML = state.countries
    .map((code) => makeCheckbox(COUNTRY_NAMES[code] || code, code, "countries"))
    .join("");

  el.articlesFilters.innerHTML = state.articles
    .map((article) => makeCheckbox(`Art. ${article}`, article, "articles"))
    .join("");
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
    caseTypes: collectCheckedValuesIn(el.chamberFilters),
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
    for (const d of c.defendants) {
      if (filters.countries.has(d)) {
        ok = true;
        break;
      }
    }
    if (!ok) return false;
  }

  if (filters.caseTypes.size) {
    let ok = false;
    for (const t of c.document_type) {
      if (filters.caseTypes.has(t)) {
        ok = true;
        break;
      }
    }
    if (!ok) return false;
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
  for (const t of filters.caseTypes) {
    chips.push(`<span class="filter-chip">${escapeHtml(t)}</span>`);
  }
  if (el.dateFrom.value) {
    chips.push(`<span class="filter-chip">From: ${escapeHtml(el.dateFrom.value)}</span>`);
  }
  if (el.dateTo.value) {
    chips.push(`<span class="filter-chip">To: ${escapeHtml(el.dateTo.value)}</span>`);
  }

  el.activeFilters.innerHTML = chips.join("");
}

function buildCaseCard(caseId, row) {
  const c = row.case;
  const defendantLabel = (c.defendants || []).map((d) => COUNTRY_NAMES[d] || d).join(", ");

  const paraBlocks = row.paragraphs
    .map((p) => {
      return `
        <div class="paragraph-item">
          <div class="para-header">
            <span class="para-section">${escapeHtml(p.sectionLabel)}</span>
            <span class="para-num">¶ ${p.paraIdx + 1}</span>
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
          <div class="case-meta">
            <span class="meta-item">📋 ${escapeHtml(c.case_no || "-")}</span>
            <span class="meta-item">📅 ${escapeHtml(c.judgment_date || "-")}</span>
            <span class="meta-item">🏳️ ${escapeHtml(defendantLabel || "-")}</span>
            <span class="meta-item">📜 ${escapeHtml(c.article_no || "-")}</span>
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
  const wordCounts = new Map();

  for (const caseId of state.currentOrderedCaseIds) {
    const data = state.currentResultsById.get(caseId);
    if (!data) continue;

    for (const d of data.case.defendants || []) {
      countryCounts.set(d, (countryCounts.get(d) || 0) + data.hitCount);
    }

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

  const checks = document.querySelectorAll("#filtersPanel input[type='checkbox']");
  for (const c of checks) {
    c.checked = false;
  }

  applySearch(true);
}

function exportCsv() {
  if (!state.currentOrderedCaseIds.length) return;

  const rows = [
    ["Case ID", "Case No", "Title", "Judgment Date", "Defendants", "Articles", "Section", "Paragraph", "Text"],
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
        p.sectionLabel,
        String(p.paraIdx + 1),
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

  const defendants = (caseObj.defendants || []).map((d) => COUNTRY_NAMES[d] || d).join(", ") || "-";
  parts.push(`Defendants: ${escapeHtml(defendants)}`);
  parts.push(`Articles: ${escapeHtml(caseObj.article_no || "-")}`);

  if (Array.isArray(caseObj.violation) && caseObj.violation.length) {
    parts.push(`Violation: ${escapeHtml(caseObj.violation.join("; "))}`);
  }

  if (Array.isArray(caseObj["non-violation"]) && caseObj["non-violation"].length) {
    parts.push(`No violation: ${escapeHtml(caseObj["non-violation"].join("; "))}`);
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
    if (e.key === "Escape" && !el.caseModal.hidden) {
      closeCaseModal();
      return;
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

  el.resultsHeader.hidden = true;
  el.noResults.hidden = true;
  el.pagination.hidden = true;

  renderBarList(el.analyticsArticles, [], (x) => x);
  renderBarList(el.analyticsCountries, [], (x) => x);
  renderBarList(el.analyticsSections, [], (x) => x);
  renderWordCloud([]);
}

init();
