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
    const ranked = snapshot.ranking || [];
    const c = snapshot.coverage;
    const statuses = c.by_status || {};
    coverageNote.textContent = `${fmtInt.format(c.judgments_with_metadata)} / ${fmtInt.format(c.judgments)} judgments have citation metadata; ${fmtInt.format(c.unique_edges)} unique resolved pairs. Snapshot: ${snapshot.cutoff}. Not a full-text ranking.`;
    const quality = document.getElementById("judgmentCitationQuality");
    const qualityLines = [
      `Reference observations across both languages: ${fmtInt.format(c.reference_observations)}. These are source entries, not unique citation pairs.`,
      `Resolved: ${fmtInt.format(statuses.resolved || 0)}; ambiguous: ${fmtInt.format(statuses.ambiguous || 0)}; unresolved: ${fmtInt.format(statuses.unresolved || 0)}.`,
      `Excluded document types: ${fmtInt.format(statuses.excluded_document_type || 0)}; chronology conflicts: ${fmtInt.format(statuses.chronology_conflict || 0)}; self-references: ${fmtInt.format(statuses.self_reference || 0)}.`,
      `Identifier conflicts: ${fmtInt.format(statuses.identifier_conflict || 0)}; identity-review references: ${fmtInt.format(statuses.identity_review || 0)}. Neither contributes to the ranking.`,
      `Metadata versions with citations: ENG ${fmtInt.format(c.metadata_versions_by_language.ENG || 0)}, FRE ${fmtInt.format(c.metadata_versions_by_language.FRE || 0)}; union: ${fmtInt.format(c.judgments_with_metadata)} unique judgment identities.`,
    ];
    const identityCounts = {};
    for (const issue of c.identity_issues || []) identityCounts[issue.reason] = (identityCounts[issue.reason] || 0) + 1;
    qualityLines.push(`Identity warnings: ${Object.entries(identityCounts).map(([key, value]) => `${key.replaceAll("_", " ")}: ${value}`).join("; ") || "none"}. Unpaired French identities are held for review, not counted again. Disagreeing application aliases are not used for secondary matches.`);
    quality.replaceChildren(...qualityLines.map((line) => {
      const p = document.createElement("p"); p.className = "citation-quality-line"; p.textContent = line; return p;
    }));
    if (!ranked.length) return;
    const select = document.getElementById("citedJudgmentSelect");
    for (const row of ranked) {
      const option = document.createElement("option"); option.value = row.case_id;
      option.textContent = `${row.title} (${row.date}) - ${fmtInt.format(row.cited_by_count)}`;
      select.appendChild(option);
    }
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
    rankingExport.addEventListener("click", () => csv([
      ["HUDOC ID", "ECLI", "Judgment", "Date", "Unique citing judgments", "Source", "Cutoff"],
      ...ranked.map((row) => [row.case_id, row.ecli || "", row.title, row.date, row.cited_by_count, "Resolved bilingual HUDOC metadata", snapshot.cutoff]),
    ], `echr-most-cited-judgments-${snapshot.cutoff}.csv`));
    let visible = 25;
    function citingRows() {
      return (snapshot.citing_by_target[select.value] || []).map((id) => ({case_id: id, ...snapshot.citing_judgments[id]}));
    }
    function renderList() {
      const rows = citingRows();
      const body = document.getElementById("citingJudgmentRows"); body.replaceChildren();
      for (const row of rows.slice(0, visible)) {
        const tr = document.createElement("tr"); const name = document.createElement("th"); name.scope = "row";
        name.appendChild(hudocLink(row)); const date = document.createElement("td"); date.textContent = row.date;
        tr.append(name, date); body.appendChild(tr);
      }
      document.getElementById("citingJudgmentsSummary").textContent = `View ${fmtInt.format(rows.length)} unique citing judgments (${Math.min(visible, rows.length)} shown)`;
      document.getElementById("moreCitingJudgments").hidden = visible >= rows.length;
    }
    function selectJudgment() {
      visible = 25;
      const row = ranked.find((r) => r.case_id === select.value);
      const identity = document.getElementById("citedJudgmentIdentity");
      identity.replaceChildren(hudocLink(row), document.createTextNode(` · ${row.date} · ${row.ecli || row.case_id} · ${fmtInt.format(row.cited_by_count)} unique citing judgments`));
      renderList();
    }
    select.addEventListener("change", selectJudgment);
    document.getElementById("moreCitingJudgments").addEventListener("click", () => { visible += 100; renderList(); });
    const citingExport = document.getElementById("citingJudgmentsExport"); citingExport.disabled = !window.EchrExport;
    citingExport.addEventListener("click", () => {
      const target = ranked.find((row) => row.case_id === select.value);
      csv([["Cited HUDOC ID", "Cited ECLI", "Citing HUDOC ID", "Citing ECLI", "Citing judgment", "Citing date"],
        ...citingRows().map((row) => [target.case_id, target.ecli || "", row.case_id, row.ecli || "", row.title, row.date])],
        `echr-citing-${select.value}-${snapshot.cutoff}.csv`);
    });
    const chart = createBarChart(document.getElementById("judgmentCitationsChart"),
      ranked.map((row) => `${row.title} | ${row.date} | ${row.case_id}`), ranked.map((row) => row.cited_by_count),
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

function selectArticleRows(rows, minimum, order) {
  const selected = rows.filter((row) => row.with_outcome >= minimum && row.with_outcome > 0);
  return selected.sort((a, b) => {
    if (order === "article") return 0; // Payload is in Convention / Protocol article order.
    const rate = (b.violation_share - a.violation_share) * (order === "lowest" ? -1 : 1);
    if (order !== "volume" && rate !== 0) return rate;
    return b.with_outcome - a.with_outcome || a.article.localeCompare(b.article, "en", { numeric: true });
  });
}

function createArticleOutcomeChart(canvas, rows, percentages) {
  if (!canvas || !rows.length) return null;
  const buckets = [
    ["Violation only", "violation_only", "#a53643"],
    ["Mixed: both outcomes", "mixed", "#b78025"],
    ["Non-violation only", "non_violation_only", "#3b7497"],
  ];
  return new Chart(canvas, {
    type: "bar",
    data: {
      labels: rows.map((row) => articleLabel(row.article) + (percentages ? ` (n=${fmtInt.format(row.with_outcome)})` : "")),
      datasets: buckets.map(([label, key, color]) => ({
        label: label + (percentages ? " (%)" : ""),
        data: rows.map((row) => percentages ? row[key] / row.with_outcome * 100 : row[key]),
        backgroundColor: color, borderWidth: 0, maxBarThickness: 24,
      })),
    },
    options: {
      responsive: true, maintainAspectRatio: false, indexAxis: "y",
      plugins: {
        legend: { position: "bottom", labels: { boxWidth: 12, font: { size: 11 } } },
        tooltip: { callbacks: {
          label(context) {
            const row = rows[context.dataIndex];
            const key = buckets[context.datasetIndex][1];
            return `${buckets[context.datasetIndex][0]}: ${fmtInt.format(row[key])} judgments (${(row[key] / row.with_outcome * 100).toFixed(1)}%)`;
          },
          footer(items) {
            const row = rows[items[0].dataIndex];
            return `Any violation: ${(row.violation_share * 100).toFixed(1)}% (${fmtInt.format(row.with_violation)}/${fmtInt.format(row.with_outcome)})`;
          },
        } },
      },
      scales: {
        x: { stacked: true, beginAtZero: true, ...(percentages ? { max: 100, ticks: { callback: (value) => `${value}%` } } : {}) },
        y: { stacked: true, grid: { display: false }, ticks: { autoSkip: false, font: { size: 11 } } },
      },
    },
  });
}

function renderArticleAnalytics(analytics) {
  const rows = analytics?.rows || [];
  const canvas = document.getElementById("articleViolationRateChart");
  const sort = document.getElementById("articleRateSort");
  const minimum = document.getElementById("articleRateMinimum");
  if (!canvas || !sort || !minimum || !rows.length) return;
  canvas.dataset.keepEmptyView = "true";
  let chart;
  function render() {
    const selected = selectArticleRows(rows, Number(minimum.value), sort.value);
    if (chart) chart.destroy();
    canvas.parentElement.style.height = `${Math.max(360, selected.length * 36 + 90)}px`;
    canvas.parentElement.hidden = !selected.length;
    chart = createArticleOutcomeChart(canvas, selected, true);
    document.getElementById("articleRateSummary").textContent = selected.length
      ? `${selected.length} of ${rows.filter((row) => row.with_outcome > 0).length} article families with outcome tags shown. Minimum ${fmtInt.format(Number(minimum.value))} judgments per article. Bar segments sum to 100%; violation share includes the mixed segment.`
      : "No articles meet this minimum sample. Choose a lower threshold.";
    const highlights = document.getElementById("articleRateHighlights");
    highlights.replaceChildren();
    if (selected.length) {
      const ranked = selectArticleRows(rows, Number(minimum.value), "highest");
      for (const [label, row] of [["Highest share", ranked[0]], ["Lowest share", ranked[ranked.length - 1]]]) {
        const item = document.createElement("p");
        const value = document.createElement("strong");
        value.textContent = `${articleLabel(row.article)} · ${(row.violation_share * 100).toFixed(1)}%`;
        item.append(`${label}: `, value, ` · ${fmtInt.format(row.with_violation)} / ${fmtInt.format(row.with_outcome)} judgments`);
        highlights.appendChild(item);
      }
    }
    const table = document.getElementById("articleOutcomeRows");
    table.replaceChildren();
    for (const row of selected) {
      const tr = document.createElement("tr");
      const values = [articleLabel(row.article), `${(row.violation_share * 100).toFixed(1)}%`,
        ...["with_outcome", "violation_only", "mixed", "non_violation_only", "without_outcome"].map((key) => fmtInt.format(row[key]))];
      values.forEach((value, index) => {
        const cell = document.createElement(index === 0 ? "th" : "td");
        if (index === 0) cell.scope = "row";
        cell.textContent = value;
        tr.appendChild(cell);
      });
      table.appendChild(tr);
    }
    syncChartTheme();
  }
  sort.addEventListener("change", render);
  minimum.addEventListener("change", render);
  render();
  const largest = selectArticleRows(rows, 1, "volume").slice(0, 15);
  const countsCanvas = document.getElementById("articleOutcomesCountChart");
  if (countsCanvas) countsCanvas.parentElement.style.height = `${Math.max(360, largest.length * 32 + 90)}px`;
  createArticleOutcomeChart(countsCanvas, largest, false);
}

function createLineChart(ctx, labels, values, color) {
  if (!ctx || !values.some((value) => Number(value) > 0)) return null;
  return new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          data: values,
          borderColor: color,
          backgroundColor: `${color}33`,
          fill: true,
          tension: 0.2,
          pointRadius: 2.5,
          pointHoverRadius: 4,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
      },
      scales: {
        x: { grid: { display: false } },
        y: { beginAtZero: true },
      },
    },
  });
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
          backgroundColor: (colors.length ? colors : labels.map((_, i) => PALETTE[i % PALETTE.length])).map(
            (c) => `${c}CC`
          ),
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
      },
    },
  });
}

function createGroupedBarChart(ctx, labels, datasets, options = {}) {
  if (!ctx || !datasets.some((dataset) => dataset.data.some((value) => Number(value) > 0))) return null;
  return new Chart(ctx, {
    type: "bar",
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: "bottom" },
      },
      scales: {
        x: { stacked: !!options.stacked, grid: { display: false } },
        y: { beginAtZero: true, stacked: !!options.stacked },
      },
    },
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

function renderStateOutcomeTable(container, rows) {
  if (!container) return;
  if (!rows.length) {
    container.innerHTML = '<p class="state-outcome-empty">No state-level rows satisfy n ≥ 5.</p>';
    return;
  }

  const bodyRows = rows
    .slice(0, 20)
    .map(
      (row) => `
        <tr>
          <td>${row[0]}</td>
          <td>${fmtInt.format(row[1] || 0)}</td>
          <td>${fmtInt.format(row[2] || 0)}</td>
          <td>${fmtInt.format(row[3] || 0)}</td>
          <td>${fmtInt.format(row[4] || 0)}</td>
          <td>${fmtInt.format(row[5] || 0)}</td>
          <td>${Number(row[6] || 0).toFixed(1)}%</td>
        </tr>
      `
    )
    .join("");

  container.innerHTML = `
    <div class="state-outcome-scroll">
      <table class="state-outcome-table">
        <thead>
          <tr>
            <th>State</th>
            <th>Cases</th>
            <th>Violation only</th>
            <th>Non-violation only</th>
            <th>Mixed</th>
            <th>No finding</th>
            <th>Violation rate</th>
          </tr>
        </thead>
        <tbody>${bodyRows}</tbody>
      </table>
    </div>
  `;
}

function rowsOrEmpty(value) {
  return Array.isArray(value) ? value : [];
}

function syncChartTheme() {
  const style = getComputedStyle(document.documentElement);
  const ink = style.getPropertyValue("--ink-3").trim() || "#706d72";
  const rule = style.getPropertyValue("--rule-soft").trim() || "#e8e0d4";
  Chart.defaults.color = ink;
  Object.values(Chart.instances).forEach((chart) => {
    chart.options.color = ink;
    for (const axis of Object.values(chart.options.scales || {})) {
      if (axis.ticks) axis.ticks.color = ink;
      if (axis.grid) axis.grid.color = rule;
    }
    if (chart.options.plugins?.legend?.labels) chart.options.plugins.legend.labels.color = ink;
    chart.update("none");
  });
}

function renderChamberTrend(rows) {
  const labels = ["Grand Chamber", "Chamber", "Committee"];
  const chart = createGroupedBarChart(document.getElementById("chamberTrendChart"), rows.map((r) => r[0]),
    labels.map((label, i) => ({label, data: rows.map((r) => r[i + 1]),
      backgroundColor: ["#395d7f", "#43705a", "#8d2f2f"][i], borderRadius: 2})));
  if (chart) {
    chart.options.scales.x.stacked = true;
    chart.options.scales.y.stacked = true;
    chart.update("none");
  }
}

function renderCoverage(data) {
  const fields = data.quality?.field_completeness || {};
  const labels = {respondent_state: "Respondent state", ecli: "ECLI identity", article_no: "Convention articles",
    conclusion: "Conclusion", originating_body: "Judicial collection", importance: "Importance classification",
    hudoc_kpthesaurus: "Thesaurus topics", strasbourg_caselaw: "HUDOC citation metadata", rules_of_court: "Rules of Court"};
  const rows = Object.entries(labels).map(([key, label]) => [label, Number(fields[key] || 0),
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

  // Provenance for the export filenames, the PNG footer and the Cite dialog.
  // Read from the payload rather than scraped back out of #metaGenerated's
  // formatted text, which would break the moment that formatting changes.
  window.EchrStatsMeta = {
    generated_at: data.generated_at,
    source_file: data.source_file,
    schema_version: data.schema_version,
    parser_version: data.parser_version,
  };

  document.getElementById("metaSource").textContent = `Source: ${data.source_file || "-"} · Schema: ${data.schema_version || "-"}`;
  document.getElementById("metaGenerated").textContent = `Generated: ${formatDateForMeta(data.generated_at)} · Parser: ${data.parser_version || "-"}`;

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

  const s = data.summary || {};
  const series = data.series || {};
  const rankings = data.rankings || {};
  const fieldCompleteness = (data.quality && data.quality.field_completeness) || {};

  const scope = data.scope || {};
  const texts = data.text_coverage || {};
  const total = Number(s.total_cases || 0);
  const withText = Number(s.cases_with_text || 0);
  const violationCount = Number(s.outcome_violation_only || 0) + Number(s.outcome_both || 0);
  document.getElementById("kpiGrid").innerHTML = [
    makeKpi("Judgment records", fmtInt.format(total), "No decisions or press releases"),
    makeKpi("Respondent states", fmtInt.format(s.unique_countries || 0), "Multi-state judgments count for each state"),
    makeKpi("At least one violation", total ? (violationCount / total * 100).toFixed(1) + "%" : "Unavailable", fmtInt.format(violationCount) + " of " + fmtInt.format(total) + " judgments"),
    makeKpi("Text rows", fmtInt.format(s.total_paragraphs || 0), fmtInt.format(withText) + " judgments with text; includes table/header rows"),
  ].join("");
  document.getElementById("metaSource").textContent = "Verified HUDOC catalog + read-only text inventories";
  document.getElementById("metaGenerated").textContent = "Built " + formatDateForMeta(data.generated_at);
  document.getElementById("scopeCutoff").textContent = "Catalog cut-off: " + (scope.cutoff || "Unavailable") + " · " + (s.date_range_label || "");
  const sourceLanguages = texts.by_language || {};
  const sourceOrigins = texts.by_origin || {};
  const knownLanguages = [["English", sourceLanguages.ENG], ["French", sourceLanguages.FRE]]
    .filter((row) => row[1] > 0).map(([label, count]) => fmtInt.format(count) + " " + label).join(", ") || "none recorded";
  document.getElementById("textCoverageSummary").textContent =
    fmtInt.format(withText) + " / " + fmtInt.format(total) + " judgment records have inventoried text. " +
    "Confirmed source language: " + knownLanguages + "; " + fmtInt.format(sourceLanguages.Unknown || 0) +
    " not recorded. " + fmtInt.format(sourceOrigins["Local source bundle"] || 0) + " local bundles are staged, not yet in live Search.";
  const caveat = document.getElementById("scopeCaveat");
  caveat.textContent = (scope.note || "") + " " + (scope.translation_title_warnings?.length || 0) + " translation-title records remain in the literal catalog count.";
  renderCoverage(data);
  renderChamberTrend(series.chambers_by_year || []);
  const citationNote = document.getElementById("citationCoverageNote");
  citationNote.textContent = "HUDOC citation metadata is populated for " +
    fmtInt.format(s.cases_with_strasbourg_caselaw || 0) + " / " + fmtInt.format(total) +
    " judgments. Counts refer to distinct citation strings, not resolved judgment identities or a citation network.";

  const casesByYear = rowsOrEmpty(series.cases_by_year);
  const chamberBreakdown = rowsOrEmpty(series.chamber_breakdown);
  const countriesTop = rowsOrEmpty(rankings.countries_top);
  const sections = rowsOrEmpty(rankings.sections);
  const importanceDistribution = rowsOrEmpty(rankings.importance_distribution);
  const outcomeRows = rowsOrEmpty(series.outcome_breakdown);
  const outcomes = outcomeRows.length ? outcomeRows : rowsOrEmpty(rankings.outcomes);
  const bodiesTop = rowsOrEmpty(rankings.originating_bodies_top);
  const separateShareByBody = rowsOrEmpty(series.separate_opinion_share_by_body);
  const keywordsTop = rowsOrEmpty(rankings.keywords_top);
  const citationsTop = rowsOrEmpty(rankings.strasbourg_caselaw_top);
  const stateOutcomesTop = rowsOrEmpty(rankings.state_outcomes_top);
  const inadmissibilityGroundsTop = rowsOrEmpty(rankings.inadmissibility_grounds_top);
  const precedentConcentrationTop = rowsOrEmpty(rankings.precedent_concentration_top);
  const precedentToCitingCasesTop = rowsOrEmpty(rankings.precedent_to_citing_cases_top);
  const outcomesByYear = rowsOrEmpty(series.outcomes_by_year);
  const proceduralVsSubstantiveByYear = rowsOrEmpty(series.procedural_vs_substantive_by_year);

  createLineChart(
    document.getElementById("casesYearChart"),
    casesByYear.map((d) => d[0]),
    casesByYear.map((d) => d[1]),
    "#d97a2b"
  );

  createBarChart(
    document.getElementById("countriesChart"),
    countriesTop.map((d) => d[0]),
    countriesTop.map((d) => d[1]),
    { horizontal: true }
  );

  // Violation Rate by Country — horizontal bar, sorted descending by rate,
  // filtered to states with at least 10 cases, top 25 shown.
  const countryRatesEl = document.getElementById("countryRatesChart");
  if (countryRatesEl && stateOutcomesTop.length) {
    const MIN_CASES = 10;
    const TOP_N = 25;
    const rateRows = stateOutcomesTop
      .filter((r) => Number(r[1]) >= MIN_CASES)
      .slice()
      .sort((a, b) => Number(b[6]) - Number(a[6]))
      .slice(0, TOP_N);

    const rateColor = (rate) => {
      // Green (low rate) → amber → red (high rate)
      if (rate >= 85) return "#c0392b";
      if (rate >= 70) return "#e67e22";
      if (rate >= 50) return "#d4a017";
      if (rate >= 30) return "#3c8d5a";
      return "#245ea8";
    };

    const labels = rateRows.map((r) => r[0]);
    const values = rateRows.map((r) => Number(r[6]));
    const totals = rateRows.map((r) => Number(r[1]));
    const colors = values.map(rateColor);

    new Chart(countryRatesEl, {
      type: "bar",
      data: {
        labels,
        datasets: [
          {
            data: values,
            backgroundColor: colors.map((c) => `${c}CC`),
            borderColor: colors,
            borderWidth: 1,
            borderRadius: 6,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        indexAxis: "y",
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: (ctx) => {
                const idx = ctx.dataIndex;
                return `${values[idx].toFixed(1)}% violation rate (${totals[idx]} cases)`;
              },
            },
          },
        },
        scales: {
          x: {
            beginAtZero: true,
            max: 100,
            ticks: { callback: (v) => `${v}%` },
            grid: { display: true },
          },
          y: { grid: { display: false } },
        },
      },
    });
  }

  createBarChart(
    document.getElementById("sectionsChart"),
    sections.map((d) => d[0]),
    sections.map((d) => d[1]),
    { horizontal: true }
  );

  createDoughnutChart(
    document.getElementById("chamberChart"),
    chamberBreakdown.map((d) => d[0]),
    chamberBreakdown.map((d) => d[1]),
    ["#395d7f", "#43705a", "#8d2f2f", "#969197"]
  );

  createBarChart(
    document.getElementById("importanceChart"),
    importanceDistribution.map((d) => d[0]),
    importanceDistribution.map((d) => d[1]),
    { colors: ["#6c5db5", "#245ea8", "#d97a2b"] }
  );

  createDoughnutChart(
    document.getElementById("outcomesChart"),
    outcomes.map((d) => d[0]),
    outcomes.map((d) => d[1]),
    ["#3c8d5a", "#245ea8", "#d97a2b", "#8c8c8c"]
  );

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

  createBarChart(
    document.getElementById("inadmissibilityChart"),
    ["Inadmissible", "Struck out"],
    [s.inadmissible_cases || 0, s.struck_out_cases || 0],
    { colors: ["#b03e45", "#8c8c8c"] }
  );

  if (outcomesByYear.length) {
    createMultiLineChart(
      document.getElementById("outcomesYearChart"),
      outcomesByYear.map((d) => d[0]),
      [
        {
          label: "Violation only",
          data: outcomesByYear.map((d) => d[1]),
          borderColor: "#3c8d5a",
          backgroundColor: "#3c8d5a33",
          fill: false,
          tension: 0.2,
          pointRadius: 2.5,
          pointHoverRadius: 4,
        },
        {
          label: "Non-violation only",
          data: outcomesByYear.map((d) => d[2]),
          borderColor: "#245ea8",
          backgroundColor: "#245ea833",
          fill: false,
          tension: 0.2,
          pointRadius: 2.5,
          pointHoverRadius: 4,
        },
        {
          label: "Mixed",
          data: outcomesByYear.map((d) => d[3]),
          borderColor: "#d97a2b",
          backgroundColor: "#d97a2b33",
          fill: false,
          tension: 0.2,
          pointRadius: 2.5,
          pointHoverRadius: 4,
        },
        {
          label: "No finding",
          data: outcomesByYear.map((d) => d[4]),
          borderColor: "#8c8c8c",
          backgroundColor: "#8c8c8c33",
          fill: false,
          tension: 0.2,
          pointRadius: 2.5,
          pointHoverRadius: 4,
        },
      ]
    );
  }

  createBarChart(
    document.getElementById("bodiesChart"),
    bodiesTop.map((d) => d[0]),
    bodiesTop.map((d) => d[1]),
    { horizontal: true, colors: ["#4f7ca6"] }
  );

  createBarChart(
    document.getElementById("separateByBodyChart"),
    separateShareByBody.map((d) => `${truncateLabel(d[0], 26)} (n=${d[2]})`),
    separateShareByBody.map((d) => d[1]),
    { horizontal: true, colors: ["#b03e45"] }
  );

  createBarChart(
    document.getElementById("keywordsChart"),
    keywordsTop.slice(0, 20).map((d) => truncateLabel(d[0], 45)),
    keywordsTop.slice(0, 20).map((d) => d[1]),
    { horizontal: true, colors: ["#b28a2f"] }
  );

  renderArticleAnalytics(data.article_analytics);
  await renderJudgmentCitations(scope);

  if (precedentConcentrationTop.length) {
    const concentrationChart = createLineChart(
      document.getElementById("precedentConcentrationChart"),
      precedentConcentrationTop.map((d) => d[0]),
      precedentConcentrationTop.map((d) => d[3]),
      "#8d4f78"
    );
    if (concentrationChart) {
      concentrationChart.options.scales.x.ticks = {
        callback(value) { return citationDisplayLabel(this.getLabelForValue(value)); },
      };
      concentrationChart.options.plugins.tooltip = { callbacks: { title: citationTooltipTitle } };
      concentrationChart.update("none");
    }
  } else {
    createBarChart(
      document.getElementById("precedentConcentrationChart"),
      ["Top 10 cumulative share"],
      [0],
      { colors: ["#8d4f78"] }
    );
  }

  const citationSourceRows = precedentToCitingCasesTop.length ? precedentToCitingCasesTop : citationsTop;
  const citationsChart = createBarChart(
    document.getElementById("citationsChart"),
    citationSourceRows.slice(0, 15).map((d) => d[0]),
    citationSourceRows.slice(0, 15).map((d) => d[1]),
    { horizontal: true, colors: ["#8d4f78"] }
  );
  if (citationsChart) {
    citationsChart.canvas.parentElement.classList.add("citation-canvas-wrap");
    citationsChart.data.datasets[0].label = "Citing judgment records";
    citationsChart.options.scales.y.ticks = {
      font: { size: 11 },
      callback(value) {
        const label = citationDisplayLabel(this.getLabelForValue(value));
        return this.chart.width < 500 ? wrapCitationText(label, 22) : label;
      },
    };
    citationsChart.options.plugins.tooltip = { callbacks: { title: citationTooltipTitle } };
    citationsChart.update("none");
  }

  // Violation Rate by Year (%)
  if (outcomesByYear.length) {
    const vrYears = [];
    const vrRates = [];
    for (const d of outcomesByYear) {
      const vOnly = d[1] || 0, nvOnly = d[2] || 0, both = d[3] || 0, neither = d[4] || 0;
      const denom = vOnly + nvOnly + both + neither;
      if (denom > 5) {
        vrYears.push(d[0]);
        vrRates.push(((vOnly + both) / denom) * 100);
      }
    }
    new Chart(document.getElementById("violationRateYearChart"), {
      type: "line",
      data: {
        labels: vrYears,
        datasets: [{
          data: vrRates,
          borderColor: "rgba(220, 80, 60, 0.85)",
          backgroundColor: "rgba(220, 80, 60, 0.15)",
          fill: true,
          tension: 0.3,
          pointRadius: 2.5,
          pointHoverRadius: 4,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { grid: { display: false } },
          y: { beginAtZero: true, min: 0, max: 100, ticks: { callback: (v) => v + "%" } },
        },
      },
    });
  }

  // Top Inadmissibility Grounds
  if (inadmissibilityGroundsTop.length) {
    const igData = inadmissibilityGroundsTop.slice(0, 12);
    createBarChart(
      document.getElementById("inadmissibilityGroundsChart"),
      igData.map((d) => truncateLabel(d[0], 45)),
      igData.map((d) => d[1]),
      { horizontal: true, colors: ["#6478b4"] }
    );
  }

  // Article × State interactive chart
  const crossTabs = data.cross_tabs || {};
  const articleByState = crossTabs.article_by_state || {};
  const articleStateSelect = document.getElementById("articleStateSelect");
  const articleByStateCtx = document.getElementById("articleByStateChart");
  let articleByStateChart = null;

  if (articleStateSelect && articleByStateCtx && Object.keys(articleByState).length) {
    const articleKeys = Object.keys(articleByState).sort((a, b) => {
      const na = parseInt(a, 10);
      const nb = parseInt(b, 10);
      if (!isNaN(na) && !isNaN(nb)) return na - nb;
      return a.localeCompare(b);
    });

    articleKeys.forEach((art) => {
      const opt = document.createElement("option");
      opt.value = art;
      opt.textContent = `Art. ${art}`;
      articleStateSelect.appendChild(opt);
    });

    function renderArticleByState(article) {
      const rows = articleByState[article] || [];
      const labels = rows.map((r) => r[0]);
      const totalCases = rows.map((r) => r[1]);
      const violations = rows.map((r) => r[2]);

      if (articleByStateChart) articleByStateChart.destroy();
      articleByStateChart = createGroupedBarChart(
        articleByStateCtx,
        labels,
        [
          {
            label: "Total cases",
            data: totalCases,
            backgroundColor: "#245ea8CC",
            borderColor: "#245ea8",
            borderWidth: 1,
            borderRadius: 5,
          },
          {
            label: "Violations",
            data: violations,
            backgroundColor: "#b03e45CC",
            borderColor: "#b03e45",
            borderWidth: 1,
            borderRadius: 5,
          },
        ]
      );
    }

    renderArticleByState(articleKeys[0]);
    articleStateSelect.addEventListener("change", () => {
      renderArticleByState(articleStateSelect.value);
    });
  }

  // Comparative State Analysis
  const compareData = crossTabs.compare || {};
  const compareYears = compareData.years || [];
  const stateProfiles = compareData.states || {};
  const compareStateNames = Object.keys(stateProfiles).sort((a, b) => {
    return (stateProfiles[b].total || 0) - (stateProfiles[a].total || 0);
  });

  const compareSelects = [1, 2, 3].map((n) => document.getElementById(`compareState${n}`));
  const compareSummaryEl = document.getElementById("compareSummaryTable");
  const compareTrendCtx = document.getElementById("compareTrendChart");
  const compareArticlesCtx = document.getElementById("compareArticlesChart");
  let compareTrendChart = null;
  let compareArticlesChart = null;

  const COMPARE_COLORS = ["#245ea8", "#b03e45", "#3c8d5a"];

  if (compareSelects[0] && compareTrendCtx && compareStateNames.length >= 2) {
    compareStateNames.forEach((state) => {
      compareSelects.forEach((sel, i) => {
        if (!sel) return;
        const opt = document.createElement("option");
        opt.value = state;
        opt.textContent = `${state} (${stateProfiles[state].total})`;
        sel.appendChild(opt);
      });
    });

    // Pre-select top states for comparison
    const topStates = countriesTop.slice(0, 3).map(d => d[0]);
    ["compareState1","compareState2","compareState3"].forEach((id, i) => {
      const sel = document.getElementById(id);
      if (sel && topStates[i]) sel.value = topStates[i];
    });

    function getSelectedStates() {
      return compareSelects
        .map((sel) => sel ? sel.value : "")
        .filter((v) => v && stateProfiles[v]);
    }

    function renderComparison() {
      const selected = getSelectedStates();
      if (selected.length < 2) return;

      // Summary table
      const headerCells = ["Metric", ...selected].map((h) => `<th>${h}</th>`).join("");
      const rows = [
        ["Total cases", ...selected.map((s) => fmtInt.format(stateProfiles[s].total))],
        ["Violation rate", ...selected.map((s) => `${stateProfiles[s].violation_rate}%`)],
        ["Violation only", ...selected.map((s) => fmtInt.format(stateProfiles[s].outcomes.violation_only))],
        ["Non-violation only", ...selected.map((s) => fmtInt.format(stateProfiles[s].outcomes.non_violation_only))],
        ["Mixed", ...selected.map((s) => fmtInt.format(stateProfiles[s].outcomes.both))],
        ["No finding", ...selected.map((s) => fmtInt.format(stateProfiles[s].outcomes.neither))],
      ];
      const bodyRows = rows.map((r) => `<tr>${r.map((c) => `<td>${c}</td>`).join("")}</tr>`).join("");
      compareSummaryEl.innerHTML = `<table class="compare-summary-table"><thead><tr>${headerCells}</tr></thead><tbody>${bodyRows}</tbody></table>`;

      // Trend chart
      if (compareTrendChart) compareTrendChart.destroy();
      compareTrendChart = createMultiLineChart(
        compareTrendCtx,
        compareYears,
        selected.map((state, i) => ({
          label: state,
          data: stateProfiles[state].cases_by_year,
          borderColor: COMPARE_COLORS[i % COMPARE_COLORS.length],
          backgroundColor: `${COMPARE_COLORS[i % COMPARE_COLORS.length]}33`,
          fill: false,
          tension: 0.2,
          pointRadius: 3,
          pointHoverRadius: 5,
        }))
      );

      // Articles chart — collect union of top articles across selected states
      const articleSet = new Set();
      selected.forEach((state) => {
        (stateProfiles[state].top_violated_articles || []).forEach(([art]) => articleSet.add(art));
      });
      const articleLabels = [...articleSet].sort((a, b) => {
        const na = parseInt(a, 10);
        const nb = parseInt(b, 10);
        if (!isNaN(na) && !isNaN(nb)) return na - nb;
        return a.localeCompare(b);
      });

      if (compareArticlesChart) compareArticlesChart.destroy();
      compareArticlesChart = createGroupedBarChart(
        compareArticlesCtx,
        articleLabels.map((a) => `Art. ${a}`),
        selected.map((state, i) => {
          const artMap = new Map((stateProfiles[state].top_violated_articles || []).map(([a, c]) => [a, c]));
          return {
            label: state,
            data: articleLabels.map((a) => artMap.get(a) || 0),
            backgroundColor: `${COMPARE_COLORS[i % COMPARE_COLORS.length]}CC`,
            borderColor: COMPARE_COLORS[i % COMPARE_COLORS.length],
            borderWidth: 1,
            borderRadius: 5,
          };
        })
      );
    }

    renderComparison();
    compareSelects.forEach((sel) => {
      if (sel) sel.addEventListener("change", renderComparison);
    });
  }

  renderStateOutcomeTable(document.getElementById("stateOutcomeTable"), stateOutcomesTop);

  // ── Thesaurus Topic Analytics ────────────────────────────────────────
  const thesaurusAnalytics = data.thesaurus_analytics || {};

  // Top Topics bar chart
  const topTerms = rowsOrEmpty(thesaurusAnalytics.top_terms);
  if (topTerms.length) {
    const ttData = topTerms.slice(0, 25);
    createBarChart(
      document.getElementById("thesaurusTopChart"),
      ttData.map((d) => truncateLabel(d[0], 50)),
      ttData.map((d) => d[1]),
      { horizontal: true, colors: ["#6c5db5"] }
    );
  }

  // Topic Trends multi-line chart
  const termsByYear = rowsOrEmpty(thesaurusAnalytics.terms_by_year);
  const termsByYearLabels = thesaurusAnalytics.terms_by_year_labels || [];
  const TREND_COLORS = ["#245ea8", "#b03e45", "#3c8d5a", "#d97a2b", "#6c5db5"];
  if (termsByYear.length && termsByYearLabels.length) {
    createMultiLineChart(
      document.getElementById("thesaurusTrendsChart"),
      termsByYear.map((d) => d[0]),
      termsByYearLabels.map((label, i) => ({
        label: truncateLabel(label, 40),
        data: termsByYear.map((d) => d[i + 1] || 0),
        borderColor: TREND_COLORS[i % TREND_COLORS.length],
        backgroundColor: `${TREND_COLORS[i % TREND_COLORS.length]}33`,
        fill: false,
        tension: 0.2,
        pointRadius: 2.5,
        pointHoverRadius: 4,
      }))
    );
  }

  // Topics by Country interactive
  const topTermsByCountry = thesaurusAnalytics.top_terms_by_country || {};
  const thesCountrySelect = document.getElementById("thesaurusCountrySelect");
  const thesCountryCtx = document.getElementById("thesaurusCountryChart");
  let thesCountryChart = null;

  if (thesCountrySelect && thesCountryCtx && Object.keys(topTermsByCountry).length) {
    const countryKeys = Object.keys(topTermsByCountry).sort((a, b) => {
      const aTotal = (topTermsByCountry[a] || []).reduce((s, d) => s + d[1], 0);
      const bTotal = (topTermsByCountry[b] || []).reduce((s, d) => s + d[1], 0);
      return bTotal - aTotal;
    });

    countryKeys.forEach((country) => {
      const opt = document.createElement("option");
      opt.value = country;
      opt.textContent = country;
      thesCountrySelect.appendChild(opt);
    });

    function renderThesaurusCountry(country) {
      const rows = topTermsByCountry[country] || [];
      if (thesCountryChart) thesCountryChart.destroy();
      thesCountryChart = createBarChart(
        thesCountryCtx,
        rows.map((d) => truncateLabel(d[0], 45)),
        rows.map((d) => d[1]),
        { horizontal: true, colors: ["#4f7ca6"] }
      );
    }

    renderThesaurusCountry(countryKeys[0]);
    thesCountrySelect.addEventListener("change", () => {
      renderThesaurusCountry(thesCountrySelect.value);
    });
  }

  // Co-occurrence chart
  const topCooccurrences = rowsOrEmpty(thesaurusAnalytics.top_cooccurrences);
  if (topCooccurrences.length) {
    const coData = topCooccurrences.slice(0, 12);
    createBarChart(
      document.getElementById("thesaurusCooccurrenceChart"),
      coData.map((d) => {
        const pair = d[0] || [];
        return truncateLabel(`${pair[0] || "?"} + ${pair[1] || "?"}`, 70);
      }),
      coData.map((d) => d[1]),
      { horizontal: true, colors: ["#8d4f78"] }
    );
  }

  // ── Conclusion / Outcome Analytics ──────────────────────────────────
  const conclusionAnalytics = data.conclusion_analytics || {};

  // Clause breakdown chart
  const clauseBreakdown = rowsOrEmpty(conclusionAnalytics.clause_breakdown);
  if (clauseBreakdown.length) {
    const cbData = clauseBreakdown.slice(0, 18);
    createBarChart(
      document.getElementById("conclusionClausesChart"),
      cbData.map((d) => d[0]),
      cbData.map((d) => d[1]),
      { horizontal: true, colors: ["#245ea8"] }
    );
  }

  // Conclusion outcome trends by year
  const conclusionTrends = rowsOrEmpty(conclusionAnalytics.conclusion_outcomes_by_year);
  if (conclusionTrends.length) {
    createMultiLineChart(
      document.getElementById("conclusionTrendsChart"),
      conclusionTrends.map((d) => d[0]),
      [
        {
          label: "Violation finding",
          data: conclusionTrends.map((d) => d[1]),
          borderColor: "#b03e45",
          backgroundColor: "#b03e4533",
          fill: false,
          tension: 0.2,
          pointRadius: 2.5,
          pointHoverRadius: 4,
        },
        {
          label: "No violation finding",
          data: conclusionTrends.map((d) => d[2]),
          borderColor: "#245ea8",
          backgroundColor: "#245ea833",
          fill: false,
          tension: 0.2,
          pointRadius: 2.5,
          pointHoverRadius: 4,
        },
        {
          label: "Award granted",
          data: conclusionTrends.map((d) => d[3]),
          borderColor: "#3c8d5a",
          backgroundColor: "#3c8d5a33",
          fill: false,
          tension: 0.2,
          pointRadius: 2.5,
          pointHoverRadius: 4,
        },
        {
          label: "Inadmissible",
          data: conclusionTrends.map((d) => d[4]),
          borderColor: "#8c8c8c",
          backgroundColor: "#8c8c8c33",
          fill: false,
          tension: 0.2,
          pointRadius: 2.5,
          pointHoverRadius: 4,
        },
      ]
    );
  }

  // Preliminary objections doughnut
  const prelimObj = conclusionAnalytics.preliminary_objections || {};
  const prelimTotal = (prelimObj.rejected || 0) + (prelimObj.accepted || 0) + (prelimObj.joined_to_merits || 0);
  if (prelimTotal > 0) {
    createDoughnutChart(
      document.getElementById("prelimObjChart"),
      ["Rejected", "Accepted", "Joined to merits"],
      [prelimObj.rejected || 0, prelimObj.accepted || 0, prelimObj.joined_to_merits || 0],
      ["#3c8d5a", "#b03e45", "#d97a2b"]
    );
  }

  // Damages & costs disposition
  const damagesCtx = document.getElementById("damagesDispositionChart");
  if (damagesCtx && clauseBreakdown.length) {
    const damageLabels = [];
    const damageValues = [];
    const damageColors = [];
    const colorMap = {
      "Pecuniary damage awarded": "#3c8d5a",
      "Pecuniary damage dismissed": "#b03e45",
      "Pecuniary damage other": "#8c8c8c",
      "Non-pecuniary damage awarded": "#245ea8",
      "Non-pecuniary: violation sufficient": "#6c5db5",
      "Non-pecuniary damage dismissed": "#d97a2b",
      "Costs & expenses awarded": "#4f7ca6",
      "Costs & expenses dismissed": "#b28a2f",
    };
    for (const [label, count] of clauseBreakdown) {
      if (label in colorMap) {
        damageLabels.push(label);
        damageValues.push(count);
        damageColors.push(colorMap[label]);
      }
    }
    if (damageLabels.length) {
      createBarChart(
        damagesCtx,
        damageLabels,
        damageValues,
        { horizontal: true, colors: damageColors }
      );
    }
  }

  // Just Satisfaction KPIs
  const justSat = conclusionAnalytics.just_satisfaction || {};
  const jsKpiGrid = document.getElementById("justSatisfactionKpis");
  if (jsKpiGrid) {
    const pStats = justSat.pecuniary_stats || {};
    const npStats = justSat.non_pecuniary_stats || {};
    const cStats = justSat.costs_stats || {};

    // Compute totals from clause breakdown
    const getClauseCount = (name) => {
      const found = clauseBreakdown.find((d) => d[0] === name);
      return found ? found[1] : 0;
    };

    const pecAwarded = getClauseCount("Pecuniary damage awarded");
    const pecDismissed = getClauseCount("Pecuniary damage dismissed");
    const npAwarded = getClauseCount("Non-pecuniary damage awarded");
    const npSufficient = getClauseCount("Non-pecuniary: violation sufficient");
    const npDismissed = getClauseCount("Non-pecuniary damage dismissed");
    const costsAwarded = getClauseCount("Costs & expenses awarded");
    const costsDismissed = getClauseCount("Costs & expenses dismissed");
    const justSatReserved = getClauseCount("Just satisfaction reserved");

    jsKpiGrid.innerHTML = [
      makeKpi("Pecuniary Damage Awarded", fmtInt.format(pecAwarded), `${fmtInt.format(pecDismissed)} dismissed`),
      makeKpi("Non-pecuniary Awarded", fmtInt.format(npAwarded), `${fmtInt.format(npSufficient)} violation sufficient`),
      makeKpi("Non-pecuniary Dismissed", fmtInt.format(npDismissed)),
      makeKpi("Costs & Expenses Awarded", fmtInt.format(costsAwarded), `${fmtInt.format(costsDismissed)} dismissed`),
      makeKpi("Just Satisfaction Reserved", fmtInt.format(justSatReserved), "For separate proceedings"),
      makeKpi("Prelim. Objections", fmtInt.format(prelimTotal),
        `${((prelimObj.rejected || 0) / Math.max(prelimTotal, 1) * 100).toFixed(0)}% rejected`),
    ].join("");
  }

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
function scrollToHashIfAny() {
  if (!location.hash) return;
  const id = decodeURIComponent(location.hash.slice(1));
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
