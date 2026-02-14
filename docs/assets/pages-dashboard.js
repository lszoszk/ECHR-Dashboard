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

function makeKpi(label, value, note = "") {
  return `
    <article class="kpi-card">
      <div class="kpi-label">${label}</div>
      <div class="kpi-value">${value}</div>
      ${note ? `<div class="kpi-note">${note}</div>` : ""}
    </article>
  `;
}

function createBarChart(ctx, labels, values, options = {}) {
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

function createLineChart(ctx, labels, values, color) {
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

function rowsOrEmpty(value) {
  return Array.isArray(value) ? value : [];
}

async function loadDashboard() {
  const res = await fetch("data/stats.json", { cache: "no-store" });
  if (!res.ok) throw new Error(`Failed to load dashboard data (${res.status})`);
  const data = await res.json();

  document.getElementById("metaSource").textContent = `Source: ${data.source_file || "-"}`;
  document.getElementById("metaGenerated").textContent = `Generated: ${formatDateForMeta(data.generated_at)}`;

  const s = data.summary || {};
  const series = data.series || {};
  const rankings = data.rankings || {};
  const fieldCompleteness = (data.quality && data.quality.field_completeness) || {};

  const metadataCoverage = [
    fieldCompleteness.keywords || 0,
    fieldCompleteness.originating_body || 0,
    fieldCompleteness.strasbourg_caselaw || 0,
    fieldCompleteness.respondent_state || 0,
  ];
  const coveragePct = metadataCoverage.length
    ? (metadataCoverage.reduce((acc, val) => acc + val, 0) / metadataCoverage.length) * 100
    : 0;

  const kpiGrid = document.getElementById("kpiGrid");
  kpiGrid.innerHTML = [
    makeKpi("Total Cases", fmtInt.format(s.total_cases || 0)),
    makeKpi("Total Paragraphs", fmtInt.format(s.total_paragraphs || 0)),
    makeKpi(
      "Date Range",
      s.date_range_label || "-",
      `${fmtInt.format(s.dated_cases || 0)} dated · ${fmtInt.format(s.undated_cases || 0)} undated`
    ),
    makeKpi("Respondent States", fmtInt.format(s.unique_countries || 0)),
    makeKpi("Distinct Articles", fmtInt.format(s.unique_articles || 0)),
    makeKpi("Avg Paragraphs / Case", Number(s.avg_paragraphs_per_case || 0).toFixed(1)),
    makeKpi("Median Paragraphs / Case", Math.round(s.median_paragraphs_per_case || 0).toString()),
    makeKpi("P90 Paragraphs / Case", Math.round(s.p90_paragraphs_per_case || 0).toString()),
    makeKpi(
      "Grand Chamber Share",
      `${Number(s.grand_chamber_share || 0).toFixed(1)}%`,
      `${fmtInt.format(s.grand_chamber_cases || 0)} of ${fmtInt.format(s.total_cases || 0)} cases`
    ),
    makeKpi("Key Cases", fmtInt.format(s.key_cases || 0), `${Number((s.total_cases ? (s.key_cases / s.total_cases) * 100 : 0)).toFixed(1)}% of corpus`),
    makeKpi("Separate Opinions", fmtInt.format(s.separate_opinion_cases || 0)),
    makeKpi("With Strasbourg Citations", fmtInt.format(s.cases_with_strasbourg_caselaw || 0)),
    makeKpi("Avg Strasbourg Citations / Case", Number(s.avg_strasbourg_citations_per_case || 0).toFixed(1)),
    makeKpi("With Domestic Law", fmtInt.format(s.cases_with_domestic_law || 0)),
    makeKpi("With International Law", fmtInt.format(s.cases_with_international_law || 0)),
    makeKpi("With Rules of Court", fmtInt.format(s.cases_with_rules_of_court || 0)),
    makeKpi("Metadata Completeness", `${coveragePct.toFixed(1)}%`),
    makeKpi(
      "Outcome Mix",
      `${fmtInt.format(s.outcome_violation_only || 0)} / ${fmtInt.format(s.outcome_non_violation_only || 0)} / ${fmtInt.format(s.outcome_both || 0)} / ${fmtInt.format(s.outcome_neither || 0)}`,
      "Violation only · Non-violation only · Both · Neither"
    ),
  ].join("");

  const casesByMonth = rowsOrEmpty(series.cases_by_month);
  const casesByYear = rowsOrEmpty(series.cases_by_year);
  const paragraphsByMonth = rowsOrEmpty(series.paragraphs_by_month);
  const chamberBreakdown = rowsOrEmpty(series.chamber_breakdown);
  const caseLengthSnapshot = rowsOrEmpty(series.case_length_snapshot);
  const countriesTop = rowsOrEmpty(rankings.countries_top);
  const articlesTop = rowsOrEmpty(rankings.articles_top);
  const sections = rowsOrEmpty(rankings.sections);
  const importanceDistribution = rowsOrEmpty(rankings.importance_distribution);
  const outcomeRows = rowsOrEmpty(series.outcome_breakdown);
  const outcomes = outcomeRows.length ? outcomeRows : rowsOrEmpty(rankings.outcomes);
  const bodiesTop = rowsOrEmpty(rankings.originating_bodies_top);
  const separateShareByBody = rowsOrEmpty(series.separate_opinion_share_by_body);
  const keywordsTop = rowsOrEmpty(rankings.keywords_top);
  const citationsTop = rowsOrEmpty(rankings.strasbourg_caselaw_top);

  createBarChart(
    document.getElementById("casesMonthChart"),
    casesByMonth.map((d) => d[0]),
    casesByMonth.map((d) => d[1]),
    { colors: ["#245ea8"] }
  );

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

  createBarChart(
    document.getElementById("articlesChart"),
    articlesTop.map((d) => `Art. ${d[0]}`),
    articlesTop.map((d) => d[1]),
    { horizontal: true, colors: ["#3c8d5a"] }
  );

  createBarChart(
    document.getElementById("sectionsChart"),
    sections.map((d) => d[0]),
    sections.map((d) => d[1]),
    { horizontal: true }
  );

  createLineChart(
    document.getElementById("paragraphsMonthChart"),
    paragraphsByMonth.map((d) => d[0]),
    paragraphsByMonth.map((d) => d[1]),
    "#6c5db5"
  );

  createDoughnutChart(
    document.getElementById("chamberChart"),
    chamberBreakdown.map((d) => d[0]),
    chamberBreakdown.map((d) => d[1]),
    ["#245ea8", "#3c8d5a", "#8c8c8c"]
  );

  createBarChart(
    document.getElementById("lengthChart"),
    caseLengthSnapshot.map((d) => d[0]),
    caseLengthSnapshot.map((d) => Math.round(d[1])),
    { colors: ["#4f7ca6", "#245ea8", "#d97a2b", "#b03e45"] }
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

  createBarChart(
    document.getElementById("citationsChart"),
    citationsTop.slice(0, 15).map((d) => truncateLabel(d[0], 80)),
    citationsTop.slice(0, 15).map((d) => d[1]),
    { horizontal: true, colors: ["#8d4f78"] }
  );
}

loadDashboard().catch((err) => {
  console.error(err);
  document.body.insertAdjacentHTML(
    "beforeend",
    `<div style="max-width:1220px;margin:16px auto;color:#b03e45;padding:0 20px;">Failed to load dashboard: ${err.message}</div>`
  );
});
