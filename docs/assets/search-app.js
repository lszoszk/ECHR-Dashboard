const SAMPLE_DATA_URL = "data/echr_cases_sample50.jsonl";
const PAGE_SIZE = 20;
const MAX_HITS = 5000;

// ---------------------------------------------------------------------------
// Server-side search API integration
// ---------------------------------------------------------------------------
// API base URL.  Three sources, in priority order:
//   1. ?api=… query param         (one-shot override for testing)
//   2. localStorage echrApiBase   (sticky local-dev pin)
//   3. auto-detect localhost      (FastAPI on :8000 if served from 127.0.0.1)
//   4. production VM              (default)
const API_BASE_URL = (() => {
  try {
    const qp = new URLSearchParams(location.search).get("api");
    if (qp) {
      // Persist an explicit ?api= override so later visits to the bare
      // URL keep using the same backend (e.g. local dev pointed at prod).
      const clean = qp.replace(/\/+$/, "");
      try { localStorage.setItem("echrApiBase", clean); } catch (_) { /* private mode */ }
      return clean;
    }
    const ls = localStorage.getItem("echrApiBase");
    if (ls) return ls.replace(/\/+$/, "");
    if (location.hostname === "127.0.0.1" || location.hostname === "localhost") {
      return `http://${location.hostname}:8000/api`;
    }
  } catch (_) { /* SSR / sandboxed contexts: fall through */ }
  return "https://150.254.115.204/echr-api/api";
})();
const API_HEALTH_URL = API_BASE_URL.replace(/\/api$/, "/health");

const serverSearch = {
  available: false,
  checking: false,
  serverStats: null,

  /** Probe the API health endpoint once. */
  async probe() {
    if (this.checking) return this.available;
    this.checking = true;
    try {
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), 4000);
      const r = await fetch(API_HEALTH_URL, { signal: ctrl.signal });
      clearTimeout(timer);
      if (r.ok) {
        const data = await r.json();
        this.available = data.status === "ok";
        if (this.available) {
          console.log(`[Server Search] API available — ${data.cases} cases indexed`);
          this.serverStats = data;
        }
      }
    } catch (_) {
      this.available = false;
    }
    this.checking = false;
    return this.available;
  },

  /** Build query params from the current UI filters. */
  _buildParams(query, filters, page = 1, sort = null, group = null) {
    const p = new URLSearchParams();
    if (query) p.set("q", query);
    p.set("page", String(page));
    p.set("page_size", String(PAGE_SIZE));
    if (sort) p.set("sort", sort);
    if (group && group !== "case") p.set("group", group);
    // Convert normalized section keys back to raw DB names.
    // SECTION_DB_NAMES values are arrays (one UI bucket may cover multiple
    // raw DB values — e.g. "facts" → ["Facts Background", "Facts Proceedings"]).
    //
    // v1 bucket-based scope.  Five high-level researcher buckets
    // (SECTION_BUCKETS) cover the body of the judgment; appendix and
    // header sit behind a separate "+ Header/Appendix" toggle for
    // power users.  ``filters.buckets`` is a Set<bucketKey>; when
    // empty we treat it as "search everywhere visible" and fall back
    // to the union of all defaultOn buckets.  The legacy
    // ``filters.sections`` granular-section filter still works as an
    // override (advanced disclosure).
    if (filters.sections && filters.sections.size) {
      const dbSections = [...filters.sections].flatMap(s => SECTION_DB_NAMES[s] || [s]);
      p.set("sections", dbSections.join(","));
    } else {
      const activeBuckets = (filters.buckets && filters.buckets.size)
        ? [...filters.buckets]
        : Object.entries(SECTION_BUCKETS)
            .filter(([_, b]) => b.defaultOn)
            .map(([k]) => k);
      const scope = activeBuckets.flatMap(b => SECTION_BUCKETS[b]?.sections || []);
      // Cover page / headings and the appendix are no longer bucket pills —
      // they opt in via the "Also search in" checkboxes in Advanced filters.
      if (filters.includeMeta) scope.push("header", "summary");
      if (filters.includeAppendix) scope.push("appendix");
      const dbSections = scope.flatMap(s => SECTION_DB_NAMES[s] || [s]);
      p.set("sections", dbSections.join(","));
    }
    // v1: heading rows are search noise (researchers don't search
    // "PROCEDURE" as a body paragraph).  Exclude unless the user
    // explicitly opts in via the "+ Search in headings" toggle.
    if (!filters.includeHeadings) {
      p.set("exclude_roles", "heading,heading_h0,heading_h1,heading_h2,heading_h3,heading_h4,metadata,signature,footer");
    } else {
      // Even with "+ Headings" on, procedural boilerplate (court-composition
      // formulae, signature lines, elision rows — P60 relabelling) is never a
      // useful search hit: it has no citable ¶ number.
      p.set("exclude_roles", "metadata,signature,footer");
    }
    if (filters.articles.size) p.set("articles", [...filters.articles].join(","));
    if (filters.countries.size) p.set("states", [...filters.countries].join(","));
    if (filters.importance.size) p.set("importance", [...filters.importance].join(","));
    if (filters.bodies.size) p.set("bodies", [...filters.bodies].join(","));
    if (filters.keywords && filters.keywords.size) p.set("keywords", [...filters.keywords].join(","));
    const serverOutcomes = [...filters.outcomes].filter(v => PRIMARY_OUTCOMES.has(v));
    if (serverOutcomes.length) p.set("outcomes", serverOutcomes.join(","));
    if (filters.docTypes.size) p.set("doc_types", [...filters.docTypes].join(","));
    // filters.dateFrom/dateTo are epoch-ms (parseDateInput → getTime()).
    // The API compares against judgment_date, so send an ISO yyyy-mm-dd
    // string it can normalise — never the raw timestamp.
    if (filters.dateFrom) {
      p.set("date_from", new Date(filters.dateFrom).toISOString().slice(0, 10));
    }
    if (filters.dateTo) {
      p.set("date_to", new Date(filters.dateTo).toISOString().slice(0, 10));
    }
    return p;
  },

  /** Coerce a citation field to an array of strings.  The API returns lists
   *  for multi-cite cases and a bare string for older single-cite records. */
  _toStringArray(v) {
    if (v == null) return [];
    if (Array.isArray(v)) {
      return v.map((s) => String(s).trim()).filter(Boolean);
    }
    const s = String(v).trim();
    return s ? [s] : [];
  },

  /** Convert an API case result into the shape that buildCaseCard expects. */
  _adaptCase(apiCase) {
    const origBody = Array.isArray(apiCase.originating_body)
      ? apiCase.originating_body[0] || ""
      : (apiCase.originating_body || "");
    const violation = apiCase.violation || [];
    const nonViolation = apiCase.non_violation || [];
    const conclusion = Array.isArray(apiCase.conclusion) ? apiCase.conclusion.join(" ") : (apiCase.conclusion || "");
    const conclusionUpper = conclusion.toUpperCase();
    const keywords = apiCase.keywords || [];
    const c = {
      case_id: apiCase.case_id,
      case_no: apiCase.case_no,
      title: apiCase.title,
      judgment_date: apiCase.judgment_date,
      hudoc_url: apiCase.hudoc_url,
      ecli: apiCase.ecli || "",
      respondent_state: apiCase.respondent_state || "",
      article_no: apiCase.articles || [],
      originating_body: apiCase.originating_body || [],
      importance: apiCase.importance || "",
      conclusion: apiCase.conclusion || [],
      violation,
      non_violation: nonViolation,
      keywords,
      __paragraphs: [],
      // Normalized fields for rendering & filtering
      __articles: apiCase.articles || [],
      __states: [apiCase.respondent_state].filter(Boolean),
      __importance: apiCase.importance || "Unspecified",
      __originatingBody: origBody || "Unknown",
      __outcomePrimary: deriveOutcomeBucket(violation, nonViolation),
      __chamberCategory: deriveChamberCategory([], origBody),
      __hasSeparateOpinion: parseBoolLike(apiCase.separate_opinion),
      // P28: citation arrays are now exposed by /api.  The API returns
      // either a list (multi-cite case) or a single string for
      // domestic_law / rules_of_court (legacy serialisation in the JSONL),
      // so coerce to array uniformly.
      strasbourg_caselaw: this._toStringArray(apiCase.strasbourg_caselaw),
      domestic_law: this._toStringArray(apiCase.domestic_law),
      international_law: this._toStringArray(apiCase.international_law),
      rules_of_court: this._toStringArray(apiCase.rules_of_court),
      __hasStrasbourgCaselaw: this._toStringArray(apiCase.strasbourg_caselaw).length > 0,
      __hasDomesticLaw: this._toStringArray(apiCase.domestic_law).length > 0,
      __hasInternationalLaw: this._toStringArray(apiCase.international_law).length > 0,
      __hasRulesOfCourt: this._toStringArray(apiCase.rules_of_court).length > 0,
      __hasInadmissibility: conclusionUpper.includes("INADMISSIBL"),
      __isStruckOut: conclusionUpper.includes("STRUCK OUT"),
      __keywordsText: normalizeSearchText(keywords.join(" ")),
      // P29 server-computed citation aggregates.  cites_count and
      // cited_by_count come from the case_citations table built by the
      // P29 extractor; they cover ALL cases (including the recent
      // committee judgments not in the JSONL feed).  Fall back to the
      // length of the JSONL-sourced strasbourg_caselaw when the server
      // doesn't ship the count (e.g. /api/browse list responses).
      __citedByCount: Number(apiCase.cited_by_count || 0),
      __citesCountServer: apiCase.cites_count != null
        ? Number(apiCase.cites_count)
        : null,
      __citationRefs: this._toStringArray(apiCase.strasbourg_caselaw),
      __citationRefsNorm: this._toStringArray(apiCase.strasbourg_caselaw)
        .map((item) => normalizeSearchText(item)),
      __isPressRelease: (apiCase.document_type || "").toLowerCase().includes("press release"),
      __isCommittee: (apiCase.document_type || "").toLowerCase().includes("committee"),
      __isGrandChamber: (apiCase.document_type || "").toLowerCase().includes("grand chamber") || (apiCase.originating_body || "").toLowerCase().includes("grand chamber"),
      document_type: apiCase.document_type || "",
      __judgmentDateTs: apiCase.judgment_date ? (() => { const p = apiCase.judgment_date.split("/"); return p.length === 3 ? new Date(`${p[2]}-${p[1]}-${p[0]}`).getTime() : new Date(apiCase.judgment_date).getTime(); })() : null,
      __sortTs: apiCase.judgment_date ? (() => { const p = apiCase.judgment_date.split("/"); return p.length === 3 ? new Date(`${p[2]}-${p[1]}-${p[0]}`).getTime() : new Date(apiCase.judgment_date).getTime(); })() : 0,
    };
    // Press releases get their own outcome bucket instead of polluting "neither"
    if (c.__isPressRelease) c.__outcomePrimary = "press_release";
    return c;
  },

  /** Full-text search via server API. */
  async search(query, filters, page = 1, sort = null, group = null) {
    const params = this._buildParams(query, filters, page, sort, group);
    const endpoint = query ? "search" : "browse";
    const r = await fetch(`${API_BASE_URL}/${endpoint}?${params}`);
    if (!r.ok) throw new Error(`API ${r.status}`);
    return r.json();
  },

  /** Fetch full case details from server. */
  async getCase(caseId) {
    const r = await fetch(`${API_BASE_URL}/cases/${encodeURIComponent(caseId)}`);
    if (!r.ok) throw new Error(`API ${r.status}`);
    return r.json();
  },

  /** Fetch facets from server.  With no args the counts cover the whole
   *  corpus; pass {q, date_from, date_to} to scope them to a search. */
  async getFacets(opts = {}) {
    const p = new URLSearchParams();
    if (opts.q) p.set("q", opts.q);
    if (opts.date_from) p.set("date_from", opts.date_from);
    if (opts.date_to) p.set("date_to", opts.date_to);
    const qs = p.toString();
    const r = await fetch(`${API_BASE_URL}/facets${qs ? `?${qs}` : ""}`);
    if (!r.ok) throw new Error(`API ${r.status}`);
    return r.json();
  },

  /** Fetch stats from server. */
  async getStats() {
    const r = await fetch(`${API_BASE_URL}/stats`);
    if (!r.ok) throw new Error(`API ${r.status}`);
    return r.json();
  },
};
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

// NOTE: Several upstream raw labels are merged into unified UI buckets:
//   * Facts Background + Facts Proceedings + Facts          → "facts"
//   * Legal Framework  + Legal Context + Relevant legal framework → "legal_framework"
//   * Operative Part   + Operative part (lowercase)         → "operative_part"
// Rationale (facts): the upstream labels are semantically inverted vs HUDOC
// convention (classical HUDOC: PROCEDURE = short admin section, THE FACTS →
// I. CIRCUMSTANCES OF THE CASE = narrative) and since 1 Sept 2021 the Court
// itself merges facts+procedure for Committee cases into "SUBJECT MATTER OF
// THE CASE" / "FACTS AND PROCEDURE". The third raw label "Facts" (~246k
// paragraphs concentrated in 2017-2025) is the modern segmenter's output for
// circumstances-of-the-case content; it is mutually exclusive with the older
// "Facts Background"/"Facts Proceedings" splits at the case level.
// Rationale (legal framework): "Legal Context" is an orphan bucket (6 paragraphs,
// 2 cases). "Relevant legal framework" (~16k paragraphs, 1.8k cases) is the
// modern label for what older cases called "Legal Framework" (~25k paragraphs,
// 1.4k cases) — only 2 cases use both, so they are parallel post-2021 vs older
// segmenter outputs, not overlapping.
// Rationale (operative_part): "Operative Part" (titlecase) was the segmenter
// output until ~2016; from 2017 onwards the same content is emitted as
// "Operative part" (lowercase 'p'). Without merging, the lowercase variant
// (~62k paragraphs, dominant since 2020) would be invisible to the filter.
// Empirically verified via scripts/harvest_headings.py — see docs/phase2/.
// docs/TODO-facts-reclassify.md remains the plan for proper Phase 2
// procedure/circumstances re-segmentation.
const SECTION_ORDER = [
  "header",
  "summary",
  "introduction",
  "facts",
  "legal_framework",
  "commission_proceedings",
  "final_submissions",
  "admissibility",
  "merits",
  "just_satisfaction",
  "article_46",
  "operative_part",
  "separate_opinion",
  "appendix",
];

const SECTION_LABELS = {
  header: "Judgment Header",
  summary: "Summary",
  introduction: "Introduction",
  facts: "Facts of the case",
  legal_framework: "Relevant legal framework",
  commission_proceedings: "Commission Proceedings",
  final_submissions: "Final Submissions",
  admissibility: "Admissibility",
  merits: "Merits",
  just_satisfaction: "Just Satisfaction",
  article_46: "Article 46 (Execution)",
  operative_part: "Operative Part",
  separate_opinion: "Separate Opinion",
  appendix: "Appendix",
};

const SECTION_COLORS = {
  header: "#8C8C8C",
  summary: "#5B7B96",                  // muted navy — keyword block
  introduction: "#4C72B0",
  facts: "#DD8452",
  legal_framework: "#937860",
  commission_proceedings: "#7B8FA3",  // muted slate — pre-Protocol-11 procedural
  final_submissions: "#B5826D",       // muted terracotta — parties' final arguments
  admissibility: "#8172B3",
  merits: "#55A868",
  just_satisfaction: "#DA8BC3",
  article_46: "#CCB974",
  operative_part: "#64B5CD",
  separate_opinion: "#8C8C8C",
  appendix: "#A5A58D",
};

// v1 high-level filter buckets that researchers think in, regardless of
// the dozen-or-so raw HUDOC sub-section variants.  Each bucket maps to
// a list of normalized section keys (which themselves flatten further
// into raw DB names via SECTION_DB_NAMES).  Order matches the visible
// HUDOC document flow (Facts → Adm/Merits → Just Sat → Operative →
// Separate Opinions).  Defaults: all body buckets ON, opinions OFF.
const SECTION_BUCKETS = {
  facts: {
    label: "Facts",
    description: "Facts of the case, legal framework, procedure, summary",
    sections: [
      "introduction", "facts", "legal_framework",
      "commission_proceedings", "summary",
    ],
    color: "#DD8452",
    defaultOn: true,
  },
  adm_merits: {
    label: "Admissibility + Merits",
    description: "Court's reasoning on admissibility and merits, including final submissions",
    sections: ["admissibility", "merits", "final_submissions"],
    color: "#55A868",
    defaultOn: true,
  },
  just_satisfaction: {
    label: "Just Satisfaction",
    description: "Article 41 (and pre-1998 Article 50) — damages, costs, compensation",
    sections: ["just_satisfaction", "article_46"],
    color: "#DA8BC3",
    defaultOn: true,
  },
  operative_part: {
    label: "Operative Part",
    description: "Dispositif — \"Holds…\", \"Decides…\", \"Declares…\"",
    sections: ["operative_part"],
    color: "#64B5CD",
    defaultOn: true,
  },
  individual_opinions: {
    label: "Individual Opinions",
    description: "Concurring, dissenting and partly concurring/dissenting opinions",
    sections: ["separate_opinion"],
    color: "#8C8C8C",
    defaultOn: true,
  },
  appendix: {
    label: "Appendix",
    description: "Annexes, compensation schedules, applicant lists (after the dispositif)",
    sections: ["appendix"],
    color: "#A5A58D",
    defaultOn: false,
  },
};

// Inverse: section-key → bucket-key (for breadcrumb labelling).
const SECTION_TO_BUCKET = Object.fromEntries(
  Object.entries(SECTION_BUCKETS).flatMap(
    ([bk, b]) => b.sections.map((s) => [s, bk])
  )
);

// Reverse map: normalized key → raw DB section name(s) (as stored in SQLite).
// Values are ARRAYS because one UI bucket may cover multiple raw DB values
// (e.g. "facts" covers both "Facts Background" and "Facts Proceedings";
// "legal_framework" also absorbs the orphan "Legal Context" bucket).
const SECTION_DB_NAMES = {
  header: ["Header"],
  summary: ["Summary"],
  introduction: ["Introduction"],
  facts: ["Facts Background", "Facts Proceedings", "Facts"],
  legal_framework: ["Legal Framework", "Legal Context", "Relevant legal framework"],
  commission_proceedings: ["Commission Proceedings"],
  final_submissions: ["Final Submissions"],
  admissibility: ["Admissibility"],
  merits: ["Merits"],
  just_satisfaction: ["Just Satisfaction"],
  article_46: ["Article 46"],
  operative_part: ["Operative Part", "Operative part"],
  separate_opinion: ["Separate Opinion"],
  appendix: ["Appendix"],
};

const SEARCH_SCORE_SECTION_WEIGHTS = {
  merits: 1.3,
  admissibility: 1.2,
  legal_framework: 1.1,
  facts: 1.0,
  appendix: 0.8,
};

const QUERY_PREFIX_KEYS = new Set(["case", "ecli", "hudoc", "article", "state", "body", "judge", "keyword"]);

const OUTCOME_LABELS = {
  violation_only: "Violation only",
  non_violation_only: "Non-violation only",
  both: "Mixed (violation + non-violation)",
  neither: "No finding",
  press_release: "Press Release",
  has_inadmissibility: "Inadmissibility",
  is_struck_out: "Struck out",
};

// HUDOC's "originating_body" field arrives in two flavours: full strings for
// non-Committee bodies ("Court (First Section)", "Court (Grand Chamber)", …)
// and bare integer codes 25-29 for the five Section Committees (totalling
// the 6,240 Committee judgments visible in the Document Type filter).  Codes
// 25-29 follow HUDOC's section ordering 1-5.  Without this lookup the filter
// rail and result-card meta show raw "29", which is opaque.
const BODY_CODE_LABELS = {
  "25": "Court (First Section Committee)",
  "26": "Court (Second Section Committee)",
  "27": "Court (Third Section Committee)",
  "28": "Court (Fourth Section Committee)",
  "29": "Court (Fifth Section Committee)",
};
function formatBodyLabel(value) {
  if (value == null) return "";
  const s = String(value);
  return BODY_CODE_LABELS[s] || s;
}

/**
 * Render-friendly importance helpers.  HUDOC's `importance` field arrives
 * as one of: "1", "2", "3", "Key cases", or "Unspecified".  For chip
 * rendering we want a short label + tooltip, and we want to suppress the
 * chip entirely when the value is "Unspecified" (it adds visual noise
 * without communicating anything to the researcher).
 */
function importanceShortLabel(value) {
  if (!value) return "";
  if (value === "Unspecified") return "";
  // For "1"/"2"/"3" keep the digit, for "Key cases" keep the phrase.
  if (/^[123]$/.test(String(value))) return String(value);
  return String(value);
}
function importanceTooltip(value) {
  return IMPORTANCE_TOOLTIPS[value] || "";
}

// Plain-language descriptions of importance levels for filter UI (M3 finding:
// users don't know what bare "1", "2", "3" mean in HUDOC's importance scheme).
// HUDOC's importance is FOUR distinct, mutually-exclusive tiers — Key cases is
// the top tier, NOT a subset of "1".  IMPORTANCE_ORDER fixes the rail order
// (default localeCompare wrongly sorts "Key cases" after "3").
const IMPORTANCE_ORDER = ["Key cases", "1", "2", "3", "Unspecified"];
// Labels follow HUDOC's official wording (Case Reports / 1 = High /
// 2 = Medium / 3 = Low) — see the HUDOC FAQ "What do the importance
// levels correspond to?"  Diverging from HUDOC's vocabulary would
// confuse researchers who arrive from there.
const IMPORTANCE_LABELS = {
  "Key cases": "Key cases",
  "1": "1 — High",
  "2": "2 — Medium",
  "3": "3 — Low",
};
const IMPORTANCE_TOOLTIPS = {
  "Key cases": "The Court's most significant judgments since 1998 — published in the official Reports (1998–2015) or selected as key cases by the Bureau (2016 on). Pre-1998 (old Court) judgments are classified by levels 1–3 only.",
  "1": "High importance — judgments that make a significant contribution to the development, clarification or modification of the case-law. Provisional until the Bureau decides on Key-case selection.",
  "2": "Medium importance — judgments that, while not significantly contributing to the case-law, go beyond merely applying existing case-law. Provisional until the Bureau decides on Key-case selection.",
  "3": "Low importance — judgments of little legal interest (apply existing case-law, friendly settlements, strike-outs)",
  "Unspecified": "Importance level not assigned in HUDOC metadata",
};
function sortImportanceLevels(arr) {
  return [...arr].sort((a, b) => {
    const ia = IMPORTANCE_ORDER.indexOf(a), ib = IMPORTANCE_ORDER.indexOf(b);
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
  });
}

// Per-section hint tooltips. Empty = no ⓘ icon. Rare/Pop-A-specific sections
// get a hint so researchers know the filter targets a small subset.
const SECTION_HINTS = {
  introduction: "In Committee and joined cases, this section may contain applicant name lists rather than procedural history.",
  facts: "In Committee cases, this section may also contain legal analysis (ALLEGED VIOLATION headings).",
  commission_proceedings: "Pre-Protocol-11 only (1959–~1998): procedural history before the European Commission. Older cases only.",
  final_submissions: "Pre-Protocol-11 only: parties' formal final arguments to the Court before the Merits.",
  article_46: "Article 46 supervisory measures — rare; only in cases ordering structural change.",
  appendix: "Annexes and applicant data tables (mostly Committee-format mass cases).",
};

/** Outcome values that map to __outcomePrimary (sent to server API).
 *  Flag-based values (has_inadmissibility, is_struck_out) are client-side only. */
const PRIMARY_OUTCOMES = new Set(["violation_only", "non_violation_only", "both", "neither", "press_release"]);

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

const COUNTRY_CODE_BY_NAME_NORM = Object.fromEntries(
  Object.entries(COUNTRY_NAMES).map(([code, name]) => [normalizeSearchText(name), code])
);

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
  keywords: [],
  importanceLevels: [],
  query: "",
  currentFilters: null,
  currentOrderedCaseIds: [],
  currentResultsById: new Map(),
  currentTerms: [],
  currentMode: "browse",
  currentPage: 1,
  activeCaseId: "",
  totalHits: 0,
  limited: false,
  searchTimeMs: 0,
  cardMode: "compact",
  // Results display mode (generalcomments-inspired): how to sort and
  // whether to group hits by judgment or list every paragraph flat.
  resultSort: "relevance",   // "relevance" | "date_desc" | "date_asc"
  resultGroup: "case",       // "case" | "paragraph"
  flatHits: [],              // ordered paragraph hits when resultGroup="paragraph"
  // Case Note drawer text-size zoom (A− / A+), persisted per browser.
  cnZoom: (() => {
    try { const v = parseFloat(localStorage.getItem("cnZoom")); return v > 0 ? v : 1; }
    catch (e) { return 1; }
  })(),
  classifierOpen: false,
  classifier: null,
  serverMode: false,
  serverTotalCases: 0,
  serverTotalPages: 0,
  // "Default view" = empty query, date-desc, cap at 100 most recent cases
  // (5 pages of PAGE_SIZE).  Flipped on by the init block after facets
  // load, and flipped off as soon as the user types a query or applies
  // filters that would make the 100-cap meaningless.
  defaultView: false,
  defaultViewCap: 100,
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
  el.queryMatchCount = byId("queryMatchCount");
  el.queryMatchLabel = byId("queryMatchLabel");
  el.filterToggleBtn = byId("filterToggleBtn");
  el.filtersPanel = byId("filtersPanel");

  el.sectionsFilters = byId("sectionsFilters");
  el.countriesFilters = byId("countriesFilters");
  el.articlesFilters = byId("articlesFilters");
  el.keywordsFilters = byId("keywordsFilters");
  el.importanceFilters = byId("importanceFilters");
  el.docTypeFilters = byId("docTypeFilters");
  el.outcomeFilters = byId("outcomeFilters");
  el.separateOpinionFilters = byId("separateOpinionFilters");
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
  el.resultsHitsLabel = byId("resultsHitsLabel");
  el.resultsCases = byId("resultsCases");
  el.resultsCasesLabel = byId("resultsCasesLabel");
  el.resultsTime = byId("resultsTime");
  el.cardModeBtn = byId("cardModeBtn");
  el.exportBtn = byId("exportBtn");
  el.exportIncludeClassifier = byId("exportIncludeClassifier");
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
  el.analyticsDocTypes = byId("analyticsDocTypes");
  el.analyticsWords = byId("analyticsWords");
  el.caseContextRail = byId("caseContextRail");
  el.caseContextRailMobile = byId("caseContextRailMobile");

  el.dossier = byId("dossier");
  el.dossierContent = byId("dossierContent");
  el.dossierResizer = byId("dossierResizer");
  el.sidebar = byId("sidebar");
  el.sidebarResizer = byId("sidebarResizer");

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

/**
 * Collapse paragraph hits that share the same logical_para_rowid into
 * one result.  A "logical paragraph" is the unit returned by the
 * paragraph-level search: a body ¶ + any quotes it contains + any
 * preceding sub-headings.  The whole operative section is also one
 * unit per case.
 *
 * The first hit in the list (which the server has ordered by best
 * BM25F rank) wins as the "representative".  We tag matchedRoles
 * with every row_role that contributed a hit, so the UI can show
 * "hit in heading" / "hit in quote" badges.
 */
/**
 * Build small inline badges showing where the FTS match landed inside
 * the logical paragraph unit — body match (no badge), heading match
 * ("in heading"), or quoted-text match ("in quote").  Multiple badges
 * stack when the same logical ¶ matched in several places (e.g. the
 * query hits both the section heading AND a quoted statute below it).
 *
 * `matchedRoles` is a Set populated by dedupParagraphHits().
 */
function buildMatchSourceBadgesHtml(matchedRoles) {
  if (!matchedRoles || matchedRoles.size === 0) return "";
  const badges = [];
  if (matchedRoles.has("heading")) {
    badges.push('<span class="match-source-badge match-source-heading" title="The query matched in a section heading attached to this paragraph">in heading</span>');
  }
  if (matchedRoles.has("quote")) {
    badges.push('<span class="match-source-badge match-source-quote" title="The query matched in a quote nested inside this paragraph">in quote</span>');
  }
  if (matchedRoles.has("operative_list")) {
    badges.push('<span class="match-source-badge match-source-operative" title="The query matched in an operative-part clause">operative</span>');
  }
  return badges.join("");
}

function dedupParagraphHits(hits) {
  if (!hits || hits.length === 0) return [];
  const byKey = new Map();
  const order = [];
  for (const h of hits) {
    const key = h.logicalParaIdx != null
      ? `L:${h.logicalParaIdx}`
      : `P:${h.paraIdx}:${h.section}`; // fallback for legacy rows (pre-P58)
    if (!byKey.has(key)) {
      const entry = { ...h, matchedRoles: new Set() };
      byKey.set(key, entry);
      order.push(key);
    }
    const entry = byKey.get(key);
    const role = (h.rowRole || "paragraph").replace(/_h\d+$/, "_heading");
    // Collapse heading_h0/h1/h2/h3/h4 → "heading" for badge purposes
    const badgeRole = role.startsWith("heading") ? "heading" : role;
    entry.matchedRoles.add(badgeRole);
  }
  return order.map((k) => byKey.get(k));
}

function normalizeSearchText(value) {
  const text = String(value || "").toLowerCase();
  try {
    return text.normalize("NFD").replace(/[\u0300-\u036f]/g, "");
  } catch {
    return text;
  }
}

function normalizeArticleToken(value) {
  return normalizeSearchText(value).replace(/\s+/g, "");
}

function canonicalizeCitation(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function normalizeCitationList(value) {
  const out = [];
  const seen = new Set();
  for (const raw of normalizeListField(value, /[;\n]/)) {
    const clean = canonicalizeCitation(raw);
    if (!clean) continue;
    const key = normalizeSearchText(clean);
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(clean);
  }
  return out;
}

function parseConclusionFlags(conclusion) {
  const norm = normalizeSearchText(conclusion);
  return {
    hasInadmissibility: norm.includes("inadmissible"),
    isStruckOut: norm.includes("struck out"),
    hasProceduralAspect: norm.includes("procedural aspect"),
    hasSubstantiveAspect: norm.includes("substantive aspect"),
  };
}

function sectionSearchWeight(section) {
  return SEARCH_SCORE_SECTION_WEIGHTS[section] || 1;
}

function caseSearchBoost(caseObj) {
  let boost = 1;
  if (String(caseObj.__importance || "").toLowerCase() === "key cases") {
    boost *= 1.1;
  }
  if (caseObj.__chamberCategory === "GRANDCHAMBER") {
    boost *= 1.1;
  }
  return boost;
}

function parseQueryWithPrefixes(query) {
  const meta = {
    case: [],
    ecli: [],
    hudoc: [],
    article: [],
    state: [],
    body: [],
    judge: [],
    keyword: [],
  };

  const prefixPattern = /(^|\s)(case|ecli|hudoc|article|state|body|judge|keyword):(?:"([^"]+)"|(\S+))/gi;
  const stripped = String(query || "").replace(prefixPattern, (full, lead, key, quoted, plain) => {
    const cleanKey = String(key || "").toLowerCase();
    const value = String(quoted || plain || "").trim();
    if (QUERY_PREFIX_KEYS.has(cleanKey) && value) {
      const normalizedValue = cleanKey === "article" ? normalizeArticleToken(value) : normalizeSearchText(value);
      meta[cleanKey].push(normalizedValue);
    }
    return lead || " ";
  });

  return {
    textQuery: stripped.replace(/\s+/g, " ").trim(),
    meta,
  };
}

function arrayIncludesNorm(haystackValues, needleNorm) {
  if (!needleNorm) return true;
  for (const value of haystackValues) {
    if (value.includes(needleNorm)) {
      return true;
    }
  }
  return false;
}

function matchesArticleToken(caseTokenNorm, queryTokenNorm) {
  if (!caseTokenNorm || !queryTokenNorm) return false;
  if (caseTokenNorm === queryTokenNorm || caseTokenNorm.startsWith(`${queryTokenNorm}-`)) {
    return true;
  }

  const parts = caseTokenNorm.split("+");
  for (const part of parts) {
    if (part === queryTokenNorm || part.startsWith(`${queryTokenNorm}-`)) {
      return true;
    }
  }
  return false;
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

function serverSnippetToPlainText(snippet, fallbackText = "") {
  return String(snippet || fallbackText || "")
    .replace(/<\/?b>/gi, "")
    .replace(/<[^>]*>/g, "");
}

function serverSnippetToHtml(snippet, fallbackText = "") {
  if (!snippet) return escapeHtml(fallbackText || "");
  const tokens = String(snippet).split(/(<\/?b>)/i);
  let inHighlight = false;
  return tokens.map((token) => {
    if (/^<b>$/i.test(token)) {
      inHighlight = true;
      return "";
    }
    if (/^<\/b>$/i.test(token)) {
      inHighlight = false;
      return "";
    }
    const safe = escapeHtml(token);
    // FTS marks every matched term, including function words ("failure TO
    // protect" paints every "to" on the page).  Keep the match for ranking,
    // drop the paint for stopwords — same list the context rail uses.
    if (inHighlight && DOSSIER_HL_SKIP.has(token.trim().toLowerCase())) return safe;
    return inHighlight ? `<mark class="hl">${safe}</mark>` : safe;
  }).join("");
}

/* Trim a parent-paragraph body to a short lead-in displayed above a
 * fragment hit (a bullet / quote / continuation row).  Cuts on a word
 * boundary near `max` chars so the matched fragment below it reads in
 * context instead of being stranded.  Used with P58's `parentText`. */
function truncateForContext(text, max = 240) {
  const s = String(text || "").trim();
  if (s.length <= max) return s;
  const cut = s.slice(0, max);
  const sp = cut.lastIndexOf(" ");
  return (sp > max * 0.6 ? cut.slice(0, sp) : cut).replace(/\s+$/, "") + "…";
}

function updateCardModeButton() {
  if (!el.cardModeBtn) return;
  const isDetailed = state.cardMode === "detailed";
  el.cardModeBtn.textContent = isDetailed ? "Compact view" : "Detailed view";
  el.cardModeBtn.setAttribute("aria-pressed", isDetailed ? "true" : "false");
}

function loadCardModePreference() {
  try {
    const saved = localStorage.getItem("echr-card-mode");
    if (saved === "compact" || saved === "detailed") {
      state.cardMode = saved;
    }
  } catch {
    // Ignore storage errors.
  }
}

function setCardMode(mode) {
  state.cardMode = mode === "detailed" ? "detailed" : "compact";
  try {
    localStorage.setItem("echr-card-mode", state.cardMode);
  } catch {
    // Ignore storage errors.
  }
  updateCardModeButton();
  renderResultsPage();
}

function toggleCardMode() {
  setCardMode(state.cardMode === "detailed" ? "compact" : "detailed");
}

function getOutcomeToneClass(outcomeKey) {
  if (outcomeKey === "violation_only" || outcomeKey === "both") return "violation";
  if (outcomeKey === "non_violation_only") return "non-violation";
  if (outcomeKey === "press_release") return "press-release";
  return "neutral";
}

function getChamberLabel(category) {
  if (category === "GRANDCHAMBER") return "Grand Chamber";
  if (category === "CHAMBER") return "Chamber";
  return "Other";
}

/* ── Accessibility settings ──────────────────────────────────────── */

const ACCESSIBILITY_DEFAULTS = {
  theme: "light",
  fontSize: 100,
  lineHeight: "normal",
  highContrast: false,
  dyslexiaFont: false,
  underlineLinks: false,
};

function getAccessibilitySettings() {
  try {
    const saved = localStorage.getItem("echr-accessibility");
    if (saved) return { ...ACCESSIBILITY_DEFAULTS, ...JSON.parse(saved) };
  } catch { /* ignore */ }
  return { ...ACCESSIBILITY_DEFAULTS };
}

function saveAccessibilitySettings(settings) {
  try { localStorage.setItem("echr-accessibility", JSON.stringify(settings)); } catch { /* ignore */ }
}

function applyAccessibilitySettings(settings) {
  document.documentElement.setAttribute("data-theme", settings.theme);
  document.documentElement.style.setProperty("--a11y-font-scale", (settings.fontSize / 100).toFixed(2));
  document.documentElement.classList.toggle("a11y-high-contrast", !!settings.highContrast);
  document.documentElement.classList.toggle("a11y-dyslexia", !!settings.dyslexiaFont);
  document.documentElement.classList.toggle("a11y-underline-links", !!settings.underlineLinks);
  if (settings.lineHeight !== "normal") {
    document.documentElement.style.setProperty("--a11y-line-height", settings.lineHeight);
  } else {
    document.documentElement.style.removeProperty("--a11y-line-height");
  }
  saveAccessibilitySettings(settings);
}

function setTheme(theme) {
  const settings = getAccessibilitySettings();
  settings.theme = theme;
  applyAccessibilitySettings(settings);
  // Cross-page interop: methodology/about/semantic read the plain "theme" key.
  try { localStorage.setItem("theme", theme); } catch { /* ignore */ }
}

function initTheme() {
  const settings = getAccessibilitySettings();
  // Migrate old theme storage
  try {
    const oldTheme = localStorage.getItem("echr-theme");
    if (oldTheme && !localStorage.getItem("echr-accessibility")) {
      settings.theme = oldTheme;
    }
  } catch { /* ignore */ }
  // Cross-page interop: honour a light/dark choice made on any other subpage
  // (methodology/about/semantic write the plain "theme" key).
  try {
    const shared = localStorage.getItem("theme");
    if (shared === "dark" || shared === "light") settings.theme = shared;
  } catch { /* ignore */ }
  applyAccessibilitySettings(settings);
}

function toggleTheme() {
  const current = document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
  setTheme(current === "dark" ? "light" : "dark");
}

function openAccessibilityPanel() {
  const panel = byId("accessibilityPanel");
  const backdrop = byId("a11yBackdrop");
  if (panel) {
    panel.hidden = false;
    if (backdrop) backdrop.hidden = false;
    syncAccessibilityControls();
  }
}

function closeAccessibilityPanel() {
  const panel = byId("accessibilityPanel");
  const backdrop = byId("a11yBackdrop");
  if (panel) panel.hidden = true;
  if (backdrop) backdrop.hidden = true;
}

function syncAccessibilityControls() {
  const s = getAccessibilitySettings();
  const themeSelect = byId("a11yTheme");
  const fontSlider = byId("a11yFontSize");
  const fontValue = byId("a11yFontSizeValue");
  const lineSelect = byId("a11yLineHeight");
  const contrastCb = byId("a11yHighContrast");
  const dyslexiaCb = byId("a11yDyslexia");
  const underlineCb = byId("a11yUnderlineLinks");
  if (themeSelect) { themeSelect.value = s.theme; }
  if (fontSlider) { fontSlider.value = s.fontSize; }
  if (fontValue) { fontValue.textContent = s.fontSize + "%"; }
  if (lineSelect) { lineSelect.value = s.lineHeight; }
  if (contrastCb) { contrastCb.checked = !!s.highContrast; }
  if (dyslexiaCb) { dyslexiaCb.checked = !!s.dyslexiaFont; }
  if (underlineCb) { underlineCb.checked = !!s.underlineLinks; }
}

function onAccessibilityChange() {
  const s = getAccessibilitySettings();
  const themeSelect = byId("a11yTheme");
  const fontSlider = byId("a11yFontSize");
  const lineSelect = byId("a11yLineHeight");
  const contrastCb = byId("a11yHighContrast");
  const dyslexiaCb = byId("a11yDyslexia");
  const underlineCb = byId("a11yUnderlineLinks");
  const fontValue = byId("a11yFontSizeValue");
  if (themeSelect) { s.theme = themeSelect.value; }
  if (fontSlider) { s.fontSize = Number(fontSlider.value); }
  if (fontValue) { fontValue.textContent = s.fontSize + "%"; }
  if (lineSelect) { s.lineHeight = lineSelect.value; }
  if (contrastCb) { s.highContrast = contrastCb.checked; }
  if (dyslexiaCb) { s.dyslexiaFont = dyslexiaCb.checked; }
  if (underlineCb) { s.underlineLinks = underlineCb.checked; }
  applyAccessibilitySettings(s);
}

/* ── ECHR Article Guide URLs ─────────────────────────────────────── */

const ARTICLE_GUIDE_URLS = {
  "2": "https://www.echr.coe.int/documents/d/echr/guide_art_2_eng",
  "3": "https://www.echr.coe.int/documents/d/echr/guide_art_3_eng",
  "4": "https://www.echr.coe.int/documents/d/echr/guide_art_4_eng",
  "5": "https://www.echr.coe.int/documents/d/echr/guide_art_5_eng",
  "6": "https://www.echr.coe.int/documents/d/echr/guide_art_6_civil_eng",
  "7": "https://www.echr.coe.int/documents/d/echr/guide_art_7_eng",
  "8": "https://www.echr.coe.int/documents/d/echr/guide_art_8_eng",
  "9": "https://www.echr.coe.int/documents/d/echr/guide_art_9_eng",
  "10": "https://www.echr.coe.int/documents/d/echr/guide_art_10_eng",
  "11": "https://www.echr.coe.int/documents/d/echr/guide_art_11_eng",
  "12": "https://www.echr.coe.int/documents/d/echr/guide_art_12_eng",
  "13": "https://www.echr.coe.int/documents/d/echr/guide_art_13_eng",
  "14": "https://www.echr.coe.int/documents/d/echr/guide_art_14_eng",
  "18": "https://www.echr.coe.int/documents/d/echr/guide_art_18_eng",
  "34": "https://www.echr.coe.int/documents/d/echr/guide_art_34_eng",
  "35": "https://www.echr.coe.int/documents/d/echr/guide_art_35_eng",
  "41": "https://www.echr.coe.int/documents/d/echr/guide_art_41_eng",
  "46": "https://www.echr.coe.int/documents/d/echr/guide_art_46_eng",
  "1": "https://www.echr.coe.int/documents/d/echr/guide_art_1_eng",
};

/* ── Citation generation helpers ─────────────────────────────────── */

/* Split a HUDOC case_no ("40660/08;60641/08") into clean application
 * numbers. */
function splitAppNos(caseNo) {
  return String(caseNo || "").split(/[;,]/).map((s) => s.trim()).filter(Boolean);
}

/* Application numbers in ECtHR citation form: "no. X" for a single
 * application, "nos. X and Y" / "nos. X, Y and Z" for several — the
 * Court's own convention, not the raw semicolon-joined HUDOC string. */
function formatAppNosCitation(caseNo) {
  const nos = splitAppNos(caseNo);
  if (!nos.length) return "";
  if (nos.length === 1) return `no. ${nos[0]}`;
  return `nos. ${nos.slice(0, -1).join(", ")} and ${nos[nos.length - 1]}`;
}

function buildStandardCitation(caseObj) {
  const title = (caseObj.title || "Untitled").replace(/^CASE OF\s+/i, "");
  const apps = formatAppNosCitation(caseObj.case_no);
  const date = caseObj.judgment_date || "";
  const year = date ? date.replace(/.*(\d{4}).*/, "$1") : "";
  const parts = [title];
  if (apps) parts[0] += `, ${apps}`;
  if (year) parts[0] += ` (ECtHR ${year})`;
  return parts.join("");
}

function buildEcliCitation(caseObj) {
  return caseObj.ecli || buildStandardCitation(caseObj);
}

/* v1 paragraph-level citation:
 *   Smith v. Croatia, no. 12345/05, § 47, ECtHR 2024
 *   https://hudoc.echr.coe.int/?i=001-XXXXX
 *
 * Used by the per-paragraph "Cite ¶" button in result rows.  Falls
 * back gracefully when the paragraph has no hudoc_para_no
 * (continuation row, operative item, heading) by emitting the case
 * citation without a paragraph anchor. */
function buildParagraphCitation(caseObj, para) {
  const head = buildStandardCitation(caseObj);
  const url = caseObj.hudoc_url || "";
  // P58: a fragment hit (bullet/quote) has no own hudoc_para_no — cite it
  // under its parent body ¶ via displayParaNo rather than anchorless.
  const hp = para && (para.hudocParaNo != null ? para.hudocParaNo : para.displayParaNo);
  const block = para && para.numberingBlock;
  let anchor = "";
  if (hp != null) {
    if (block === "operative_dispositif" || block === "separate_opinion") {
      anchor = `, Op. § ${hp}`;
    } else {
      anchor = `, § ${hp}`;
    }
  }
  // Insert the anchor BEFORE the trailing year-parenthesis if present
  // ("Smith v. Croatia, App. no. … (ECtHR YYYY)"), otherwise append.
  const withAnchor = anchor
    ? head.replace(/\s\(ECtHR\b/, `${anchor} (ECtHR`).replace(
        /^(.+)$/,
        head.includes("(ECtHR") ? "$1" : `$1${anchor}`,
      )
    : head;
  return url ? `${withAnchor}\n${url}` : withAnchor;
}

/* Build a per-paragraph HUDOC URL.  HUDOC's modern viewer doesn't
 * natively honour `#paragraph_N`, so we keep the case-level URL but
 * append a fragment that the user can paste / Ctrl-F against in the
 * HUDOC page.  Falls back to the case URL when no para number. */
function paragraphHudocUrl(caseObj, para) {
  const base = caseObj.hudoc_url || "";
  if (!base) return "";
  // Fall back to the P58 display number so a fragment hit still anchors
  // at its parent ¶ in HUDOC rather than dropping to the case URL.
  const hp = para && (para.hudocParaNo != null ? para.hudocParaNo : para.displayParaNo);
  if (hp == null) return base;
  return `${base}#${"{"}\"paragraphno\":\"${hp}\"${"}"}`;
}

function buildKeyInfoBlock(caseObj) {
  const lines = [];
  const title = (caseObj.title || "Untitled").replace(/^CASE OF\s+/i, "");
  const states = (caseObj.__states || []).map(d => COUNTRY_NAMES[d] || d).join(", ");
  lines.push(`Case: ${title}`);
  lines.push(`Application no.: ${caseObj.case_no || "-"}`);
  lines.push(`Respondent State: ${states || "-"}`);
  lines.push(`Judgment date: ${caseObj.judgment_date || "-"}`);
  lines.push(`Originating body: ${formatBodyLabel(caseObj.__originatingBody) || "-"}`);
  const chamberLabel = getChamberLabel(caseObj.__chamberCategory);
  lines.push(`Chamber: ${chamberLabel}`);
  if (caseObj.chamber_composed_of && caseObj.chamber_composed_of.length) {
    lines.push(`Composition: ${caseObj.chamber_composed_of.join(", ")}`);
  }
  lines.push(`Articles: ${caseObj.article_no || "-"}`);
  if (caseObj.violation && caseObj.violation.length) {
    lines.push(`Violations found: ${caseObj.violation.join("; ")}`);
  }
  if (caseObj["non-violation"] && caseObj["non-violation"].length) {
    lines.push(`No violation: ${caseObj["non-violation"].join("; ")}`);
  }
  lines.push(`Importance: ${caseObj.__importance || "-"}`);
  if (caseObj.__hasSeparateOpinion) lines.push(`Separate opinion: Yes`);
  if (caseObj.ecli) lines.push(`ECLI: ${caseObj.ecli}`);
  if (caseObj.hudoc_url) lines.push(`HUDOC: ${caseObj.hudoc_url}`);
  return lines.join("\n");
}

function copyToClipboardWithFeedback(text, buttonEl) {
  navigator.clipboard?.writeText(text).then(() => {
    const original = buttonEl.textContent;
    buttonEl.textContent = "Copied!";
    buttonEl.classList.add("copied");
    setTimeout(() => {
      buttonEl.textContent = original;
      buttonEl.classList.remove("copied");
    }, 1400);
  });
}

/* ── Cited-by count computation ──────────────────────────────────── */

function computeCitedByCounts(cases) {
  // Build a map of title-fragments → case_id for cases in the dataset
  const titleIndex = new Map();
  for (const c of cases) {
    const shortTitle = (c.title || "").replace(/^CASE OF\s+/i, "").trim().toLowerCase();
    if (shortTitle) titleIndex.set(shortTitle, c.case_id);
    // Also index by case_no
    if (c.case_no) titleIndex.set(c.case_no.toLowerCase(), c.case_id);
  }

  const citedByMap = new Map(); // case_id → Set of citing case_ids

  for (const c of cases) {
    const refs = c.__citationRefs || c.strasbourg_caselaw || [];
    for (const ref of refs) {
      const refLower = ref.toLowerCase();
      // Check if any case in dataset is referenced
      for (const [titleFrag, targetId] of titleIndex) {
        if (targetId === c.case_id) continue; // don't self-cite
        if (refLower.includes(titleFrag)) {
          if (!citedByMap.has(targetId)) citedByMap.set(targetId, new Set());
          citedByMap.get(targetId).add(c.case_id);
        }
      }
    }
  }

  // Attach count to each case
  for (const c of cases) {
    const citers = citedByMap.get(c.case_id);
    c.__citedByCount = citers ? citers.size : 0;
  }
}

function setDatasetStatus(message, isError = false) {
  // Preserve server connection note if present
  const serverNote = el.datasetStatus.querySelector(".server-note");
  el.datasetStatus.textContent = message;
  if (serverNote) el.datasetStatus.appendChild(serverNote);
  el.datasetStatus.classList.toggle("dataset-error", isError);
}

function setDatasetMeta(message) {
  // Preserve server badge if it exists
  const badge = el.datasetMeta.querySelector(".server-badge");
  el.datasetMeta.textContent = message;
  if (badge) el.datasetMeta.appendChild(badge);
}

function setSearchEnabled(enabled) {
  el.searchInput.disabled = !enabled;
  el.searchBtn.disabled = !enabled;
  if (el.inlineSearchInput) el.inlineSearchInput.disabled = !enabled;
  if (el.inlineSearchBtn) el.inlineSearchBtn.disabled = !enabled;
  el.filterToggleBtn.disabled = !enabled;
  el.dateFrom.disabled = !enabled;
  el.dateTo.disabled = !enabled;
  if (el.exportIncludeClassifier) el.exportIncludeClassifier.disabled = !enabled;

  const dynamicInputs = document.querySelectorAll(
    "#sectionsFilters input, #countriesFilters input, #articlesFilters input, #keywordsFilters input, #importanceFilters input, #outcomeFilters input, #separateOpinionFilters input"
  );
  for (const input of dynamicInputs) {
    input.disabled = !enabled;
  }

  el.searchForm.classList.toggle("search-disabled", !enabled);

  el.exportBtn.disabled = !enabled || !state.currentOrderedCaseIds.length;
  if (el.cardModeBtn) el.cardModeBtn.disabled = !enabled;
  if (el.clearBtn) el.clearBtn.disabled = !enabled;
  el.openClassifierBtn.disabled = !enabled;
  if (el.classifierQuickOpenBtn) el.classifierQuickOpenBtn.disabled = !enabled;
}

function setDatasetLoading(loading) {
  el.loadSampleBtn.disabled = loading;
  el.fileInput.disabled = loading;
  if (!state.loaded) {
    el.openClassifierBtn.disabled = true;
    if (el.classifierQuickOpenBtn) el.classifierQuickOpenBtn.disabled = true;
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
    // Both raw DB labels collapse into the unified "facts" bucket.
    // See the note above SECTION_ORDER for the rationale.
    "facts background": "facts",
    facts_background: "facts",
    "facts proceedings": "facts",
    facts_proceedings: "facts",
    facts: "facts",
    // "Legal Context" is an orphan (6 paragraphs in 2 Polish 2026 cases) —
    // collapse into legal_framework. See SECTION_ORDER note above.
    "legal framework": "legal_framework",
    legal_framework: "legal_framework",
    "legal context": "legal_framework",
    legal_context: "legal_framework",
    "relevant legal framework": "legal_framework",
    relevant_legal_framework: "legal_framework",
    "commission proceedings": "commission_proceedings",
    commission_proceedings: "commission_proceedings",
    "final submissions": "final_submissions",
    final_submissions: "final_submissions",
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

function extractHudocId(hudocUrl) {
  const text = String(hudocUrl || "").trim();
  if (!text) return "";
  const match = text.match(/[?&]i=([^&#]+)/i);
  return match ? String(match[1] || "").trim() : "";
}

function buildStateSearchValues(states) {
  const values = new Set();
  for (const rawState of states) {
    const stateText = String(rawState || "").trim();
    if (!stateText) continue;

    const stateUpper = stateText.toUpperCase();
    const fromCode = COUNTRY_NAMES[stateUpper] || "";
    const nameNorm = normalizeSearchText(fromCode || stateText);
    if (nameNorm) values.add(nameNorm);

    const codeFromName = COUNTRY_CODE_BY_NAME_NORM[nameNorm] || (COUNTRY_NAMES[stateUpper] ? stateUpper : "");
    if (codeFromName) values.add(normalizeSearchText(codeFromName));
  }
  return [...values];
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
    const stateSearchValues = buildStateSearchValues(states);
    const documentType = normalizeDocumentTypes(caseObj);
    const originatingBody = String(caseObj.originating_body || "").trim();
    const importance = String(caseObj.importance || "").trim();
    const separateOpinion = parseBoolLike(caseObj.separate_opinion);
    const keywords = normalizeListField(caseObj.keywords);
    const violation = normalizeListField(caseObj.violation);
    const nonViolation = normalizeListField(caseObj["non-violation"]);
    const chamberComposedOf = normalizeListField(caseObj.chamber_composed_of);
    const strasbourgCaselaw = normalizeCitationList(caseObj.strasbourg_caselaw);
    const representedBy = String(caseObj.represented_by || "").trim();
    const ecli = String(caseObj.ecli || "").trim();
    const hudocUrl = String(caseObj.hudoc_url || "").trim();
    const hudocId = extractHudocId(hudocUrl);
    const articleTokens = splitArticles(caseObj.article_no);
    const articleTokensNorm = articleTokens.map((token) => normalizeArticleToken(token));
    const chamberCategory = deriveChamberCategory(documentType, originatingBody);
    const conclusion = String(caseObj.conclusion || "").trim();
    const outcomeFlags = parseConclusionFlags(conclusion);
    const citationRefsNorm = strasbourgCaselaw.map((item) => normalizeSearchText(item));

    const rawParagraphs = Array.isArray(caseObj.paragraphs) ? caseObj.paragraphs : [];
    const parsedParagraphs = [];

    for (let p = 0; p < rawParagraphs.length; p += 1) {
      const para = rawParagraphs[p] || {};
      const section = normalizeSectionKey(para.section || "unknown");
      const text = String(para.text || "").trim();
      if (!text) continue;

      const idx = Number(para.para_idx);
      const paraIdx = Number.isFinite(idx) ? idx : p;
      const hudocParaNo = (para.hudoc_para_no != null && Number.isFinite(Number(para.hudoc_para_no)))
        ? Number(para.hudoc_para_no) : null;
      const numberingBlock = para.numbering_block || null;
      const rowRole = para.row_role || null;

      parsedParagraphs.push({
        section,
        paraIdx,
        hudocParaNo,
        numberingBlock,
        rowRole,
        localIdx: parsedParagraphs.length,
        text,
        textLower: text.toLowerCase(),
        textNorm: normalizeSearchText(text),
      });
    }

    const ts = parseDateInput(caseObj.judgment_date);
    const metadataSearchParts = [
      caseId,
      caseObj.case_no || "",
      caseObj.title || "",
      ecli,
      hudocUrl,
      hudocId,
      originatingBody,
      representedBy,
      importance,
      states.join(" "),
      articleTokens.join(" "),
      keywords.join(" "),
      chamberComposedOf.join(" "),
      strasbourgCaselaw.join(" "),
      conclusion,
    ];
    const searchMetaText = normalizeSearchText(metadataSearchParts.join(" "));

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
      __articles: articleTokens,
      __articlesNorm: articleTokensNorm,
      __states: states,
      __stateSearchValues: stateSearchValues,
      __originatingBody: originatingBody || "Unknown",
      __originatingBodyNorm: normalizeSearchText(originatingBody || "Unknown"),
      __importance: importance || "Unspecified",
      __outcomeBucket: deriveOutcomeBucket(violation, nonViolation),
      __hasInadmissibility: outcomeFlags.hasInadmissibility,
      __isStruckOut: outcomeFlags.isStruckOut,
      __hasProceduralAspect: outcomeFlags.hasProceduralAspect,
      __hasSubstantiveAspect: outcomeFlags.hasSubstantiveAspect,
      __hasSeparateOpinion: separateOpinion,
      __hasStrasbourgCaselaw: strasbourgCaselaw.length > 0,
      __hasDomesticLaw: isPresentValue(caseObj.domestic_law),
      __hasInternationalLaw: isPresentValue(caseObj.international_law),
      __hasRulesOfCourt: isPresentValue(caseObj.rules_of_court),
      __keywordsNorm: keywords.map((k) => normalizeSearchText(k)),
      __keywordsText: normalizeSearchText(keywords.join(" ")),
      __judgesNorm: chamberComposedOf.map((judge) => normalizeSearchText(judge)),
      __citationRefsNorm: citationRefsNorm,
      __citationRefs: strasbourgCaselaw,
      __searchMetaText: searchMetaText,
      __caseNoNorm: normalizeSearchText(caseObj.case_no || ""),
      __caseIdNorm: normalizeSearchText(caseId),
      __titleNorm: normalizeSearchText(caseObj.title || ""),
      __ecliNorm: normalizeSearchText(ecli),
      __hudocNorm: normalizeSearchText(hudocUrl),
      __hudocIdNorm: normalizeSearchText(hudocId),
      __chamberCategory: chamberCategory,
      __isPressRelease: documentType.some(dt => dt.toLowerCase().includes("press release")),
      __outcomePrimary: documentType.some(dt => dt.toLowerCase().includes("press release")) ? "press_release" : deriveOutcomeBucket(violation, nonViolation),
      __judgmentDateTs: ts,
      __sortTs: ts == null ? -Infinity : ts,
      __paragraphs: enrichContinuationParaNos(parsedParagraphs),
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
        hudocParaNo: para.hudocParaNo,
        numberingBlock: para.numberingBlock,
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
        hudocParaNo: para.hudocParaNo,
        numberingBlock: para.numberingBlock,
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
  state.importanceLevels = sortImportanceLevels([...importanceLevels]);
  state.sectionsInDataset = [...sections].sort((a, b) => {
    const ai = SECTION_ORDER.indexOf(a);
    const bi = SECTION_ORDER.indexOf(b);
    if (ai !== -1 && bi !== -1) return ai - bi;
    if (ai !== -1) return -1;
    if (bi !== -1) return 1;
    return a.localeCompare(b);
  });
  computeCitedByCounts(cases);
  state.loaded = true;
}

function makeCheckbox(label, value, name, count = null, opts = {}) {
  // Show the count whenever one is supplied — including 0, so a value that
  // exists in the corpus but has no hits in the current search is visibly
  // de-emphasised rather than silently losing its number.
  const countSuffix = (count != null)
    ? ` <span class="filter-count${count === 0 ? " is-zero" : ""}">${fmtInt.format(count)}</span>`
    : "";
  // The hint icon goes INSIDE the label span so it stays inline with the
  // label text rather than wrapping to the next row in a flex/grid layout.
  const hint = opts.hint
    ? ` <span class="section-hint-icon" title="${escapeHtml(opts.hint)}">ⓘ</span>`
    : "";
  const tooltip = opts.tooltip ? ` title="${escapeHtml(opts.tooltip)}"` : "";
  return `<label class="cb-label"${tooltip}><input type="checkbox" data-name="${name}" value="${escapeHtml(value)}"> <span>${escapeHtml(label)}${countSuffix}${hint}</span></label>`;
}

/** Render filter SHELL on page load — before facets API has returned —
 *  so the user immediately sees structure (filter group titles, fixed
 *  options, and "Loading…" placeholders for dynamic lists). Eliminates
 *  the 1-2s blank-filter window during server probe + facets fetch. */
function renderFiltersSkeleton() {
  const loading = '<p class="filter-loading">Loading…</p>';
  if (el.sectionsFilters) el.sectionsFilters.innerHTML = loading;
  if (el.countriesFilters) el.countriesFilters.innerHTML = loading;
  if (el.articlesFilters) el.articlesFilters.innerHTML = loading;
  if (el.keywordsFilters) el.keywordsFilters.innerHTML = loading;
  if (el.importanceFilters) el.importanceFilters.innerHTML = loading;

  // Fixed filters that don't depend on facets — render immediately.
  // Court Formation = the bench that decided the case (Chamber / Grand
  // Chamber / Committee); the raw HUDOC "originating_body" breakdown is
  // just this aggregated, so it isn't shown as a separate filter.
  if (el.docTypeFilters) {
    el.docTypeFilters.innerHTML = [
      makeCheckbox("Chamber", "chamber", "docTypes", null,
        { tooltip: "Standard 7-judge Chamber judgments — the typical post-1998 format." }),
      makeCheckbox("Grand Chamber", "grand_chamber", "docTypes", null,
        { tooltip: "17-judge Grand Chamber judgments — major principles and inter-state cases." }),
      makeCheckbox("Committee", "committee", "docTypes", null,
        { tooltip: "3-judge Committee judgments — repetitive cases following well-established case-law." }),
    ].join("");
  }
  if (el.outcomeFilters) {
    el.outcomeFilters.innerHTML = [
      makeCheckbox("Violation only", "violation_only", "outcomes"),
      makeCheckbox("Non-violation only", "non_violation_only", "outcomes"),
      makeCheckbox("Mixed (violation + non-violation)", "both", "outcomes"),
      makeCheckbox("No finding", "neither", "outcomes"),
      makeCheckbox("Inadmissibility", "has_inadmissibility", "outcomes"),
      makeCheckbox("Struck out", "is_struck_out", "outcomes"),
    ].join("");
  }
  if (el.separateOpinionFilters) {
    el.separateOpinionFilters.innerHTML = [
      makeCheckbox("Yes", "yes", "separateOpinion"),
      makeCheckbox("No", "no", "separateOpinion"),
    ].join("");
  }
}

function renderFilters() {
  const fc = state.facetCounts || { sections: {}, articles: {}, countries: {}, bodies: {}, importance: {}, docTypes: {} };

  // Sections — with hints for rare or pre-Protocol-11 sections.
  // Section hint also serves as the checkbox tooltip so users hovering the
  // label (not just the ⓘ icon) get the same info.
  el.sectionsFilters.innerHTML = state.sectionsInDataset
    .map((sec) => makeCheckbox(
      SECTION_LABELS[sec] || sec,
      sec,
      "sections",
      fc.sections[sec],
      { hint: SECTION_HINTS[sec] || null, tooltip: SECTION_HINTS[sec] || null }
    ))
    .join("");

  el.countriesFilters.innerHTML = state.countries
    .map((code) => makeCheckbox(COUNTRY_NAMES[code] || code, code, "countries", fc.countries[code]))
    .join("");

  el.articlesFilters.innerHTML = state.articles
    .map((article) => makeCheckbox(`Art. ${article}`, article, "articles", fc.articles[article]))
    .join("");

  // Keywords — HUDOC thesaurus labels (full verbatim, no truncation:
  // researchers recognise them in their entirety).  Search-as-you-type
  // box above is attached by attachFilterSearchBoxes for the 500-ish
  // value list.
  if (el.keywordsFilters) {
    el.keywordsFilters.innerHTML = state.keywords
      .map((kw) => makeCheckbox(kw, kw, "keywords", (fc.keywords || {})[kw]))
      .join("");
  }

  // Importance — descriptive labels + tooltip explaining HUDOC's scheme
  el.importanceFilters.innerHTML = state.importanceLevels
    .map((level) => makeCheckbox(
      IMPORTANCE_LABELS[level] || level,
      level,
      "importance",
      fc.importance[level],
      { tooltip: IMPORTANCE_TOOLTIPS[level] || null }
    ))
    .join("");

  el.docTypeFilters.innerHTML = [
    makeCheckbox("Chamber", "chamber", "docTypes", fc.docTypes.chamber,
      { tooltip: "Standard 7-judge Chamber judgments — the typical post-1998 format." }),
    makeCheckbox("Grand Chamber", "grand_chamber", "docTypes", fc.docTypes.grand_chamber,
      { tooltip: "17-judge Grand Chamber judgments — major principles and inter-state cases." }),
    makeCheckbox("Committee", "committee", "docTypes", fc.docTypes.committee,
      { tooltip: "3-judge Committee judgments — repetitive cases following well-established case-law. Often have applicant tables in Introduction." }),
  ].join("");

  el.outcomeFilters.innerHTML = [
    makeCheckbox("Violation only", "violation_only", "outcomes", null,
      { tooltip: "Court found at least one violation; no non-violation findings." }),
    makeCheckbox("Non-violation only", "non_violation_only", "outcomes", null,
      { tooltip: "Court found no violation on any complaint examined." }),
    makeCheckbox("Mixed (violation + non-violation)", "both", "outcomes", null,
      { tooltip: "Court found violation on some Articles, no violation on others." }),
    makeCheckbox("No finding", "neither", "outcomes", null,
      { tooltip: "Procedural disposition without substantive Article finding (e.g., struck out, settled)." }),
    makeCheckbox("Inadmissibility", "has_inadmissibility", "outcomes", null,
      { tooltip: "Application declared inadmissible in whole or in part." }),
    makeCheckbox("Struck out", "is_struck_out", "outcomes", null,
      { tooltip: "Case struck out of the list (settled, withdrawn, applicant deceased, etc.)." }),
  ].join("");

  el.separateOpinionFilters.innerHTML = [
    makeCheckbox("Yes", "yes", "separateOpinion", null,
      { tooltip: "Case has at least one dissenting / concurring / partly dissenting opinion." }),
    makeCheckbox("No", "no", "separateOpinion", null,
      { tooltip: "Unanimous decision — no separate opinions." }),
  ].join("");

  // Wire up search filter inputs (boxes for long lists)
  attachFilterSearchBoxes();
  // Wire up per-group "Clear" buttons
  attachFilterGroupClearButtons();
  // Update toggle button "Advanced Filters (N active)" badge
  updateActiveFilterCount();
}

/** Transform a raw /api/facets response into the value→count maps that
 *  renderFilters() / applyRailCounts() consume.  Used both for the
 *  whole-corpus counts (page load) and the per-search scoped counts. */
function buildFacetCounts(facets) {
  const fc = { sections: {}, articles: {}, countries: {}, bodies: {}, importance: {}, docTypes: {}, keywords: {} };
  // Reverse map: DB section name → normalized bucket key.
  const DB_TO_NORM = {};
  for (const [norm, dbArr] of Object.entries(SECTION_DB_NAMES)) {
    for (const db of dbArr) DB_TO_NORM[db] = norm;
  }
  if (facets.sections) {
    // MAX (not SUM) per bucket — a case may have paragraphs in several raw
    // DB sections that collapse to one bucket; summing would double-count.
    for (const f of facets.sections) {
      const key = DB_TO_NORM[f.value] || f.value;
      if (SECTION_LABELS[key]) {
        fc.sections[key] = Math.max(fc.sections[key] || 0, f.count || 0);
      }
    }
  }
  if (facets.states) {
    for (const f of facets.states) if (f.value) fc.countries[f.value] = f.count || 0;
  }
  if (facets.articles) {
    for (const f of facets.articles) fc.articles[f.value] = f.count || 0;
  }
  if (facets.keywords) {
    for (const f of facets.keywords) if (f.value) fc.keywords[f.value] = f.count || 0;
  }
  if (facets.bodies) {
    for (const f of facets.bodies) fc.bodies[f.value] = f.count || 0;
  }
  if (facets.importance) {
    for (const f of facets.importance) if (f.value) fc.importance[f.value] = f.count || 0;
  }
  if (facets.doc_types) {
    // Collapse raw doc_type strings into the 4 frontend buckets.
    const dt = fc.docTypes;
    for (const f of facets.doc_types) {
      const v = (f.value || "").toLowerCase();
      if (v.includes("press release")) dt.press_release = (dt.press_release || 0) + (f.count || 0);
      else if (v.includes("committee")) dt.committee = (dt.committee || 0) + (f.count || 0);
      else dt.chamber = (dt.chamber || 0) + (f.count || 0);
    }
    // Grand Chamber count comes from the originating_body facet.
    const gcBody = (facets.bodies || []).find(
      (b) => (b.value || "").toLowerCase().includes("grand chamber"));
    if (gcBody) {
      dt.grand_chamber = gcBody.count;
      dt.chamber = Math.max(0, (dt.chamber || 0) - gcBody.count);
    }
  }
  return fc;
}

/** Update the filter-rail count badges in place from state.facetCounts —
 *  without re-rendering the rail, so checkbox + filter-search-box state is
 *  preserved.  Counts of 0 are shown (de-emphasised via .is-zero). */
function applyRailCounts() {
  const fc = state.facetCounts;
  if (!fc || !el.filtersPanel) return;
  const groupMap = {
    sections: fc.sections, countries: fc.countries, articles: fc.articles,
    keywords: fc.keywords, bodies: fc.bodies, importance: fc.importance,
    docTypes: fc.docTypes,
  };
  el.filtersPanel.querySelectorAll('input[type="checkbox"][data-name]').forEach((input) => {
    const map = groupMap[input.getAttribute("data-name")];
    if (!map) return; // outcomes / separateOpinion — no facet data
    const count = map[input.value];
    const labelSpan = input.parentElement.querySelector("span");
    if (!labelSpan) return;
    let span = labelSpan.querySelector(".filter-count");
    if (count == null) {
      if (span) span.remove();
      return;
    }
    if (!span) {
      // Insert before the hint icon so order stays "label  N  ⓘ".
      span = document.createElement("span");
      span.className = "filter-count";
      const hint = labelSpan.querySelector(".section-hint-icon");
      labelSpan.insertBefore(document.createTextNode(" "), hint || null);
      labelSpan.insertBefore(span, hint || null);
    }
    span.textContent = fmtInt.format(count);
    span.classList.toggle("is-zero", count === 0);
  });
}

let _railCountSeq = 0;
/** Refresh the filter-rail counts so they reflect the active search.
 *  No query and no date range → whole-corpus counts (cached on load);
 *  otherwise the counts are scoped to the matching cases via /api/facets.
 *  The checkbox filters are deliberately NOT applied — the rail shows a
 *  stable breakdown of the text search, not a self-narrowing facet view. */
async function refreshRailCounts(query, filters) {
  if (!serverSearch.available) return;
  const q = (query || "").trim();
  const dFrom = (filters && filters.dateFrom)
    ? new Date(filters.dateFrom).toISOString().slice(0, 10) : "";
  const dTo = (filters && filters.dateTo)
    ? new Date(filters.dateTo).toISOString().slice(0, 10) : "";
  if (!q && !dFrom && !dTo) {
    // Whole-corpus view — restore the cached global counts.
    if (state.globalFacetCounts) {
      state.facetCounts = state.globalFacetCounts;
      applyRailCounts();
    }
    return;
  }
  const seq = ++_railCountSeq;
  try {
    const facets = await serverSearch.getFacets({ q, date_from: dFrom, date_to: dTo });
    if (seq !== _railCountSeq) return; // a newer search superseded this one
    const fc = buildFacetCounts(facets);
    // Zero-fill against the stable option lists so every checkbox shows a
    // number (0 = value exists in the corpus, no hits in this search).
    for (const s of (state.sectionsInDataset || [])) if (fc.sections[s] == null) fc.sections[s] = 0;
    for (const c of (state.countries || [])) if (fc.countries[c] == null) fc.countries[c] = 0;
    for (const a of (state.articles || [])) if (fc.articles[a] == null) fc.articles[a] = 0;
    for (const k of (state.keywords || [])) if (fc.keywords[k] == null) fc.keywords[k] = 0;
    for (const b of (state.bodies || [])) if (fc.bodies[b] == null) fc.bodies[b] = 0;
    for (const i of (state.importanceLevels || [])) if (fc.importance[i] == null) fc.importance[i] = 0;
    for (const d of ["chamber", "grand_chamber", "committee", "press_release"]) {
      if (fc.docTypes[d] == null) fc.docTypes[d] = 0;
    }
    state.facetCounts = fc;
    applyRailCounts();
  } catch (e) {
    console.warn("[Rail Counts] scoped facets fetch failed:", e);
  }
}

/** Attach a search input above any scrollable filter list, hiding non-matching
 *  checkbox labels as the user types. Idempotent — re-run after renderFilters(). */
function attachFilterSearchBoxes() {
  const targets = [
    { container: el.countriesFilters, placeholder: "Search countries…", key: "countries" },
    { container: el.articlesFilters, placeholder: "Search articles…", key: "articles" },
    { container: el.keywordsFilters, placeholder: "Search keywords…", key: "keywords" },
  ];
  for (const t of targets) {
    if (!t.container) continue;
    const parent = t.container.parentElement;
    if (!parent) continue;
    let searchInput = parent.querySelector(`.filter-search-input[data-key="${t.key}"]`);
    if (!searchInput) {
      searchInput = document.createElement("input");
      searchInput.type = "search";
      searchInput.className = "filter-search-input";
      searchInput.placeholder = t.placeholder;
      searchInput.dataset.key = t.key;
      searchInput.setAttribute("aria-label", t.placeholder);
      parent.insertBefore(searchInput, t.container);
      searchInput.addEventListener("input", () => {
        const q = searchInput.value.trim().toLowerCase();
        const labels = t.container.querySelectorAll("label.cb-label");
        let visible = 0;
        labels.forEach((lbl) => {
          const txt = lbl.textContent.toLowerCase();
          const match = !q || txt.includes(q);
          lbl.style.display = match ? "" : "none";
          if (match) visible++;
        });
        let emptyMsg = parent.querySelector(".filter-empty-msg");
        if (visible === 0 && q) {
          if (!emptyMsg) {
            emptyMsg = document.createElement("p");
            emptyMsg.className = "filter-empty-msg";
            emptyMsg.textContent = "No matches.";
            t.container.parentElement.insertBefore(emptyMsg, t.container.nextSibling);
          }
          emptyMsg.hidden = false;
        } else if (emptyMsg) {
          emptyMsg.hidden = true;
        }
      });
    }
  }
}

/** Add a small "Clear" button next to each filter-group title that has any
 *  checked checkboxes. Click clears just that group + reruns search. */
function attachFilterGroupClearButtons() {
  document.querySelectorAll("#filtersPanel .filter-group").forEach((group) => {
    const titles = group.querySelectorAll(".filter-title");
    titles.forEach((title) => {
      // Find the checkbox container that follows this title
      let next = title.nextElementSibling;
      while (next && !next.classList.contains("checkbox-grid") && !next.classList.contains("date-range")) {
        next = next.nextElementSibling;
      }
      if (!next) return;
      // Check if there's at least one checked input in this container
      const checked = next.querySelectorAll('input[type="checkbox"]:checked').length;
      let btn = title.querySelector(".filter-group-clear");
      if (checked > 0) {
        if (!btn) {
          btn = document.createElement("button");
          btn.type = "button";
          btn.className = "filter-group-clear";
          btn.textContent = "Clear";
          btn.title = "Clear selections in this group";
          title.appendChild(btn);
          btn.addEventListener("click", (e) => {
            e.stopPropagation();
            next.querySelectorAll('input[type="checkbox"]:checked').forEach((cb) => {
              cb.checked = false;
            });
            // Trigger filter change handler
            next.dispatchEvent(new Event("change", { bubbles: true }));
          });
        }
        btn.style.display = "";
        btn.textContent = `Clear (${checked})`;
      } else if (btn) {
        btn.style.display = "none";
      }
    });
  });
}

/** Show "Advanced Filters (N active)" on the toggle button so users always
 *  know how many filters are currently constraining results. */
function updateActiveFilterCount() {
  if (!el.filterToggleBtn) return;
  // Count only ADVANCED filters — the badge surfaces selections hidden
  // inside the collapsed advanced section.  Common filters (countries,
  // articles, date, importance, outcome) are always visible, so they
  // need no badge.
  const active = document.querySelectorAll('#filtersAdvanced input[type="checkbox"]:checked').length;
  // Caret reflects the collapse state: ▶ collapsed, ▼ expanded.
  const expanded = el.filterToggleBtn.getAttribute("aria-expanded") === "true";
  const iconHTML = `<span class="filter-toggle-icon">${expanded ? "▼" : "▶"}</span>`;
  if (active > 0) {
    el.filterToggleBtn.innerHTML = `${iconHTML} Advanced Filters <span class="active-filter-badge">${active}</span>`;
  } else {
    el.filterToggleBtn.innerHTML = `${iconHTML} Advanced Filters`;
  }
}

function renderGlobalStats() {
  // When server API is connected, KPI bar shows full server stats — don't overwrite
  if (serverSearch.available) return;

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
  // v1 bucket toggles — checkbox `data-name="buckets" value="<bucket-key>"`.
  // When none are checked AND no granular section is selected, fall
  // back to all defaultOn buckets (Facts + Adm/Merits + Just Sat +
  // Operative).  Individual opinions are off by default.
  const buckets = collectChecked("buckets");
  return {
    sections: collectChecked("sections"),
    buckets,
    countries: collectChecked("countries"),
    articles: collectChecked("articles"),
    keywords: collectChecked("keywords"),
    bodies: collectChecked("bodies"),
    importance: collectChecked("importance"),
    outcomes: collectChecked("outcomes"),
    docTypes: collectChecked("docTypes"),
    separateOpinion: collectChecked("separateOpinion"),
    presence: collectChecked("presence"),
    dateFrom: parseDateInput(el.dateFrom.value),
    dateTo: parseDateInput(el.dateTo.value),
    // Search-scope toggles: by default we search only judgment BODY
    // sections (Facts → Operative).  These flags opt-in to the
    // additional content classes.
    includeOpinions: buckets.has("individual_opinions") || !!document.getElementById("scopeIncludeOpinions")?.checked,
    // "Cover page & headings" — a single Advanced-filters toggle that
    // expands the scope to both the cover-page (header) section and the
    // section-heading rows.  includeMeta + includeHeadings drive distinct
    // downstream logic (section list vs exclude_roles) but are now flipped
    // together by one user-facing switch.
    includeMeta: !!document.getElementById("scopeIncludeExtra")?.checked,
    includeHeadings: !!document.getElementById("scopeIncludeExtra")?.checked,
    // "Appendix" — its own "Also search in" checkbox (annexes, applicant
    // tables, compensation schedules that follow the operative part).
    includeAppendix: !!document.getElementById("scopeIncludeAppendix")?.checked,
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

  if (filters.bodies.size && !filters.bodies.has(c.__originatingBody)) {
    return false;
  }

  if (filters.importance.size && !filters.importance.has(c.__importance)) {
    return false;
  }

  if (filters.outcomes.size) {
    // OR semantics across all outcome options.
    // Primary outcomes (violation_only etc.) match __outcomePrimary;
    // flag-based options (has_inadmissibility, is_struck_out) match boolean fields.
    const primaryMatch = [...filters.outcomes].some(
      v => PRIMARY_OUTCOMES.has(v) && v === c.__outcomePrimary
    );
    const inadmissibleMatch = filters.outcomes.has("has_inadmissibility") && c.__hasInadmissibility;
    const struckOutMatch = filters.outcomes.has("is_struck_out") && c.__isStruckOut;
    if (!primaryMatch && !inadmissibleMatch && !struckOutMatch) return false;
  }

  if (filters.docTypes.size) {
    const dtKeys = c.__isPressRelease
      ? ["press_release"]
      : c.__isGrandChamber
        ? ["grand_chamber", "judgment"]
        : c.__isCommittee
          ? ["committee", "judgment"]
          : ["chamber", "judgment"];
    if (!dtKeys.some(k => filters.docTypes.has(k))) return false;
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

  if (filters.dateFrom != null && (c.__judgmentDateTs == null || c.__judgmentDateTs < filters.dateFrom)) {
    return false;
  }

  if (filters.dateTo != null && (c.__judgmentDateTs == null || c.__judgmentDateTs > filters.dateTo)) {
    return false;
  }

  return true;
}

/**
 * Format a paragraph number for display.
 *
 * HUDOC has multiple independent numbering schemes within a single judgment:
 *   - main_judgment        — paragraphs 1..N of the body
 *   - operative_dispositif — numbered ruling clauses ("1. Decides", "2. Holds")
 *   - separate_opinion_N   — paragraph M within the Nth separate opinion
 *
 * To disambiguate, this helper reads `numberingBlock` (set by P12) and adds
 * a prefix where appropriate:
 *   "¶ 56"            → main judgment paragraph 56
 *   "Op. ¶ 1"         → operative dispositif clause 1
 *   "SO 2 · ¶ 5"      → 5th paragraph of the 2nd separate opinion
 *   "¶ 76*"           → fallback (no HUDOC number — heading, fragment, or
 *                       committee-case paragraph without preserved numbering)
 *
 * Discovered during expert manual review M3/M4 (2026-04-28).
 * See methodology-internal/data-cleaning-full.md §11.
 */
function formatParaNum(p) {
  if (!p) return "¶ ?";
  // Priority: hudocParaNo > inheritedParaNo (continuation row of most-recent
  // numbered ¶) > "—" placeholder.  paraIdx is NOT used as a label fallback:
  // post-P23 every Pop C row carries an in-document position, but rendering
  // it as "¶ 37*" alongside real ¶ 37 from the Court's own numbering created
  // false-paragraph confusion (L.P. Operative Part: "Op. ¶ 37* Decides…"
  // looked like a continuation of JS ¶ 37).  An em-dash makes it clear the
  // row is unnumbered.
  let num;
  if (p.displayParaNo != null) {
    // P58: persisted display number — for a fragment hit (bullet/quote/
    // continuation) this is the parent body ¶, so the result row reads
    // "¶ 54" instead of a stranded "¶ —".  Only search hits carry it;
    // modal rows don't, so continuation rows there stay marker-less.
    num = `¶ ${p.displayParaNo}`;
  } else if (p.hudocParaNo != null) {
    num = `¶ ${p.hudocParaNo}`;
  } else if (p.inheritedParaNo != null) {
    // Continuation row: NO visible marker.  CSS (.modal-para-continuation)
    // provides the visual indent + left rule; the row is treated as part
    // of the parent paragraph for citation/search-result purposes.
    num = "";
  } else {
    num = "¶ —";
  }
  const block = p.numberingBlock;
  if (!block || block === "main_judgment") return num;
  if (block === "operative_dispositif") return `Op. ${num}`;
  if (block.startsWith("separate_opinion_")) {
    const n = block.split("_")[2];
    return `SO ${n} · ${num}`;
  }
  return num;
}

/**
 * Walk paragraphs in document order; on every orphan row (no hudoc_para_no
 * AND no para_idx) that follows a numbered row in the same section, record
 * the parent ¶ number on `inheritedParaNo`.  This lets:
 *   - the modal render the row as a continuation block (indented quote);
 *   - search results cite the orphan as "¶ N cont." instead of "¶ —";
 *   - downstream features (export, citation copy) treat the parent + its
 *     continuations as one logical paragraph-level unit.
 *
 * A structural heading or a section change breaks the chain — anything
 * after a sub-section title can no longer claim to be a continuation of
 * the paragraph above the heading.
 *
 * Mutates paragraphs in place; safe to call multiple times (idempotent).
 */
function enrichContinuationParaNos(paragraphs) {
  if (!Array.isArray(paragraphs)) return paragraphs;
  let lastNumberedParaNo = null;
  let lastSection = null;
  // pendingOrphans: indices of orphan rows that haven't been able to claim a
  // parent ¶ yet because nothing numbered has appeared in the current
  // section.  When we eventually hit the first numbered ¶ N, every pending
  // orphan inherits (N − 1) — i.e. the implied tail of the previous
  // paragraph that the PDF segmenter detached when crossing a section
  // boundary or a quoted blockquote.
  let pendingOrphans = [];
  const flushPending = (parentNo) => {
    for (const idx of pendingOrphans) {
      const p = paragraphs[idx];
      if (p && parentNo != null) p.inheritedParaNo = parentNo;
    }
    pendingOrphans = [];
  };
  for (let i = 0; i < paragraphs.length; i++) {
    const p = paragraphs[i];
    if (!p) continue;
    if (p.section !== lastSection) {
      // Section changed — abandon any orphans we couldn't place; they keep
      // null inheritedParaNo so the renderer falls back to "¶ —".
      pendingOrphans = [];
      lastSection = p.section;
      lastNumberedParaNo = null;
    }
    const isHeadingRole = p.rowRole && (
      p.rowRole === "heading" ||
      p.rowRole.startsWith("heading_") ||
      ["metadata", "signature", "footer", "table_cell"].includes(p.rowRole)
    );
    // Quote rows (Ju_Quot) carry the source document's own numbering
    // including elision markers like "..." that look all-uppercase /
    // all-digit-and-punctuation to `isStructuralHeading`.  Don't let
    // that misclassification break the quote→parent chain: only check
    // structural heading text when the row is NOT already tagged as
    // a quote.
    const looksStructural = p.rowRole !== "quote" && isStructuralHeading(p.text);
    if (isHeadingRole || looksStructural) {
      lastNumberedParaNo = null;
      pendingOrphans = [];
      p.inheritedParaNo = null;
      continue;
    }
    if (p.hudocParaNo != null) {
      // OUT-OF-ORDER GUARD.  A numbered ¶ N that appears far away from the
      // most-recent ¶ M in the same section is almost always a fragment of
      // M's running text where the segmenter saw "(see paragraph N above)"
      // or "Article N § X of the Convention" and tokenised "N." as a
      // paragraph start.  L.P. v. Hungary shows ¶ 7 sandwiched between
      // ¶ 23 and ¶ 24, ¶ 1 between ¶ 26 and ¶ 27 (back-jumps), and ¶ 44
      // after ¶ 37 with text starting "§ 2 of the Convention" (forward
      // jump + mid-sentence opener).
      const strippedHead = (p.text || "").replace(/^\d+\.\s+/, "").slice(0, 12);
      const looksMidSentence = /^[§(),·]/.test(strippedHead) || /^[a-z]/.test(strippedHead);
      const backJump = lastNumberedParaNo != null && p.hudocParaNo + 5 <= lastNumberedParaNo;
      const forwardJump = lastNumberedParaNo != null && p.hudocParaNo >= lastNumberedParaNo + 4 && looksMidSentence;
      if (backJump || forwardJump) {
        p.inheritedParaNo = lastNumberedParaNo;
        p.hudocParaNoOriginal = p.hudocParaNo;
        p.hudocParaNo = null;
        continue;
      }
      // First numbered ¶ after a run of orphans → orphans belong to (N − 1).
      if (pendingOrphans.length && lastNumberedParaNo == null) {
        flushPending(Math.max(1, p.hudocParaNo - 1));
      }
      lastNumberedParaNo = p.hudocParaNo;
      p.inheritedParaNo = null;
    } else if (lastNumberedParaNo != null) {
      // Orphan within a section that already has a numbered ¶ — continuation.
      // We do NOT bail out when paraIdx is set, because P23 backfilled
      // paraIdx on every Pop C row; gating on it would suppress the cont.
      // label entirely on committee judgments.
      p.inheritedParaNo = lastNumberedParaNo;
    } else {
      // Orphan with no numbered antecedent yet — park it; flushPending will
      // fill in inheritedParaNo when we eventually see a numbered ¶.
      p.inheritedParaNo = null;
      pendingOrphans.push(i);
    }
  }
  return paragraphs;
}

function formatParaNumTitle(p) {
  if (!p) return "";
  const block = p.numberingBlock;
  let baseDesc;
  if (p.hudocParaNo != null) {
    baseDesc = `HUDOC paragraph ${p.hudocParaNo}`;
  } else if (p.paraIdx != null) {
    baseDesc = `Internal index ¶${p.paraIdx + 1} (no HUDOC number)`;
  } else if (p.inheritedParaNo != null) {
    baseDesc = `Continuation of HUDOC paragraph ${p.inheritedParaNo} — typically a quoted statute or treaty article that appears as a sub-block within ¶ ${p.inheritedParaNo}`;
  } else {
    baseDesc = "Unnumbered fragment (no HUDOC paragraph number)";
  }
  if (!block || block === "main_judgment") return baseDesc;
  if (block === "operative_dispositif") return `Operative Part dispositif clause ${p.hudocParaNo ?? "(no number)"}`;
  if (block.startsWith("separate_opinion_")) {
    const n = block.split("_")[2];
    return `${n}${{1:"st",2:"nd",3:"rd"}[n] || "th"} separate opinion, ${baseDesc.toLowerCase()}`;
  }
  return baseDesc;
}

function buildParagraphResult(para, terms) {
  return {
    key: para.key || "",
    section: para.section,
    sectionLabel: SECTION_LABELS[para.section] || para.section,
    sectionColor: SECTION_COLORS[para.section] || "#718096",
    paraIdx: para.paraIdx,
    hudocParaNo: para.hudocParaNo,
    numberingBlock: para.numberingBlock,
    rowRole: para.rowRole,
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

function matchesPrefixedQuery(caseObj, metaQuery) {
  for (const value of metaQuery.case) {
    const matchesCase = (caseObj.__caseNoNorm || "").includes(value)
      || (caseObj.__caseIdNorm || "").includes(value)
      || (caseObj.__titleNorm || "").includes(value);
    if (!matchesCase) return false;
  }

  for (const value of metaQuery.ecli) {
    if (!(caseObj.__ecliNorm || "").includes(value)) return false;
  }

  for (const value of metaQuery.hudoc) {
    const matchesHudoc = (caseObj.__hudocNorm || "").includes(value) || (caseObj.__hudocIdNorm || "").includes(value);
    if (!matchesHudoc) return false;
  }

  for (const value of metaQuery.article) {
    let found = false;
    for (const articleToken of caseObj.__articlesNorm || []) {
      if (matchesArticleToken(articleToken, value)) {
        found = true;
        break;
      }
    }
    if (!found) return false;
  }

  for (const value of metaQuery.state) {
    if (!arrayIncludesNorm(caseObj.__stateSearchValues || [], value)) return false;
  }

  for (const value of metaQuery.body) {
    if (!(caseObj.__originatingBodyNorm || "").includes(value)) return false;
  }

  for (const value of metaQuery.judge) {
    if (!arrayIncludesNorm(caseObj.__judgesNorm || [], value)) return false;
  }

  for (const value of metaQuery.keyword) {
    if (!arrayIncludesNorm(caseObj.__keywordsNorm || [], value)) return false;
  }

  return true;
}

function buildQueryResults(query, filters) {
  const advanced = parseQueryWithPrefixes(query);
  const parsed = parseQuery(advanced.textQuery);
  const allTerms = [...parsed.andTerms, ...parsed.orGroups.flat()];
  const hasTextTerms = allTerms.length > 0;

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
    if (!matchesPrefixedQuery(c, advanced.meta)) {
      continue;
    }

    if (hasTextTerms) {
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
    }

    if (!resultsById.has(c.case_id)) {
      resultsById.set(c.case_id, {
        case: c,
        paragraphs: [],
        hitCount: 0,
        score: 0,
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
    row.score += sectionSearchWeight(entry.section) * caseSearchBoost(c);

    totalHits += 1;
    if (totalHits >= MAX_HITS) {
      limited = true;
      break;
    }
  }

  const orderedCaseIds = [...resultsById.entries()]
    .sort((a, b) => {
      if (b[1].score !== a[1].score) {
        return b[1].score - a[1].score;
      }
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
  if (filters.keywords) {
    for (const kw of filters.keywords) {
      chips.push(`<span class="filter-chip" title="HUDOC keyword">${escapeHtml(kw)}</span>`);
    }
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
    const label = OUTCOME_LABELS[outcome] || outcome;
    chips.push(`<span class="filter-chip">${escapeHtml(label)}</span>`);
  }
  for (const dt of filters.docTypes) {
    const label = dt === "press_release" ? "Press Releases" : "Judgments";
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
      <span title="${escapeHtml(formatParaNumTitle(paragraph))}">${escapeHtml(formatParaNum(paragraph))}</span>
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

// Articles that the Court invokes mostly for procedural framing rather than
// to recognise a substantive right.  When a researcher is hunting for "the
// Article 8 cases" they don't want Art 34/35/37/41/44/46 cluttering the
// result card; those still matter, just in a quieter slot.
const PROCEDURAL_ARTICLE_BASES = new Set(["34", "35", "37", "39", "41", "44", "46"]);

/**
 * Parse a HUDOC article token like "8", "8-1", "8 § 1", "P1-1-2" into a
 * canonical { base, sub } pair.  base = "8" or "P1-1"; sub = "1" or "1.2"
 * (joined sub-clauses) or null.  Tolerates whitespace and the "§" sigil.
 */
function parseArticleToken(token) {
  const t = String(token || "").trim();
  if (!t) return null;
  // Protocol article: P1-1, P1-1-2, P7-4-1
  const pm = t.match(/^P(\d+)-(\d+)(?:[-\s]+(\d+(?:[-\s]+\d+)*))?$/i);
  if (pm) {
    const sub = pm[3] ? pm[3].replace(/[\s]+/g, ".").replace(/-+/g, ".") : null;
    return { base: `P${pm[1]}-${pm[2]}`, sub, isProtocol: true };
  }
  // Main convention article: "8", "8-1", "8 § 1", "8-1-a"
  const m = t.match(/^(\d+)(?:[-\s]*(?:§\s*)?(\d+(?:[-\s]*[a-z]+)?(?:\s*§?\s*\d+)?))?$/i);
  if (!m) return null;
  let sub = m[2] ? m[2].replace(/\s+/g, "").replace(/^§/, "") : null;
  if (sub) sub = sub.replace(/§/g, "-");
  return { base: m[1], sub, isProtocol: false };
}

/**
 * Group an array of raw HUDOC article tokens by base article so that
 * "8, 8-1, 8-2" collapses to a single "Art 8 §§ 1, 2" entry, and split
 * substantive articles from procedural refs (34/35/37/41/44/46…) for
 * researcher-friendly result-card display.  Returns:
 *   {
 *     substantive: [{label, base, subs}, …],
 *     procedural:  [{label, base, subs}, …],
 *   }
 */
function groupArticleTokens(articles) {
  const out = { substantive: [], procedural: [] };
  if (!articles) return out;
  // Cope with three input shapes encountered in the wild:
  //   ["8"]                                   — one token per element
  //   ["34, 8, 41"]                           — single compound element
  //   "34, 8, 41"                             — bare string
  // Each string element may carry newlines and stray "§" sigils that need
  // normalisation before splitting.  Mirrors backend _split_article_values.
  const rawList = Array.isArray(articles) ? articles : [articles];
  const list = [];
  for (const item of rawList) {
    const cleaned = String(item || "").replace(/\s+/g, " ").trim();
    if (!cleaned) continue;
    if (/[,;]/.test(cleaned)) {
      for (const part of cleaned.split(/[,;]/)) {
        const t = part.trim();
        if (t) list.push(t);
      }
    } else {
      list.push(cleaned);
    }
  }
  const groups = new Map();   // base → Set<sub>
  const order = [];           // preserve first-seen order
  for (const raw of list) {
    const parsed = parseArticleToken(raw);
    if (!parsed) continue;
    if (!groups.has(parsed.base)) {
      groups.set(parsed.base, new Set());
      order.push(parsed.base);
    }
    if (parsed.sub) groups.get(parsed.base).add(parsed.sub);
  }
  for (const base of order) {
    const subs = [...groups.get(base)].sort((a, b) => {
      // numeric-aware sort: "1" < "2" < "10" < "1-a"
      const an = parseInt(a, 10), bn = parseInt(b, 10);
      if (!Number.isNaN(an) && !Number.isNaN(bn) && an !== bn) return an - bn;
      return String(a).localeCompare(String(b));
    });
    const label = subs.length ? `Art ${base} §§ ${subs.join(", ")}` : `Art ${base}`;
    const entry = { label, base, subs };
    if (PROCEDURAL_ARTICLE_BASES.has(base)) out.procedural.push(entry);
    else out.substantive.push(entry);
  }
  return out;
}

function buildArticleChips(articles, maxVisible = 4) {
  const grouped = groupArticleTokens(articles);
  if (!grouped.substantive.length && !grouped.procedural.length) {
    return '<span class="legal-chip muted">No articles listed</span>';
  }

  const chips = [];
  const visibleSubst = grouped.substantive.slice(0, maxVisible);
  for (const g of visibleSubst) {
    const guideUrl = ARTICLE_GUIDE_URLS[g.base.replace(/^P\d+-/, "")];
    if (guideUrl) {
      chips.push(`<a href="${escapeHtml(guideUrl)}" class="legal-chip article article-link" target="_blank" rel="noopener noreferrer" title="View ECHR Guide on Article ${escapeHtml(g.base)}">${escapeHtml(g.label)}</a>`);
    } else {
      chips.push(`<span class="legal-chip article">${escapeHtml(g.label)}</span>`);
    }
  }
  const hiddenSubst = grouped.substantive.length - visibleSubst.length;
  if (hiddenSubst > 0) {
    chips.push(`<span class="legal-chip muted">+${fmtInt.format(hiddenSubst)} more substantive</span>`);
  }
  if (grouped.procedural.length) {
    const procTitle = grouped.procedural.map((p) => p.label).join(", ");
    chips.push(`<span class="legal-chip muted procedural-pill" title="Procedural references: ${escapeHtml(procTitle)}">+${fmtInt.format(grouped.procedural.length)} procedural</span>`);
  }
  return chips.join("");
}

function buildLegalStatusChips(caseObj) {
  const chips = [];
  if (caseObj.__hasInadmissibility) {
    chips.push('<span class="legal-chip status">Inadmissibility</span>');
  }
  if (caseObj.__isStruckOut) {
    chips.push('<span class="legal-chip status">Struck out</span>');
  }
  if (caseObj.__hasProceduralAspect) {
    chips.push('<span class="legal-chip status">Procedural aspect</span>');
  }
  if (caseObj.__hasSubstantiveAspect) {
    chips.push('<span class="legal-chip status">Substantive aspect</span>');
  }

  if (!chips.length) {
    chips.push('<span class="legal-chip muted">No procedural flags</span>');
  }
  return chips.join("");
}

function formatCaseDateForDisplay(c) {
  const raw = c?.judgment_date || "";
  if (!raw) return "-";
  const parts = raw.split("/");
  if (parts.length === 3) {
    const iso = `${parts[2]}-${parts[1]}-${parts[0]}`;
    const d = new Date(iso);
    if (!Number.isNaN(d.getTime())) {
      return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
    }
  }
  const d = new Date(raw);
  if (!Number.isNaN(d.getTime())) {
    return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
  }
  return raw;
}

function cleanCaseTitle(title) {
  return String(title || "Untitled case").replace(/^CASE OF\s+/i, "");
}

function buildResearcherArticleChips(articles, maxVisible = 4) {
  const grouped = groupArticleTokens(articles);
  if (!grouped.substantive.length && !grouped.procedural.length) {
    return '<span class="chip muted">No articles listed</span>';
  }
  const chips = [];
  const visibleSubst = grouped.substantive.slice(0, maxVisible);
  for (const g of visibleSubst) {
    chips.push(`<span class="chip">${escapeHtml(g.label)}</span>`);
  }
  const hiddenSubst = grouped.substantive.length - visibleSubst.length;
  if (hiddenSubst > 0) {
    chips.push(`<span class="chip muted">+${fmtInt.format(hiddenSubst)} more</span>`);
  }
  if (grouped.procedural.length) {
    const procTitle = grouped.procedural.map((p) => p.label).join(", ");
    chips.push(`<span class="chip muted procedural-pill" title="Procedural references: ${escapeHtml(procTitle)}">+${fmtInt.format(grouped.procedural.length)} procedural</span>`);
  }
  return chips.join("");
}

function buildResearcherBars(c, row) {
  const cited = Number(c.__citedByCount || 0);
  // Prefer the P29 server-computed count (covers every case, incl.
  // recent committee judgments absent from the JSONL feed); fall back
  // to the JSONL-sourced strasbourg_caselaw length only when the
  // server didn't ship a count.  Mirrors the cites legal-chip below.
  const cites = Number(
    c.__citesCountServer != null
      ? c.__citesCountServer
      : (c.__citationRefs || []).length || 0
  );
  const hits = Number(row.hitCount || row.paragraphs?.length || 0);
  const max = Math.max(cited, cites, hits, 1);
  // `dimZero`: the citation graph (P29) has partial coverage, so a 0 is
  // ambiguous — "truly uncited" vs "not in our data". For landmark cases
  // a bare "0" is misleading and corrodes trust, so render it as "—".
  const bar = (label, value, accent = false, dimZero = false) => {
    const na = dimZero && !value;
    const width = Math.max(4, Math.round((value / max) * 100));
    return `
      <div class="researcher-bar${na ? " researcher-bar-na" : ""}"${na ? ' title="Citation-graph coverage is partial — no citation data recorded for this case"' : ""}>
        <div class="researcher-bar-head">
          <span>${escapeHtml(label)}</span>
          <strong>${na ? "—" : fmtInt.format(value)}</strong>
        </div>
        <div class="researcher-bar-track"><div class="researcher-bar-fill${accent ? " accent" : ""}" style="width:${width}%"></div></div>
      </div>
    `;
  };
  return `${bar("hits", hits, true)}${bar("cites", cites, false, true)}${bar("cited by", cited, false, true)}`;
}

const CASENOTE_STEP = 5; // paragraphs revealed per ↑/↓ expansion click

/* A ±before/±after window of LOGICAL paragraphs around the matched
 * paragraph, clamped to the section.  Consecutive physical rows that
 * share a logical paragraph (a numbered ¶ plus its indented quote /
 * continuation rows) are grouped into one unit — so the Case Note
 * renders one "¶ N" block, mirroring HUDOC, instead of repeating the
 * number for every fragment.  before/after and moreBefore/moreAfter
 * count logical paragraphs. */
function getCaseNoteContext(paras, activeIdx, before, after) {
  const secKey = paras[activeIdx].section || "";
  let start = activeIdx, end = activeIdx;
  while (start > 0 && (paras[start - 1].section || "") === secKey) start--;
  while (end < paras.length - 1 && (paras[end + 1].section || "") === secKey) end++;

  const logKey = (p) => (p.logicalParaIdx != null) ? p.logicalParaIdx : p.paraIdx;
  const groups = [];
  for (let i = start; i <= end; i++) {
    const k = logKey(paras[i]);
    const last = groups[groups.length - 1];
    if (last && last.key === k) last.rows.push(paras[i]);
    else groups.push({ key: k, rows: [paras[i]] });
  }
  let activeGi = groups.findIndex((g) => g.rows.includes(paras[activeIdx]));
  if (activeGi < 0) activeGi = 0;
  const fromGi = Math.max(0, activeGi - before);
  const toGi = Math.min(groups.length - 1, activeGi + after);
  return {
    prev: groups.slice(fromGi, activeGi),
    active: groups[activeGi],
    next: groups.slice(activeGi + 1, toGi + 1),
    moreBefore: fromGi,
    moreAfter: (groups.length - 1) - toGi,
    totalInSection: groups.length,
  };
}

/* Context block for the Case Note: the matched paragraph plus its
 * neighbours within the section, a section breadcrumb, and incremental
 * ↑/↓ expanders.  Reuses the .dossier-ctx-* paragraph CSS. */
function caseNoteContextHtml(ctx, paras, activeIdx) {
  const terms = state.currentTerms || [];
  const activeSec = ctx.active.rows[0] || {};

  // #2 — breadcrumb from the judgment's own heading rows, verbatim from
  // HUDOC ("THE LAW › II. ALLEGED VIOLATION OF ARTICLE 8 …").  Walk back
  // collecting the ancestor chain by heading level; fall back to the
  // section-bucket label only if the document carries no headings.
  const hlevel = (role) => {
    const m = /^heading_h(\d)/.exec(role || "");
    if (m) return Number(m[1]);
    return ((role || "") === "heading") ? 5 : null;
  };
  const segs = [];
  let minLvl = Infinity;
  for (let i = activeIdx; i >= 0; i--) {
    const L = hlevel(paras[i].rowRole);
    if (L == null || L >= minLvl) continue;
    minLvl = L;
    const t = (paras[i].text || "").trim();
    if (t && t.length <= 140) segs.unshift(t);
  }
  const bcParts = segs.length ? segs : [activeSec.sectionLabel || "—"];
  const breadcrumb = bcParts.map(escapeHtml).join('<span class="dossier-bc-sep">›</span>');

  // #5 — the matched row's role, to flag a match inside quoted material.
  const matchedInQuote = !!(paras[activeIdx]
    && (paras[activeIdx].rowRole || "") === "quote");

  // One logical paragraph → one "¶ N" block: the numbered body text,
  // plus any quote / continuation rows rendered as indented sub-blocks
  // (HUDOC shows ¶ N once, with the quotation indented inside it).
  const renderGroup = (g, isActive) => {
    const head = g.rows.find((r) => !((r.rowRole || "").startsWith("quote")))
               || g.rows[0];
    const inner = g.rows.map((r) => {
      const isQuote = (r.rowRole || "") === "quote";
      const html = dossierHighlight(r.text, terms);
      return isQuote
        ? `<div class="dossier-ctx-quote">${html}</div>`
        : `<div class="dossier-ctx-body">${html}</div>`;
    }).join("");
    const quoteBadge = (isActive && matchedInQuote)
      ? `<span class="match-source-badge match-source-quote" title="The query matched inside quoted material — a Convention article, domestic law or other source — not the Court's own reasoning">in quote</span>`
      : "";
    return `
      <div class="dossier-ctx-para${isActive ? " dossier-ctx-active" : ""}">
        <span class="dossier-ctx-num">${escapeHtml(dossierParaNumLabel(head))}</span>${quoteBadge}${inner}
      </div>`;
  };
  const moreBtn = (dir, count) => {
    const step = Math.min(CASENOTE_STEP, count);
    const arrow = dir === "before" ? "↑" : "↓";
    const word = dir === "before" ? "earlier" : "later";
    const tail = count > step ? ` · ${count} more in section` : "";
    return `<button type="button" class="dossier-expand casenote-more" data-action="casenote-more-${dir}">${arrow} show ${step} ${word}${tail}</button>`;
  };
  return `
    <div class="case-note-context">
      <div class="dossier-breadcrumb">${breadcrumb}</div>
      ${ctx.moreBefore > 0 ? moreBtn("before", ctx.moreBefore) : ""}
      ${ctx.prev.map((g) => renderGroup(g, false)).join("")}
      ${renderGroup(ctx.active, true)}
      ${ctx.next.map((g) => renderGroup(g, false)).join("")}
      ${ctx.moreAfter > 0 ? moreBtn("after", ctx.moreAfter) : ""}
    </div>`;
}

const CN_ZOOM_STEPS = [0.8, 0.9, 1, 1.15, 1.3, 1.5];

/* Step the Case Note drawer text size ("A−" / "A+").  Applied as a CSS
 * `zoom` on .cn-zoom-wrap (width pre-divided so the box still fills the
 * rail exactly); the chosen level is persisted to localStorage. */
function setCaseNoteZoom(direction) {
  let idx = CN_ZOOM_STEPS.indexOf(state.cnZoom || 1);
  if (idx === -1) idx = 2;
  idx = Math.max(0, Math.min(CN_ZOOM_STEPS.length - 1, idx + direction));
  state.cnZoom = CN_ZOOM_STEPS[idx];
  try { localStorage.setItem("cnZoom", String(state.cnZoom)); } catch (e) {}
  document.querySelectorAll(".cn-zoom-wrap").forEach((w) => {
    w.style.zoom = String(state.cnZoom);
    w.style.width = (100 / state.cnZoom).toFixed(2) + "%";
  });
}

function renderCaseContextRail(caseId = state.activeCaseId, opts = {}) {
  if (!el.caseContextRail && !el.caseContextRailMobile) return;
  const renderToRails = (html) => {
    // Wrap in a zoom layer so the "A− / A+" controls can scale the whole
    // Case Note.  width is pre-divided by the zoom factor so the zoomed
    // box still fills the rail exactly (no horizontal overflow).
    const z = state.cnZoom || 1;
    const wrapped = `<div class="cn-zoom-wrap" style="zoom:${z};width:${(100 / z).toFixed(2)}%">${html}</div>`;
    if (el.caseContextRail) el.caseContextRail.innerHTML = wrapped;
    if (el.caseContextRailMobile) el.caseContextRailMobile.innerHTML = wrapped;
  };
  const row = caseId ? state.currentResultsById.get(caseId) : null;
  if (!row) {
    document.body.classList.remove("casenote-open");
    renderToRails(`
      <div class="folio-label garnet">Case details</div>
      <h3>Awaiting results</h3>
      <p class="case-context-empty">Run a search or select a result to see judgment context here.</p>
    `);
    return;
  }

  const c = row.case;
  const primaryPara = row.paragraphs[0] || null;
  const title = cleanCaseTitle(c.title);
  const states = (c.__states || []).map((d) => COUNTRY_NAMES[d] || d).filter(Boolean).join(", ") || "-";
  const outcomeLabel = OUTCOME_LABELS[c.__outcomePrimary] || c.__outcomePrimary || "-";
  const outcomeToneClass = getOutcomeToneClass(c.__outcomePrimary);
  const chamberLabel = getChamberLabel(c.__chamberCategory);
  // Outgoing cites for the Case Note meta row — prefer the P29
  // server-computed count (covers every case); fall back to the
  // JSONL-sourced strasbourg_caselaw length only when absent.
  const citations = (c.__citesCountServer != null)
    ? c.__citesCountServer
    : (c.__citationRefs || []).length;

  // Compact, grouped fact header — one block (articles · facts grid ·
  // outcome) instead of the old loose 6-cell grid + scattered chip row.
  const caseRef = c.ecli || splitAppNos(c.case_no).join(", ") || "";
  const caseRefHtml = !caseRef
    ? ""
    : (c.hudoc_url
      ? `<a class="case-context-ecli case-context-ecli-link" href="${escapeHtml(c.hudoc_url)}" target="_blank" rel="noopener noreferrer" title="Open this judgment on HUDOC">${escapeHtml(caseRef)}<span class="ext-icon" aria-hidden="true">↗</span></a>`
      : `<div class="case-context-ecli">${escapeHtml(caseRef)}</div>`);
  const headHtml = `
    <div class="cn-head-row">
      <div class="folio-label garnet">Case details</div>
      <div class="cn-zoom" role="group" aria-label="Case Note text size">
        <button type="button" class="cn-zoom-btn" data-action="cn-zoom-out" title="Smaller text" aria-label="Decrease Case Note text size">A&minus;</button>
        <button type="button" class="cn-zoom-btn" data-action="cn-zoom-in" title="Larger text" aria-label="Increase Case Note text size">A+</button>
        <button type="button" class="cn-zoom-btn cn-close-btn" data-action="close-casenote" title="Close case details (Esc)" aria-label="Close case details">&times;</button>
      </div>
    </div>
    <h3>${escapeHtml(title)}</h3>
    ${caseRefHtml}

    <div class="case-note-meta">
      <div class="cnm-articles">
        <span class="cnm-label">Articles</span>
        <span class="cnm-article-chips">${buildResearcherArticleChips(c.__articles, 8)}</span>
      </div>
      <dl class="cnm-facts">
        <div><dt>Application</dt><dd>${escapeHtml(splitAppNos(c.case_no).join(", ") || "—")}</dd></div>
        <div><dt>Decided</dt><dd>${escapeHtml(formatCaseDateForDisplay(c))}</dd></div>
        <div><dt>Court</dt><dd>${escapeHtml(formatBodyLabel(c.__originatingBody) || chamberLabel || "—")}</dd></div>
        <div><dt>State</dt><dd>${escapeHtml(states)}</dd></div>
        <div><dt>Importance</dt><dd${importanceShortLabel(c.__importance) ? ` title="${escapeHtml(importanceTooltip(c.__importance))}"` : ""}>${escapeHtml(IMPORTANCE_LABELS[c.__importance] || importanceShortLabel(c.__importance) || "—")}</dd></div>
        <div><dt>Citations</dt><dd${citations > 0 ? "" : ` title="${c.__importance === "3" ? "No citations recorded. HUDOC does not analyse cited case-law for importance-3 judgments (HUDOC FAQ §12); our text-extracted graph also found none here" : "Citation-graph coverage is partial — no citation data recorded for this case"}"`}>${citations > 0 ? fmtInt.format(citations) : "—"}</dd></div>
      </dl>
      <div class="cnm-outcome">
        <span class="cnm-outcome-badge ${escapeHtml(outcomeToneClass)}">${escapeHtml(outcomeLabel)}</span>
        ${c.document_type ? `<span class="cnm-doctype">${escapeHtml(c.document_type)}</span>` : ""}
      </div>
    </div>`;

  // Action bar: HUDOC ↗ · Cite · Copy.  `activePara` is the matched
  // paragraph once context loads; Copy is omitted while it is absent.
  // `activeGroup` is the active logical-paragraph group (or null while
  // loading): HUDOC link anchors on the numbered body row, Copy copies
  // the whole logical ¶ (body + quote rows).
  const actionsHtml = (activeGroup) => {
    const head = activeGroup
      ? (activeGroup.rows.find((r) => !((r.rowRole || "").startsWith("quote")))
         || activeGroup.rows[0])
      : null;
    const hudocUrl = head ? paragraphHudocUrl(c, head) : (c.hudoc_url || "");
    const copyText = activeGroup
      ? activeGroup.rows.map((r) => r.text || "").join("\n") : "";
    return `
      <div class="case-context-actions">
        ${hudocUrl ? `<a href="${escapeHtml(hudocUrl)}" class="cn-action" target="_blank" rel="noopener noreferrer">HUDOC ↗</a>` : ""}
        <button type="button" class="cn-action" data-action="copy-citation" data-case-id="${escapeHtml(caseId)}">Cite</button>
        ${activeGroup ? `<button type="button" class="cn-action" data-action="copy-paragraph" data-text="${escapeHtml(copyText)}">Copy</button>` : ""}
      </div>`;
  };

  if (!primaryPara) {
    const note = state.currentMode === "browse"
      ? "This browse result is a case record. Run a full-text query to see matched paragraphs in this note."
      : "No paragraph preview is available for this result.";
    renderToRails(headHtml + `<p class="case-context-empty">${escapeHtml(note)}</p>` + actionsHtml(null));
    return;
  }

  // Initial paint with a placeholder; the context window needs the full
  // judgment so we fetch it and re-render when it arrives.
  renderToRails(headHtml
    + `<div class="case-note-context"><p class="case-context-empty">Loading paragraph context…</p></div>`
    + actionsHtml(null));

  (async () => {
    try {
      const paras = await loadDossierCase(caseId);
      if (state.activeCaseId !== caseId) return; // selection moved on
      const cn = (state.caseNote && state.caseNote.caseId === caseId)
        ? state.caseNote : { caseId, before: 1, after: 1, paraIdx: null };
      // Anchor: an explicitly-clicked hit row (cn.paraIdx) wins;
      // otherwise the row that actually matched the query — so the
      // centred paragraph carries the keyword and matches the card.
      const wantIdx = (cn.paraIdx != null) ? cn.paraIdx
        : (primaryPara.paraIdx != null) ? primaryPara.paraIdx
        : primaryPara.logicalParaIdx;
      let activeIdx = (wantIdx != null)
        ? paras.findIndex((p) => p.paraIdx === wantIdx) : -1;
      if (activeIdx < 0) activeIdx = paras.findIndex((p) => p.hudocParaNo != null);
      if (activeIdx < 0) activeIdx = 0;
      const ctx = getCaseNoteContext(paras, activeIdx, cn.before, cn.after);
      renderToRails(headHtml
        + caseNoteContextHtml(ctx, paras, activeIdx)
        + actionsHtml(ctx.active));
      if (opts.center) {
        // Centre the active paragraph WITHIN the sidebar scroll only —
        // scrollIntoView would also nudge the main column / window.
        requestAnimationFrame(() => {
          const sb = el.sidebar;
          const active = el.caseContextRail?.querySelector(".dossier-ctx-active");
          if (sb && active) {
            const d = (active.getBoundingClientRect().top - sb.getBoundingClientRect().top)
              - (sb.clientHeight / 2 - active.offsetHeight / 2);
            sb.scrollTop += d;
          }
        });
      }
    } catch (err) {
      console.error("[Case Note] context load failed:", err);
      if (state.activeCaseId === caseId) {
        renderToRails(headHtml
          + `<p class="case-context-empty">Paragraph context unavailable.</p>`
          + actionsHtml(null));
      }
    }
  })();
}

function selectCase(caseId) {
  if (!caseId || !state.currentResultsById.has(caseId)) return;
  state.activeCaseId = caseId;
  document.body.classList.add("casenote-open");
  // Fresh Case Note for a newly-selected case: ±1, anchored on the
  // case's best hit (paraIdx null → renderCaseContextRail picks it).
  if (!state.caseNote || state.caseNote.caseId !== caseId) {
    state.caseNote = { caseId, before: 1, after: 1, paraIdx: null };
  }
  el.casesList?.querySelectorAll(".researcher-result.active").forEach((node) => {
    node.classList.remove("active");
  });
  const selected = byId(`case-${caseId}`);
  if (selected) selected.classList.add("active");
  renderCaseContextRail(caseId, { center: true });
}

/* Show a SPECIFIC paragraph (a clicked hit row) in the Case Note,
 * rather than the case's best hit. */
function selectCaseParagraph(caseId, paraIdx) {
  if (!caseId || !state.currentResultsById.has(caseId)) return;
  state.activeCaseId = caseId;
  document.body.classList.add("casenote-open");
  state.caseNote = {
    caseId,
    before: 1,
    after: 1,
    paraIdx: (paraIdx != null && paraIdx !== "") ? Number(paraIdx) : null,
  };
  el.casesList?.querySelectorAll(".researcher-result.active").forEach((node) => {
    node.classList.remove("active");
  });
  const selected = byId(`case-${caseId}`);
  if (selected) selected.classList.add("active");
  renderCaseContextRail(caseId, { center: true });
}

function buildCaseCard(caseId, row, rank = 1) {
  const c = row.case;
  const stateNames = (c.__states || []).map((d) => COUNTRY_NAMES[d] || d).filter(Boolean);
  const respondentSummary = stateNames.length > 1
    ? `${stateNames[0]} +${stateNames.length - 1}`
    : (stateNames[0] || "-");
  const outcomeLabel = OUTCOME_LABELS[c.__outcomePrimary] || c.__outcomePrimary || "-";
  const outcomeToneClass = getOutcomeToneClass(c.__outcomePrimary);
  const chamberLabel = getChamberLabel(c.__chamberCategory);
  const keyCaseChip = String(c.__importance || "").toLowerCase() === "key cases"
    ? '<span class="legal-chip keycase">Key case</span>'
    : "";
  const primaryPara = row.paragraphs[0] || null;
  const caseOnlyBrowse = !primaryPara && state.currentMode === "browse";
  const activeClass = state.activeCaseId === caseId ? " active" : "";
  const paraNo = primaryPara ? formatParaNum(primaryPara) : "CASE";
  const paraTitle = primaryPara ? formatParaNumTitle(primaryPara) : "Case record";
  const dateLabel = formatCaseDateForDisplay(c);
  const title = cleanCaseTitle(c.title);
  // P58: when the top hit is a fragment (bullet / quote / continuation),
  // prepend a muted lead-in from its parent body ¶ so the snippet on the
  // collapsed card reads in context instead of starting mid-list.
  // #6: when the match itself is quoted material, drop it onto its own
  // indented line so the Court's narration and the quotation read as
  // two distinct things, not one run-on sentence (mirrors HUDOC).
  const primaryContextLead = (primaryPara && primaryPara.parentText)
    ? `<span class="para-context-lead-inline">${escapeHtml(truncateForContext(primaryPara.parentText))}</span>`
    : "";
  const primaryBody = !primaryPara ? ""
    : ((primaryPara.rowRole || "") === "quote"
        ? `<span class="pr-snippet-quote">${primaryPara.textHtml}</span>`
        : (primaryContextLead ? " " : "") + primaryPara.textHtml);
  const primaryText = primaryPara
    ? primaryContextLead + primaryBody
    : (caseOnlyBrowse
      ? '<span class="case-only-note">Case record only in recent-cases browse mode. Enter a full-text query to surface matched paragraphs from this judgment.</span>'
      : "No paragraphs for current filters.");
  const displayHitCount = caseOnlyBrowse ? 1 : row.hitCount;

  // v1.1 bullet grouping: consecutive quote-role hits in the same
  // section (CATT-class Convention 108 enumerations) collapse into a
  // single visual block headed by "{Section} · in quote · N matches".
  // Researchers see one "logical quote block" instead of 5 disjoint
  // bullet hits.  Heuristic: same case + same section + same row
  // role (quote/operative_list) + para_idx gap ≤ BULLET_GAP_MAX.
  const BULLET_GAP_MAX = 5;
  const groups = [];
  for (const p of row.paragraphs) {
    const role = p.rowRole || "paragraph";
    const isGroupable = role === "quote" || role === "operative_list";
    const last = groups[groups.length - 1];
    if (
      isGroupable && last && last.type === "group"
      && last.role === role && last.section === p.section
      && p.paraIdx != null && last.lastParaIdx != null
      && (p.paraIdx - last.lastParaIdx) <= BULLET_GAP_MAX
    ) {
      last.paras.push(p);
      last.lastParaIdx = p.paraIdx;
    } else if (isGroupable) {
      groups.push({
        type: "group",
        role,
        section: p.section,
        sectionLabel: p.sectionLabel,
        paras: [p],
        firstParaIdx: p.paraIdx,
        lastParaIdx: p.paraIdx,
      });
    } else {
      groups.push({ type: "single", para: p });
    }
  }
  // Drop the group wrapper for trivially-single bullet groups
  // (1-row "groups" render the same as a single hit, no need for
  // the group header chrome).
  const finalGroups = groups.map((g) => (
    g.type === "group" && g.paras.length === 1
      ? { type: "single", para: g.paras[0] }
      : g
  ));

  const renderParaItem = (p, isGrouped = false) => {
    const hudocUrl = paragraphHudocUrl(c, p);
    const paraLabel = formatParaNum(p);
    const hudocLink = hudocUrl
      ? `<a class="hudoc-para-link" data-action="open-hudoc" href="${escapeHtml(hudocUrl)}" target="_blank" rel="noopener noreferrer" title="Open in HUDOC (use Ctrl-F for ${escapeHtml(paraLabel)})">HUDOC ↗</a>`
      : "";
    // Whole row → show this paragraph in the Case Note. Nested
    // buttons/links carry their own data-action so the delegated
    // handler resolves them first.
    const cnIdx = (p.paraIdx != null) ? p.paraIdx : "";
    return `
      <div class="paragraph-item${isGrouped ? " grouped-item" : ""}"
           data-action="select-para" data-case-id="${escapeHtml(caseId)}"
           data-para-idx="${escapeHtml(String(cnIdx))}"
           title="Show this paragraph in the Case Note">
        <div class="para-header">
          ${isGrouped ? "" : `<span class="para-section">${escapeHtml(p.sectionLabel)}</span>`}
          <span class="para-num" title="${escapeHtml(formatParaNumTitle(p))}">${escapeHtml(paraLabel)}</span>
          ${isGrouped ? "" : buildMatchSourceBadgesHtml(p.matchedRoles)}
          ${buildParagraphLabelBadgesHtml(p.key)}
          <span class="para-actions">
            ${hudocLink}
            <button class="cite-para-btn" data-action="copy-paragraph-citation" data-case-id="${escapeHtml(caseId)}" data-para-key="${escapeHtml(p.key || "")}" title="Copy paragraph citation">Cite ¶</button>
            <button class="copy-btn" data-action="copy-paragraph" data-text="${escapeHtml(p.rawText)}" title="Copy paragraph text">Copy</button>
          </span>
        </div>
        ${p.parentText
          ? `<p class="para-context-lead" title="Opening of ${escapeHtml(formatParaNum(p))} — the paragraph this excerpt belongs to">${escapeHtml(truncateForContext(p.parentText))}</p>`
          : ""}
        <p class="para-text">${p.textHtml}</p>
      </div>
    `;
  };

  const paraBlocks = finalGroups
    .map((g) => {
      if (g.type === "single") {
        return renderParaItem(g.para);
      }
      // group with N≥2 paragraphs — render a quote block container
      const roleBadge = g.role === "quote"
        ? '<span class="match-source-badge match-source-quote">in quote</span>'
        : '<span class="match-source-badge match-source-operative">operative</span>';
      const countLabel = `${g.paras.length} match${g.paras.length === 1 ? "" : "es"} in same quote block`;
      const inner = g.paras.map((p) => renderParaItem(p, /*isGrouped*/ true)).join("");
      return `
        <div class="paragraph-group">
          <div class="paragraph-group-header">
            <span class="para-section">${escapeHtml(g.sectionLabel)}</span>
            ${roleBadge}
            <span class="paragraph-group-count">${escapeHtml(countLabel)}</span>
          </div>
          <div class="paragraph-group-body">${inner}</div>
        </div>
      `;
    })
    .join("");

  const hitLabel = caseOnlyBrowse
    ? "case"
    : state.currentMode === "browse"
    ? (row.hitCount === 1 ? "para" : "paras")
    : (row.hitCount === 1 ? "hit" : "hits");

  return `
    <article class="researcher-result${activeClass}" id="case-${escapeHtml(caseId)}" data-action="select-case" data-case-id="${escapeHtml(caseId)}" tabindex="0">
      <div class="researcher-marginalia">
        <div class="researcher-rank">№ ${String(rank).padStart(2, "0")}</div>
        <div class="researcher-para-no" title="${escapeHtml(paraTitle)}">${escapeHtml(paraNo)}</div>
        ${keyCaseChip ? '<div class="researcher-key">KEY</div>' : ""}
      </div>

      <div class="researcher-result-body">
        <div class="researcher-title-line">
          <h2 class="case-title">${escapeHtml(title)}</h2>
          <span class="researcher-title-rule"></span>
          <span class="researcher-date">${escapeHtml(dateLabel)}</span>
        </div>

        <p class="para-text researcher-primary-text">${primaryText}</p>

        <div class="researcher-chip-row">
          ${buildResearcherArticleChips(c.__articles)}
          <span class="chip">${escapeHtml(formatBodyLabel(c.__originatingBody) || chamberLabel || "-")}</span>
          <span class="chip outcome ${escapeHtml(outcomeToneClass)}">${escapeHtml(outcomeLabel)}</span>
          <span class="chip">${escapeHtml(respondentSummary)}</span>
        </div>

        <div class="case-actions-inline compact-actions">
          ${c.hudoc_url ? `<a href="${escapeHtml(c.hudoc_url)}" class="case-open-link primary" target="_blank" rel="noopener noreferrer">Open in HUDOC ↗</a>` : ""}
          <button type="button" class="case-open-secondary cite-btn" data-action="copy-citation" data-case-id="${escapeHtml(caseId)}" title="Copy citation to clipboard">Cite</button>
          <button type="button" class="case-open-secondary info-btn" data-action="copy-info-card" data-case-id="${escapeHtml(caseId)}" title="Copy key info block to clipboard">Copy info</button>
          <button
            type="button"
            class="case-open-secondary expand-paras-btn"
            data-action="toggle-case"
            data-case-id="${escapeHtml(caseId)}"
            aria-expanded="false"
            aria-label="Show or hide matched paragraphs">
            <span class="hit-count">${fmtInt.format(displayHitCount)}</span>
            <span class="hit-label">${hitLabel}</span>
            <span class="toggle-icon" id="icon-${escapeHtml(caseId)}">▶</span>
          </button>
        </div>
      </div>

      <aside class="researcher-influence">
        <div class="folio-label">Influence</div>
        ${buildResearcherBars(c, row)}
        <div class="researcher-ecli">${escapeHtml(c.ecli || splitAppNos(c.case_no).join(", ") || "")}</div>
      </aside>

      <div class="case-body" id="body-${escapeHtml(caseId)}">
        ${paraBlocks || `<div class="paragraph-item"><p class="para-text">${caseOnlyBrowse ? "Run a full-text query to load matched paragraphs for this case." : "No paragraphs for current filters."}</p></div>`}
      </div>
    </article>
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
  const totalCases = state.serverMode
    ? (state.serverTotalCases || state.currentOrderedCaseIds.length)
    : state.currentOrderedCaseIds.length;
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
  el.casesList.classList.toggle("card-mode-detailed", state.cardMode === "detailed");
  el.casesList.classList.toggle("card-mode-compact", state.cardMode !== "detailed");

  if (totalCases === 0) {
    el.casesList.innerHTML = "";
    el.noResults.hidden = false;
    el.pagination.hidden = true;
    el.exportBtn.disabled = true;
    state.activeCaseId = "";
    renderCaseContextRail("");
    return;
  }

  el.noResults.hidden = true;

  // Flat "by paragraph" mode — every hit is an independent result row.
  if (state.resultGroup === "paragraph" && state.currentMode === "search") {
    renderFlatResults();
    return;
  }

  // In server mode, each API call returns only the current page's cases,
  // so totalPages must come from the server's total count, not the local array.
  const effectiveTotal = state.serverMode
    ? (state.serverTotalCases || totalCases)
    : totalCases;
  const totalPages = Math.ceil(effectiveTotal / PAGE_SIZE);
  if (state.currentPage > totalPages) {
    state.currentPage = totalPages;
  }

  // In server mode, the API already returned the correct page — show all results.
  // In local mode, slice the full array to the current page window.
  const pageCaseIds = state.serverMode
    ? state.currentOrderedCaseIds
    : state.currentOrderedCaseIds.slice(
        (state.currentPage - 1) * PAGE_SIZE,
        Math.min(state.currentPage * PAGE_SIZE, totalCases)
      );

  if (!pageCaseIds.includes(state.activeCaseId)) {
    state.activeCaseId = pageCaseIds[0] || "";
  }

  el.casesList.innerHTML = pageCaseIds
    .map((caseId, idx) => buildCaseCard(caseId, state.currentResultsById.get(caseId), idx + 1))
    .join("");

  renderCaseContextRail(state.activeCaseId);
  renderPagination();
}

/* One result row in flat "by paragraph" mode: the matched paragraph,
 * its case title + section + date, ranked independently. Clicking it
 * opens that paragraph in the Case Note. */
function buildParagraphResult(h, rank) {
  const c = h.case;
  const title = cleanCaseTitle(c.title);
  const date = formatCaseDateForDisplay(c);
  const num = (h.displayParaNo != null) ? `¶ ${h.displayParaNo}`
            : (h.hudocParaNo != null) ? `¶ ${h.hudocParaNo}` : "¶ —";
  // #6 parity for by-paragraph results: when the hit is a fragment
  // (quote / bullet) show its parent body ¶ as a muted lead-in, then
  // the quoted text on its own indented line — mirrors buildCaseCard.
  const ctxLead = h.parentText
    ? `<span class="para-context-lead-inline">${escapeHtml(truncateForContext(h.parentText))}</span>`
    : "";
  const prBody = (h.rowRole || "") === "quote"
    ? `<span class="pr-snippet-quote">${h.textHtml}</span>`
    : (ctxLead ? " " : "") + h.textHtml;
  return `
    <article class="paragraph-result" data-action="select-para"
             data-case-id="${escapeHtml(c.case_id)}"
             data-para-idx="${escapeHtml(String(h.paraIdx != null ? h.paraIdx : ""))}"
             tabindex="0" title="Show this paragraph in the Case Note">
      <div class="researcher-marginalia">
        <div class="researcher-rank">№ ${String(rank).padStart(2, "0")}</div>
        <div class="researcher-para-no">${escapeHtml(num)}</div>
      </div>
      <div class="paragraph-result-body">
        <div class="pr-head">
          <span class="pr-case">${escapeHtml(title)}</span>
          <span class="pr-meta">${escapeHtml(h.sectionLabel)} · ${escapeHtml(date)}</span>
          ${(h.rowRole || "") === "quote" ? `<span class="match-source-badge match-source-quote" title="The query matched inside quoted material — a Convention article, domestic law or other source — not the Court's own reasoning">in quote</span>` : ""}
        </div>
        <p class="para-text">${ctxLead}${prBody}</p>
        <div class="case-actions-inline compact-actions">
          ${c.hudoc_url ? `<a href="${escapeHtml(c.hudoc_url)}" class="cn-action" data-action="open-hudoc" target="_blank" rel="noopener noreferrer">HUDOC ↗</a>` : ""}
          <button type="button" class="cn-action" data-action="copy-paragraph" data-text="${escapeHtml(h.rawText)}">Copy</button>
        </div>
      </div>
    </article>`;
}

function renderFlatResults() {
  const hits = state.flatHits || [];
  el.casesList.innerHTML = hits.map((h, i) => buildParagraphResult(h, i + 1)).join("");
  if (!hits.some((h) => h.caseId === state.activeCaseId)) {
    state.activeCaseId = hits[0] ? hits[0].caseId : "";
  }
  renderCaseContextRail(state.activeCaseId);
  renderPagination();
}

/* Sync the Sort / Group segmented controls with state, and disable the
 * options that need a query (Relevance, By paragraph). */
function syncResultControls() {
  const hasQuery = !!(state.query && state.query.trim());
  document.querySelectorAll("#resultSortControls .rdc-opt").forEach((b) => {
    const on = b.dataset.sort === state.resultSort;
    b.classList.toggle("is-active", on);
    b.setAttribute("aria-pressed", on ? "true" : "false");
    b.disabled = (b.dataset.sort === "relevance" && !hasQuery);
  });
  document.querySelectorAll("#resultGroupControls .rdc-opt").forEach((b) => {
    const on = b.dataset.group === state.resultGroup;
    b.classList.toggle("is-active", on);
    b.setAttribute("aria-pressed", on ? "true" : "false");
    b.disabled = (b.dataset.group === "paragraph" && !hasQuery);
  });
}

function computeAnalytics() {
  const countryCounts = new Map();
  const articleCounts = new Map();
  const sectionCounts = new Map();
  const bodyCounts = new Map();
  const importanceCounts = new Map();
  const outcomeCounts = new Map();
  const docTypeCounts = new Map();
  const wordCounts = new Map();

  for (const caseId of state.currentOrderedCaseIds) {
    const data = state.currentResultsById.get(caseId);
    if (!data) continue;

    for (const d of data.case.__states || []) {
      countryCounts.set(d, (countryCounts.get(d) || 0) + data.hitCount);
    }

    bodyCounts.set(data.case.__originatingBody, (bodyCounts.get(data.case.__originatingBody) || 0) + data.hitCount);
    importanceCounts.set(data.case.__importance, (importanceCounts.get(data.case.__importance) || 0) + data.hitCount);
    outcomeCounts.set(data.case.__outcomePrimary, (outcomeCounts.get(data.case.__outcomePrimary) || 0) + data.hitCount);

    // Document type
    const docTypeLabel = data.case.__isPressRelease ? "Press Release" : (data.case.document_type || "Judgment");
    docTypeCounts.set(docTypeLabel, (docTypeCounts.get(docTypeLabel) || 0) + 1);

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
    docTypes: [...docTypeCounts.entries()].sort(sortDesc).slice(0, 10),
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
  _renderAnalyticsData(a);
}

function _renderAnalyticsData(a) {
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
    (label) => formatBodyLabel(label),
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
    (label) => OUTCOME_LABELS[label] || label,
    "country"
  );

  renderBarList(
    el.analyticsDocTypes,
    a.docTypes,
    (label) => label,
    "section"
  );

  renderWordCloud(a.words || []);
}

/** Fetch full analytics from server for current query/filters and render. */
async function fetchAndRenderServerAnalytics(query, filters) {
  try {
    const p = new URLSearchParams();
    if (query) p.set("q", query);
    if (filters.sections.size) {
      const dbSections = [...filters.sections].flatMap(s => SECTION_DB_NAMES[s] || [s]);
      p.set("sections", dbSections.join(","));
    }
    if (filters.articles.size) p.set("articles", [...filters.articles].join(","));
    if (filters.countries.size) p.set("states", [...filters.countries].join(","));
    if (filters.importance.size) p.set("importance", [...filters.importance].join(","));
    if (filters.bodies.size) p.set("bodies", [...filters.bodies].join(","));
    if (filters.keywords && filters.keywords.size) p.set("keywords", [...filters.keywords].join(","));
    const serverOutcomes = [...filters.outcomes].filter(v => PRIMARY_OUTCOMES.has(v));
    if (serverOutcomes.length) p.set("outcomes", serverOutcomes.join(","));
    if (filters.docTypes.size) p.set("doc_types", [...filters.docTypes].join(","));
    if (filters.dateFrom) p.set("date_from", filters.dateFrom);
    if (filters.dateTo) p.set("date_to", filters.dateTo);

    const r = await fetch(`${API_BASE_URL}/analytics?${p}`);
    if (!r.ok) throw new Error(`API ${r.status}`);
    const data = await r.json();

    // Convert server format [{value, count}] → [[label, count]]
    const toEntries = (arr) => (arr || []).map(x => [x.value, x.count]);

    // Section labels: map DB names → display names. Multiple DB values may
    // collapse into a single normalized bucket (e.g. "Facts Background" and
    // "Facts Proceedings" both → "facts"), so aggregate counts by label.
    const sectionCounts = new Map();
    for (const x of data.sections || []) {
      const normKey = Object.entries(SECTION_DB_NAMES)
        .find(([_, dbArr]) => dbArr.includes(x.value))?.[0] || x.value;
      const label = SECTION_LABELS[normKey] || normKey;
      sectionCounts.set(label, (sectionCounts.get(label) || 0) + (x.count || 0));
    }
    // Preserve SECTION_ORDER when rendering.
    const sectionEntries = [...sectionCounts.entries()].sort((a, b) => {
      const ka = Object.entries(SECTION_LABELS).find(([_, lbl]) => lbl === a[0])?.[0];
      const kb = Object.entries(SECTION_LABELS).find(([_, lbl]) => lbl === b[0])?.[0];
      const ia = ka ? SECTION_ORDER.indexOf(ka) : -1;
      const ib = kb ? SECTION_ORDER.indexOf(kb) : -1;
      if (ia !== -1 && ib !== -1) return ia - ib;
      return b[1] - a[1];
    });

    // Importance: map empty value → "Unspecified"
    const importanceEntries = (data.importance || []).map(x => [x.value || "Unspecified", x.count]);

    _renderAnalyticsData({
      articles: toEntries(data.articles),
      countries: toEntries(data.countries),
      sections: sectionEntries,
      bodies: toEntries(data.bodies),
      importance: importanceEntries,
      outcomes: toEntries(data.outcomes),
      docTypes: toEntries(data.doc_types),
      words: [],  // word cloud only available from local paragraph text
    });
    console.log(`[Server Analytics] Rendered (${data.analytics_time_ms}ms, ${data.total_cases} cases)`);
  } catch (e) {
    console.warn("[Server Analytics] Failed, falling back to local:", e);
    renderAnalytics();
  }
}

function updateResultsHeader() {
  const totalCases = state.currentOrderedCaseIds.length;
  const totalPages = Math.ceil(totalCases / PAGE_SIZE) || 1;
  const modeLabel = state.currentMode === "browse" ? "browse" : "search";
  const limitedNote = state.limited ? ` · limited to ${MAX_HITS} hits` : "";
  const browseMode = state.currentMode === "browse";

  el.resultsHeader.hidden = false;
  el.resultsHits.textContent = fmtInt.format(browseMode ? totalCases : state.totalHits);
  if (el.resultsHitsLabel) el.resultsHitsLabel.textContent = browseMode ? "cases" : "passages";
  el.resultsCases.textContent = fmtInt.format(totalCases);
  if (el.resultsCasesLabel) el.resultsCasesLabel.textContent = "judgments";
  el.resultsTime.textContent = `(${(state.searchTimeMs / 1000).toFixed(3)}s · page ${state.currentPage}/${totalPages} · ${modeLabel}${limitedNote})`;
  if (el.queryMatchCount) el.queryMatchCount.textContent = fmtInt.format(browseMode ? totalCases : state.totalHits);
  if (el.queryMatchLabel) el.queryMatchLabel.textContent = browseMode ? "cases shown" : "¶ matched";

  el.exportBtn.disabled = !totalCases;
  if (el.clearBtn) el.clearBtn.disabled = !state.loaded;
}

function applySearch(resetPage = true) {
  // When the server is available, route EVERYTHING through it — both
  // full-text queries (/api/search) and empty-query browse (/api/browse).
  // The previous behaviour ("empty query uses local data") was a dead
  // path: since the sample50 preload was removed, state.cases is empty
  // when the server is live, so empty-query browse would render nothing.
  const query = el.searchInput.value.trim();
  const filters = getCurrentFilters();

  // Keep the address bar shareable: the current query lives in ?q= (same
  // contract as semantic.html). Empty query → clean path.
  try {
    history.replaceState(null, "", query
      ? `${location.pathname}?q=${encodeURIComponent(query)}`
      : location.pathname);
  } catch (_) { /* sandboxed iframes may block history */ }

  if (serverSearch.available) {
    // Default-view mode stays on only while the user hasn't typed a
    // query and hasn't applied filters.  As soon as they do either,
    // the 100-case cap lifts and we show the full result set.
    const hasActiveFilters =
      filters.sections.size ||
      filters.articles.size ||
      filters.countries.size ||
      (filters.keywords && filters.keywords.size) ||
      filters.importance.size ||
      filters.bodies.size ||
      filters.outcomes.size ||
      filters.docTypes.size ||
      filters.dateFrom ||
      filters.dateTo;
    const isDefaultView = !query && !hasActiveFilters;
    state.defaultView = isDefaultView;
    applyServerSearch(query, filters, resetPage, {
      sort: isDefaultView ? "date_desc" : null,
      defaultView: isDefaultView,
    });
    return;
  }

  if (!state.loaded) {
    return;
  }

  state.query = query;
  if (el.inlineSearchInput) el.inlineSearchInput.value = query;
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
  state.serverMode = false;

  if (resetPage) {
    state.currentPage = 1;
  }

  renderActiveFilters(filters);
  renderResultsPage();
  renderAnalytics();
  updateResultsHeader();
}

/** Server-side search — calls API and adapts results to local format. */
async function applyServerSearch(query, filters, resetPage = true, opts = {}) {
  const defaultView = !!opts.defaultView;
  // Sort + grouping are driven by the result-bar controls (state).
  // Relevance only makes sense with a query; paragraph (flat) mode
  // likewise needs a query — browse always stays case-grouped, date-sorted.
  const sort = (!query && state.resultSort === "relevance")
    ? "date_desc" : state.resultSort;
  const group = (query && state.resultGroup === "paragraph") ? "paragraph" : "case";

  state.query = query;
  if (el.inlineSearchInput) el.inlineSearchInput.value = query;
  state.currentFilters = filters;

  // Adapt the filter-rail counts to this search (fire-and-forget — runs
  // in parallel with the search request, updates the rail when it lands).
  refreshRailCounts(query, filters);

  if (resetPage) state.currentPage = 1;

  // Show loading state
  const loadingMsg = defaultView
    ? "Loading 100 most recent cases…"
    : (query ? "Searching 18,000+ cases…" : "Browsing cases…");
  hideSemanticHint();
  el.casesList.innerHTML = `<div class="search-loading" style="text-align:center;padding:2rem;color:var(--text-secondary);">${loadingMsg}</div>`;
  el.noResults.hidden = true;
  el.pagination.hidden = true;
  el.resultsHeader.hidden = false;
  el.resultsHits.textContent = "…";
  el.resultsCases.textContent = "…";
  el.resultsTime.textContent = defaultView ? "(loading recent cases…)" : "(searching server…)";

  const t0 = performance.now();
  try {
    const data = await serverSearch.search(query, filters, state.currentPage, sort, group);
    const t1 = performance.now();
    maybeShowSemanticHint(query, data);

    // ── group=paragraph — flat list, every paragraph an independent result ──
    if (group === "paragraph" && Array.isArray(data.hits)) {
      const flat = [];
      const resultsById = new Map();
      const orderedCaseIds = [];
      for (const h of data.hits) {
        const c = serverSearch._adaptCase(h.case || {});
        state.caseById.set(c.case_id, c);
        const sec = normalizeSectionKey(h.section);
        const hit = {
          key: `${c.case_id}:${sec}:${h.para_idx}`,
          caseId: c.case_id, case: c,
          section: sec, sectionLabel: SECTION_LABELS[sec] || sec,
          paraIdx: h.para_idx,
          hudocParaNo: (h.hudoc_para_no != null) ? Number(h.hudoc_para_no) : null,
          displayParaNo: (h.display_para_no != null) ? Number(h.display_para_no) : null,
          logicalParaIdx: (h.logical_para_idx != null) ? Number(h.logical_para_idx) : null,
          numberingBlock: h.numbering_block || null,
          rowRole: h.row_role || null,
          score: h.score || 0,
          rawText: serverSnippetToPlainText(h.snippet, ""),
          textHtml: serverSnippetToHtml(h.snippet, ""),
          // P58: body ¶ a fragment hit (quote / bullet) belongs to —
          // shown as a muted lead-in so the excerpt reads in context.
          parentText: h.parent_text || null,
        };
        flat.push(hit);
        // Also group hits by case so the Case Note lookups still work.
        let entry = resultsById.get(c.case_id);
        if (!entry) {
          entry = { case: c, paragraphs: [], hitCount: 0 };
          resultsById.set(c.case_id, entry);
          orderedCaseIds.push(c.case_id);
        }
        entry.paragraphs.push(hit);
        entry.hitCount += 1;
      }
      state.flatHits = flat;
      state.currentMode = "search";
      state.currentResultsById = resultsById;
      state.currentOrderedCaseIds = orderedCaseIds;
      state.currentTerms = query.toLowerCase().split(/\s+/).filter(Boolean);
      state.totalHits = data.total_hits || 0;
      state.limited = false;
      state.searchTimeMs = data.search_time_ms || (t1 - t0);
      state.serverMode = true;
      // Pagination is paragraph-level in flat mode.
      state.serverTotalCases = data.total_hits || 0;
      state.serverTotalPages = Math.ceil((data.total_hits || 0) / PAGE_SIZE) || 1;
      renderActiveFilters(filters);
      renderResultsPage();
      fetchAndRenderServerAnalytics(query, filters);
      updateResultsHeaderServer(data, { defaultView: false });
      return;
    }
    state.flatHits = [];

    const resultsById = new Map();
    const orderedCaseIds = [];

    for (const apiCase of (data.cases || [])) {
      const c = serverSearch._adaptCase(apiCase);
      // Store adapted case for modal access
      state.caseById.set(c.case_id, c);

      const rawHits = (apiCase.paragraphs || []).map((p) => {
        const sec = normalizeSectionKey(p.section);
        return {
          key: `${c.case_id}:${sec}:${p.para_idx}`,
          section: sec,
          sectionLabel: SECTION_LABELS[sec] || sec,
          paraIdx: p.para_idx,
          hudocParaNo: (p.hudoc_para_no != null) ? Number(p.hudoc_para_no) : null,
          numberingBlock: p.numbering_block || null,
          rowRole: p.row_role || null,
          // P58 logical-paragraph fields.  `logicalParaIdx` collapses
          // bullet/quote/continuation hits onto their body ¶; `displayParaNo`
          // is the ¶ number to label the hit with; `parentText` is the body
          // ¶ text shown as context when the hit itself is a fragment.
          logicalParaIdx: (p.logical_para_idx != null) ? Number(p.logical_para_idx) : null,
          displayParaNo: (p.display_para_no != null) ? Number(p.display_para_no) : null,
          parentText: p.parent_text || null,
          rawText: serverSnippetToPlainText(p.snippet, p.text),
          textHtml: serverSnippetToHtml(p.snippet, p.text),
        };
      });
      // Paragraph-as-unit dedupe: collapse multiple FTS hits that share
      // the same logical_para_rowid into one search result.  Track which
      // row roles contributed to the match so we can display
      // "matched in heading / quote / body" badges.
      let paragraphs = dedupParagraphHits(rawHits);

      // v1 frontend filter: drop heading rows unless explicitly opted-in.
      // Server doesn't currently honour `exclude_roles`, so this lives
      // here to keep "PROCEDURE" / "THE FACTS" / sub-section labels out
      // of the result list by default.  Researchers can flip the
      // "+ Headings" toggle in the scope bar to include them.
      if (!filters.includeHeadings) {
        paragraphs = paragraphs.filter((p) => {
          const r = p.rowRole || "";
          return !r.startsWith("heading");
        });
      }
      // Drop paragraph-less cases only in SEARCH mode: a query hit whose
      // sole matches were heading rows (filtered out above) shouldn't show.
      // In browse mode (no query) /api/browse legitimately returns cases
      // with no paragraphs — those are the "100 recent cases" cards and
      // must be kept (buildCaseCard renders them via caseOnlyBrowse).
      if (query && !paragraphs.length) continue;

      // Client-side post-filter for filters the server doesn't support
      if (!passesCaseFilters(c, filters)) continue;

      resultsById.set(c.case_id, {
        case: c,
        paragraphs,
        hitCount: apiCase.hit_count || paragraphs.length,
        score: apiCase.score || 0,
      });
      orderedCaseIds.push(c.case_id);
    }

    // Browse mode whenever there is no query (default view OR no-query +
    // filters); search mode only when a query is present.  Drives the
    // caseOnlyBrowse rendering path + "para/hit" result labels.
    state.currentMode = query ? "search" : "browse";
    state.currentOrderedCaseIds = orderedCaseIds;
    state.currentResultsById = resultsById;
    state.currentTerms = query.toLowerCase().split(/\s+/).filter(Boolean);
    state.totalHits = data.total_hits || 0;
    state.limited = false;
    state.searchTimeMs = data.search_time_ms || (t1 - t0);
    state.serverMode = true;
    // Default view: cap visible total at 100 cases / 5 pages even though
    // the server knows about the full 18k+ corpus.
    const rawTotalCases = data.total_cases || 0;
    if (defaultView) {
      state.serverTotalCases = Math.min(state.defaultViewCap, rawTotalCases);
      state.serverTotalPages = Math.ceil(state.serverTotalCases / PAGE_SIZE) || 1;
    } else {
      state.serverTotalCases = rawTotalCases;
      state.serverTotalPages = Math.ceil(rawTotalCases / PAGE_SIZE);
    }

    renderActiveFilters(filters);
    renderResultsPage();
    // For real searches/filters: hit the server analytics endpoint for
    // corpus-wide aggregates over the matching set.  For the initial
    // browse view we used to skip the call entirely, leaving the Search
    // Analytics sidebar showing "No data" — visually inert and confusing
    // on the redesigned researcher layout.  Instead derive page-level
    // aggregates from the cases we already loaded.  This matches what
    // the user sees on screen.
    if (!defaultView) {
      fetchAndRenderServerAnalytics(query, filters);
    } else {
      try { renderAnalytics(); } catch (e) { console.warn("[Browse Analytics] local render failed:", e); }
    }
    updateResultsHeaderServer(data, { defaultView });
  } catch (err) {
    console.error("[Server Search] Error:", err);
    // Fall back to local search
    state.serverMode = false;
    const t1 = performance.now();
    if (state.loaded) {
      const result = buildQueryResults(query, filters);
      state.currentMode = result.mode;
      state.currentOrderedCaseIds = result.orderedCaseIds;
      state.currentResultsById = result.resultsById;
      state.currentTerms = result.terms;
      state.totalHits = result.totalHits;
      state.limited = result.limited;
      state.searchTimeMs = t1 - t0;
      if (resetPage) state.currentPage = 1;
      renderActiveFilters(filters);
      renderResultsPage();
      renderAnalytics();
      updateResultsHeader();
    } else {
      el.casesList.innerHTML = '';
      el.noResults.hidden = false;
      el.noResults.textContent = "Server search failed and no local data loaded.";
    }
  }
}

/** Update results header for server-side search results. */
function updateResultsHeaderServer(data, opts = {}) {
  const defaultView = !!opts.defaultView;
  // In default view, the "cases" count is the 100-cap, not the full corpus.
  const totalCases = defaultView
    ? (state.serverTotalCases || 0)
    : (data.total_cases || state.currentOrderedCaseIds.length);
  const totalPages = defaultView
    ? (state.serverTotalPages || 1)
    : (Math.ceil(totalCases / PAGE_SIZE) || 1);
  const serverTag = defaultView
    ? "server · 100 most recent"
    : "server · full dataset";

  el.resultsHeader.hidden = false;
  el.resultsHits.textContent = fmtInt.format(defaultView ? totalCases : (data.total_hits || 0));
  if (el.resultsHitsLabel) el.resultsHitsLabel.textContent = defaultView ? "recent cases" : "passages";
  el.resultsCases.textContent = fmtInt.format(defaultView ? (data.total_cases || totalCases) : totalCases);
  if (el.resultsCasesLabel) el.resultsCasesLabel.textContent = defaultView ? "records" : "judgments";
  el.resultsTime.textContent = `(${((data.search_time_ms || state.searchTimeMs) / 1000).toFixed(3)}s · page ${state.currentPage}/${totalPages} · ${serverTag})`;
  if (el.queryMatchCount) el.queryMatchCount.textContent = fmtInt.format(defaultView ? totalCases : (data.total_hits || 0));
  if (el.queryMatchLabel) el.queryMatchLabel.textContent = defaultView ? "recent cases" : "¶ matched";

  el.exportBtn.disabled = !state.currentOrderedCaseIds.length;
  if (el.clearBtn) el.clearBtn.disabled = false;
  syncResultControls();
}

function resetFiltersAndQuery() {
  el.searchInput.value = "";
  if (el.inlineSearchInput) el.inlineSearchInput.value = "";
  el.dateFrom.value = "";
  el.dateTo.value = "";

  const checks = document.querySelectorAll("#filtersPanel input[type='checkbox']");
  for (const c of checks) {
    c.checked = false;
  }

  applySearch(true);
}

async function exportResults() {
  if (!state.currentOrderedCaseIds.length) return;
  const includeClassifierLabels = !!el.exportIncludeClassifier?.checked;

  const header = [
    "Case ID",
    "Case No",
    "Title",
    "Judgment Date",
    "Defendants",
    "Articles",
    "Respondent State",
    "Originating Body",
    "Importance",
    "Document Type",
    "Outcome Primary",
    "Inadmissibility",
    "Struck out",
    "Procedural aspect",
    "Substantive aspect",
    "Separate Opinion",
    "ECLI",
    "HUDOC URL",
    "Violation",
    "Non-violation",
    "Keywords",
    "Strasbourg citation count",
    "Top Strasbourg precedents",
    "Section",
    "Paragraph (display)",
    "HUDOC paragraph",
    "Internal index",
  ];
  if (includeClassifierLabels) {
    header.push("Assigned Labels");
  }
  header.push("Text");

  const rows = [header];

  // In server mode, fetch ALL results (not just current page)
  let allCaseIds = state.currentOrderedCaseIds;
  let allResultsById = state.currentResultsById;

  if (state.serverMode && state.serverTotalCases > state.currentOrderedCaseIds.length) {
    el.exportBtn.disabled = true;
    el.exportBtn.textContent = "⏳ Exporting…";
    try {
      const params = serverSearch._buildParams(state.query, state.currentFilters, 1);
      params.set("page_size", String(state.serverTotalCases));
      params.set("export", "true");
      const endpoint = state.query ? "search" : "browse";
      const r = await fetch(`${API_BASE_URL}/${endpoint}?${params}`);
      if (!r.ok) throw new Error(`API ${r.status}`);
      const data = await r.json();

      allCaseIds = [];
      allResultsById = new Map();
      for (const apiCase of (data.cases || [])) {
        const c = serverSearch._adaptCase(apiCase);
        const paragraphs = (apiCase.paragraphs || []).map((p) => {
          const sec = normalizeSectionKey(p.section);
          return {
            key: `${c.case_id}:${sec}:${p.para_idx}`,
            section: sec,
            sectionLabel: SECTION_LABELS[sec] || sec,
            paraIdx: p.para_idx,
            hudocParaNo: (p.hudoc_para_no != null) ? Number(p.hudoc_para_no) : null,
            numberingBlock: p.numbering_block || null,
            rowRole: p.row_role || null,
            rawText: serverSnippetToPlainText(p.snippet, p.text),
          };
        });
        allCaseIds.push(c.case_id);
        allResultsById.set(c.case_id, { case: c, paragraphs });
      }
    } catch (e) {
      console.error("[Export] Failed to fetch all results:", e);
      // Fall back to current page data
    } finally {
      el.exportBtn.disabled = false;
      el.exportBtn.innerHTML = "Export Excel";
    }
  }

  for (const caseId of allCaseIds) {
    const data = allResultsById.get(caseId);
    if (!data) continue;

    for (const p of data.paragraphs) {
      const row = [
        caseId,
        data.case.case_no || "",
        data.case.title || "",
        data.case.judgment_date || "",
        (data.case.defendants || []).join(", "),
        data.case.article_no || "",
        (data.case.__states || []).join(", "),
        data.case.__originatingBody || "",
        data.case.__importance || "",
        data.case.__isPressRelease ? "Press Release" : (data.case.document_type || "Judgment"),
        data.case.__outcomePrimary || "",
        data.case.__hasInadmissibility ? "yes" : "no",
        data.case.__isStruckOut ? "yes" : "no",
        data.case.__hasProceduralAspect ? "yes" : "no",
        data.case.__hasSubstantiveAspect ? "yes" : "no",
        data.case.__hasSeparateOpinion ? "yes" : "no",
        data.case.ecli || "",
        data.case.hudoc_url || "",
        (data.case.violation || []).join("; "),
        (data.case["non-violation"] || []).join("; "),
        (data.case.keywords || []).join("; "),
        String(data.case.__citesCountServer != null
          ? data.case.__citesCountServer
          : (data.case.__citationRefs || []).length),
        (data.case.__citationRefs || []).slice(0, 3).join("; "),
        p.sectionLabel,
        // Display: HUDOC if available, internal index otherwise (with * marker).
        p.hudocParaNo != null ? String(p.hudocParaNo) : String((p.paraIdx ?? 0) + 1) + "*",
        // Raw fields for both, so consumers can always reconstruct.
        p.hudocParaNo != null ? String(p.hudocParaNo) : "",
        String((p.paraIdx ?? 0) + 1),
      ];

      if (includeClassifierLabels) {
        row.push(getCombinedParagraphLabels(p.key).map((x) => x.label).join("; "));
      }
      row.push(p.rawText);
      rows.push(row);
    }
  }

  const suffix = state.query ? state.query.slice(0, 24).replace(/\s+/g, "_") : "all_cases";
  const baseName = `echr_search_${suffix}`;
  try {
    const XLSX = await loadSheetJS();
    const ws = XLSX.utils.aoa_to_sheet(rows);
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, "ECHR results");
    XLSX.writeFile(wb, `${baseName}.xlsx`);
  } catch (err) {
    // SheetJS unavailable (offline / CDN blocked) \u2014 fall back to CSV so
    // the export never silently fails.
    console.warn("[Export] xlsx writer unavailable, exporting CSV:", err);
    const csv = rows
      .map((row) =>
        row
          .map((cell) => `"${String(cell ?? "").replaceAll('"', '""')}"`)
          .join(",")
      )
      .join("\n");
    const blob = new Blob([`\uFEFF${csv}`], { type: "text/csv;charset=utf-8" });
    _triggerDownload(blob, `${baseName}.csv`);
  }
}

// Excel (.xlsx) export uses SheetJS, lazy-loaded from its CDN on first
// export so the ~900 KB library never touches initial page load.
let _sheetJsPromise = null;
function loadSheetJS() {
  if (window.XLSX) return Promise.resolve(window.XLSX);
  if (_sheetJsPromise) return _sheetJsPromise;
  _sheetJsPromise = new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = "https://cdn.sheetjs.com/xlsx-0.20.3/package/dist/xlsx.full.min.js";
    s.onload = () => (window.XLSX ? resolve(window.XLSX)
                                  : reject(new Error("XLSX not defined")));
    s.onerror = () => { _sheetJsPromise = null; reject(new Error("CDN load failed")); };
    document.head.appendChild(s);
  });
  return _sheetJsPromise;
}

function _triggerDownload(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
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

  const toggleButtons = el.casesList.querySelectorAll(`button[data-action="toggle-case"][data-case-id="${caseId}"]`);
  for (const btn of toggleButtons) {
    btn.setAttribute("aria-expanded", isOpen ? "true" : "false");
  }
}

function buildCaseMeta(caseObj) {
  const parts = [];
  parts.push(`Case no: ${escapeHtml(caseObj.case_no || "-")}`);
  parts.push(`Judgment: ${escapeHtml(caseObj.judgment_date || "-")}`);

  const states = (caseObj.__states || []).map((d) => COUNTRY_NAMES[d] || d).join(", ") || "-";
  parts.push(`Respondent State: ${escapeHtml(states)}`);
  parts.push(`Originating Body: ${escapeHtml(formatBodyLabel(caseObj.__originatingBody) || "-")}`);
  parts.push(`Importance: ${escapeHtml(caseObj.__importance || "-")}`);
  parts.push(`Outcome: ${escapeHtml(OUTCOME_LABELS[caseObj.__outcomePrimary] || caseObj.__outcomePrimary || "-")}`);
  parts.push(`Inadmissibility: ${caseObj.__hasInadmissibility ? "Yes" : "No"}`);
  parts.push(`Struck out: ${caseObj.__isStruckOut ? "Yes" : "No"}`);
  parts.push(`Procedural aspect: ${caseObj.__hasProceduralAspect ? "Yes" : "No"}`);
  parts.push(`Substantive aspect: ${caseObj.__hasSubstantiveAspect ? "Yes" : "No"}`);
  parts.push(`Separate Opinion: ${caseObj.__hasSeparateOpinion ? "Yes" : "No"}`);
  parts.push(`Articles: ${escapeHtml(caseObj.article_no || "-")}`);
  // Citation aggregates: prefer the server-computed P29 count when
  // available (covers cases not in the JSONL); otherwise fall back to
  // the JSONL strasbourg_caselaw length.
  {
    const cites = (caseObj.__citesCountServer != null)
      ? caseObj.__citesCountServer
      : (caseObj.__citationRefs || []).length;
    parts.push(`Cites: ${fmtInt.format(cites)}`);
    if (caseObj.__citedByCount > 0) {
      parts.push(`Cited by: ${fmtInt.format(caseObj.__citedByCount)}`);
    }
  }
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

  if (Array.isArray(caseObj.__citationRefs) && caseObj.__citationRefs.length) {
    parts.push(`Top precedents: ${escapeHtml(caseObj.__citationRefs.slice(0, 3).join("; "))}`);
  }

  if (caseObj.__citedByCount > 0) {
    parts.push(`<span class="legal-chip cited-by" title="Cited by ${caseObj.__citedByCount} other case(s) in this dataset">Cited ${caseObj.__citedByCount}×</span>`);
  }

  if (caseObj.hudoc_url) {
    parts.push(`<a href="${escapeHtml(caseObj.hudoc_url)}" target="_blank" rel="noopener noreferrer">Open in HUDOC ↗</a>`);
  }

  return parts.join(" · ");
}

/**
 * Detect structural heading paragraphs — lines that are pure section/sub-section
 * titles (e.g. "THE FACTS", "I. THE APPLICANT ASSOCIATION", "A. Background")
 * with no actual numbered-paragraph content.  These should be rendered as
 * styled sub-headings rather than as ¶ N content paragraphs.
 *
 * Rules (all must pass):
 *   1. Short — under 220 characters (real paragraphs are much longer)
 *   2. Does NOT start with an Arabic-numeral paragraph marker ("1.", "2)", "12 .")
 *   3. Text is composed of only: uppercase letters, Roman-numeral chars, spaces,
 *      dots, hyphens, parentheses, quotes, slashes, colons, commas, and digits
 *      that appear inside a heading (e.g. "ARTICLE 8", "SECTION 1").
 *
 * Conservative: anything with a lowercase letter passes through as normal content.
 */
// NOTE: in Unicode mode (/u), identity escapes inside a character class
// are illegal — \-, \(, \), \/, \: all raise SyntaxError: "Invalid escape".
// None of those characters are special inside [...] anyway, so drop the
// backslashes; keep the `-` at the END of the class so it stays literal.
const HEADING_ONLY_RE = /^[A-ZÉÀÈÙÂÊÎÔÛÇ0-9\s.()"'/:,\u201C\u201D\u2018\u2019\u2013\u2014-]+$/u;
const NUMBERED_PARA_RE = /^\d+\s*[.)]\s+\S/;
const SUBHEADING_RE = /^([A-Z]\.|\([a-z]\)|[IVX]+\.)\s+[A-Z][\p{L}\d \-,/'’()".§]*$/u;
// Finite/auxiliary verbs that signal prose rather than a noun-phrase heading.
// Used to reject "B. Smith was the applicant's lawyer in 1995" while still
// accepting "B. The Court's assessment", "A. Preventive measures…", etc.
const PROSE_VERB_RE = /\b(was|were|is|are|had|have|has|did|does|do|been|being)\b/i;

function isStructuralHeading(text) {
  if (!text) return false;
  const t = text.trim();
  if (t.length === 0 || t.length > 220) return false;
  if (NUMBERED_PARA_RE.test(t)) return false;       // real numbered paragraph
  if (HEADING_ONLY_RE.test(t)) return true;
  // Title-case sub-headings — short noun-phrase lines that mark
  // sub-sections within a numbered judgment.  After the P34 HUDOC-rebuild
  // these come straight from the source DOCX, e.g.:
  //   "A. Damage", "B. Costs and expenses", "C. Default interest",
  //   "(a) The applicant", "(b) Application of the above principles…",
  //   "B. Merits 1. The applicant", "B. The Court's assessment".
  // Anchored at the marker; capped to 100 chars; rejected if the line
  // contains a finite/auxiliary verb (signals prose, e.g. "B. Smith was…").
  if (t.length <= 100 && SUBHEADING_RE.test(t) && !PROSE_VERB_RE.test(t)) return true;
  return false;
}

// ───────────────────────────────────────────────────────────────────
// Paragraph dossier — resizable right-column panel that shows a clicked
// paragraph in the context of its ±2 neighbours within the same section.
// Replaces the in-app case modal as the paragraph-preview surface.
// ───────────────────────────────────────────────────────────────────
const dossierCaseCache = new Map(); // caseId -> full ordered paragraph list
const DOSSIER_WIN = 2;
const DOSSIER_MIN_W = 320;
const DOSSIER_MAX_W = 760;
const DOSSIER_DEFAULT_W = 440;
const DOSSIER_LS_KEY = "echr.dossierWidth";

async function loadDossierCase(caseId) {
  if (dossierCaseCache.has(caseId)) return dossierCaseCache.get(caseId);
  const data = await serverSearch.getCase(caseId);
  const paras = (data.paragraphs || []).map((p) => {
    const sec = normalizeSectionKey(p.section);
    return {
      section: sec,
      sectionLabel: SECTION_LABELS[sec] || p.section || sec,
      text: String(p.text || ""),
      paraIdx: (p.para_idx != null) ? Number(p.para_idx) : null,
      hudocParaNo: (p.hudoc_para_no != null) ? Number(p.hudoc_para_no) : null,
      displayParaNo: (p.display_para_no != null) ? Number(p.display_para_no) : null,
      logicalParaIdx: (p.logical_para_idx != null) ? Number(p.logical_para_idx) : null,
      numberingBlock: p.numbering_block || null,
      rowRole: p.row_role || null,
    };
  });
  dossierCaseCache.set(caseId, paras);
  return paras;
}

/* Window of ±`win` paragraphs around `activeIdx`, clamped to the section
 * the active paragraph belongs to.  `expanded` widens it to the whole
 * section.  Section identity = the (bucket) `section` key. */
function getDossierContext(paras, activeIdx, win, expanded) {
  const secKey = paras[activeIdx].section || "";
  let start = activeIdx, end = activeIdx;
  while (start > 0 && (paras[start - 1].section || "") === secKey) start--;
  while (end < paras.length - 1 && (paras[end + 1].section || "") === secKey) end++;
  const totalInSection = end - start + 1;
  const fromIdx = expanded ? start : Math.max(start, activeIdx - win);
  const toIdx = expanded ? end : Math.min(end, activeIdx + win);
  return {
    prev: paras.slice(fromIdx, activeIdx),
    active: paras[activeIdx],
    next: paras.slice(activeIdx + 1, toIdx + 1),
    totalInSection,
    canExpand: !expanded && (toIdx - fromIdx + 1) < totalInSection,
  };
}

// Boolean operators plus function words: highlighting "to" or "of" paints
// noise over every paragraph of a query like "failure to protect".
const DOSSIER_HL_SKIP = new Set([
  "and", "or", "not", "to", "of", "in", "on", "at", "by", "for", "the",
  "a", "an", "as", "is", "are", "was", "were", "be", "been", "has",
  "have", "had", "it", "its", "with", "from", "under", "that", "this",
]);
function dossierHighlight(text, terms) {
  let html = escapeHtml(text);
  for (let t of (terms || [])) {
    if (!t || t.includes(":")) continue; // skip field operators (article:8)
    // Strip phrase quotes / edge punctuation so "biometric and data"
    // (split from a "phrase" query) still matches the bare words.
    t = t.replace(/^[^\p{L}\p{N}]+|[^\p{L}\p{N}]+$/gu, "");
    if (t.length < 2 || DOSSIER_HL_SKIP.has(t.toLowerCase())) continue;
    try {
      // Leading word-boundary + trailing letter-run: match whole words that
      // START with the term ("protect" still lights up "protection", like
      // FTS porter stemming) but never start mid-word ("discrimina|to|ry").
      html = html.replace(
        new RegExp("(?<![\\p{L}\\p{N}])(" + escapeRegExp(t) + "\\p{L}*)", "giu"),
        '<mark class="hl">$1</mark>');
    } catch { /* skip malformed term */ }
  }
  return html;
}

function dossierParaNumLabel(p) {
  const n = (p.displayParaNo != null) ? p.displayParaNo
          : (p.hudocParaNo != null) ? p.hudocParaNo : null;
  return n != null ? `¶ ${n}` : "¶ —";
}

async function openDossier(caseId, paraIdx) {
  if (!caseId) return;
  state.dossier = {
    caseId,
    paraIdx: (paraIdx != null && paraIdx !== "") ? Number(paraIdx) : null,
    expanded: false,
  };
  document.body.classList.add("dossier-open");
  el.dossierContent.innerHTML = `<div class="dossier-empty">Loading paragraph context…</div>`;
  try {
    const paras = await loadDossierCase(caseId);
    if (!state.dossier || state.dossier.caseId !== caseId) return; // superseded
    // Resolve the active paragraph. Case-level opens (no para_idx) fall
    // back to the first numbered body paragraph.
    let idx = -1;
    if (state.dossier.paraIdx != null) {
      idx = paras.findIndex((p) => p.paraIdx === state.dossier.paraIdx);
    }
    if (idx < 0) idx = paras.findIndex((p) => p.hudocParaNo != null);
    if (idx < 0) idx = 0;
    state.dossier.paraIdx = paras[idx] ? paras[idx].paraIdx : null;
    paintDossier();
  } catch (err) {
    console.error("[Dossier] load failed:", err);
    el.dossierContent.innerHTML =
      `<div class="dossier-empty">Could not load this judgment. ` +
      `<button type="button" class="dossier-expand" data-action="close-dossier">Close</button></div>`;
  }
}

function closeDossier() {
  document.body.classList.remove("dossier-open");
  state.dossier = null;
}

function paintDossier() {
  const d = state.dossier;
  if (!d || !d.caseId) return;
  const paras = dossierCaseCache.get(d.caseId);
  if (!paras) return;
  const activeIdx = paras.findIndex((p) => p.paraIdx === d.paraIdx);
  if (activeIdx < 0) {
    el.dossierContent.innerHTML = `<div class="dossier-empty">Paragraph not found in this judgment.</div>`;
    return;
  }
  const caseObj = state.caseById.get(d.caseId);
  const ctx = getDossierContext(paras, activeIdx, DOSSIER_WIN, d.expanded);
  const terms = state.currentTerms || [];

  // Breadcrumb: section bucket label + nearest preceding heading row.
  let headingText = "";
  for (let i = activeIdx; i >= 0; i--) {
    if ((paras[i].section || "") !== (ctx.active.section || "")) break;
    const r = paras[i].rowRole || "";
    if (r === "heading" || r.startsWith("heading")) { headingText = paras[i].text || ""; break; }
  }
  const bc = [escapeHtml(ctx.active.sectionLabel || "—")];
  if (headingText.trim() && headingText.trim().length <= 120) {
    bc.push(escapeHtml(headingText.trim()));
  }
  const breadcrumb = bc.join('<span class="dossier-bc-sep">›</span>');

  const renderCtx = (p) => `
    <div class="dossier-ctx-para">
      <span class="dossier-ctx-num">${escapeHtml(dossierParaNumLabel(p))}</span>${escapeHtml(p.text)}
    </div>`;
  const activeHtml = `
    <div class="dossier-ctx-para dossier-ctx-active">
      <span class="dossier-ctx-num">${escapeHtml(dossierParaNumLabel(ctx.active))}</span>${dossierHighlight(ctx.active.text, terms)}
    </div>`;

  let expander = "";
  if (ctx.canExpand) {
    expander = `<button type="button" class="dossier-expand" data-action="dossier-expand">Show entire section (${ctx.totalInSection} ¶)</button>`;
  } else if (d.expanded && ctx.totalInSection > (2 * DOSSIER_WIN + 1)) {
    expander = `<button type="button" class="dossier-expand" data-action="dossier-collapse">Collapse to ±${DOSSIER_WIN}</button>`;
  }

  const hudocUrl = caseObj ? paragraphHudocUrl(caseObj, ctx.active) : "";
  el.dossierContent.innerHTML = `
    <div class="dossier-header">
      <div class="dossier-header-text">
        <div class="dossier-kicker">Dossier · ${escapeHtml(dossierParaNumLabel(ctx.active))}</div>
        <h3 class="dossier-case-title">${escapeHtml(cleanCaseTitle(caseObj && caseObj.title) || d.caseId)}</h3>
      </div>
      <button type="button" class="dossier-close" data-action="close-dossier" title="Close (Esc)" aria-label="Close dossier">×</button>
    </div>
    <div class="dossier-body">
      <div class="dossier-breadcrumb">${breadcrumb}</div>
      ${ctx.prev.map(renderCtx).join("")}
      ${activeHtml}
      ${ctx.next.map(renderCtx).join("")}
      ${expander}
    </div>
    <div class="dossier-footer">
      ${hudocUrl ? `<a class="case-open-link primary" href="${escapeHtml(hudocUrl)}" target="_blank" rel="noopener noreferrer">Open in HUDOC ↗</a>` : ""}
      <button type="button" class="case-open-secondary" data-action="dossier-cite">Cite ¶</button>
    </div>`;
}

function initDossierResizer() {
  const handle = el.dossierResizer;
  if (!handle || !el.dossier) return;
  const clampW = (px) => Math.max(DOSSIER_MIN_W, Math.min(DOSSIER_MAX_W, Math.round(px)));
  const setW = (px) => document.documentElement.style.setProperty("--col-dossier", clampW(px) + "px");
  const persist = () => {
    const cur = parseInt(getComputedStyle(document.documentElement).getPropertyValue("--col-dossier"), 10);
    if (!Number.isNaN(cur)) localStorage.setItem(DOSSIER_LS_KEY, String(cur));
  };
  const saved = parseInt(localStorage.getItem(DOSSIER_LS_KEY) || "", 10);
  if (!Number.isNaN(saved)) setW(saved);

  let dragging = false, rightEdge = 0;
  const onMove = (ev) => { if (dragging && ev.clientX != null) setW(rightEdge - ev.clientX); };
  const onUp = () => {
    if (!dragging) return;
    dragging = false;
    handle.classList.remove("is-dragging");
    document.body.classList.remove("is-resizing-dossier");
    persist();
    window.removeEventListener("pointermove", onMove);
    window.removeEventListener("pointerup", onUp);
  };
  handle.addEventListener("pointerdown", (ev) => {
    ev.preventDefault();
    dragging = true;
    rightEdge = el.dossier.getBoundingClientRect().right;
    handle.classList.add("is-dragging");
    document.body.classList.add("is-resizing-dossier");
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  });
  handle.addEventListener("dblclick", () => { setW(DOSSIER_DEFAULT_W); persist(); });
  handle.addEventListener("keydown", (ev) => {
    if (ev.key !== "ArrowLeft" && ev.key !== "ArrowRight") return;
    ev.preventDefault();
    const cur = parseInt(getComputedStyle(document.documentElement).getPropertyValue("--col-dossier"), 10) || DOSSIER_DEFAULT_W;
    setW(cur + (ev.key === "ArrowLeft" ? 24 : -24));
    persist();
  });
}

// Drag-resize handle for the Case Note sidebar (workspace column 3).
function initSidebarResizer() {
  const handle = el.sidebarResizer;
  if (!handle || !el.sidebar) return;
  const MIN = 280, DEF = 360, KEY = "echr.sidebarWidth";
  // Cap the Case Note at half the viewport so it can be widened for reading
  // context (recomputed each clamp so it adapts to window resizes).
  const maxW = () => Math.max(MIN, Math.round(window.innerWidth * 0.5));
  const clampW = (px) => Math.max(MIN, Math.min(maxW(), Math.round(px)));
  const setW = (px) => document.documentElement.style.setProperty("--col-sidebar", clampW(px) + "px");
  const persist = () => {
    const cur = parseInt(getComputedStyle(document.documentElement).getPropertyValue("--col-sidebar"), 10);
    if (!Number.isNaN(cur)) localStorage.setItem(KEY, String(cur));
  };
  const saved = parseInt(localStorage.getItem(KEY) || "", 10);
  if (!Number.isNaN(saved)) setW(saved);

  let dragging = false, rightEdge = 0;
  const onMove = (ev) => { if (dragging && ev.clientX != null) setW(rightEdge - ev.clientX); };
  const onUp = () => {
    if (!dragging) return;
    dragging = false;
    handle.classList.remove("is-dragging");
    document.body.classList.remove("is-resizing-dossier");
    persist();
    window.removeEventListener("pointermove", onMove);
    window.removeEventListener("pointerup", onUp);
  };
  handle.addEventListener("pointerdown", (ev) => {
    ev.preventDefault();
    dragging = true;
    rightEdge = el.sidebar.getBoundingClientRect().right;
    handle.classList.add("is-dragging");
    document.body.classList.add("is-resizing-dossier");
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  });
  handle.addEventListener("dblclick", () => { setW(DEF); persist(); });
  handle.addEventListener("keydown", (ev) => {
    if (ev.key !== "ArrowLeft" && ev.key !== "ArrowRight") return;
    ev.preventDefault();
    const cur = parseInt(getComputedStyle(document.documentElement).getPropertyValue("--col-sidebar"), 10) || DEF;
    setW(cur + (ev.key === "ArrowLeft" ? 24 : -24));
    persist();
  });
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

  // Don't overwrite server connection status when server is active
  if (!serverSearch.available) {
    setDatasetStatus(
      `Loaded ${fmtInt.format(state.cases.length)} cases and ${fmtInt.format(state.paragraphIndex.length)} indexed paragraphs.` +
      (invalidCount ? ` Skipped ${fmtInt.format(invalidCount)} invalid lines.` : "")
    );
    setDatasetMeta(metaLine);
  }

  closeClassifierPane();
  loadClassifierStateForDataset();
  setSearchEnabled(true);

  // Auto-collapse data source panel after load
  const dsPanel = document.getElementById("dataSourcePanel");
  if (dsPanel && !dsPanel.querySelector(".collapse-toggle")) {
    const colBtn = document.createElement("button");
    colBtn.type = "button";
    colBtn.className = "collapse-toggle";
    colBtn.textContent = "[collapse]";
    colBtn.addEventListener("click", () => {
      dsPanel.classList.toggle("collapsed");
      colBtn.textContent = dsPanel.classList.contains("collapsed") ? "[expand]" : "[collapse]";
    });
    dsPanel.querySelector("#dataSourceTitle")?.appendChild(colBtn);
  }
  setTimeout(() => dsPanel?.classList.add("collapsed"), 500);

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
    // Rebuild the button (caret ▶/▼ + active-filter badge) for the new state.
    updateActiveFilterCount();
    // The advanced panel sits BELOW two long always-on groups — without this
    // scroll it opens ~1000px under the fold and the click looks like a no-op.
    if (open) {
      // Bring the advanced panel into view — it sits ~1000px down the rail,
      // past two long always-on groups, so the click otherwise looks dead.
      // NB: smooth scrollIntoView dies in this nested-scroller layout
      // (moves ~8px and stops), so scroll the rail container explicitly.
      setTimeout(() => {
        const adv = byId("filtersAdvanced");
        if (!adv) return;
        const rail = adv.closest(".editorial-filter-rail");
        if (rail && rail.scrollHeight > rail.clientHeight) {
          rail.scrollTop += adv.getBoundingClientRect().top - rail.getBoundingClientRect().top - 8;
        } else {
          adv.scrollIntoView({ block: "nearest" });
        }
      }, 180);
    }
  });

  el.searchForm.addEventListener("submit", (e) => {
    e.preventDefault();
    applySearch(true);
  });

  el.inlineSearchForm?.addEventListener("submit", (e) => {
    e.preventDefault();
    el.searchInput.value = el.inlineSearchInput?.value || "";
    applySearch(true);
  });

  el.filtersPanel.addEventListener("change", () => {
    if (!state.loaded && !serverSearch.available) return;
    // Refresh per-group clear buttons + active-filter count badge before
    // re-running the search (so the UI reflects what is about to be applied).
    attachFilterGroupClearButtons();
    updateActiveFilterCount();
    applySearch(true);
  });

  // v1 bucket scope bar — bucket pills + headings/meta toggles sit
  // above the filters panel, outside its change listener.  Wire them
  // up to re-run the search on any change.
  document.getElementById("bucketScope")?.addEventListener("change", () => {
    if (!state.loaded && !serverSearch.available) return;
    updateActiveFilterCount();
    applySearch(true);
  });

  // Date inputs affect the active-filter count badge.
  el.dateFrom?.addEventListener("change", updateActiveFilterCount);
  el.dateTo?.addEventListener("change", updateActiveFilterCount);

  // Result-display controls: Sort (relevance/newest/oldest) + Group
  // (by case / by paragraph). Restore persisted choice, then wire.
  try {
    const s = localStorage.getItem("echr.resultSort");
    if (["relevance", "date_desc", "date_asc"].includes(s)) state.resultSort = s;
    const g = localStorage.getItem("echr.resultGroup");
    if (["case", "paragraph"].includes(g)) state.resultGroup = g;
  } catch (_) { /* private mode */ }
  syncResultControls();

  document.getElementById("resultSortControls")?.addEventListener("click", (e) => {
    const b = e.target.closest(".rdc-opt[data-sort]");
    if (!b || b.disabled || state.resultSort === b.dataset.sort) return;
    state.resultSort = b.dataset.sort;
    try { localStorage.setItem("echr.resultSort", state.resultSort); } catch (_) {}
    syncResultControls();
    applySearch(true);
  });
  document.getElementById("resultGroupControls")?.addEventListener("click", (e) => {
    const b = e.target.closest(".rdc-opt[data-group]");
    if (!b || b.disabled || state.resultGroup === b.dataset.group) return;
    state.resultGroup = b.dataset.group;
    try { localStorage.setItem("echr.resultGroup", state.resultGroup); } catch (_) {}
    syncResultControls();
    applySearch(true);
  });

  el.clearBtn?.addEventListener("click", () => {
    if (!state.loaded && !serverSearch.available) return;
    resetFiltersAndQuery();
  });

  el.exportBtn.addEventListener("click", exportResults);
  el.cardModeBtn?.addEventListener("click", () => {
    if (!state.loaded) return;
    toggleCardMode();
  });

  el.backToSearch.addEventListener("click", (e) => {
    e.preventDefault();
    resetFiltersAndQuery();
  });

  el.loadSampleBtn.addEventListener("click", loadSampleDataset);
  el.openClassifierBtn.addEventListener("click", openClassifierPane);
  el.classifierQuickOpenBtn?.addEventListener("click", openClassifierPane);
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

    if (action === "select-case" && caseId) {
      selectCase(caseId);
      return;
    }

    if (action === "toggle-case" && caseId) {
      toggleCase(caseId);
      selectCase(caseId);
      return;
    }

    // HUDOC ↗ link inside a paragraph row: let the browser follow the
    // anchor, but don't also fire the row's select-para action.
    if (action === "open-hudoc") {
      return;
    }

    if (action === "select-para" && caseId) {
      selectCaseParagraph(caseId, clickable.getAttribute("data-para-idx"));
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
      openDossier(caseId);
      return;
    }

    if (action === "copy-citation" && caseId) {
      e.preventDefault();
      const caseObj = state.caseById.get(caseId);
      if (caseObj) copyToClipboardWithFeedback(buildStandardCitation(caseObj), clickable);
      return;
    }

    if (action === "copy-paragraph-citation" && caseId) {
      e.preventDefault();
      const caseObj = state.caseById.get(caseId);
      const paraKey = clickable.getAttribute("data-para-key") || "";
      if (caseObj) {
        // Look up the paragraph object so the citation can include
        // the proper § N anchor.  We search the case's __paragraphs
        // list by the same key the result row was built from.
        let para = null;
        for (const p of (caseObj.__paragraphs || [])) {
          if ((p.key || "") === paraKey) { para = p; break; }
        }
        copyToClipboardWithFeedback(
          buildParagraphCitation(caseObj, para),
          clickable,
        );
      }
      return;
    }

    if (action === "copy-info-card" && caseId) {
      e.preventDefault();
      const caseObj = state.caseById.get(caseId);
      if (caseObj) copyToClipboardWithFeedback(buildKeyInfoBlock(caseObj), clickable);
      return;
    }
  });

  el.casesList.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" && e.key !== " ") return;
    const result = e.target.closest("[data-action='select-case'][data-case-id]");
    if (!result) return;
    e.preventDefault();
    selectCase(result.getAttribute("data-case-id"));
  });

  // Dossier panel — button actions (close / expand / collapse / cite)
  // plus the drag-to-resize handle.
  el.dossier?.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-action]");
    if (!btn) return;
    const action = btn.getAttribute("data-action");
    if (action === "close-dossier") { closeDossier(); return; }
    if (action === "dossier-expand") {
      if (state.dossier) { state.dossier.expanded = true; paintDossier(); }
      return;
    }
    if (action === "dossier-collapse") {
      if (state.dossier) { state.dossier.expanded = false; paintDossier(); }
      return;
    }
    if (action === "dossier-cite") {
      const d = state.dossier;
      if (!d) return;
      const caseObj = state.caseById.get(d.caseId);
      const active = (dossierCaseCache.get(d.caseId) || [])
        .find((p) => p.paraIdx === d.paraIdx);
      if (caseObj && active) {
        copyToClipboardWithFeedback(buildParagraphCitation(caseObj, active), btn);
      }
      return;
    }
  });
  initDossierResizer();
  initSidebarResizer();

  const bindCaseContextActions = (rail) => rail?.addEventListener("click", (e) => {
    const clickable = e.target.closest("[data-action]");
    if (!clickable) return;
    const action = clickable.getAttribute("data-action");
    const caseId = clickable.getAttribute("data-case-id");
    if (action === "cn-zoom-in" || action === "cn-zoom-out") {
      e.preventDefault();
      setCaseNoteZoom(action === "cn-zoom-in" ? 1 : -1);
      return;
    }
    if (action === "close-casenote") {
      e.preventDefault();
      document.body.classList.remove("casenote-open");
      return;
    }
    if (action === "copy-citation" && caseId) {
      e.preventDefault();
      const caseObj = state.caseById.get(caseId);
      if (caseObj) copyToClipboardWithFeedback(buildStandardCitation(caseObj), clickable);
      return;
    }
    if (action === "copy-paragraph") {
      e.preventDefault();
      copyToClipboardWithFeedback(clickable.getAttribute("data-text") || "", clickable);
      return;
    }
    if (action === "casenote-more-before" || action === "casenote-more-after") {
      e.preventDefault();
      if (state.caseNote) {
        if (action === "casenote-more-before") state.caseNote.before += CASENOTE_STEP;
        else state.caseNote.after += CASENOTE_STEP;
      }
      renderCaseContextRail(state.activeCaseId);
      return;
    }
  });
  bindCaseContextActions(el.caseContextRail);
  bindCaseContextActions(el.caseContextRailMobile);

  el.pagination.addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-page]");
    if (!btn) return;

    const totalPages = state.serverMode
      ? (state.serverTotalPages || 1)
      : Math.ceil(state.currentOrderedCaseIds.length / PAGE_SIZE);
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

    // In server mode, re-fetch the requested page from API.  Preserve
    // default-view mode (and its sort=date_desc + 100-cap) across page
    // clicks so "next page" in the recent-cases view stays in that view.
    if (state.serverMode) {
      applyServerSearch(state.query, state.currentFilters, false, {
        sort: state.defaultView ? "date_desc" : null,
        defaultView: state.defaultView,
      });
      window.scrollTo({ top: 0, behavior: "smooth" });
      return;
    }

    renderResultsPage();
    updateResultsHeader();
    window.scrollTo({ top: 0, behavior: "smooth" });
  });

  // Accessibility panel events
  const a11yBtn = byId("accessibilityBtn");
  const a11yClose = byId("a11yCloseBtn");
  const a11yBackdrop = byId("a11yBackdrop");
  if (a11yBtn) a11yBtn.addEventListener("click", openAccessibilityPanel);
  if (a11yClose) a11yClose.addEventListener("click", closeAccessibilityPanel);
  if (a11yBackdrop) a11yBackdrop.addEventListener("click", closeAccessibilityPanel);

  const a11yControls = ["a11yTheme", "a11yFontSize", "a11yLineHeight", "a11yHighContrast", "a11yDyslexia", "a11yUnderlineLinks"];
  for (const id of a11yControls) {
    const ctrl = byId(id);
    if (ctrl) ctrl.addEventListener("input", onAccessibilityChange);
    if (ctrl) ctrl.addEventListener("change", onAccessibilityChange);
  }

  const a11yReset = byId("a11yResetBtn");
  if (a11yReset) a11yReset.addEventListener("click", () => {
    const defaults = { ...ACCESSIBILITY_DEFAULTS };
    defaults.theme = document.documentElement.getAttribute("data-theme") || "light";
    applyAccessibilitySettings(defaults);
    syncAccessibilityControls();
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      const a11yPanel = byId("accessibilityPanel");
      if (a11yPanel && !a11yPanel.hidden) {
        closeAccessibilityPanel();
        return;
      }
      if (state.classifierOpen) {
        closeClassifierPane();
        return;
      }

      if (document.body.classList.contains("dossier-open")) {
        closeDossier();
        return;
      }

      if (document.body.classList.contains("casenote-open")) {
        document.body.classList.remove("casenote-open");
        return;
      }
    }

    // Alt+A opens/closes accessibility panel
    if (e.altKey && (e.key === "a" || e.key === "A")) {
      e.preventDefault();
      const a11yPanel = byId("accessibilityPanel");
      if (a11yPanel && !a11yPanel.hidden) {
        closeAccessibilityPanel();
      } else {
        openAccessibilityPanel();
      }
      return;
    }

    if (e.key === "/" && !["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName)) {
      if (!el.searchInput.disabled) {
        e.preventDefault();
        el.searchInput.focus();
      }
    }
  });

  // Hamburger menu
  const hamburger = document.getElementById("navHamburger");
  if (hamburger) hamburger.addEventListener("click", () => {
    const links = document.querySelector(".nav-links");
    const expanded = hamburger.getAttribute("aria-expanded") === "true";
    hamburger.setAttribute("aria-expanded", !expanded);
    links?.classList.toggle("open");
  });

  // Back to top
  const backToTop = document.getElementById("backToTopBtn");
  if (backToTop) {
    window.addEventListener("scroll", () => {
      backToTop.hidden = window.scrollY < 400;
    }, { passive: true });
    backToTop.addEventListener("click", () => window.scrollTo({ top: 0, behavior: "smooth" }));
  }

}

function init() {
  cacheElements();
  loadCardModePreference();
  updateCardModeButton();
  initTheme();
  bindEvents();

  setSearchEnabled(false);
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
  renderBarList(el.analyticsDocTypes, [], (x) => x);
  renderWordCloud([]);

  // Render filter SHELL immediately so the panel structure is visible from the
  // first paint, instead of being empty until the facets API returns 1-2s
  // later. Real data fills in via renderFilters() after serverSearch.probe().
  renderFiltersSkeleton();

  // Probe server-side search API — this is the primary data source
  serverSearch.probe().then(async (available) => {
    if (available) {
      setSearchEnabled(true);

      // Fetch full stats from server for KPI bar
      try {
        const statsData = await serverSearch.getStats();
        const fmt = new Intl.NumberFormat("en-US");
        el.statTotalCases.textContent = fmt.format(statsData.total_cases || 0);
        el.statTotalParagraphs.textContent = fmt.format(statsData.total_paragraphs || 0);
        el.statTotalCountries.textContent = fmt.format(statsData.total_countries || 0);
        // Parse DD/MM/YYYY dates into readable range
        const parseDMY = (s) => { if (!s) return null; const p = s.split("/"); return p.length === 3 ? `${p[2]}-${p[1]}-${p[0]}` : s; };
        const df = parseDMY(statsData.date_from);
        const dt = parseDMY(statsData.date_to);
        if (df && dt) el.statDateRange.textContent = `${df} to ${dt}`;
      } catch (e) {
        console.warn("[Server Stats] Could not fetch stats:", e);
      }

      // Update data source panel
      setDatasetStatus("Connected to HUDOC Researcher API — full-text search across all judgments (English texts).");
      const badgeEl = document.getElementById("serverBadgeHeader");
      if (badgeEl) {
        badgeEl.textContent = `Connected`;
        badgeEl.style.cssText = "display:inline-block;background:#2ecc71;color:#fff;font-size:0.7rem;padding:1px 8px;border-radius:10px;margin-left:8px;vertical-align:middle;";
      }

      // NOTE: intentionally do NOT load the 50-row sample dataset here.
      //
      // Earlier versions of this code silently fetched SAMPLE_DATA_URL
      // "for local browse fallback", but activateDataset() calls
      // preprocessDataset() which REPLACES state.cases with whatever
      // rows it's handed — so loading the sample after a successful
      // server connection would overwrite the 18k+ cases the dashboard
      // had just connected to with only 50 rows, which the user would
      // see as "18000+ → 50" flicker on page load.  When the server
      // is available, all queries flow through serverSearch; there is
      // no in-memory dataset to "fall back to".  If the server later
      // becomes unavailable mid-session, the existing offline-reload
      // path (loadSampleBtn) handles it explicitly.

      // Fetch full facets from server and override local sample filters
      try {
        const facets = await serverSearch.getFacets();

        // Whole-corpus facet counts.  Cached as globalFacetCounts so the
        // rail can fall back to them whenever there is no active search
        // (see refreshRailCounts); facetCounts is the currently-shown set.
        state.globalFacetCounts = buildFacetCounts(facets);
        state.facetCounts = state.globalFacetCounts;

        // Build the stable filter option lists — the universe of values.
        // These never change; only the counts beside them do (per search).
        // Reverse map: DB section name → normalized key. Multiple DB values
        // may point at the same key (e.g. both "Facts Background" and
        // "Facts Proceedings" → "facts"), so expand the arrays.
        const DB_TO_NORM = {};
        for (const [norm, dbArr] of Object.entries(SECTION_DB_NAMES)) {
          for (const db of dbArr) DB_TO_NORM[db] = norm;
        }
        if (facets.sections) {
          // Dedupe: two raw DB values may collapse into the same normalized
          // key, which would otherwise render a duplicate filter checkbox.
          const normalized = facets.sections
            .map((f) => DB_TO_NORM[f.value] || f.value)
            .filter((s) => SECTION_LABELS[s]);
          state.sectionsInDataset = [...new Set(normalized)]
            .sort((a, b) => {
              const ai = SECTION_ORDER.indexOf(a);
              const bi = SECTION_ORDER.indexOf(b);
              if (ai !== -1 && bi !== -1) return ai - bi;
              if (ai !== -1) return -1;
              if (bi !== -1) return 1;
              return a.localeCompare(b);
            });
        }
        if (facets.states) {
          state.countries = facets.states
            .filter((f) => f.value)
            .map((f) => f.value)
            .sort((a, b) => a.localeCompare(b));
        }
        if (facets.articles) {
          state.articles = facets.articles
            .map((f) => f.value)
            .sort((a, b) => (a.length - b.length) || a.localeCompare(b));
        }
        if (facets.keywords) {
          // Preserve server order (descending by case count) — most-cited
          // HUDOC keywords come first, which is what a researcher wants.
          state.keywords = facets.keywords.map((f) => f.value).filter(Boolean);
        }
        if (facets.bodies) {
          state.bodies = facets.bodies
            .map((f) => f.value)
            .sort((a, b) => a.localeCompare(b));
        }
        if (facets.importance) {
          state.importanceLevels = sortImportanceLevels(
            facets.importance.filter((f) => f.value).map((f) => f.value)
          );
        }
        renderFilters();
        console.log("[Server Facets] Filters updated from server:", {
          sections: state.sectionsInDataset.length,
          countries: state.countries.length,
          articles: state.articles.length,
          bodies: state.bodies.length,
          importance: state.importanceLevels.length,
        });
      } catch (e) {
        console.warn("[Server Facets] Could not fetch facets:", e);
      }

      // Deep link: ?q= runs the query as soon as the server is ready —
      // same contract as semantic.html, so keyword searches are
      // shareable/bookmarkable.  Otherwise fall through to the default
      // view: the 100 most recent cases (date_desc), paginated across
      // 5 pages of PAGE_SIZE (empty query + no filters → applySearch()
      // routes through applyServerSearch with { defaultView: true }).
      const deepQ = new URLSearchParams(location.search).get("q");
      if (deepQ && deepQ.trim() && !el.searchInput.value.trim()) {
        el.searchInput.value = deepQ.trim();
      }
      try {
        applySearch(true);
      } catch (e) {
        console.warn("[Default View] Could not load recent cases:", e);
      }

    } else {
      // Server not available — fall back to sample dataset with file upload option
      setDatasetStatus("Server unavailable — using local sample dataset.");
      const sourceActions = document.getElementById("sourceActions");
      if (sourceActions) sourceActions.classList.remove("hidden");
      document.getElementById("loadSampleBtn")?.click();

      // Try to populate KPI from stats.json
      try {
        const r = await fetch("data/stats.json");
        if (r.ok) {
          const data = await r.json();
          if (data?.summary) {
            const s = data.summary;
            const fmt = new Intl.NumberFormat("en-US");
            if (el.statTotalCases.textContent === "-") el.statTotalCases.textContent = fmt.format(s.total_cases || 0);
            if (el.statTotalParagraphs.textContent === "-") el.statTotalParagraphs.textContent = fmt.format(s.total_paragraphs || 0);
            if (el.statTotalCountries.textContent === "-") el.statTotalCountries.textContent = fmt.format(s.unique_countries || 0);
            if (el.statDateRange.textContent === "-") el.statDateRange.textContent = s.date_range_label || "-";
          }
        }
      } catch (_) {}
    }
  });
}

init();

/* ── Concept-query nudge ─────────────────────────────────────────────────
   A long free-text query (4+ words, no phrase/operator syntax) usually
   describes a CONCEPT in the researcher's own words — the case where
   literal FTS is weakest and Semantic Search retrieves by meaning.
   Short 1–3-word lookups and operator/phrase queries are deliberate
   keyword searches, so no nudge there. */
function hideSemanticHint() {
  const h = byId("semanticHint");
  if (h) h.hidden = true;
}
function maybeShowSemanticHint(query, data) {
  const q = (query || "").trim();
  if (!q) return hideSemanticHint();
  if (/["“”:]|\bOR\b|\bNEAR\b/.test(q)) return hideSemanticHint();  // phrase / operator query
  if (q.split(/\s+/).length < 4) return hideSemanticHint();          // short = deliberate keyword lookup
  const hits = (data && (data.total_hits || (data.hits || []).length)) || 0;
  if (!hits) return hideSemanticHint();
  let h = byId("semanticHint");
  if (!h) {
    h = document.createElement("div");
    h.id = "semanticHint";
    h.className = "semantic-hint";
    el.resultsHeader?.insertAdjacentElement("afterend", h);
  }
  h.innerHTML = `Looking for the <em>concept</em> rather than the exact word? ` +
    `<a href="semantic.html?q=${encodeURIComponent(q)}">Try <strong>Semantic Search</strong> for “${escapeHtml(q)}” →</a>` +
    `<span class="semantic-hint-why">matches by legal substance — the Court may phrase it differently (e.g. “private life”)</span>`;
  h.hidden = false;
}
