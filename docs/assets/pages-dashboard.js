const PALETTE = [
  "#245ea8",
  "#d97a2b",
  "#3c8d5a",
  "#b03e45",
  "#6c5db5",
  "#4f7ca6",
  "#8c8c8c",
  "#b28a2f",
  "#3d95a8",
  "#8d4f78",
];

const fmtInt = new Intl.NumberFormat("en-US");

// One colour per outcome (Okabe–Ito, colour-blind safe), identical in every chart; legends and
// labels always name the outcome too. Keys read the outcome rows of stats.json.
const OUTCOME_SERIES = [
  { key: "v", label: "Violation only", color: "#D55E00" },
  { key: "both", label: "Violation and no violation", color: "#E69F00" },
  { key: "nv", label: "No violation", color: "#0072B2" },
  { key: "none", label: "No outcome tag", color: "#999999" },
];
const FORMATION_COLORS = { "Grand Chamber": "#AA4499", Chamber: "#009E73", Committee: "#56B4E9", Other: "#999999" };
const STATE_COLORS = ["#6a5acd", "#1a9e6e", "#a8326e"];
// Rates resting on fewer judgments than this are greyed or left out, and the page says so.
const MIN_RATE_N = 20;

// Outcome rows: [year, violation_only, non_violation_only, both, neither] and
// [state, total, violation_only, non_violation_only, both, neither, rate, settled].
const yearOutcome = (r) => ({ v: r[1], nv: r[2], both: r[3], none: r[4] });
const stateOutcome = (r) => ({ v: r[2], nv: r[3], both: r[4], none: r[5] });
const outcomeTotal = (o) => o.v + o.nv + o.both + o.none;
const withViolation = (o) => o.v + o.both;
const pct = (part, whole, digits = 0) => (whole ? `${(part / whole * 100).toFixed(digits)}%` : "–");
const rateWithN = (part, whole, digits = 0) => `${pct(part, whole, digits)} (n=${fmtInt.format(whole)})`;

function cssVar(name, fallback) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

// ── View state in the URL, so a view can be shared ──────────────────────────
// ?states=POL,TUR&topics=top10|<a>|<b>&formation=committee&articles=convention#stats-…
const pageParams = new URLSearchParams(location.search);
function setPageParam(key, value) {
  const params = new URLSearchParams(location.search);
  if (value) params.set(key, value); else params.delete(key);
  const query = params.toString().replace(/%2C/gi, ",").replace(/%7C/gi, "|");
  history.replaceState(history.state, "", `${location.pathname}${query ? `?${query}` : ""}${location.hash}`);
}

/** Buttons with aria-pressed acting as one toggle group. */
function bindToggle(buttons, attribute, onSelect) {
  const select = (value) => {
    buttons.forEach((b) => b.setAttribute("aria-pressed", String(b.dataset[attribute] === value)));
    onSelect(value);
  };
  buttons.forEach((b) => b.addEventListener("click", () => select(b.dataset[attribute])));
  return select;
}

// The catalog's final year is partial unless the cut-off is 31 December.
let partialYear = "";
const yearLabels = (years) => years.map((y) => (String(y) === partialYear ? `${y} (partial)` : String(y)));

/** A short label just past the end of each horizontal (stacked) bar. */
const barEndLabels = {
  id: "barEndLabels",
  afterDatasetsDraw(chart, _args, options) {
    if (!options?.text) return;
    const metas = chart.getSortedVisibleDatasetMetas();
    const { ctx } = chart;
    ctx.save();
    ctx.font = `11px ${Chart.defaults.font.family}`;
    ctx.fillStyle = cssVar("--ink-2", "#48464c");
    ctx.textBaseline = "middle";
    chart.data.labels.forEach((_, i) => {
      const bars = metas.map((meta) => meta.data[i]).filter(Boolean);
      if (bars.length) ctx.fillText(options.text(i), Math.max(...bars.map((bar) => bar.x)) + 6, bars[0].y);
    });
    ctx.restore();
  },
};

// Three events marked, sparingly, on the year charts (frac = point in the year).
const COURT_EVENTS = [
  { year: "1998", frac: 10 / 12, label: "Protocol No. 11", short: "P11" },
  { year: "2010", frac: 5 / 12, label: "Protocol No. 14", short: "P14" },
  { year: "2022", frac: 8.5 / 12, label: "Russia leaves", short: "RU" },
];
const eventLines = {
  id: "eventLines",
  afterDatasetsDraw(chart) {
    const scale = chart.scales.x;
    const labels = (chart.data.labels || []).map(String);
    if (!scale || labels.length < 2) return;
    const { ctx, chartArea: area } = chart;
    const step = scale.getPixelForValue(1) - scale.getPixelForValue(0);
    const ink = cssVar("--ink-2", "#48464c");
    ctx.save();
    ctx.font = `10px ${Chart.defaults.font.family}`;
    ctx.textBaseline = "top";
    COURT_EVENTS.forEach((event, k) => {
      const i = labels.findIndex((label) => label.startsWith(event.year));
      if (i < 0) return;
      const x = scale.getPixelForValue(i) + (event.frac - 0.5) * step;
      ctx.strokeStyle = ink;
      ctx.lineWidth = 1;
      ctx.setLineDash([3, 3]);
      ctx.beginPath(); ctx.moveTo(x, area.top); ctx.lineTo(x, area.bottom); ctx.stroke();
      const text = chart.width < 560 ? event.short : event.label;
      const width = ctx.measureText(text).width + 6;
      const left = x + width + 4 > area.right ? x - width - 2 : x + 2;
      const y = area.top + 2 + k * 14;
      ctx.fillStyle = cssVar("--bg-card", "#fffdf8");
      ctx.fillRect(left, y - 1, width, 13);
      ctx.fillStyle = ink;
      ctx.fillText(text, left + 3, y);
    });
    ctx.restore();
  },
};

function formatDateForMeta(raw) {
  const dt = new Date(raw);
  if (Number.isNaN(dt.getTime())) return raw || "-";
  return dt.toLocaleString("en-US", {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZoneName: "short",
  });
}

function truncateLabel(text, limit = 60) {
  const value = String(text || "");
  if (value.length <= limit) return value;
  return `${value.slice(0, limit - 1)}...`;
}

function citationDisplayLabel(raw) {
  const title = String(raw || "")
    .split(/\s*\[GC\]|,\s*(?:nos?\.|\u00a7|ECHR\b|Series A\b|Reports\b|(?:judgment|decision) of\b|\d{1,2}\s+[A-Z])|\s+(?:judgment|decision) of\b/i)[0]
    .trim();
  // Preserve document-stage qualifiers: a merits judgment and just
  // satisfaction judgment can share a case name without being the same item.
  const shorten = (text, limit) => text.length > limit ? text.slice(0, limit - 3) + "..." : text;
  const versus = title.lastIndexOf(" v. ");
  if (title.length > 48 && versus > 0) {
    const respondent = title.slice(versus);
    if (respondent.length < 36) return shorten(title.slice(0, versus), 48 - respondent.length) + respondent;
  }
  return shorten(title || String(raw || ""), 48);
}

function wrapCitationText(text, limit) {
  const words = String(text || "").split(/\s+/);
  const lines = [""];
  for (const word of words) {
    const last = lines.length - 1;
    if (lines[last] && lines[last].length + word.length + 1 > limit) lines.push(word);
    else lines[last] += (lines[last] ? " " : "") + word;
  }
  return lines;
}

function citationTooltipTitle(items) {
  return wrapCitationText(items[0]?.label, items[0]?.chart.width < 500 ? 38 : 75);
}

async function renderJudgmentCitations(scope) {
  const section = document.getElementById("stats-cited-judgments");
  if (!section) return;
  const coverageNote = document.getElementById("judgmentCitationCoverage");
  try {
    const response = await fetch("data/judgment-citations.json", { cache: "no-store" });
    if (!response.ok) throw new Error("Citation snapshot unavailable");
    const snapshot = await response.json();
    if (snapshot.schema_version !== "judgment-citations-v1" || snapshot.cutoff !== scope.cutoff ||
        snapshot.statistics_scope_sha256 !== scope.catalog_sha256 ||
        (scope.catalog_content_sha256 && snapshot.catalog_content_sha256 !== scope.catalog_content_sha256)) {
      throw new Error("Citation snapshot scope does not match statistics");
    }
    // Two kinds of evidence, never mixed silently: HUDOC's curated case-law lists, and (when the snapshot
    // has it) the application numbers HUDOC extracted from each judgment's text.
    const views = { curated: snapshot };
    if (snapshot.with_extracted_appno) views.extracted = { ...snapshot, ...snapshot.with_extracted_appno };
    // Shown first: the counts of Search's "Cited by", so that a judgment has one number on the whole site.
    if (snapshot.with_search_graph) views.search = { ...snapshot, ...snapshot.with_search_graph };
    let view = views.search || views.curated;
    let ranked = view.ranking || [];
    const quality = document.getElementById("judgmentCitationQuality");
    const evidenceSelect = document.getElementById("citationEvidence");
    function describe() {
      const c = view.coverage;
      const statuses = c.by_status || {};
      const lines = [];
      if (view === views.search) {
        coverageNote.textContent = `Counted as in Search: judgments citing it in their text or in HUDOC's metadata, and judgments HUDOC publishes only in French that cite it according to HUDOC's metadata. ${fmtInt.format(c.citation_pairs)} citation pairs in the corpus, plus ${fmtInt.format(c.french_only_pairs)} from French-only judgments. Snapshot: ${snapshot.cutoff}.`;
        lines.push(
          "These are the numbers shown under Cited by on every search result. They count judgments, not mentions: a judgment that refers to the case in ten paragraphs counts once.",
          "Citations by French-only judgments come from HUDOC's metadata alone, so they are minimums and carry no paragraph; the share is shown for each judgment.",
          "The two other choices of Evidence count HUDOC's metadata alone, for comparison.");
      } else if (view === views.curated) {
        coverageNote.textContent = `${fmtInt.format(c.judgments_with_metadata)} / ${fmtInt.format(c.judgments)} judgments have citation metadata; ${fmtInt.format(c.unique_edges)} unique resolved pairs. Snapshot: ${snapshot.cutoff}. Not a full-text ranking.`;
        lines.push(
          `Reference observations across both languages: ${fmtInt.format(c.reference_observations)}. These are source entries, not unique citation pairs.`,
          `Resolved: ${fmtInt.format(statuses.resolved || 0)}; ambiguous: ${fmtInt.format(statuses.ambiguous || 0)}; unresolved: ${fmtInt.format(statuses.unresolved || 0)}.`,
          `Excluded document types: ${fmtInt.format(statuses.excluded_document_type || 0)}; chronology conflicts: ${fmtInt.format(statuses.chronology_conflict || 0)}; self-references: ${fmtInt.format(statuses.self_reference || 0)}.`,
          `Identifier conflicts: ${fmtInt.format(statuses.identifier_conflict || 0)}; identity-review references: ${fmtInt.format(statuses.identity_review || 0)}. Neither contributes to the ranking.`,
          `Metadata versions with citations: ENG ${fmtInt.format(c.metadata_versions_by_language.ENG || 0)}, FRE ${fmtInt.format(c.metadata_versions_by_language.FRE || 0)}; union: ${fmtInt.format(c.judgments_with_metadata)} unique judgment identities.`);
        const identityCounts = {};
        for (const issue of c.identity_issues || []) identityCounts[issue.reason] = (identityCounts[issue.reason] || 0) + 1;
        lines.push(`Identity warnings: ${Object.entries(identityCounts).map(([key, value]) => `${key.replaceAll("_", " ")}: ${value}`).join("; ") || "none"}. Unpaired French identities are held for review, not counted again. Disagreeing application aliases are not used for secondary matches.`);
      } else {
        coverageNote.textContent = `${fmtInt.format(c.judgments_with_metadata)} / ${fmtInt.format(c.judgments)} judgments have citation metadata; ${fmtInt.format(c.unique_edges)} unique resolved pairs, ${fmtInt.format(c.edges_from_curated_list)} from the curated lists and ${fmtInt.format(c.edges_from_extracted_application)} from extracted application numbers (${fmtInt.format(c.edges_in_both)} in both). Snapshot: ${snapshot.cutoff}. HUDOC extracted the numbers from the full text; they carry no citation context.`;
        lines.push(
          `Application numbers HUDOC extracted from the full text: ${fmtInt.format(c.reference_observations)} across ${fmtInt.format(c.judgments_with_extracted_application_numbers)} judgments.`,
          `Resolved to one earlier judgment: ${fmtInt.format(statuses.resolved || 0)}; ambiguous (several judgments of the application): ${fmtInt.format(statuses.ambiguous || 0)}; no judgment in the catalog (for example decisions): ${fmtInt.format(statuses.unresolved || 0)}.`,
          `The judgment's own application numbers: ${fmtInt.format(statuses.self_reference || 0)}; only later judgments: ${fmtInt.format(statuses.chronology_conflict || 0)}. Neither contributes to the ranking.`,
          `Judgments with at least one resolved citation: ${fmtInt.format(c.judgments_with_resolved_citations)}. An extracted number can also come from a decision cited under the same application, so counts are approximate; against the text of English judgments about 96% of these pairs agree.`);
      }
      quality.replaceChildren(...lines.map((line) => {
        const p = document.createElement("p"); p.className = "citation-quality-line"; p.textContent = line; return p;
      }));
    }
    describe();
    if (evidenceSelect) {
      evidenceSelect.hidden = !views.extracted && !views.search;
      if (!views.search) evidenceSelect.querySelector('option[value="search"]')?.remove();
      evidenceSelect.value = views.search ? "search" : "curated";
    }
    const evidenceLabel = document.querySelector('label[for="citationEvidence"]');
    if (evidenceLabel) evidenceLabel.hidden = !views.extracted && !views.search;
    if (!ranked.length) return;
    const sayTopCited = () => {
      const [top, next] = ranked;
      document.getElementById("citationTakeaway").textContent = `${top.title} (${top.date.slice(0, 4)}) is the most cited judgment: ` +
        `${fmtInt.format(top.cited_by_count)} judgments cite it${next ? `, ahead of ${next.title} (${fmtInt.format(next.cited_by_count)})` : ""}.`;
    };
    sayTopCited();
    const select = document.getElementById("citedJudgmentSelect");
    function fillSelect() {
      select.replaceChildren();
      for (const row of ranked) {
        const option = document.createElement("option"); option.value = row.case_id;
        option.textContent = `${row.title} (${row.date}) - ${fmtInt.format(row.cited_by_count)}`;
        select.appendChild(option);
      }
    }
    fillSelect();
    select.disabled = false;
    function hudocLink(row) {
      const a = document.createElement("a"); a.href = `https://hudoc.echr.coe.int/eng?i=${encodeURIComponent(row.case_id)}`;
      a.target = "_blank"; a.rel = "noopener"; a.textContent = row.title; return a;
    }
    function csv(rows, filename) {
      if (window.EchrExport) window.EchrExport.triggerDownload(window.EchrExport.rowsToCsvBlob(rows), filename);
    }
    const rankingExport = document.getElementById("citationRankingExport");
    rankingExport.disabled = !window.EchrExport;
    rankingExport.addEventListener("click", () => {
      const extended = view === views.extracted;
      csv([
        ["HUDOC ID", "ECLI", "Judgment", "Date", "Unique citing judgments",
          ...(extended ? ["Citing via curated lists", "Citing via extracted application numbers"] : []), "Source", "Cutoff"],
        ...ranked.map((row) => [row.case_id, row.ecli || "", row.title, row.date, row.cited_by_count,
          ...(extended ? [row.cited_by_curated_list, row.cited_by_extracted_application] : []),
          view === views.search ? "As Search's Cited by: text and HUDOC metadata, plus French-only judgments (HUDOC metadata)"
            : extended ? "Resolved bilingual HUDOC metadata plus application numbers extracted by HUDOC" : "Resolved bilingual HUDOC metadata",
          snapshot.cutoff]),
      ], `echr-most-cited-judgments${extended ? "-with-extracted-application-numbers" : ""}-${snapshot.cutoff}.csv`);
    });
    let visible = 25;
    function citingRows() {
      return (view.citing_by_target[select.value] || []).map((id) => ({case_id: id, ...view.citing_judgments[id]}));
    }
    function renderList() {
      const rows = citingRows();
      const body = document.getElementById("citingJudgmentRows"); body.replaceChildren();
      for (const row of rows.slice(0, visible)) {
        const tr = document.createElement("tr"); const name = document.createElement("th"); name.scope = "row";
        name.appendChild(hudocLink(row)); const date = document.createElement("td"); date.textContent = row.date;
        tr.append(name, date); body.appendChild(tr);
      }
      document.getElementById("citingJudgmentsSummary").textContent = `View ${fmtInt.format(rows.length)} citing judgments, each counted once however often it refers to this one (${Math.min(visible, rows.length)} shown)`;
      document.getElementById("moreCitingJudgments").hidden = visible >= rows.length;
    }
    function selectJudgment() {
      visible = 25;
      const row = ranked.find((r) => r.case_id === select.value);
      const identity = document.getElementById("citedJudgmentIdentity");
      const split = view === views.extracted
        ? ` (${fmtInt.format(row.cited_by_curated_list)} via curated lists, ${fmtInt.format(row.cited_by_extracted_application)} via extracted application numbers)`
        : view === views.search && row.cited_by_french_only ? ` (${fmtInt.format(row.cited_by_french_only)} only in French)` : "";
      identity.replaceChildren(hudocLink(row), document.createTextNode(` · ${row.date} · ${row.ecli || row.case_id} · ${fmtInt.format(row.cited_by_count)} unique citing judgments${split}`));
      renderList();
    }
    select.addEventListener("change", selectJudgment);
    document.getElementById("moreCitingJudgments").addEventListener("click", () => { visible += 100; renderList(); });
    const citingExport = document.getElementById("citingJudgmentsExport"); citingExport.disabled = !window.EchrExport;
    citingExport.addEventListener("click", () => {
      const target = ranked.find((row) => row.case_id === select.value);
      csv([["Cited HUDOC ID", "Cited ECLI", "Citing HUDOC ID", "Citing ECLI", "Citing judgment", "Citing date"],
        ...citingRows().map((row) => [target.case_id, target.ecli || "", row.case_id, row.ecli || "", row.title, row.date])],
        `echr-citing-${select.value}${view === views.extracted ? "-with-extracted-application-numbers" : ""}-${snapshot.cutoff}.csv`);
    });
    const chartLabels = () => ranked.map((row) => `${row.title} | ${row.date} | ${row.case_id}`);
    const chart = createBarChart(document.getElementById("judgmentCitationsChart"),
      chartLabels(), ranked.map((row) => row.cited_by_count),
      { horizontal: true, colors: ["#4f83ad"] });
    if (chart) {
      chart.data.datasets[0].label = "Unique citing judgments";
      chart.options.scales.y.ticks = { font: { size: 11 }, callback(value) {
        const row = ranked[value]; const name = citationDisplayLabel(row.title);
        return [...(this.chart.width < 500 ? wrapCitationText(name, 22) : [name]), row.date];
      }};
      chart.options.plugins.tooltip = {callbacks: { title: citationTooltipTitle }};
      chart.options.onClick = (_, elements) => {
        if (!elements.length) return;
        select.value = ranked[elements[0].index].case_id; selectJudgment();
        document.getElementById("citingJudgmentsDetails").open = true;
      };
      chart.update("none");
    }
    if (evidenceSelect) evidenceSelect.addEventListener("change", () => {
      view = views[evidenceSelect.value] || views.curated;
      ranked = view.ranking || [];
      describe(); fillSelect(); sayTopCited();
      if (chart) {
        chart.data.labels = chartLabels();
        chart.data.datasets[0].data = ranked.map((row) => row.cited_by_count);
        chart.update("none");
      }
      selectJudgment();
    });
    selectJudgment();
  } catch (error) {
    section.dataset.keepEmptyView = "true";
    coverageNote.textContent = `${error.message}. No judgment-level citation ranking is shown; reference-entry analytics below remain available.`;
    section.querySelectorAll(".chart-controls, details, #citedJudgmentIdentity").forEach((el) => el.remove());
  }
}

function makeKpi(label, value, note = "") {
  if (value === "0") return "";
  return `
    <article class="kpi-card">
      <div class="kpi-label">${label}</div>
      <div class="kpi-value">${value}</div>
      ${note ? `<div class="kpi-note">${note}</div>` : ""}
    </article>
  `;
}

function createBarChart(ctx, labels, values, options = {}) {
  if (!ctx || !values.some((value) => Number(value) > 0)) return null;
  return new Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          data: values,
          backgroundColor: (options.colors || labels.map((_, i) => PALETTE[i % PALETTE.length])).map(
            (c) => (c.endsWith("CC") ? c : `${c}CC`)
          ),
          borderColor: options.colors || labels.map((_, i) => PALETTE[i % PALETTE.length]),
          borderWidth: 1,
          borderRadius: 6,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      indexAxis: options.horizontal ? "y" : "x",
      plugins: {
        legend: { display: false },
      },
      scales: {
        x: {
          beginAtZero: true,
          grid: { display: !options.horizontal },
        },
        y: {
          beginAtZero: true,
          grid: { display: options.horizontal ? false : true },
        },
      },
    },
  });
}

function articleLabel(article) {
  if (!article.startsWith("P")) return `Art. ${article}`;
  const [protocol, number] = article.split("-");
  return `${protocol}, Art. ${number}`;
}

const listNames = (names) => (names.length > 1 ? `${names.slice(0, -1).join(", ")} and ${names.at(-1)}` : names[0] || "");

/** Outcomes by Article: one chart of judgments with an outcome tag, the violation share (with n) at each bar's end. */
function renderArticleAnalytics(analytics) {
  const canvas = document.getElementById("articleViolationRateChart");
  const tagged = (analytics?.rows || []).filter((row) => row.with_outcome > 0);
  if (!canvas || !tagged.length) return;
  const rows = tagged.filter((row) => row.with_outcome >= MIN_RATE_N); // payload order is Convention order
  const hidden = tagged.length - rows.length;
  document.getElementById("articleHiddenNote").textContent = hidden
    ? `${hidden} Article${hidden === 1 ? "" : "s"} with fewer than ${MIN_RATE_N} such judgments ${hidden === 1 ? "is" : "are"} left out.` : "";
  const largest = rows.reduce((a, b) => (b.with_outcome > a.with_outcome ? b : a));
  const rated = rows.filter((row) => row.with_outcome >= 500).sort((a, b) => b.violation_share - a.violation_share);
  document.getElementById("articleTakeaway").textContent =
    `${articleLabel(largest.article)} has the most judgments with an outcome (n=${fmtInt.format(largest.with_outcome)}; ${pct(largest.with_violation, largest.with_outcome)} with a violation).` +
    (rated.length > 1 ? ` Among Articles with 500 or more, the violation share runs from ${rateWithN(rated.at(-1).with_violation, rated.at(-1).with_outcome)} under ${articleLabel(rated.at(-1).article)} to ${rateWithN(rated[0].with_violation, rated[0].with_outcome)} under ${articleLabel(rated[0].article)}.` : "");
  canvas.parentElement.style.height = `${rows.length * 26 + 90}px`;
  const buckets = [["violation_only", OUTCOME_SERIES[0]], ["mixed", OUTCOME_SERIES[1]], ["non_violation_only", OUTCOME_SERIES[2]]];
  let ordered = rows;
  const chart = new Chart(canvas, {
    type: "bar",
    data: { labels: [], datasets: buckets.map(([, { label, color }]) => ({ label, data: [], backgroundColor: color, borderWidth: 0, maxBarThickness: 20 })) },
    options: {
      responsive: true, maintainAspectRatio: false, indexAxis: "y",
      layout: { padding: { right: 92 } },
      plugins: {
        legend: { position: "bottom", labels: { boxWidth: 12, font: { size: 11 } } },
        barEndLabels: { text: (i) => `${fmtInt.format(ordered[i].with_outcome)} · ${pct(ordered[i].with_violation, ordered[i].with_outcome)}` },
        tooltip: { callbacks: {
          label(context) {
            const row = ordered[context.dataIndex];
            const key = buckets[context.datasetIndex][0];
            return `${context.dataset.label}: ${fmtInt.format(row[key])} (${pct(row[key], row.with_outcome, 1)})`;
          },
          footer(items) {
            const row = ordered[items[0].dataIndex];
            return `At least one violation: ${rateWithN(row.with_violation, row.with_outcome, 1)}`;
          },
        } },
      },
      scales: {
        x: { stacked: true, beginAtZero: true },
        y: { stacked: true, grid: { display: false }, ticks: { autoSkip: false, font: { size: 11 } } },
      },
    },
    plugins: [barEndLabels],
  });
  const table = document.getElementById("articleOutcomeRows");
  const draw = (order) => {
    ordered = order === "convention" ? rows : rows.slice().sort((a, b) => b.with_outcome - a.with_outcome);
    chart.data.labels = ordered.map((row) => articleLabel(row.article));
    chart.data.datasets.forEach((dataset, i) => { dataset.data = ordered.map((row) => row[buckets[i][0]]); });
    chart.update("none");
    table.replaceChildren(...ordered.map((row) => {
      const tr = document.createElement("tr");
      [articleLabel(row.article), pct(row.with_violation, row.with_outcome, 1),
        ...["with_outcome", "violation_only", "mixed", "non_violation_only", "without_outcome"].map((key) => fmtInt.format(row[key]))]
        .forEach((value, index) => {
          const cell = document.createElement(index === 0 ? "th" : "td");
          if (index === 0) cell.scope = "row";
          cell.textContent = value;
          tr.appendChild(cell);
        });
      return tr;
    }));
    setPageParam("articles", order === "convention" ? "convention" : "");
  };
  const select = bindToggle([...document.querySelectorAll("[data-article-sort]")], "articleSort", draw);
  select(pageParams.get("articles") === "convention" ? "convention" : "count");
}

function createDoughnutChart(ctx, labels, values, colors = []) {
  if (!ctx || !values.some((value) => Number(value) > 0)) return null;
  return new Chart(ctx, {
    type: "doughnut",
    data: {
      labels,
      datasets: [
        {
          data: values,
          // Fixed colours (outcomes, formations) are used exactly; the generic palette is softened.
          backgroundColor: colors.length ? colors : labels.map((_, i) => `${PALETTE[i % PALETTE.length]}CC`),
          borderColor: colors.length ? colors : labels.map((_, i) => PALETTE[i % PALETTE.length]),
          borderWidth: 1,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: "bottom" },
        tooltip: { callbacks: { label(context) {
          const sum = context.dataset.data.reduce((a, b) => a + Number(b || 0), 0);
          return `${context.label}: ${fmtInt.format(context.parsed)} (${pct(context.parsed, sum, 1)})`;
        } } },
      },
    },
  });
}

function createGroupedBarChart(ctx, labels, datasets, options = {}) {
  if (!ctx || !datasets.some((dataset) => dataset.data.some((value) => Number(value) > 0))) return null;
  const [category, value] = options.horizontal ? ["y", "x"] : ["x", "y"];
  return new Chart(ctx, {
    type: "bar",
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      indexAxis: category,
      plugins: {
        legend: { position: "bottom" },
      },
      scales: {
        [category]: { stacked: !!options.stacked, grid: { display: false } },
        [value]: { beginAtZero: true, stacked: !!options.stacked },
      },
    },
    plugins: options.plugins || [],
  });
}

function createMultiLineChart(ctx, labels, datasets) {
  if (!ctx || !datasets.some((dataset) => dataset.data.some((value) => Number(value) > 0))) return null;
  return new Chart(ctx, {
    type: "line",
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: "bottom" },
      },
      scales: {
        x: { grid: { display: false } },
        y: { beginAtZero: true },
      },
    },
  });
}

/** Outcomes by respondent State: every State, sticky header, frozen first column, sorted by clicking a column. */
function renderStateOutcomeTable(container, rows) {
  if (!container) return;
  if (!rows.length) {
    container.innerHTML = '<p class="state-outcome-empty">No state-level rows.</p>';
    return;
  }
  // The Court's own columns ("Violations by Article and by State"), as far as HUDOC metadata allow.
  const cols = [
    ["State", (r) => r[0]],
    ["Judgments", (r) => r[1]],
    ["≥ 1 violation", (r) => r[2] + r[4]],
    ["No violation", (r) => r[3]],
    ["Friendly settlement / struck out", (r) => r[7]],
    ["Other", (r) => r[5] - r[7]],
    ["Violation rate", (r) => (r[2] + r[4]) / r[1] * 100],
  ];
  const rateCol = cols.length - 1;
  let sortCol = 1, desc = true;
  const cell = (row, i) => (i === rateCol ? `${cols[i][1](row).toFixed(1)}%` : fmtInt.format(cols[i][1](row)));
  const draw = () => {
    const sorted = rows.slice().sort((a, b) => {
      const c = sortCol === 0 ? String(a[0]).localeCompare(String(b[0])) : cols[sortCol][1](a) - cols[sortCol][1](b);
      return desc ? -c : c;
    });
    container.innerHTML = `
      <div class="state-outcome-scroll" tabindex="0" role="region" aria-label="Outcomes by respondent State">
        <table class="state-outcome-table">
          <thead><tr>${cols.map(([label], i) => `
            <th scope="col" aria-sort="${i === sortCol ? (desc ? "descending" : "ascending") : "none"}">
              <button type="button" class="sort-btn" data-col="${i}">${label}<span aria-hidden="true">${i === sortCol ? (desc ? " ▾" : " ▴") : ""}</span></button>
            </th>`).join("")}</tr></thead>
          <tbody>${sorted.map((row) => {
            const few = row[1] < MIN_RATE_N;
            return `<tr${few ? ' class="few"' : ""}><th scope="row">${row[0]}</th>${cols.slice(1).map((_, j) =>
              `<td${j + 1 === rateCol && few ? ` title="Fewer than ${MIN_RATE_N} judgments"` : ""}>${cell(row, j + 1)}</td>`).join("")}</tr>`;
          }).join("")}</tbody>
        </table>
      </div>`;
  };
  container.addEventListener("click", (e) => {
    const btn = e.target.closest(".sort-btn");
    if (!btn) return;
    const col = Number(btn.dataset.col);
    if (col === sortCol) desc = !desc;
    else { sortCol = col; desc = col !== 0; }
    const scroller = container.querySelector(".state-outcome-scroll");
    const [left, top] = [scroller.scrollLeft, scroller.scrollTop];
    draw();
    const redrawn = container.querySelector(".state-outcome-scroll");
    redrawn.scrollLeft = left; redrawn.scrollTop = top;
    container.querySelector(`.sort-btn[data-col="${col}"]`).focus();
  });
  draw();
  const busiest = rows.reduce((a, b) => (b[1] > a[1] ? b : a));
  const rated = rows.filter((r) => r[1] >= MIN_RATE_N).sort((a, b) => cols[rateCol][1](b) - cols[rateCol][1](a));
  const rate = (r) => `${rateWithN(r[2] + r[4], r[1])} in ${r[0]}`;
  document.getElementById("stateTableTakeaway").textContent = `${busiest[0]} has the most judgments (${fmtInt.format(busiest[1])}).` +
    (rated.length > 1 ? ` Among the ${rated.length} States with ${MIN_RATE_N} or more, the violation rate runs from ${rate(rated.at(-1))} to ${rate(rated[0])}.` : "");
}

/** The 15 States with most judgments plus the rest together: count (bar) and violation rate (label) at once. */
function renderStateChart(rows, totalJudgments, topShare) {
  const canvas = document.getElementById("countriesChart");
  if (!canvas || !rows.length) return;
  const sorted = rows.slice().sort((a, b) => b[1] - a[1]);
  const rest = sorted.slice(15);
  const bars = sorted.slice(0, 15).map((r) => ({ label: r[0], ...stateOutcome(r) }));
  if (rest.length) {
    const sum = (key) => rest.reduce((total, r) => total + stateOutcome(r)[key], 0);
    bars.push({ label: `Other ${rest.length}`, title: `Other ${rest.length} States together`, v: sum("v"), nv: sum("nv"), both: sum("both"), none: sum("none") });
  }
  canvas.parentElement.style.height = `${bars.length * 28 + 90}px`;
  new Chart(canvas, {
    type: "bar",
    data: {
      labels: bars.map((b) => b.label),
      datasets: OUTCOME_SERIES.map(({ key, label, color }) => ({ label, data: bars.map((b) => b[key]), backgroundColor: color, borderWidth: 0, maxBarThickness: 20 })),
    },
    options: {
      responsive: true, maintainAspectRatio: false, indexAxis: "y",
      layout: { padding: { right: 92 } },
      plugins: {
        legend: { position: "bottom", labels: { boxWidth: 12, font: { size: 11 } } },
        barEndLabels: { text: (i) => `${fmtInt.format(outcomeTotal(bars[i]))} · ${pct(withViolation(bars[i]), outcomeTotal(bars[i]))}` },
        tooltip: { callbacks: {
          title: (items) => bars[items[0].dataIndex].title || items[0].label,
          label: (context) => `${context.dataset.label}: ${fmtInt.format(context.parsed.x)} (${pct(context.parsed.x, outcomeTotal(bars[context.dataIndex]), 1)})`,
          footer: (items) => `At least one violation: ${rateWithN(withViolation(bars[items[0].dataIndex]), outcomeTotal(bars[items[0].dataIndex]), 1)}`,
        } },
      },
      scales: {
        x: { stacked: true, beginAtZero: true },
        y: { stacked: true, grid: { display: false }, ticks: { autoSkip: false } },
      },
    },
    plugins: [barEndLabels],
  });
  const shown = bars.slice(0, 15).sort((a, b) => withViolation(b) / outcomeTotal(b) - withViolation(a) / outcomeTotal(a));
  const rate = (b) => `${b.label}, ${rateWithN(withViolation(b), outcomeTotal(b))}`;
  document.getElementById("stateChartTakeaway").textContent =
    (topShare?.states?.length ? `${listNames(topShare.states)} are the respondent States in ${pct(topShare.judgments, totalJudgments)} of all judgments (${fmtInt.format(topShare.judgments)} of ${fmtInt.format(totalJudgments)}). ` : "") +
    `Of the 15 shown, the violation rate is highest for ${rate(shown[0])}, and lowest for ${rate(shown.at(-1))}.`;
}

/** State profile: 1–3 States → judgments by year, Articles found violated, most frequent topics. */
function renderStateProfile(compare, topicsByState) {
  const profiles = compare.states || {};
  const names = Object.keys(profiles).sort((a, b) => profiles[b].total - profiles[a].total);
  const selects = [1, 2, 3].map((n) => document.getElementById(`compareState${n}`));
  if (!names.length || selects.some((sel) => !sel)) return;
  const options = names.map((name) => `<option value="${name}">${name} (${fmtInt.format(profiles[name].total)})</option>`).join("");
  selects.forEach((sel, i) => { sel.innerHTML = (i ? '<option value="">(none)</option>' : "") + options; });
  // ?states= takes ISO codes (POL,TUR) or names.
  const find = (token) => names.find((name) => profiles[name].code === token.toUpperCase() || name.toLowerCase() === token.toLowerCase());
  const fromUrl = [...new Set((pageParams.get("states") || "").split(",").map((t) => find(t.trim())).filter(Boolean))].slice(0, 3);
  const initial = fromUrl.length ? fromUrl : names.slice(0, 3);
  selects.forEach((sel, i) => { sel.value = initial[i] || ""; });

  const years = yearLabels(compare.years || []);
  const share = (count, state) => Math.round(count / profiles[state].total * 1000) / 10;
  const violationRate = (p) => {
    const text = rateWithN(p.outcomes.violation_only + p.outcomes.both, p.total);
    return p.total < MIN_RATE_N ? `<span class="few-rate" title="Fewer than ${MIN_RATE_N} judgments">${text}</span>` : text;
  };
  const metrics = [
    ["Judgments", (p) => fmtInt.format(p.total)],
    ["At least one violation", violationRate],
    ["No violation", (p) => fmtInt.format(p.outcomes.non_violation_only)],
    ["Friendly settlement / struck out", (p) => fmtInt.format(p.settled)],
    ["Other", (p) => fmtInt.format(p.outcomes.neither - p.settled)],
    ["Most often found violated", (p) => (p.articles[0] ? `${articleLabel(p.articles[0][0])} (${fmtInt.format(p.articles[0][1])})` : "–")],
  ];
  const charts = {};
  const horizontalShare = (chart, tooltipLabel) => {
    if (!chart) return;
    chart.options.scales.x.ticks = { callback: (v) => `${v}%` };
    chart.options.scales.y.ticks = { autoSkip: false, font: { size: 11 } };
    chart.options.plugins.tooltip = { callbacks: { label: tooltipLabel } };
    chart.update("none");
  };

  const render = () => {
    const selected = [...new Set(selects.map((sel) => sel.value).filter((v) => profiles[v]))];
    document.getElementById("compareSummaryTable").innerHTML = `<table class="compare-summary-table"><thead><tr><th scope="col">Metric</th>${selected
      .map((s, i) => `<th scope="col"><span class="state-swatch" style="background:${STATE_COLORS[i]}" aria-hidden="true"></span>${s}</th>`).join("")}</tr></thead><tbody>${metrics
      .map(([label, fn]) => `<tr><th scope="row">${label}</th>${selected.map((s) => `<td>${fn(profiles[s])}</td>`).join("")}</tr>`).join("")}</tbody></table>`;

    Object.values(charts).forEach((chart) => chart?.destroy());
    charts.trend = createMultiLineChart(document.getElementById("compareTrendChart"), years, selected.map((state, i) => ({
      label: state, data: profiles[state].cases_by_year, borderColor: STATE_COLORS[i], backgroundColor: STATE_COLORS[i],
      fill: false, tension: 0.2, borderWidth: 2, pointRadius: 0, pointHoverRadius: 4,
    })));

    const articleCounts = Object.fromEntries(selected.map((s) => [s, new Map(profiles[s].articles.map(([a, v, o]) => [a, [v, o]]))]));
    const articles = [...new Set(selected.flatMap((s) => profiles[s].articles.slice(0, 6).map(([a]) => a)))]
      .map((a) => [a, Math.max(...selected.map((s) => share((articleCounts[s].get(a) || [0])[0], s)))])
      .sort((x, y) => y[1] - x[1]).slice(0, 8).map(([a]) => a);
    charts.articles = createGroupedBarChart(document.getElementById("compareArticlesChart"), articles.map(articleLabel), selected.map((state, i) => ({
      label: state, data: articles.map((a) => share((articleCounts[state].get(a) || [0])[0], state)),
      backgroundColor: STATE_COLORS[i], borderWidth: 0, maxBarThickness: 14,
    })), { horizontal: true });
    horizontalShare(charts.articles, (context) => {
      const state = selected[context.datasetIndex];
      const [violations, tagged] = articleCounts[state].get(articles[context.dataIndex]) || [0, 0];
      return `${state}: ${fmtInt.format(violations)} of ${fmtInt.format(profiles[state].total)} judgments (${context.parsed.x}%); ` +
        `violation share under this Article ${rateWithN(violations, tagged)}`;
    });

    // Topics: each State's top ten are stored; a topic outside a State's top ten has no bar for it.
    const topicCounts = Object.fromEntries(selected.map((s) => [s, new Map(topicsByState[s] || [])]));
    const topics = [...new Set(selected.flatMap((s) => (topicsByState[s] || []).slice(0, 4).map(([t]) => t)))].slice(0, 8);
    charts.topics = createGroupedBarChart(document.getElementById("thesaurusCountryChart"), topics.map((t) => truncateLabel(t, 34)), selected.map((state, i) => ({
      label: state, data: topics.map((t) => (topicCounts[state].has(t) ? share(topicCounts[state].get(t), state) : null)),
      backgroundColor: STATE_COLORS[i], borderWidth: 0, maxBarThickness: 14,
    })), { horizontal: true });
    horizontalShare(charts.topics, (context) => {
      const state = selected[context.datasetIndex];
      return `${state}: ${fmtInt.format(topicCounts[state].get(topics[context.dataIndex]))} of ${fmtInt.format(profiles[state].total)} judgments (${context.parsed.x}%)`;
    });
    syncChartTheme();

    const rateOf = (s) => (profiles[s].outcomes.violation_only + profiles[s].outcomes.both) / profiles[s].total;
    const describe = (s) => `${s}, ${rateWithN(profiles[s].outcomes.violation_only + profiles[s].outcomes.both, profiles[s].total)}`;
    const byRate = selected.slice().sort((a, b) => rateOf(b) - rateOf(a));
    const top = profiles[selected[0]].articles[0];
    document.getElementById("compareTakeaway").textContent = selected.length > 1
      ? `Of ${listNames(selected)}, the violation rate is highest for ${describe(byRate[0])}, and lowest for ${describe(byRate.at(-1))}.`
      : `${selected[0]}: ${fmtInt.format(profiles[selected[0]].total)} judgments, ${pct(profiles[selected[0]].outcomes.violation_only + profiles[selected[0]].outcomes.both, profiles[selected[0]].total)} with at least one violation` +
        (top ? `; the Article most often found violated is ${articleLabel(top[0])}, in ${pct(top[1], profiles[selected[0]].total)} of its judgments.` : ".");
    return selected;
  };
  render();
  selects.forEach((sel) => sel.addEventListener("change", () => {
    setPageParam("states", render().map((s) => profiles[s].code || s).join(","));
  }));
}

function rowsOrEmpty(value) {
  return Array.isArray(value) ? value : [];
}

function syncChartTheme() {
  const style = getComputedStyle(document.documentElement);
  const ink = style.getPropertyValue("--ink-3").trim() || "#706d72";
  const rule = style.getPropertyValue("--rule-soft").trim() || "#e8e0d4";
  const strongInk = style.getPropertyValue("--ink").trim() || "#242328";
  Chart.defaults.color = ink;
  Object.values(Chart.instances).forEach((chart) => {
    chart.options.color = ink;
    for (const axis of Object.values(chart.options.scales || {})) {
      if (axis.ticks) axis.ticks.color = ink;
      if (axis.grid) axis.grid.color = rule;
    }
    if (chart.options.plugins?.legend?.labels) chart.options.plugins.legend.labels.color = ink;
    chart.data.datasets.forEach((dataset) => {
      if (dataset.inkLine) dataset.borderColor = dataset.backgroundColor = strongInk;
    });
    chart.update("none");
  });
}

/** Judgments by year, stacked by formation: the bar height is the year's total. */
function renderFormationTrend(rows, lastFullYear) {
  const names = ["Grand Chamber", "Chamber", "Committee"];
  const chart = createGroupedBarChart(document.getElementById("casesYearChart"), yearLabels(rows.map((r) => r[0])),
    names.map((label, i) => ({ label, data: rows.map((r) => r[i + 1]), backgroundColor: FORMATION_COLORS[label], borderWidth: 0 })),
    { stacked: true, plugins: [eventLines] });
  if (!chart) return;
  chart.options.interaction = { mode: "index", intersect: false };
  chart.options.plugins.tooltip = { callbacks: {
    footer: (items) => `Total: ${fmtInt.format(rows[items[0].dataIndex].slice(1).reduce((a, b) => a + b, 0))} judgments`,
  } };
  chart.update("none");
  const row = rows.find((r) => r[0] === lastFullYear);
  if (!row) return;
  const total = row[1] + row[2] + row[3];
  document.getElementById("formationTakeaway").textContent = `In ${lastFullYear}, Committees delivered ${fmtInt.format(row[3])} of the ${fmtInt.format(total)} judgments ` +
    `(${pct(row[3], total)}), Chambers ${fmtInt.format(row[2])} and the Grand Chamber ${fmtInt.format(row[1])}.`;
}

/** The rate line's latest value, written beside its last point. */
const rateEndLabel = {
  id: "rateEndLabel",
  afterDatasetsDraw(chart) {
    const index = chart.data.datasets.findIndex((dataset) => dataset.type === "line");
    if (index < 0 || !chart.isDatasetVisible(index)) return;
    const data = chart.data.datasets[index].data;
    let i = data.length - 1;
    while (i >= 0 && data[i] == null) i -= 1;
    const point = chart.getDatasetMeta(index).data[i];
    if (!point) return;
    const { ctx } = chart;
    const text = `${Math.round(data[i])}%`;
    ctx.save();
    ctx.font = `bold 11px ${Chart.defaults.font.family}`;
    const width = ctx.measureText(text).width + 6;
    ctx.fillStyle = cssVar("--bg-card", "#fffdf8");
    ctx.fillRect(point.x - width - 4, point.y - 17, width, 14);
    ctx.fillStyle = cssVar("--ink", "#242328");
    ctx.textBaseline = "bottom";
    ctx.fillText(text, point.x - width - 1, point.y - 4);
    ctx.restore();
  },
};

/** Outcome shares by year (100% bars) with the violation rate as a line, for all judgments or one formation. */
function renderOutcomeTrend(series, lastFullYear) {
  const canvas = document.getElementById("outcomesYearChart");
  const all = rowsOrEmpty(series.outcomes_by_year);
  const byFormation = series.outcomes_by_year_formation || {};
  if (!canvas || !all.length) return;
  // outcomes_by_year_formation rows share the years (and order) of outcomes_by_year.
  const parts = { chamber: ["Grand Chamber", "Chamber"], committee: ["Committee"] };
  const rowsFor = (formation) => (parts[formation] && byFormation.Committee
    ? all.map((row, i) => [row[0], ...[1, 2, 3, 4].map((j) => parts[formation].reduce((sum, name) => sum + byFormation[name][i][j], 0))])
    : all);
  const yearRate = (formation) => {
    const row = rowsFor(formation).find((r) => r[0] === lastFullYear);
    return row ? [withViolation(yearOutcome(row)), outcomeTotal(yearOutcome(row))] : [0, 0];
  };
  const [allV, allN] = yearRate("all"), [coV, coN] = yearRate("committee"), [chV, chN] = yearRate("chamber");
  if (allN) {
    document.getElementById("outcomeYearTakeaway").textContent = `In ${lastFullYear}, ${pct(allV, allN)} of judgments found at least one violation (n=${fmtInt.format(allN)})` +
      (coN ? `: ${pct(coV, coN)} of Committee judgments (n=${fmtInt.format(coN)}) against ${pct(chV, chN)} of Chamber and Grand Chamber judgments (n=${fmtInt.format(chN)}).` : ".");
  }
  let chart = null;
  const draw = (formation) => {
    const rows = rowsFor(formation);
    const outcomes = rows.map(yearOutcome);
    const totals = outcomes.map(outcomeTotal);
    const enough = totals.map((n) => n >= MIN_RATE_N);
    const share = (part, i) => (totals[i] ? Math.round(part / totals[i] * 1000) / 10 : null);
    const datasets = OUTCOME_SERIES.map(({ key, label, color }) => ({
      label, stack: "outcomes", legendColor: color, data: outcomes.map((o, i) => share(o[key], i)),
      backgroundColor: enough.map((ok) => (ok ? color : `${color}55`)), borderWidth: 0, barPercentage: 1, categoryPercentage: 0.9,
    }));
    datasets.push({
      type: "line", label: "At least one violation", stack: "rate", inkLine: true, order: -1, // drawn above the bars
      data: outcomes.map((o, i) => (enough[i] ? share(withViolation(o), i) : null)),
      borderColor: cssVar("--ink", "#242328"), backgroundColor: cssVar("--ink", "#242328"),
      borderWidth: 2, pointRadius: 0, pointHoverRadius: 4, tension: 0,
    });
    if (chart) chart.destroy();
    chart = new Chart(canvas, {
      type: "bar",
      data: { labels: yearLabels(rows.map((r) => r[0])), datasets },
      options: {
        responsive: true, maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          // Faded (small-n) years must not fade the legend: it takes the full outcome colour.
          legend: { position: "bottom", labels: { boxWidth: 12, font: { size: 11 }, generateLabels: (c) => Chart.defaults.plugins.legend.labels
            .generateLabels(c).map((item) => ({ ...item, fillStyle: c.data.datasets[item.datasetIndex].legendColor || item.fillStyle })) } },
          tooltip: { callbacks: {
            title: (items) => `${items[0].label} · n=${fmtInt.format(totals[items[0].dataIndex])} judgments`,
            label: (context) => (context.dataset.type === "line"
              ? `At least one violation: ${context.parsed.y}%`
              : `${context.dataset.label}: ${context.parsed.y}% (${fmtInt.format(outcomes[context.dataIndex][OUTCOME_SERIES[context.datasetIndex].key])})`),
            footer: (items) => (enough[items[0].dataIndex] ? "" : `Fewer than ${MIN_RATE_N} judgments: no rate shown`),
          } },
        },
        scales: {
          x: { stacked: true, grid: { display: false } },
          y: { stacked: true, min: 0, max: 100, ticks: { callback: (v) => `${v}%` } },
        },
      },
      plugins: [eventLines, rateEndLabel],
    });
    syncChartTheme();
    setPageParam("formation", formation === "all" ? "" : formation);
  };
  const select = bindToggle([...document.querySelectorAll("[data-formation]")], "formation", draw);
  select(["chamber", "committee"].includes(pageParams.get("formation")) ? pageParams.get("formation") : "all");
}

/** Topic trends: top 5 (default), top 10 or up to 10 chosen; more than five lines are grey until one is picked out. */
function renderTopicTrends(thesaurus) {
  const TREND_COLORS = ["#245ea8", "#b03e45", "#3c8d5a", "#d97a2b", "#6c5db5", "#1f8a8a", "#a3612a", "#8d4f78", "#55708f", "#7a8b2f"];
  const termTrends = thesaurus.term_trends || null;
  const trendLabels = thesaurus.terms_by_year_labels || [];
  const termsByYear = rowsOrEmpty(thesaurus.terms_by_year);
  const trendYears = termTrends ? termTrends.years : termsByYear.map((d) => d[0]);
  const trendSeries = termTrends ? termTrends.series
    : Object.fromEntries(trendLabels.map((t, i) => [t, termsByYear.map((d) => d[i + 1] || 0)]));
  const canvas = document.getElementById("thesaurusTrendsChart");
  const controls = document.getElementById("topicControls");
  const picker = document.getElementById("topicPicker");
  const input = document.getElementById("topicInput");
  const chips = document.getElementById("topicChips");
  if (!canvas || !controls || !trendYears.length || !trendLabels.length) return;
  let chart = null;
  let customTopics = [];
  let mode = "5";
  const grey = () => `${cssVar("--ink-4", "#969197")}77`;
  const draw = (topics) => {
    const shown = topics.filter((t) => trendSeries[t]);
    const many = shown.length > 5;
    if (chart) chart.destroy();
    chart = createMultiLineChart(canvas, yearLabels(trendYears), shown.map((t, i) => ({
      label: truncateLabel(t, 40),
      data: trendSeries[t],
      topicColor: TREND_COLORS[i % TREND_COLORS.length],
      borderColor: many ? grey() : TREND_COLORS[i % TREND_COLORS.length],
      backgroundColor: TREND_COLORS[i % TREND_COLORS.length],
      borderWidth: many ? 1.5 : 2, fill: false, tension: 0.2, pointRadius: many ? 0 : 2, pointHoverRadius: 4,
    })));
    let peak = null;
    shown.forEach((t) => trendSeries[t].forEach((n, i) => { if (!peak || n > peak.n) peak = { t, n, year: trendYears[i] }; }));
    document.getElementById("trendTakeaway").textContent = peak
      ? `Of the topics shown, “${peak.t}” reached the highest yearly count: ${fmtInt.format(peak.n)} judgments in ${peak.year}.` : "";
    if (!chart || !many) return;
    let current = -1;
    const highlight = (index) => {
      if (index === current) return;
      current = index;
      chart.data.datasets.forEach((dataset, j) => {
        dataset.borderColor = j === index ? dataset.topicColor : grey();
        dataset.borderWidth = j === index ? 3 : 1.5;
      });
      chart.update("none");
    };
    const legend = chart.options.plugins.legend;
    legend.labels = { ...legend.labels, generateLabels: (c) => Chart.defaults.plugins.legend.labels.generateLabels(c)
      .map((item) => ({ ...item, fillStyle: c.data.datasets[item.datasetIndex].topicColor, strokeStyle: c.data.datasets[item.datasetIndex].topicColor })) };
    legend.onHover = (_, item) => highlight(item.datasetIndex);
    legend.onLeave = () => highlight(-1);
    legend.onClick = (_, item) => highlight(item.datasetIndex);
    chart.options.interaction = { mode: "nearest", intersect: false };
    chart.options.onHover = (_, elements) => { if (elements.length) highlight(elements[0].datasetIndex); };
    chart.update("none");
  };
  const writeUrl = () => setPageParam("topics", mode === "custom" ? customTopics.join("|") : mode === "10" ? "top10" : "");
  const paintChips = () => {
    chips.innerHTML = customTopics.map((t, i) => `<span class="topic-chip" style="border-color:${TREND_COLORS[i]}">${t
      .replace(/</g, "&lt;")}<button type="button" data-remove="${i}" aria-label="Remove ${t.replace(/"/g, "&quot;")}">×</button></span>`).join("");
    input.disabled = customTopics.length >= 10;
    input.placeholder = customTopics.length >= 10 ? "Ten topics chosen" : "Type a topic, e.g. Article 8 or detention…";
  };
  const showMode = (next, focus = true) => {
    mode = next;
    controls.querySelectorAll("[data-topics]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.topics === mode)));
    picker.hidden = mode !== "custom";
    if (mode === "custom") {
      if (!customTopics.length) customTopics = trendLabels.slice(0, 3);
      paintChips();
      draw(customTopics);
      if (focus) input.focus();
    } else {
      draw(trendLabels.slice(0, Number(mode)));
    }
    syncChartTheme();
    writeUrl();
  };
  document.getElementById("topicOptions").innerHTML = Object.keys(trendSeries).map((t) => `<option value="${t.replace(/"/g, "&quot;")}"></option>`).join("");
  controls.addEventListener("click", (e) => {
    const button = e.target.closest("[data-topics]");
    if (button) return showMode(button.dataset.topics);
    const rm = e.target.closest("[data-remove]");
    if (rm) { customTopics.splice(Number(rm.dataset.remove), 1); paintChips(); draw(customTopics); syncChartTheme(); writeUrl(); }
  });
  const addTopic = () => {
    const t = input.value.trim();
    if (!trendSeries[t] || customTopics.includes(t) || customTopics.length >= 10) return;
    customTopics.push(t);
    input.value = "";
    paintChips();
    draw(customTopics);
    syncChartTheme();
    writeUrl();
  };
  input.addEventListener("input", addTopic);   // picking a suggestion fills the exact name
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); addTopic(); } });
  // ?topics=top10, or ?topics=<topic>|<topic>|… for your own choice.
  const param = pageParams.get("topics") || "";
  const chosen = [...new Set(param.split("|").filter((t) => trendSeries[t]))].slice(0, 10);
  if (param === "top10") showMode("10", false);
  else if (chosen.length) { customTopics = chosen; showMode("custom", false); }
  else showMode("5", false);
}

function renderCoverage(data) {
  const fields = data.quality?.field_completeness || {};
  const labels = {respondent_state: "Respondent state", ecli: "ECLI identity", article_no: "Convention articles",
    conclusion: "Conclusion", originating_body: "Judicial collection", importance: "Importance classification",
    hudoc_kpthesaurus: "Thesaurus topics", strasbourg_caselaw: "HUDOC citation metadata",
    strasbourg_caselaw_any_language: "HUDOC citation metadata, English or French version",
    extracted_application_numbers: "Application numbers HUDOC extracted from the text",
    separate_opinion: "Separate-opinion flag", rules_of_court: "Rules of Court"};
  // Rows for fields a snapshot does not carry (older snapshots) are left out, not shown as 0%.
  const rows = Object.entries(labels).filter(([key]) => key in fields || data.quality?.field_counts?.[key] != null).map(([key, label]) => [label, Number(fields[key] || 0),
    data.quality?.field_counts?.[key] ?? Math.round(Number(fields[key] || 0) * data.summary.total_cases)]);
  const table = document.createElement("table");
  table.className = "coverage-table";
  const head = table.createTHead().insertRow();
  ["Metadata field", "Populated records", "Coverage"].forEach((label) => {
    const th = document.createElement("th"); th.scope = "col"; th.textContent = label; head.appendChild(th);
  });
  const body = table.createTBody();
  rows.forEach(([label, fraction, count]) => {
    const row = body.insertRow();
    [label, fmtInt.format(count), (fraction * 100).toFixed(2) + "%"]
      .forEach((value) => { row.insertCell().textContent = value; });
  });
  document.getElementById("coverageTable").replaceChildren(table);
  const languages = data.text_coverage?.by_language || {};
  const languageRows = [["Confirmed English", languages.ENG || 0], ["Confirmed French", languages.FRE || 0],
    ["Production language not recorded", languages.Unknown || 0]].filter((row) => row[1] > 0);
  createBarChart(document.getElementById("textLanguageChart"),
    languageRows.map((row) => row[0]), languageRows.map((row) => row[1]),
    {horizontal: true, colors: ["#395d7f", "#43705a", "#969197"]});
}

function pruneEmptyCharts() {
  document.querySelectorAll(".stats-main canvas").forEach((canvas) => {
    if (Chart.getChart(canvas) || canvas.dataset.keepEmptyView === "true") return;
    const wrapper = canvas.closest(".chart-container, .chart-canvas-wrap");
    const heading = wrapper?.previousElementSibling;
    if (heading?.classList.contains("chart-section-subtitle")) heading.remove();
    wrapper?.remove();
  });
  document.querySelectorAll(".stats-main .chart-row").forEach((row) => {
    if (!row.querySelector("canvas")) row.remove();
  });
  document.querySelectorAll(".stats-main .chart-section").forEach((section) => {
    if (section.querySelector("canvas, table, .kpi-card") || section.dataset.keepEmptyView === "true") return;
    section.remove();
  });
  document.querySelectorAll(".sidebar-link").forEach((link) => {
    if (!document.getElementById(link.dataset.target)) link.remove();
  });
  document.querySelectorAll(".sidebar-category").forEach((group) => {
    if (!group.querySelector(".sidebar-link")) group.remove();
  });
  document.getElementById("statsMain").setAttribute("aria-busy", "false");
}

async function loadDashboard() {
  const res = await fetch("data/stats.json", { cache: "no-store" });
  if (!res.ok) throw new Error(`Failed to load dashboard data (${res.status})`);
  const data = await res.json();
  Chart.defaults.font.family = getComputedStyle(document.documentElement).getPropertyValue("--font-mono").trim() || "Georgia";
  Chart.defaults.color = getComputedStyle(document.documentElement).getPropertyValue("--ink-3").trim() || "#706d72";

  const s = data.summary || {};
  const series = data.series || {};
  const rankings = data.rankings || {};
  const scope = data.scope || {};
  const texts = data.text_coverage || {};
  const thesaurus = data.thesaurus_analytics || {};

  // Provenance for the export filenames, the CSV source line, the PNG footer and the Cite dialog.
  // Read from the payload rather than scraped back out of #metaGenerated's
  // formatted text, which would break the moment that formatting changes.
  window.EchrStatsMeta = {
    generated_at: data.generated_at,
    cutoff: scope.cutoff,
    source_file: data.source_file,
    schema_version: data.schema_version,
    parser_version: data.parser_version,
  };

  document.getElementById("metaSource").textContent = "Verified HUDOC catalog + read-only text inventories";
  document.getElementById("metaGenerated").textContent = "Built " + formatDateForMeta(data.generated_at);

  // Some figures may have been refreshed from the live DB after the snapshot
  // was built (P66 does this for the section counts and corpus totals, which
  // the Phase 2 Procedure/Circumstances split invalidated). Say so, rather
  // than letting the build date above imply the whole page is that old.
  const pr = data.partial_refresh;
  const prEl = document.getElementById("metaPartialRefresh");
  if (pr && prEl) {
    const fields = (pr.refreshed || []).length;
    prEl.textContent = `${fields} figure${fields === 1 ? "" : "s"} refreshed from the live corpus since that build — section counts and corpus totals. Yearly series and citation analytics are from the snapshot.`;
    prEl.hidden = false;
  }

  const total = Number(s.total_cases || 0);
  const withText = Number(s.cases_with_text || 0);
  const violationCount = Number(s.outcome_violation_only || 0) + Number(s.outcome_both || 0);
  const casesByYear = rowsOrEmpty(series.cases_by_year);
  const cutoff = scope.cutoff || "";
  partialYear = cutoff && !cutoff.endsWith("-12-31") ? cutoff.slice(0, 4) : "";
  const lastYear = cutoff.slice(0, 4) || String(casesByYear.at(-1)?.[0] || "");
  const lastFullYear = partialYear ? String(Number(lastYear) - 1) : lastYear;

  // ── 1 · At a glance ──────────────────────────────────────────────────
  const perYear = new Map(casesByYear);
  const latest = perYear.get(lastFullYear);
  const previous = perYear.get(String(Number(lastFullYear) - 1));
  const change = latest && previous
    ? `${lastFullYear}: ${fmtInt.format(latest)} judgments, ${latest >= previous ? "+" : "−"}${Math.abs((latest / previous - 1) * 100).toFixed(0)}% on ${Number(lastFullYear) - 1}`
    : "No decisions or press releases";
  document.getElementById("kpiGrid").innerHTML = [
    makeKpi("Judgments", fmtInt.format(total), change),
    makeKpi("Respondent States", fmtInt.format(s.unique_countries || 0), "A judgment against several States counts for each"),
    makeKpi("At least one violation", total ? pct(violationCount, total, 1) : "Unavailable", `${fmtInt.format(violationCount)} of ${fmtInt.format(total)} judgments`),
    makeKpi("Committee judgments", pct(s.committee_cases || 0, total), `${fmtInt.format(s.committee_cases || 0)} · Chamber ${fmtInt.format(s.chamber_cases || 0)} · Grand Chamber ${fmtInt.format(s.grand_chamber_cases || 0)}`),
  ].join("");
  if (cutoff) {
    const cutoffDate = new Date(`${cutoff}T00:00:00Z`).toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" });
    document.getElementById("howCountDate").textContent = `Snapshot: judgments delivered up to ${cutoffDate}.`;
  }
  document.getElementById("scopeCutoff").textContent = "Catalog cut-off: " + (cutoff || "Unavailable") + " · " + (s.date_range_label || "");
  const caveat = document.getElementById("scopeCaveat");
  caveat.textContent = (scope.note || "") + " " + (scope.translation_title_warnings?.length || 0) + " translation-title records remain in the literal catalog count.";

  // ── 2 · Respondent States ────────────────────────────────────────────
  const stateRows = rowsOrEmpty(rankings.state_outcomes_all);
  renderStateOutcomeTable(document.getElementById("stateOutcomeTable"), stateRows);
  renderStateChart(stateRows, total, rankings.top_states_share);
  renderStateProfile(data.cross_tabs?.compare || {}, thesaurus.top_terms_by_country || {});

  // ── 3 · Convention Articles ──────────────────────────────────────────
  renderArticleAnalytics(data.article_analytics);

  // ── 4 · Over time ────────────────────────────────────────────────────
  renderFormationTrend(rowsOrEmpty(series.chambers_by_year), lastFullYear);
  renderOutcomeTrend(series, lastFullYear);

  // ── 5 · Topics ───────────────────────────────────────────────────────
  const topTerms = rowsOrEmpty(thesaurus.top_terms);
  if (topTerms.length) {
    const ttData = topTerms.slice(0, 25);
    createBarChart(
      document.getElementById("thesaurusTopChart"),
      ttData.map((d) => truncateLabel(d[0], 50)),
      ttData.map((d) => d[1]),
      { horizontal: true, colors: ["#6c5db5"] }
    );
    const withTopics = Number(thesaurus.cases_with_thesaurus || 0);
    document.getElementById("topicTakeaway").textContent = `“${topTerms[0][0]}” is the most frequent topic: ${fmtInt.format(topTerms[0][1])} judgments` +
      (withTopics ? `, ${pct(topTerms[0][1], withTopics)} of the ${fmtInt.format(withTopics)} with HUDOC topics.` : ".");
  }
  renderTopicTrends(thesaurus);

  // ── 6 · Citations ────────────────────────────────────────────────────
  await renderJudgmentCitations(scope);

  // ── 7 · Procedure ────────────────────────────────────────────────────
  const chamberBreakdown = rowsOrEmpty(series.chamber_breakdown).filter((d) => d[1] > 0);
  createDoughnutChart(
    document.getElementById("chamberChart"),
    chamberBreakdown.map((d) => d[0]),
    chamberBreakdown.map((d) => d[1]),
    chamberBreakdown.map((d) => FORMATION_COLORS[d[0]] || FORMATION_COLORS.Other)
  );

  const importanceDistribution = rowsOrEmpty(rankings.importance_distribution);
  createBarChart(
    document.getElementById("importanceChart"),
    importanceDistribution.map((d) => d[0]),
    importanceDistribution.map((d) => d[1]),
    { colors: ["#6c5db5", "#245ea8", "#d97a2b"] }
  );

  const outcomeTotals = { v: s.outcome_violation_only || 0, nv: s.outcome_non_violation_only || 0, both: s.outcome_both || 0, none: s.outcome_neither || 0 };
  createDoughnutChart(
    document.getElementById("outcomesChart"),
    OUTCOME_SERIES.map((o) => o.label),
    OUTCOME_SERIES.map((o) => outcomeTotals[o.key]),
    OUTCOME_SERIES.map((o) => o.color)
  );

  const proceduralVsSubstantiveByYear = rowsOrEmpty(series.procedural_vs_substantive_by_year);
  if (proceduralVsSubstantiveByYear.length) {
    createGroupedBarChart(
      document.getElementById("proceduralSubstantiveChart"),
      proceduralVsSubstantiveByYear.map((d) => d[0]),
      [
        {
          label: "Procedural aspect",
          data: proceduralVsSubstantiveByYear.map((d) => d[1]),
          backgroundColor: "#245ea8CC",
          borderColor: "#245ea8",
          borderWidth: 1,
          borderRadius: 5,
        },
        {
          label: "Substantive aspect",
          data: proceduralVsSubstantiveByYear.map((d) => d[2]),
          backgroundColor: "#d97a2bCC",
          borderColor: "#d97a2b",
          borderWidth: 1,
          borderRadius: 5,
        },
      ]
    );
  } else {
    createDoughnutChart(
      document.getElementById("proceduralSubstantiveChart"),
      ["Procedural aspect", "Substantive aspect"],
      [s.procedural_aspect_cases || 0, s.substantive_aspect_cases || 0],
      ["#245ea8", "#d97a2b"]
    );
  }

  const separateShareByBody = rowsOrEmpty(series.separate_opinion_share_by_body);
  createBarChart(
    document.getElementById("separateByBodyChart"),
    separateShareByBody.map((d) => `${truncateLabel(d[0], 26)} (n=${fmtInt.format(d[2])})`),
    separateShareByBody.map((d) => d[1]),
    { horizontal: true, colors: ["#b03e45"] }
  );
  const grandChamberOpinions = separateShareByBody.find((d) => d[0] === "Grand Chamber");
  document.getElementById("typesTakeaway").textContent = `Committees delivered ${pct(s.committee_cases || 0, total)} of all judgments, Chambers ${pct(s.chamber_cases || 0, total)} ` +
    `and the Grand Chamber ${pct(s.grand_chamber_cases || 0, total, 1)}` +
    (grandChamberOpinions ? `; ${pct(grandChamberOpinions[3], grandChamberOpinions[2])} of Grand Chamber judgments carry a separate opinion (n=${fmtInt.format(grandChamberOpinions[2])}).` : ".");

  const inadmissibilityGroundsTop = rowsOrEmpty(rankings.inadmissibility_grounds_top);
  if (inadmissibilityGroundsTop.length) {
    const igData = inadmissibilityGroundsTop.slice(0, 12);
    createBarChart(
      document.getElementById("inadmissibilityGroundsChart"),
      igData.map((d) => truncateLabel(d[0], 45)),
      igData.map((d) => d[1]),
      { horizontal: true, colors: ["#6478b4"] }
    );
  }
  const unspecified = (inadmissibilityGroundsTop.find((d) => d[0] === "Other / unspecified") || [0, 0])[1];
  document.getElementById("inadmissibilityTakeaway").textContent = `${fmtInt.format(s.inadmissible_cases || 0)} judgments (${pct(s.inadmissible_cases || 0, total, 1)}) ` +
    `declare part of an application inadmissible and ${fmtInt.format(s.struck_out_cases || 0)} (${pct(s.struck_out_cases || 0, total, 1)}) strike part of it out` +
    (unspecified ? `; in ${fmtInt.format(unspecified)} of the ${fmtInt.format(s.inadmissible_cases || 0)} the conclusion names no specific ground.` : ".");

  // ── 8 · About the data ───────────────────────────────────────────────
  const sections = rowsOrEmpty(rankings.sections);
  createBarChart(
    document.getElementById("sectionsChart"),
    sections.map((d) => d[0]),
    sections.map((d) => d[1]),
    { horizontal: true }
  );
  const sectionRows = sections.reduce((sum, d) => sum + d[1], 0);
  if (sections.length > 1) {
    document.getElementById("paragraphTakeaway").textContent = `${sections[0][0]} rows are the largest part of the ${fmtInt.format(sectionRows)} text rows ` +
      `(${pct(sections[0][1], sectionRows)}), followed by ${sections[1][0]} (${pct(sections[1][1], sectionRows)}).`;
  }

  renderCoverage(data);
  const sourceLanguages = texts.by_language || {};
  const sourceOrigins = texts.by_origin || {};
  const knownLanguages = [["English", sourceLanguages.ENG], ["French", sourceLanguages.FRE]]
    .filter((row) => row[1] > 0).map(([label, count]) => fmtInt.format(count) + " " + label).join(", ") || "none recorded";
  document.getElementById("textCoverageSummary").textContent =
    fmtInt.format(withText) + " / " + fmtInt.format(total) + " judgment records have inventoried text: " +
    fmtInt.format(s.total_paragraphs || 0) + " text rows, including table and header rows. " +
    "Confirmed source language: " + knownLanguages + "; " + fmtInt.format(sourceLanguages.Unknown || 0) +
    " not recorded. " + fmtInt.format(sourceOrigins["Local source bundle"] || 0) + " local bundles are staged, not yet in live Search.";

  // Legacy charts whose canvases are no longer on the page (createBarChart returns null for them).
  const bodiesTop = rowsOrEmpty(rankings.originating_bodies_top);
  const keywordsTop = rowsOrEmpty(rankings.keywords_top);

  createBarChart(
    document.getElementById("bodiesChart"),
    bodiesTop.map((d) => d[0]),
    bodiesTop.map((d) => d[1]),
    { horizontal: true, colors: ["#4f7ca6"] }
  );

  createBarChart(
    document.getElementById("keywordsChart"),
    keywordsTop.slice(0, 20).map((d) => truncateLabel(d[0], 45)),
    keywordsTop.slice(0, 20).map((d) => d[1]),
    { horizontal: true, colors: ["#b28a2f"] }
  );

  // ── Citation Network Analytics ──────────────────────────────────────────
  const citNet = data.citation_network || {};
  const citSummary = citNet.summary || {};

  // — Landmark Cases —
  const landmarkCases = citNet.landmark_cases || [];
  const landmarkKpiEl = document.getElementById("landmarkKpis");
  if (landmarkKpiEl && citSummary.total_nodes) {
    landmarkKpiEl.innerHTML = [
      makeKpi("Network Nodes", fmtInt.format(citSummary.total_nodes), "cases in graph"),
      makeKpi("Directed Edges", fmtInt.format(citSummary.total_edges), "citation links"),
      makeKpi("Top Landmark", landmarkCases.length ? landmarkCases[0].title.replace("CASE OF ", "") : "-",
        landmarkCases.length ? `${fmtInt.format(landmarkCases[0].cited_by)} citations` : ""),
      makeKpi("Avg Forward Cites", citSummary.avg_forward_citations || "-", `median ${citSummary.median_forward || "-"}`),
    ].join("");
  }

  if (landmarkCases.length) {
    const lcData = landmarkCases.slice(0, 25);
    createBarChart(
      document.getElementById("landmarkCasesChart"),
      lcData.map((d) => truncateLabel(d.title.replace("CASE OF ", ""), 45)),
      lcData.map((d) => d.cited_by),
      { horizontal: true, colors: ["#245ea8"] }
    );

    // Landmark table
    const ltEl = document.getElementById("landmarkTable");
    if (ltEl) {
      const hdr = "<tr><th>#</th><th>Case</th><th>Year</th><th>State</th><th>Article</th><th>Cited By</th><th>Cites</th></tr>";
      const rows = landmarkCases.map((c, i) =>
        `<tr><td>${i + 1}</td><td>${c.title.replace("CASE OF ", "")}</td><td>${c.year}</td><td>${c.state}</td><td>${c.article || "-"}</td><td>${fmtInt.format(c.cited_by)}</td><td>${c.cites}</td></tr>`
      ).join("");
      ltEl.innerHTML = `<table class="compare-summary-table"><thead>${hdr}</thead><tbody>${rows}</tbody></table>`;
    }
  }

  // — Citation Distribution —
  const inDegreeHist = citNet.in_degree_histogram || [];
  const citDistKpiEl = document.getElementById("citDistKpis");
  if (citDistKpiEl && citSummary.gini_coefficient != null) {
    citDistKpiEl.innerHTML = [
      makeKpi("Gini Coefficient", citSummary.gini_coefficient.toFixed(4), "0 = equal, 1 = max concentration"),
      makeKpi("Top 5% → Citations", `${citSummary.pct_cases_for_50pct_citations}%`, "of cases hold 50% of citations"),
      makeKpi("Top 18% → Citations", `${citSummary.pct_cases_for_80pct_citations}%`, "of cases hold 80% of citations"),
      makeKpi("Max In-Degree", fmtInt.format(citSummary.max_backward), "citations to single case"),
    ].join("");
  }

  if (inDegreeHist.length) {
    createBarChart(
      document.getElementById("citationDistChart"),
      inDegreeHist.map((d) => d[0] + " citations"),
      inDegreeHist.map((d) => d[1]),
      { colors: ["#6c5db5"] }
    );
  }

  // — Citation Age —
  const citAgeHist = citNet.citation_age_histogram || [];
  const citsByDecade = citNet.citations_by_decade || [];
  const citAgeKpiEl = document.getElementById("citAgeKpis");
  if (citAgeKpiEl && citSummary.mean_citation_age_years != null) {
    citAgeKpiEl.innerHTML = [
      makeKpi("Mean Citation Age", `${citSummary.mean_citation_age_years} yr`, "gap between citing & cited"),
      makeKpi("Median Citation Age", `${citSummary.median_citation_age_years} yr`),
      makeKpi("Self-Citation Rate", `${citSummary.self_citation_rate_overall}%`, "same-state citations"),
    ].join("");
  }

  if (citAgeHist.length) {
    createBarChart(
      document.getElementById("citationAgeChart"),
      citAgeHist.map((d) => d[0]),
      citAgeHist.map((d) => d[1]),
      { colors: ["#3d95a8"] }
    );
  }

  if (citsByDecade.length) {
    // citations_by_decade: [decade, cases, avg_fwd, avg_bwd, total_fwd, total_bwd]
    createGroupedBarChart(
      document.getElementById("citationDecadeChart"),
      citsByDecade.map((d) => d[0]),
      [
        {
          label: "Avg forward citations",
          data: citsByDecade.map((d) => d[2]),
          backgroundColor: "#245ea8CC",
          borderColor: "#245ea8",
          borderWidth: 1,
          borderRadius: 5,
        },
        {
          label: "Avg backward citations",
          data: citsByDecade.map((d) => d[3]),
          backgroundColor: "#b03e45CC",
          borderColor: "#b03e45",
          borderWidth: 1,
          borderRadius: 5,
        },
      ]
    );
  }

  // — Cross-Article Heatmap —
  const heatmap = citNet.cross_article_heatmap || {};
  const heatmapCtx = document.getElementById("citationHeatmapChart");
  if (heatmapCtx && heatmap.articles && heatmap.matrix) {
    const articles = heatmap.articles.map((a) => `Art. ${a}`);
    const matrix = heatmap.matrix;
    // Flatten to find max for color scaling
    const allVals = matrix.flat().filter((v) => v > 0);
    const maxVal = Math.max(...allVals, 1);

    // Build bubble-style scatter data
    const scatterData = [];
    for (let r = 0; r < matrix.length; r++) {
      for (let c = 0; c < matrix[r].length; c++) {
        if (matrix[r][c] > 0) {
          scatterData.push({ x: c, y: r, v: matrix[r][c] });
        }
      }
    }

    new Chart(heatmapCtx, {
      type: "bubble",
      data: {
        datasets: [{
          label: "Cross-article citations",
          data: scatterData.map((d) => ({
            x: d.x,
            y: d.y,
            r: Math.max(3, Math.sqrt(d.v / maxVal) * 28),
            // Carry the raw citation count. `r` is a bubble radius derived from
            // it, so without this the CSV export would emit radii; recovering v
            // by inverting the sqrt would be lossy. Chart.js's bubble parser
            // reads x/y/r and leaves the rest of the object untouched.
            v: d.v,
          })),
          backgroundColor: scatterData.map((d) => {
            const intensity = Math.min(d.v / maxVal, 1);
            const r = Math.round(36 + (180 - 36) * (1 - intensity));
            const g = Math.round(94 + (180 - 94) * (1 - intensity));
            const b = Math.round(168 + (180 - 168) * (1 - intensity));
            return `rgba(${r},${g},${b},0.8)`;
          }),
          borderColor: "#24508899",
          borderWidth: 1,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        layout: { padding: { left: 10, right: 20, top: 0, bottom: 10 } },
        scales: {
          x: {
            type: "linear",
            min: 0,
            max: articles.length - 1,
            position: "bottom",
            ticks: {
              stepSize: 1,
              autoSkip: false,
              callback: (val) => articles[Math.round(val)] || "",
              font: { size: 11, weight: "bold" },
              maxRotation: 45,
              minRotation: 45,
            },
            title: { display: true, text: "Cited article (target)", font: { size: 13, weight: "600" }, padding: { top: 6 } },
            grid: { color: "#e0e0e0", drawTicks: true },
          },
          y: {
            type: "linear",
            min: 0,
            max: articles.length - 1,
            ticks: {
              stepSize: 1,
              autoSkip: false,
              callback: (val) => articles[Math.round(val)] || "",
              font: { size: 11, weight: "bold" },
            },
            title: { display: true, text: "Citing article (source)", font: { size: 13, weight: "600" }, padding: { bottom: 6 } },
            reverse: true,
            grid: { color: "#e0e0e0", drawTicks: true },
          },
        },
        plugins: {
          legend: { display: false },
          title: {
            display: true,
            text: "Bubble size = citation volume between article pairs  •  Darker = more citations",
            font: { size: 12, weight: "normal", style: "italic" },
            padding: { bottom: 16 },
            color: "#666",
          },
          tooltip: {
            callbacks: {
              title: () => "",
              label: (ctx) => {
                const idx = ctx.dataIndex;
                const d = scatterData[idx];
                const pct = ((d.v / citSummary.total_edges) * 100).toFixed(1);
                return [
                  `${articles[d.y]} → ${articles[d.x]}`,
                  `${fmtInt.format(d.v)} citations (${pct}% of all edges)`,
                  d.x === d.y ? "⬤ Same-article (diagonal)" : "◉ Cross-article",
                ];
              },
            },
          },
        },
      },
    });
  }

  // — Cross-State Influence —
  const crossStateCited = citNet.cross_state_most_cited || [];
  if (crossStateCited.length) {
    createBarChart(
      document.getElementById("crossStateCitedChart"),
      crossStateCited.map((d) => d[0]),
      crossStateCited.map((d) => d[1]),
      { horizontal: true, colors: ["#245ea8"] }
    );
  }

  const selfCitRates = citNet.self_citation_rates || [];
  if (selfCitRates.length) {
    // self_citation_rates: [state, rate%, self_cites, total_cites]
    const scData = selfCitRates.slice(0, 15);
    createBarChart(
      document.getElementById("selfCitationChart"),
      scData.map((d) => d[0]),
      scData.map((d) => d[1]),
      { horizontal: true, colors: ["#d97a2b"] }
    );
  }

  // — PageRank & Betweenness —
  const prRanking = citNet.pagerank_ranking || [];
  if (prRanking.length) {
    createBarChart(
      document.getElementById("pagerankChart"),
      prRanking.map((d) => truncateLabel(d.title.replace("CASE OF ", ""), 35)),
      prRanking.map((d) => d.pagerank),
      { horizontal: true, colors: ["#3c8d5a"] }
    );
  }

  const bwRanking = citNet.betweenness_ranking || [];
  if (bwRanking.length) {
    createBarChart(
      document.getElementById("betweennessChart"),
      bwRanking.map((d) => truncateLabel(d.title.replace("CASE OF ", ""), 35)),
      bwRanking.map((d) => d.betweenness),
      { horizontal: true, colors: ["#8d4f78"] }
    );
  }

  // PageRank comparison table
  const prTableEl = document.getElementById("pagerankTable");
  if (prTableEl && prRanking.length) {
    const hdr = "<tr><th>#</th><th>Case</th><th>Year</th><th>State</th><th>PageRank</th><th>Cited By</th><th>Citation Rank</th></tr>";
    const rows = prRanking.map((c, i) =>
      `<tr><td>${i + 1}</td><td>${c.title.replace("CASE OF ", "")}</td><td>${c.year}</td><td>${c.state}</td><td>${c.pagerank.toLocaleString()}</td><td>${fmtInt.format(c.cited_by)}</td><td>#${c.rank_by_citations}</td></tr>`
    ).join("");
    prTableEl.innerHTML = `<details><summary style="cursor:pointer;font-weight:600;margin-bottom:8px;">PageRank vs Citation Rank — Full Table (click to expand)</summary><table class="compare-summary-table"><thead>${hdr}</thead><tbody>${rows}</tbody></table></details>`;
  }

  pruneEmptyCharts();
  syncChartTheme();
  new MutationObserver(syncChartTheme).observe(document.documentElement,
    {attributes: true, attributeFilter: ["data-theme"]});

  // Build TOC
  const tocList = document.getElementById("tocList");
  const tocToggle = document.getElementById("tocToggle");
  if (tocList) {
    document.querySelectorAll(".chart-title").forEach((h3, i) => {
      const id = "chart-sec-" + i;
      h3.closest(".chart-container, article")?.setAttribute("id", id);
      const li = document.createElement("li");
      li.innerHTML = '<a href="#' + id + '">' + h3.textContent + '</a>';
      tocList.appendChild(li);
    });
  }
  if (tocToggle) tocToggle.addEventListener("click", () => tocList?.classList.toggle("open"));
}

loadDashboard()
  .then(scrollToHashIfAny)
  .catch((err) => {
    console.error(err);
    const main = document.getElementById("statsMain");
    main.setAttribute("aria-busy", "false");
    const error = document.createElement("p");
    error.className = "chart-caveat"; error.setAttribute("role", "alert");
    error.textContent = "Statistics could not be loaded. Reload this page to retry. " + err.message;
    main.prepend(error);
  });

/**
 * Re-scroll to an incoming #stats-… anchor once the charts exist.
 *
 * The browser performs its native hash jump at parse time, when every canvas
 * still has zero height, so the landing position is wrong by however tall the
 * charts above it turn out to be. `copySectionLink()` has been handing out
 * these URLs from 17 sections, so they were already broken in the wild.
 * behavior:"auto" — this is a correction, not a second animation.
 */
// Sections merged in the October 2026 redesign: old shared links land on their successor.
const SECTION_ALIASES = {
  "stats-chamber-trend": "stats-cases-year",
  "stats-violation-rate-year": "stats-outcomes-year",
  "stats-article-counts": "stats-article-rates",
  "stats-country-rates": "stats-country-cases",
  "stats-citations-country": "stats-country-compare",
  "stats-thesaurus-country": "stats-country-compare",
  "stats-admissibility-overview": "stats-inadmissibility",
};

function scrollToHashIfAny() {
  if (!location.hash) return;
  let id = decodeURIComponent(location.hash.slice(1));
  if (SECTION_ALIASES[id]) {
    id = SECTION_ALIASES[id];
    history.replaceState(history.state, "", `#${id}`);
  }
  const target = document.getElementById(id);
  if (!target) return;
  target.scrollIntoView({ behavior: "auto", block: "start" });
  // Move the highlight too. The markup ships `.active` on the first link, so
  // without this an incoming deep link scrolls to the right place while the
  // sidebar still points at "Key Statistics".
  document
    .querySelectorAll(".sidebar-link")
    .forEach((l) => l.classList.toggle("active", l.dataset.target === id));
}

// ── Stats Sidebar Navigation (Phase 3) ──────────────────────────────────
(function initSidebarNav() {
  const links = () => document.querySelectorAll(".sidebar-link");

  /**
   * Suppresses scroll-spy while a click-driven smooth scroll is in flight.
   *
   * The observer band is `-20% 0px -70% 0px` — a strip 10% of the viewport
   * tall. A smooth scroll drags every intervening section through it, and each
   * one steals `.active` from the link the user actually clicked. Worse, a
   * short section at the very bottom (stats-coverage) can never enter the strip
   * at all, so without this its highlight would never stick.
   */
  let navLock = false;
  let navLockTimer = null;
  let idleTimer = null;

  function releaseNavLock() {
    navLock = false;
    clearTimeout(navLockTimer);
    clearTimeout(idleTimer);
    window.removeEventListener("scroll", onNavScroll);
  }

  function onNavScroll() {
    // Idle detection: the lock lifts ~120 ms after scrolling actually stops.
    clearTimeout(idleTimer);
    idleTimer = setTimeout(releaseNavLock, 120);
  }

  function lockNav() {
    navLock = true;
    clearTimeout(navLockTimer);
    clearTimeout(idleTimer);
    window.addEventListener("scroll", onNavScroll, { passive: true });
    // Hard ceiling. `scrollend` support is still uneven, and a lock that fails
    // to release would freeze scroll-spy for the rest of the session — so the
    // debounce above is the real mechanism and this is the backstop.
    navLockTimer = setTimeout(releaseNavLock, 1000);
  }

  function setActive(id) {
    links().forEach((l) => l.classList.toggle("active", l.dataset.target === id));
  }

  function goTo(id, { push }) {
    const section = document.getElementById(id);
    if (!section) return;
    lockNav();
    section.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
    setActive(id);
    const hash = "#" + id;
    // Repeated clicks on the same entry must not stack duplicate history
    // entries, or Back becomes a no-op the user has to press several times.
    if (location.hash !== hash) history.pushState({ statsSection: id }, "", hash);
    else history.replaceState({ statsSection: id }, "", hash);
  }

  links().forEach((link) => {
    link.addEventListener("click", (e) => {
      // Keep preventDefault: no `scroll-behavior: smooth` exists anywhere in
      // the stylesheets, so handing this to the browser would downgrade the
      // smooth scroll to an instant jump. The href is still a real anchor, so
      // middle-click, "copy link address" and no-JS all work.
      e.preventDefault();
      goTo(link.dataset.target, { push: true });
    });
  });

  window.addEventListener("popstate", () => {
    const id = (location.hash || "").slice(1);
    if (!id) return;
    const section = document.getElementById(decodeURIComponent(id));
    if (!section) return;
    setActive(decodeURIComponent(id));
    section.scrollIntoView({ behavior: "auto", block: "start" });
  });

  // Scroll-spy: highlight sidebar item when its section enters the viewport.
  // Presentational only — it never touches the URL. The address bar means
  // "where you navigated", not "what happens to be under the cursor"; writing
  // it here would fight Back and spray entries during ordinary scrolling.
  const chartSections = document.querySelectorAll(".chart-section");
  if (chartSections.length && "IntersectionObserver" in window) {
    const observer = new IntersectionObserver(
      (entries) => {
        if (navLock) return;
        entries.forEach((entry) => {
          if (entry.isIntersecting) setActive(entry.target.id);
        });
      },
      { rootMargin: "-20% 0px -70% 0px", threshold: 0 }
    );
    chartSections.forEach((s) => observer.observe(s));
  }
})();
