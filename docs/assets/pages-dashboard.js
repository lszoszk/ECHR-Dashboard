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

async function loadDashboard() {
  const res = await fetch("data/stats.json", { cache: "no-store" });
  if (!res.ok) throw new Error(`Failed to load dashboard data (${res.status})`);
  const data = await res.json();

  document.getElementById("metaSource").textContent = `Source: ${data.source_file || "-"}`;
  document.getElementById("metaGenerated").textContent = `Generated: ${formatDateForMeta(data.generated_at)}`;

  const s = data.summary;
  const kpiGrid = document.getElementById("kpiGrid");
  kpiGrid.innerHTML = [
    makeKpi("Total Cases", fmtInt.format(s.total_cases)),
    makeKpi("Total Paragraphs", fmtInt.format(s.total_paragraphs)),
    makeKpi("Date Range", s.date_range_label, `${fmtInt.format(s.dated_cases)} dated · ${fmtInt.format(s.undated_cases)} undated`),
    makeKpi("Respondent States", fmtInt.format(s.unique_countries)),
    makeKpi("Distinct Articles", fmtInt.format(s.unique_articles)),
    makeKpi("Avg Paragraphs / Case", s.avg_paragraphs_per_case.toFixed(1)),
    makeKpi("Median Paragraphs / Case", Math.round(s.median_paragraphs_per_case).toString()),
    makeKpi("P90 Paragraphs / Case", Math.round(s.p90_paragraphs_per_case).toString()),
    makeKpi("Grand Chamber Share", `${s.grand_chamber_share.toFixed(1)}%`, `${fmtInt.format(s.grand_chamber_cases)} of ${fmtInt.format(s.total_cases)} cases`),
    makeKpi("Violations / Non-violations", `${fmtInt.format(s.violation_cases)} / ${fmtInt.format(s.non_violation_cases)}`),
  ].join("");

  const series = data.series;
  const rankings = data.rankings;

  createBarChart(
    document.getElementById("casesMonthChart"),
    series.cases_by_month.map((d) => d[0]),
    series.cases_by_month.map((d) => d[1]),
    { colors: ["#245ea8"] }
  );

  createLineChart(
    document.getElementById("casesYearChart"),
    series.cases_by_year.map((d) => d[0]),
    series.cases_by_year.map((d) => d[1]),
    "#d97a2b"
  );

  createBarChart(
    document.getElementById("countriesChart"),
    rankings.countries_top.map((d) => d[0]),
    rankings.countries_top.map((d) => d[1]),
    { horizontal: true }
  );

  createBarChart(
    document.getElementById("articlesChart"),
    rankings.articles_top.map((d) => `Art. ${d[0]}`),
    rankings.articles_top.map((d) => d[1]),
    { horizontal: true, colors: ["#3c8d5a"] }
  );

  createBarChart(
    document.getElementById("sectionsChart"),
    rankings.sections.map((d) => d[0]),
    rankings.sections.map((d) => d[1]),
    { horizontal: true }
  );

  createLineChart(
    document.getElementById("paragraphsMonthChart"),
    series.paragraphs_by_month.map((d) => d[0]),
    series.paragraphs_by_month.map((d) => d[1]),
    "#6c5db5"
  );

  new Chart(document.getElementById("chamberChart"), {
    type: "doughnut",
    data: {
      labels: series.chamber_breakdown.map((d) => d[0]),
      datasets: [
        {
          data: series.chamber_breakdown.map((d) => d[1]),
          backgroundColor: ["#245ea8CC", "#3c8d5aCC", "#8c8c8cCC"],
          borderColor: ["#245ea8", "#3c8d5a", "#8c8c8c"],
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

  createBarChart(
    document.getElementById("lengthChart"),
    series.case_length_snapshot.map((d) => d[0]),
    series.case_length_snapshot.map((d) => Math.round(d[1])),
    { colors: ["#4f7ca6", "#245ea8", "#d97a2b", "#b03e45"] }
  );
}

loadDashboard().catch((err) => {
  console.error(err);
  document.body.insertAdjacentHTML(
    "beforeend",
    `<div style="max-width:1220px;margin:16px auto;color:#b03e45;padding:0 20px;">Failed to load dashboard: ${err.message}</div>`
  );
});
