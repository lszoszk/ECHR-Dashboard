/* HUDOC Researcher — per-chart CSV / PNG export for the Statistics page
 * ---------------------------------------------------------------------------
 * Adds a small toolbar under every chart. Modelled on the sibling app
 * lszoszk.github.io/hrc-voting, which offers CSV + PNG on each of its charts;
 * this page had 40 charts and no export at all.
 *
 * WHY THE SWEEP IS PER CANVAS, NOT PER SECTION
 * analytics.html has 33 .chart-section blocks but four different inner shapes:
 * 5 sections hold no canvas (KPI grids, tables, two "coming soon"
 * placeholders), 7 use <article class="chart-container"> instead of
 * .chart-canvas-wrap, 3 hold two canvases, and stats-judgment-types holds six.
 * Iterating canvases instead of sections removes every one of those special
 * cases: a section with no canvas is simply never visited, and the six-chart
 * section gets six toolbars, one under each chart.
 *
 * WHY DOM IS MOUNTED BEFORE CHARTS EXIST
 * The .chart-container canvases are responsive with only a max-height, so
 * inserting elements into their parent AFTER Chart.js has measured itself can
 * start a resize↔insert feedback loop. Mounting on DOMContentLoaded means
 * layout is settled before Chart.js ever measures.
 */
(function () {
  "use strict";

  const HAS_EXPORT = typeof window.EchrExport !== "undefined";

  // ------------------------------------------------------------------ utils

  /** Snapshot date of the underlying stats build, for filenames. */
  function snapshotDate() {
    try {
      const meta = window.EchrStatsMeta;
      if (meta && meta.generated_at) return String(meta.generated_at).slice(0, 10);
    } catch (e) { /* fall through */ }
    return new Date().toISOString().slice(0, 10);
  }

  /**
   * Human title for a chart. Four markup variants, and the <h2> often carries
   * a trailing 🔗 share button whose text would otherwise end up in filenames.
   */
  function chartTitleFor(canvas) {
    const local = canvas.closest(".chart-container, .compare-chart-wrap");
    if (local) {
      const t = local.querySelector(".chart-title, .chart-subtitle");
      if (t) return cleanText(t);
    }
    // Second chart in a two-chart section is titled by an h3 sibling.
    let node = (canvas.closest(".chart-canvas-wrap") || canvas).previousElementSibling;
    while (node) {
      if (node.classList && node.classList.contains("chart-section-subtitle")) return cleanText(node);
      if (node.classList && node.classList.contains("chart-section-title")) break;
      node = node.previousElementSibling;
    }
    const section = canvas.closest(".chart-section");
    const h2 = section && section.querySelector(".chart-section-title");
    if (h2) return cleanText(h2);
    return canvas.id || "chart";
  }

  /** textContent with any nested <button> (the share glyph) removed. */
  function cleanText(el) {
    const clone = el.cloneNode(true);
    clone.querySelectorAll("button").forEach((b) => b.remove());
    return clone.textContent.replace(/\s+/g, " ").trim();
  }

  function fileBase(canvas) {
    const slug = HAS_EXPORT ? window.EchrExport.slugify(chartTitleFor(canvas)) : canvas.id;
    return `echr-${slug || canvas.id}-${snapshotDate()}`;
  }

  // -------------------------------------------------------------- CSV shape

  /**
   * Chart → array-of-arrays. Shared with the accessibility data table so the
   * table and the download can never disagree.
   *
   * Wide format (one row per label, one column per dataset) for the 39
   * categorical charts: every multi-dataset chart here is a grouped bar or
   * multi-line over a SHARED label axis, so the matrix is dense and opens
   * correctly in Excel.
   */
  function chartToRows(chart) {
    const data = chart && chart.data;
    if (!data || !Array.isArray(data.datasets) || !data.datasets.length) return [];

    const first = data.datasets[0].data || [];
    const isPointObjects = first.length && typeof first[0] === "object" && first[0] !== null &&
                           !Array.isArray(first[0]) && "x" in first[0];

    if (isPointObjects) return pointRows(chart);

    const labels = data.labels || [];
    const title = chartTitleFor(chart.canvas);
    const header = ["Label"].concat(
      data.datasets.map((ds, i) => ds.label || (data.datasets.length === 1 ? title : "Series " + (i + 1)))
    );
    const rows = [header];
    for (let i = 0; i < labels.length; i++) {
      rows.push([labels[i]].concat(data.datasets.map((ds) => valueAt(ds.data, i))));
    }
    return rows;
  }

  function valueAt(arr, i) {
    const v = Array.isArray(arr) ? arr[i] : undefined;
    if (v === null || v === undefined) return "";
    if (typeof v === "object") return v.y !== undefined ? v.y : JSON.stringify(v);
    return v;
  }

  /**
   * Long format for the one scatter/bubble chart (citationHeatmapChart).
   *
   * Its axis labels are article names produced by ticks.callback, and the real
   * citation count rides along as `v` (see the `v: d.v` line in
   * pages-dashboard.js) — `r` is a bubble RADIUS derived from it, so exporting
   * chart.data naively would emit radii. Recovering v by inverting the radius
   * formula would be lossy and would couple this file to a rendering constant.
   */
  function pointRows(chart) {
    const ds = chart.data.datasets[0];
    const xs = chart.scales && chart.scales.x;
    const ys = chart.scales && chart.scales.y;
    const xTitle = (xs && xs.options && xs.options.title && xs.options.title.text) || "X";
    const yTitle = (ys && ys.options && ys.options.title && ys.options.title.text) || "Y";
    const hasV = (ds.data || []).some((p) => p && p.v !== undefined);

    const rows = [[yTitle, xTitle, hasV ? "Value" : "Size"]];
    (ds.data || []).forEach((p) => {
      if (!p) return;
      rows.push([tickLabel(ys, p.y), tickLabel(xs, p.x), hasV ? p.v : p.r]);
    });
    return rows;
  }

  function tickLabel(scale, value) {
    try {
      const cb = scale && scale.options && scale.options.ticks && scale.options.ticks.callback;
      if (typeof cb === "function") {
        const out = cb.call(scale, value);
        if (out !== undefined && out !== null && out !== "") return out;
      }
    } catch (e) { /* fall through to the raw value */ }
    return value;
  }

  // ------------------------------------------------------------------- PNG

  /**
   * Composite offscreen at export time — no background plugin, and none of the
   * five chart-creation helpers in pages-dashboard.js are touched.
   *
   * Background is ALWAYS white regardless of theme: Chart.js is never given a
   * theme-aware Chart.defaults.color anywhere on this page, so ticks and legend
   * text are drawn in its default dark grey in both light and dark mode.
   * Compositing onto the dark card colour would produce an illegible export.
   * White is also the right choice for print and for pasting into a document.
   */
  function chartToPngBlob(chart, title, cb) {
    const src = chart.canvas;
    const dpr = chart.currentDevicePixelRatio || window.devicePixelRatio || 1;
    const footer = Math.round(34 * dpr);
    const out = document.createElement("canvas");
    out.width = src.width;
    out.height = src.height + footer;

    const ctx = out.getContext("2d");
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, out.width, out.height);
    ctx.drawImage(src, 0, 0);

    ctx.fillStyle = "#555555";
    ctx.font = Math.round(12 * dpr) + "px Inter, system-ui, sans-serif";
    ctx.textBaseline = "middle";
    const pad = Math.round(10 * dpr);
    ctx.fillText(title, pad, src.height + footer / 2);
    const credit = "HUDOC Researcher · " + snapshotDate();
    const w = ctx.measureText(credit).width;
    ctx.fillText(credit, out.width - w - pad, src.height + footer / 2);

    out.toBlob(cb, "image/png");
  }

  // --------------------------------------------------------------- toolbar

  function injectStyles() {
    if (document.getElementById("echr-chart-tools-styles")) return;
    const css =
      ".chart-tools{display:flex;gap:.4rem;justify-content:flex-end;" +
      "align-items:center;margin:.35rem 0 .2rem}" +
      // .export-btn carries margin-left:auto in two stylesheets, which would
      // shove the first button around inside a flex toolbar.
      ".chart-tools .export-btn{margin-left:0}" +
      ".chart-tools button[disabled]{opacity:.4;cursor:default}" +
      "@media print{.chart-tools{display:none}}";
    const style = document.createElement("style");
    style.id = "echr-chart-tools-styles";
    style.textContent = css;
    document.head.appendChild(style);
  }

  function makeButton(label, title) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "export-btn";
    b.textContent = label;
    b.title = title;
    b.disabled = true; // enabled once the chart actually exists
    return b;
  }

  function mountChartTools() {
    injectStyles();
    const canvases = document.querySelectorAll("#statsMain canvas[id]");
    canvases.forEach((canvas) => {
      const anchor = canvas.closest(".chart-canvas-wrap") || canvas;
      if (anchor.nextElementSibling &&
          anchor.nextElementSibling.classList.contains("chart-tools")) return;

      const bar = document.createElement("div");
      bar.className = "chart-tools";
      bar.dataset.canvas = canvas.id;

      const csv = makeButton("CSV", "Download this chart's data as CSV");
      csv.addEventListener("click", () => exportCsv(canvas.id));
      const png = makeButton("PNG", "Download this chart as a PNG image");
      png.addEventListener("click", () => exportPng(canvas.id));

      bar.appendChild(csv);
      bar.appendChild(png);
      anchor.insertAdjacentElement("afterend", bar);
    });
  }

  function toolbarFor(canvasId) {
    return document.querySelector('.chart-tools[data-canvas="' + CSS.escape(canvasId) + '"]');
  }

  /** Charts are resolved at CLICK time, never captured: three canvases on this
   *  page are destroyed and recreated when their <select> changes. */
  function getChart(canvasId) {
    try {
      return window.Chart && window.Chart.getChart ? window.Chart.getChart(canvasId) : null;
    } catch (e) {
      return null;
    }
  }

  function exportCsv(canvasId) {
    const chart = getChart(canvasId);
    if (!chart || !HAS_EXPORT) return;
    const rows = chartToRows(chart);
    if (!rows.length) return;
    window.EchrExport.triggerDownload(
      window.EchrExport.rowsToCsvBlob(rows),
      fileBase(chart.canvas) + ".csv"
    );
  }

  function exportPng(canvasId) {
    const chart = getChart(canvasId);
    if (!chart || !HAS_EXPORT) return;
    const title = chartTitleFor(chart.canvas);
    chartToPngBlob(chart, title, (blob) => {
      if (blob) window.EchrExport.triggerDownload(blob, fileBase(chart.canvas) + ".png");
    });
  }

  // ---------------------------------------------------------------- plugin

  /**
   * Enables a toolbar once its chart exists, and again whenever the chart is
   * rebuilt.
   *
   * afterUpdate, NOT afterRender: the latter fires from draw() on every
   * animation frame. afterUpdate fires once per construction and once per
   * .update(), i.e. exactly when the data changed.
   *
   * The whole body is wrapped: an exception thrown inside a globally
   * registered plugin propagates through Chart.update() and would break
   * rendering for every chart on the page.
   */
  function registerPlugin() {
    if (!window.Chart || !window.Chart.register) return;
    window.Chart.register({
      id: "echrChartTools",
      afterUpdate: function (chart) {
        try {
          const id = chart.canvas && chart.canvas.id;
          if (!id) return;
          const bar = toolbarFor(id);
          if (!bar) return;
          const hasData = !!(chart.data && chart.data.datasets &&
                             chart.data.datasets.some((d) => (d.data || []).length));
          bar.querySelectorAll("button").forEach((b) => { b.disabled = !hasData; });
          bar.dataset.stale = "1"; // consumed by the a11y data table
        } catch (e) {
          console.warn("[chart-tools] afterUpdate:", e);
        }
      },
    });
  }

  registerPlugin();

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mountChartTools);
  } else {
    mountChartTools();
  }

  // Exposed for the accessibility layer, which reuses chartToRows.
  window.EchrChartTools = {
    chartToRows: chartToRows,
    chartTitleFor: chartTitleFor,
    getChart: getChart,
  };
})();
