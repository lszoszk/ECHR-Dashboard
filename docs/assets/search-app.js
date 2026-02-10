const DATA_URL = "data/echr_cases.jsonl";
const MAX_HITS = 1000;

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

let CASES = [];
let CASES_BY_ID = new Map();
let PARAGRAPH_INDEX = [];
let ARTICLES = [];
let COUNTRIES = [];
let LAST_RESULTS = [];
let LAST_RESULTS_MAP = new Map();
let LAST_QUERY_TERMS = [];
let LAST_QUERY = "";
let CURRENT_MODAL_CASE_ID = null;

function escapeHtml(text) {
  return String(text)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function escapeRegExp(text) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function parseDate(raw) {
  if (!raw) return null;
  const s = String(raw).trim();
  if (!s) return null;

  let m = s.match(/^(\d{2})\/(\d{2})\/(\d{4})$/);
  if (m) {
    const d = Number(m[1]);
    const mo = Number(m[2]);
    const y = Number(m[3]);
    return new Date(Date.UTC(y, mo - 1, d));
  }

  m = s.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (m) {
    const y = Number(m[1]);
    const mo = Number(m[2]);
    const d = Number(m[3]);
    return new Date(Date.UTC(y, mo - 1, d));
  }

  m = s.match(/^(\d{4})\/(\d{2})\/(\d{2})$/);
  if (m) {
    const y = Number(m[1]);
    const mo = Number(m[2]);
    const d = Number(m[3]);
    return new Date(Date.UTC(y, mo - 1, d));
  }

  m = s.match(/^(\d{4})$/);
  if (m) {
    return new Date(Date.UTC(Number(m[1]), 0, 1));
  }

  return null;
}

function parseDateInput(raw) {
  const dt = parseDate(raw);
  return dt ? dt.getTime() : null;
}

function parseQuery(query) {
  if (!query || !query.trim()) return { andTerms: [], orGroups: [] };

  const phrases = [...query.matchAll(/"([^"]+)"/g)].map((m) => m[1].trim().toLowerCase()).filter(Boolean);
  const remaining = query.replace(/"[^"]*"/g, " ").trim();

  const andTerms = [];
  const orGroups = [];

  const parts = remaining.split(/\s+[oO][rR]\s+/).map((p) => p.trim()).filter(Boolean);
  if (parts.length > 1) {
    orGroups.push(parts.map((p) => p.toLowerCase()));
  } else {
    for (const token of remaining.split(/\s+/)) {
      const t = token.trim();
      if (t) andTerms.push(t.toLowerCase());
    }
  }

  for (const phrase of phrases) {
    andTerms.push(phrase);
  }

  return { andTerms, orGroups };
}

function highlightTerms(text, terms) {
  let html = escapeHtml(text);
  const ordered = [...new Set(terms)].sort((a, b) => b.length - a.length);
  for (const term of ordered) {
    if (!term) continue;
    const re = new RegExp(escapeRegExp(escapeHtml(term)), "gi");
    html = html.replace(re, (m) => `<mark class="hl">${m}</mark>`);
  }
  return html;
}

function splitArticles(articleNo) {
  if (!articleNo) return [];
  return String(articleNo)
    .split(/[;,]/)
    .map((x) => x.trim())
    .filter(Boolean);
}

function makeCheckbox(label, value, name) {
  return `<label class="cb-label"><input type="checkbox" data-name="${name}" value="${escapeHtml(value)}"> <span>${escapeHtml(label)}</span></label>`;
}

function setLoadingStatus(message) {
  const el = document.getElementById("loadMeta");
  if (el) el.textContent = `Status: ${message}`;
}

function renderGlobalStats() {
  const totalCases = CASES.length;
  const totalParagraphs = PARAGRAPH_INDEX.length;
  const countriesCount = COUNTRIES.length;

  const dates = CASES.map((c) => c.__judgmentDateTs).filter((x) => Number.isFinite(x)).sort((a, b) => a - b);
  let dateRange = "n/a";
  if (dates.length) {
    const from = new Date(dates[0]).toISOString().slice(0, 10);
    const to = new Date(dates[dates.length - 1]).toISOString().slice(0, 10);
    dateRange = `${from} to ${to}`;
  }

  const html = [
    `<article class="stat-chip"><span class="stat-value">${fmtInt.format(totalCases)}</span><span class="stat-label">Cases</span></article>`,
    `<article class="stat-chip"><span class="stat-value">${fmtInt.format(totalParagraphs)}</span><span class="stat-label">Indexed Paragraphs</span></article>`,
    `<article class="stat-chip"><span class="stat-value">${fmtInt.format(countriesCount)}</span><span class="stat-label">Respondent States</span></article>`,
    `<article class="stat-chip"><span class="stat-value">${escapeHtml(dateRange)}</span><span class="stat-label">Judgment Date Range</span></article>`,
  ].join("");

  document.getElementById("globalStats").innerHTML = html;
}

function renderFilters() {
  const sectionsHtml = SECTION_ORDER.map((sec) => makeCheckbox(SECTION_LABELS[sec] || sec, sec, "sections")).join("");
  document.getElementById("sectionsFilters").innerHTML = sectionsHtml;

  const countriesHtml = COUNTRIES.map((code) => makeCheckbox(COUNTRY_NAMES[code] || code, code, "countries")).join("");
  document.getElementById("countriesFilters").innerHTML = countriesHtml;

  const articlesHtml = ARTICLES.map((a) => makeCheckbox(`Art. ${a}`, a, "articles")).join("");
  document.getElementById("articlesFilters").innerHTML = articlesHtml;
}

function collectChecked(name) {
  return new Set(
    [...document.querySelectorAll(`input[data-name="${name}"]:checked`)].map((el) => el.value)
  );
}

function collectCheckedValuesIn(containerId) {
  return new Set(
    [...document.querySelectorAll(`#${containerId} input[type="checkbox"]:checked`)].map((el) => el.value)
  );
}

function searchParagraphs(query, filters) {
  const { andTerms, orGroups } = parseQuery(query);
  const allTerms = [...andTerms, ...orGroups.flat()];
  if (!allTerms.length) {
    return { orderedIds: [], resultsMap: new Map(), totalHits: 0, limited: false, terms: [] };
  }

  const resultsMap = new Map();
  let totalHits = 0;
  let limited = false;

  for (const entry of PARAGRAPH_INDEX) {
    if (filters.sections.size && !filters.sections.has(entry.section)) {
      continue;
    }

    const c = CASES[entry.caseIdx];

    if (filters.articles.size) {
      let articleMatch = false;
      for (const a of c.__articles) {
        if (filters.articles.has(a)) {
          articleMatch = true;
          break;
        }
      }
      if (!articleMatch) continue;
    }

    if (filters.countries.size) {
      let countryMatch = false;
      for (const d of c.defendants || []) {
        if (filters.countries.has(d)) {
          countryMatch = true;
          break;
        }
      }
      if (!countryMatch) continue;
    }

    if (filters.caseTypes.size) {
      let typeMatch = false;
      for (const t of c.document_type || []) {
        if (filters.caseTypes.has(t)) {
          typeMatch = true;
          break;
        }
      }
      if (!typeMatch) continue;
    }

    if (filters.dateFrom != null && (c.__judgmentDateTs == null || c.__judgmentDateTs < filters.dateFrom)) {
      continue;
    }
    if (filters.dateTo != null && (c.__judgmentDateTs == null || c.__judgmentDateTs > filters.dateTo)) {
      continue;
    }

    const textLower = entry.textLower;

    let andOk = true;
    for (const term of andTerms) {
      if (!textLower.includes(term)) {
        andOk = false;
        break;
      }
    }
    if (!andOk) continue;

    let orOk = true;
    for (const group of orGroups) {
      let groupMatch = false;
      for (const term of group) {
        if (textLower.includes(term)) {
          groupMatch = true;
          break;
        }
      }
      if (!groupMatch) {
        orOk = false;
        break;
      }
    }
    if (!orOk) continue;

    const caseId = c.case_id;
    if (!resultsMap.has(caseId)) {
      resultsMap.set(caseId, { case: c, paragraphs: [], hitCount: 0 });
    }

    const item = resultsMap.get(caseId);
    item.paragraphs.push({
      section: entry.section,
      sectionLabel: SECTION_LABELS[entry.section] || entry.section,
      sectionColor: SECTION_COLORS[entry.section] || "#718096",
      paraIdx: entry.paraIdx,
      rawText: entry.text,
      textHtml: highlightTerms(entry.text, allTerms),
    });
    item.hitCount += 1;
    totalHits += 1;

    if (totalHits >= MAX_HITS) {
      limited = true;
      break;
    }
  }

  const orderedIds = [...resultsMap.entries()]
    .sort((a, b) => b[1].hitCount - a[1].hitCount)
    .map((x) => x[0]);

  return { orderedIds, resultsMap, totalHits, limited, terms: allTerms };
}

function renderResults(orderedIds, resultsMap) {
  const list = document.getElementById("resultsList");
  if (!orderedIds.length) {
    list.innerHTML = `<article class="error">No results found. Try broader terms or fewer filters.</article>`;
    return;
  }

  const cards = [];
  for (const caseId of orderedIds) {
    const data = resultsMap.get(caseId);
    const c = data.case;
    const defendants = (c.defendants || []).map((d) => COUNTRY_NAMES[d] || d).join(", ");

    const paras = data.paragraphs
      .map((p) => {
        return `
          <article class="paragraph-item">
            <div class="para-header">
              <span class="section-pill" style="background:${escapeHtml(p.sectionColor)}">${escapeHtml(p.sectionLabel)}</span>
              <span class="para-num">¶ ${p.paraIdx + 1}</span>
              <button type="button" class="copy-btn" data-action="copy-paragraph" data-text="${escapeHtml(p.rawText)}">Copy</button>
            </div>
            <p class="para-text">${p.textHtml}</p>
          </article>
        `;
      })
      .join("");

    cards.push(`
      <article class="case-card" id="case-${escapeHtml(caseId)}">
        <div class="case-header">
          <div>
            <h2 class="case-title">${escapeHtml(c.title || "Untitled case")}</h2>
            <div class="case-meta">
              <span>Case no: ${escapeHtml(c.case_no || "-")}</span>
              <span>Judgment: ${escapeHtml(c.judgment_date || "-")}</span>
              <span>Defendants: ${escapeHtml(defendants || "-")}</span>
              <span>Articles: ${escapeHtml(c.article_no || "-")}</span>
            </div>
          </div>
          <div class="case-badge">
            <span class="hit-count">${fmtInt.format(data.hitCount)}</span>
            <button type="button" class="toggle-btn" data-action="toggle-case" data-case-id="${escapeHtml(caseId)}">Open</button>
          </div>
        </div>
        <div class="case-body" id="body-${escapeHtml(caseId)}">
          ${paras}
          <div class="case-footer">
            <button type="button" class="open-btn" data-action="open-case" data-case-id="${escapeHtml(caseId)}">View full judgment</button>
          </div>
        </div>
      </article>
    `);
  }

  list.innerHTML = cards.join("");

  if (orderedIds.length) {
    const first = orderedIds[0];
    const firstBody = document.getElementById(`body-${first}`);
    const firstBtn = document.querySelector(`button[data-action="toggle-case"][data-case-id="${first}"]`);
    if (firstBody) firstBody.classList.add("open");
    if (firstBtn) firstBtn.textContent = "Close";
  }
}

function computeAnalytics(resultsMap, orderedIds) {
  const countryCounts = new Map();
  const articleCounts = new Map();
  const sectionCounts = new Map();
  const wordCounts = new Map();

  for (const caseId of orderedIds) {
    const data = resultsMap.get(caseId);
    const c = data.case;

    for (const d of c.defendants || []) {
      countryCounts.set(d, (countryCounts.get(d) || 0) + data.hitCount);
    }

    for (const a of c.__articles) {
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

function renderBarList(containerId, rows, labelTransform = (x) => x, color = "var(--accent)") {
  const el = document.getElementById(containerId);
  if (!rows.length) {
    el.className = "bar-list empty";
    el.textContent = "No data";
    return;
  }

  const max = rows[0][1] || 1;
  const html = rows
    .map(([label, value]) => {
      const width = Math.max(2, Math.round((value / max) * 100));
      return `
        <div class="bar-item">
          <span>${escapeHtml(labelTransform(label))}</span>
          <span class="bar-track"><span class="bar-fill" style="width:${width}%;background:${color}"></span></span>
          <span class="bar-value">${fmtInt.format(value)}</span>
        </div>
      `;
    })
    .join("");

  el.className = "bar-list";
  el.innerHTML = html;
}

function renderWordCloud(containerId, rows) {
  const el = document.getElementById(containerId);
  if (!rows.length) {
    el.className = "word-cloud empty";
    el.textContent = "No data";
    return;
  }

  const max = rows[0][1] || 1;
  const html = rows
    .map(([w, count]) => {
      const scale = count / max;
      const size = 0.7 + scale * 0.6;
      const opacity = 0.55 + scale * 0.45;
      return `<span class="word-tag" style="font-size:${size.toFixed(2)}rem;opacity:${opacity.toFixed(2)}">${escapeHtml(w)}</span>`;
    })
    .join("");

  el.className = "word-cloud";
  el.innerHTML = html;
}

function renderAnalytics(analytics) {
  renderBarList(
    "analyticsArticles",
    analytics.articles,
    (label) => `Art. ${label}`,
    "#245ea8"
  );
  renderBarList(
    "analyticsCountries",
    analytics.countries,
    (label) => COUNTRY_NAMES[label] || label,
    "#1c7d4b"
  );
  renderBarList("analyticsSections", analytics.sections, (label) => label, "#8172B3");
  renderWordCloud("analyticsWords", analytics.words);
}

function updateResultsHeader(stats) {
  const header = document.getElementById("resultsHeader");
  header.hidden = false;

  const totalCases = stats.orderedIds.length;
  const totalHits = stats.totalHits;
  const time = stats.searchTimeMs / 1000;

  const limitedNote = stats.limited ? ` (limited to ${MAX_HITS} paragraph hits)` : "";
  document.getElementById("resultsCount").textContent = fmtInt.format(totalHits);
  document.getElementById("resultsMeta").textContent = `paragraph hits in ${fmtInt.format(totalCases)} cases · ${time.toFixed(3)}s${limitedNote}`;
}

function runSearch() {
  const query = document.getElementById("queryInput").value.trim();
  LAST_QUERY = query;

  const placeholder = document.getElementById("placeholderCard");
  if (placeholder) placeholder.classList.add("hidden");

  if (!query) {
    document.getElementById("resultsList").innerHTML = `<article class="error">Enter a query first.</article>`;
    document.getElementById("resultsHeader").hidden = true;
    renderAnalytics({ countries: [], articles: [], sections: [], words: [] });
    LAST_RESULTS = [];
    LAST_RESULTS_MAP = new Map();
    return;
  }

  const filters = {
    sections: collectChecked("sections"),
    countries: collectChecked("countries"),
    articles: collectChecked("articles"),
    caseTypes: collectCheckedValuesIn("chamberFilters"),
    dateFrom: parseDateInput(document.getElementById("dateFrom").value),
    dateTo: parseDateInput(document.getElementById("dateTo").value),
  };

  const t0 = performance.now();
  const result = searchParagraphs(query, filters);
  const t1 = performance.now();

  LAST_RESULTS = result.orderedIds;
  LAST_RESULTS_MAP = result.resultsMap;
  LAST_QUERY_TERMS = result.terms;

  renderResults(result.orderedIds, result.resultsMap);
  renderAnalytics(computeAnalytics(result.resultsMap, result.orderedIds));
  updateResultsHeader({
    orderedIds: result.orderedIds,
    totalHits: result.totalHits,
    limited: result.limited,
    searchTimeMs: t1 - t0,
  });
}

function clearSearch() {
  document.getElementById("queryInput").value = "";
  document.getElementById("dateFrom").value = "";
  document.getElementById("dateTo").value = "";

  for (const cb of document.querySelectorAll("input[type='checkbox']")) {
    cb.checked = false;
  }

  document.getElementById("resultsList").innerHTML = "";
  document.getElementById("resultsHeader").hidden = true;
  const placeholder = document.getElementById("placeholderCard");
  if (placeholder) placeholder.classList.remove("hidden");

  renderAnalytics({ countries: [], articles: [], sections: [], words: [] });
  LAST_RESULTS = [];
  LAST_RESULTS_MAP = new Map();
  LAST_QUERY_TERMS = [];
  LAST_QUERY = "";
}

function exportCsv() {
  if (!LAST_RESULTS.length) return;

  const rows = [
    ["Case ID", "Case No", "Title", "Judgment Date", "Defendants", "Articles", "Section", "Paragraph", "Text"],
  ];

  for (const caseId of LAST_RESULTS) {
    const data = LAST_RESULTS_MAP.get(caseId);
    const c = data.case;
    for (const p of data.paragraphs) {
      rows.push([
        caseId,
        c.case_no || "",
        c.title || "",
        c.judgment_date || "",
        (c.defendants || []).join(", "),
        c.article_no || "",
        p.sectionLabel,
        String((p.paraIdx || 0) + 1),
        p.rawText || "",
      ]);
    }
  }

  const csv = rows
    .map((row) =>
      row
        .map((cell) => {
          const v = String(cell ?? "");
          const escaped = v.replaceAll('"', '""');
          return `"${escaped}"`;
        })
        .join(",")
    )
    .join("\n");

  const blob = new Blob([`\uFEFF${csv}`], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  const suffix = LAST_QUERY ? LAST_QUERY.slice(0, 24).replace(/\s+/g, "_") : "results";
  a.href = url;
  a.download = `echr_search_${suffix}.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function toggleCase(caseId) {
  const body = document.getElementById(`body-${caseId}`);
  const btn = document.querySelector(`button[data-action='toggle-case'][data-case-id='${caseId}']`);
  if (!body || !btn) return;

  const isOpen = body.classList.toggle("open");
  btn.textContent = isOpen ? "Close" : "Open";
}

function buildCaseMeta(caseObj) {
  const parts = [];
  parts.push(`Case no: ${escapeHtml(caseObj.case_no || "-")}`);
  parts.push(`Judgment: ${escapeHtml(caseObj.judgment_date || "-")}`);

  const defendants = (caseObj.defendants || []).map((d) => COUNTRY_NAMES[d] || d).join(", ") || "-";
  parts.push(`Defendants: ${escapeHtml(defendants)}`);
  parts.push(`Articles: ${escapeHtml(caseObj.article_no || "-")}`);

  if (caseObj.violation && caseObj.violation.length) {
    parts.push(`Violation: ${escapeHtml(caseObj.violation.join("; "))}`);
  }
  if (caseObj["non-violation"] && caseObj["non-violation"].length) {
    parts.push(`No violation: ${escapeHtml(caseObj["non-violation"].join("; "))}`);
  }

  return parts.join(" · ");
}

function openCaseModal(caseId) {
  const c = CASES_BY_ID.get(caseId);
  if (!c) return;

  CURRENT_MODAL_CASE_ID = caseId;

  document.getElementById("modalTitle").textContent = c.title || "Untitled case";
  document.getElementById("modalMeta").innerHTML = buildCaseMeta(c);
  document.getElementById("modalQuery").value = "";

  const sectionSelect = document.getElementById("modalSectionFilter");
  sectionSelect.innerHTML = `<option value="all">All sections</option>`;

  const availableSections = new Set();
  const grouped = new Map();

  for (const para of c.paragraphs || []) {
    if (!para || para.section === "header") continue;
    const text = String(para.text || "").trim();
    if (!text) continue;
    const sec = para.section || "unknown";
    availableSections.add(sec);
    if (!grouped.has(sec)) grouped.set(sec, []);
    grouped.get(sec).push({
      paraIdx: para.para_idx || 0,
      text,
      textLower: text.toLowerCase(),
    });
  }

  for (const sec of SECTION_ORDER) {
    if (!availableSections.has(sec)) continue;
    const label = SECTION_LABELS[sec] || sec;
    sectionSelect.insertAdjacentHTML("beforeend", `<option value="${escapeHtml(sec)}">${escapeHtml(label)}</option>`);
  }

  for (const sec of [...availableSections].sort()) {
    if (SECTION_ORDER.includes(sec)) continue;
    const label = SECTION_LABELS[sec] || sec;
    sectionSelect.insertAdjacentHTML("beforeend", `<option value="${escapeHtml(sec)}">${escapeHtml(label)}</option>`);
  }

  const bodyHtml = [];
  for (const sec of SECTION_ORDER) {
    if (!grouped.has(sec)) continue;
    bodyHtml.push(renderModalSection(sec, grouped.get(sec)));
  }
  for (const sec of [...grouped.keys()].sort()) {
    if (SECTION_ORDER.includes(sec)) continue;
    bodyHtml.push(renderModalSection(sec, grouped.get(sec)));
  }

  document.getElementById("modalBody").innerHTML = bodyHtml.join("");

  document.getElementById("modalCount").textContent = `${fmtInt.format(document.querySelectorAll(".modal-para").length)} paragraphs`;

  const modal = document.getElementById("caseModal");
  modal.hidden = false;
  document.body.style.overflow = "hidden";
}

function renderModalSection(sectionKey, paragraphs) {
  const label = SECTION_LABELS[sectionKey] || sectionKey;
  const color = SECTION_COLORS[sectionKey] || "#4C72B0";

  const parasHtml = paragraphs
    .map(
      (p) => `
      <p class="modal-para" data-section="${escapeHtml(sectionKey)}" data-text="${escapeHtml(p.textLower)}">
        <span class="modal-para-num">¶ ${p.paraIdx + 1}</span>
        <span>${escapeHtml(p.text)}</span>
      </p>
    `
    )
    .join("");

  return `
    <section class="modal-section" data-section="${escapeHtml(sectionKey)}">
      <h3 style="border-bottom-color:${escapeHtml(color)}66">${escapeHtml(label)}</h3>
      ${parasHtml}
    </section>
  `;
}

function closeCaseModal() {
  CURRENT_MODAL_CASE_ID = null;
  const modal = document.getElementById("caseModal");
  modal.hidden = true;
  document.body.style.overflow = "";
}

function filterModalParagraphs() {
  if (!CURRENT_MODAL_CASE_ID) return;

  const q = document.getElementById("modalQuery").value.trim().toLowerCase();
  const sec = document.getElementById("modalSectionFilter").value;
  const paras = [...document.querySelectorAll(".modal-para")];
  let visibleCount = 0;

  for (const p of paras) {
    const text = p.getAttribute("data-text") || "";
    const pSec = p.getAttribute("data-section") || "";

    const secOk = sec === "all" || sec === pSec;
    const queryOk = !q || text.includes(q);

    const show = secOk && queryOk;
    p.classList.toggle("hidden", !show);
    p.classList.toggle("visible-hit", !!q && show);
    if (show) visibleCount += 1;
  }

  for (const section of document.querySelectorAll(".modal-section")) {
    const hasVisible = section.querySelector(".modal-para:not(.hidden)");
    section.classList.toggle("hidden", !hasVisible);
  }

  document.getElementById("modalCount").textContent = q
    ? `${fmtInt.format(visibleCount)} matching paragraphs`
    : `${fmtInt.format(visibleCount)} paragraphs`;
}

function bindUI() {
  document.getElementById("searchForm").addEventListener("submit", (e) => {
    e.preventDefault();
    runSearch();
  });

  document.getElementById("toggleFilters").addEventListener("click", (e) => {
    const panel = document.getElementById("filtersPanel");
    const open = panel.classList.toggle("open");
    e.currentTarget.setAttribute("aria-expanded", open ? "true" : "false");
  });

  document.getElementById("clearBtn").addEventListener("click", clearSearch);
  document.getElementById("exportBtn").addEventListener("click", exportCsv);

  document.getElementById("resultsList").addEventListener("click", (e) => {
    const button = e.target.closest("button");
    if (!button) return;

    const action = button.getAttribute("data-action");
    if (!action) return;

    if (action === "toggle-case") {
      const id = button.getAttribute("data-case-id");
      if (id) toggleCase(id);
      return;
    }

    if (action === "copy-paragraph") {
      const text = button.getAttribute("data-text") || "";
      navigator.clipboard?.writeText(text).then(() => {
        const original = button.textContent;
        button.textContent = "Copied";
        setTimeout(() => {
          button.textContent = original;
        }, 1200);
      });
      return;
    }

    if (action === "open-case") {
      const id = button.getAttribute("data-case-id");
      if (id) openCaseModal(id);
    }
  });

  document.getElementById("closeModal").addEventListener("click", closeCaseModal);
  document.querySelector(".modal-backdrop").addEventListener("click", closeCaseModal);

  document.getElementById("modalQuery").addEventListener("input", filterModalParagraphs);
  document.getElementById("modalSectionFilter").addEventListener("change", filterModalParagraphs);

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !document.getElementById("caseModal").hidden) {
      closeCaseModal();
    }
    if (e.key === "/" && !["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName)) {
      e.preventDefault();
      document.getElementById("queryInput").focus();
    }
  });
}

function preprocessCases(cases) {
  const articles = new Set();
  const countries = new Set();

  CASES = cases;
  CASES_BY_ID = new Map();
  PARAGRAPH_INDEX = [];

  for (let i = 0; i < CASES.length; i += 1) {
    const c = CASES[i];
    CASES_BY_ID.set(c.case_id, c);

    c.__articles = splitArticles(c.article_no);
    c.__judgmentDateTs = parseDateInput(c.judgment_date);

    for (const a of c.__articles) {
      articles.add(a);
    }
    for (const d of c.defendants || []) {
      countries.add(d);
    }

    for (const para of c.paragraphs || []) {
      const text = String(para?.text || "").trim();
      const section = para?.section || "unknown";
      if (!text || section === "header") continue;
      PARAGRAPH_INDEX.push({
        caseIdx: i,
        section,
        paraIdx: Number(para.para_idx || 0),
        text,
        textLower: text.toLowerCase(),
      });
    }
  }

  ARTICLES = [...articles].sort((a, b) => (a.length - b.length) || a.localeCompare(b));
  COUNTRIES = [...countries].sort((a, b) => (COUNTRY_NAMES[a] || a).localeCompare(COUNTRY_NAMES[b] || b));
}

async function loadJsonl(url) {
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`Failed to load ${url} (${res.status})`);
  }
  const text = await res.text();
  const lines = text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);

  const rows = [];
  for (const line of lines) {
    try {
      rows.push(JSON.parse(line));
    } catch {
      // Skip malformed lines to keep app robust.
    }
  }
  return rows;
}

async function init() {
  bindUI();
  setLoadingStatus("loading dataset...");

  try {
    const rows = await loadJsonl(DATA_URL);
    preprocessCases(rows);
    renderFilters();
    renderGlobalStats();

    document.getElementById("datasetMeta").textContent = `Dataset: ${DATA_URL}`;
    setLoadingStatus(`ready (${fmtInt.format(CASES.length)} cases, ${fmtInt.format(PARAGRAPH_INDEX.length)} indexed paragraphs)`);
  } catch (err) {
    console.error(err);
    setLoadingStatus("failed");
    const list = document.getElementById("resultsList");
    list.innerHTML = `<article class="error">Could not load dataset: ${escapeHtml(err.message)}</article>`;
  }
}

init();
