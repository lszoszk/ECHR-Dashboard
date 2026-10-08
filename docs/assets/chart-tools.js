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
      ".chart-data-table{margin:.2rem 0 1rem;font-size:.85rem}" +
      ".chart-data-table summary{cursor:pointer;color:var(--text-muted,#6b7280);" +
      "padding:.25rem 0}" +
      ".chart-data-table table{width:100%;border-collapse:collapse;margin-top:.4rem}" +
      ".chart-data-table th,.chart-data-table td{text-align:left;padding:.3rem .6rem;" +
      "border-bottom:1px solid var(--border,#e2e8f0)}" +
      ".chart-data-table th{font-weight:600}" +
      ".chart-data-table .table-note{color:var(--text-muted,#6b7280);" +
      "font-size:.8rem;margin:.4rem 0 0}" +
      ".chart-data-wrap{max-height:22rem;overflow:auto}" +
      ".echr-cite{border:1px solid var(--rule,#d8d2c6);border-radius:4px;" +
      "background:var(--paper,#faf8f4);color:var(--ink,#1a1a1a);padding:1.1rem 1.2rem;" +
      "max-width:min(46rem,92vw)}" +
      ".echr-cite::backdrop{background:rgba(0,0,0,.35)}" +
      ".echr-cite h3{margin:0 0 .6rem;font-size:1.05rem}" +
      ".echr-cite-text{white-space:pre-wrap;word-break:break-word;font-size:.82rem;" +
      "line-height:1.5;background:var(--bg-card,#f1f5f9);padding:.7rem .8rem;" +
      "border-radius:3px;margin:0 0 .8rem;max-height:40vh;overflow:auto}" +
      ".echr-cite-actions{display:flex;gap:.45rem;flex-wrap:wrap}" +
      ".echr-cite-actions .export-btn{margin-left:0}" +
      "@media print{.chart-tools{display:none}.chart-data-table{display:none}}";
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
    b.dataset.needsData = "1";
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
      const cite = makeButton("CITE", "Copy an academic citation for this chart");
      cite.disabled = false; // citation does not depend on chart data
      cite.addEventListener("click", () => openCiteDialog(canvas));

      bar.appendChild(csv);
      bar.appendChild(png);
      bar.appendChild(cite);
      anchor.insertAdjacentElement("afterend", bar);

      describeCanvas(canvas);
      mountDataTable(canvas, bar);
    });
  }

  // --------------------------------------------------------- accessibility

  /**
   * Point the canvas at the section's existing prose.
   *
   * Every one of the 33 sections already carries a hand-written
   * <p class="chart-section-desc">. Giving those an id and referencing them
   * turns 33 good descriptions into screen-reader content for nothing — by far
   * the best value-per-line item here. The canvas itself gets role="img" and a
   * name; Chart.js sets neither.
   */
  let descSeq = 0;
  function describeCanvas(canvas) {
    canvas.setAttribute("role", "img");
    const section = canvas.closest(".chart-section");
    const desc = section && section.querySelector(".chart-section-desc");
    if (desc) {
      if (!desc.id) desc.id = "chart-desc-" + (++descSeq);
      const existing = canvas.getAttribute("aria-describedby");
      if (!existing) canvas.setAttribute("aria-describedby", desc.id);
    }
    // aria-label is refreshed in afterUpdate, once data exists.
    if (!canvas.getAttribute("aria-label")) {
      canvas.setAttribute("aria-label", chartTitleFor(canvas));
    }
  }

  /** "Bar chart, 63 data points, values from 1 to 1,503." */
  function summarise(chart) {
    try {
      const title = chartTitleFor(chart.canvas);
      const type = (chart.config && (chart.config.type || (chart.config._config || {}).type)) || "chart";
      const nums = [];
      (chart.data.datasets || []).forEach((ds) => {
        (ds.data || []).forEach((v) => {
          const n = typeof v === "object" && v !== null ? (v.v !== undefined ? v.v : v.y) : v;
          if (typeof n === "number" && isFinite(n)) nums.push(n);
        });
      });
      if (!nums.length) return title;
      const min = Math.min.apply(null, nums);
      const max = Math.max.apply(null, nums);
      const series = (chart.data.datasets || []).length;
      return title + ". " + type + " chart, " +
        (series > 1 ? series + " series, " : "") +
        nums.length + " data points, values from " +
        min.toLocaleString() + " to " + max.toLocaleString() + ".";
    } catch (e) {
      return chartTitleFor(chart.canvas);
    }
  }

  const TABLE_ROW_CAP = 250;

  /**
   * A <details> data table, built lazily on first open from the SAME
   * chartToRows() the CSV export uses — so the table and the download can
   * never disagree.
   *
   * Visible <details> rather than an .sr-only table on purpose: no sr-only
   * utility exists in any of this site's four stylesheets, and a disclosure
   * serves keyboard and low-vision users too, while keeping the DOM light
   * because nothing is built until it is opened.
   */
  function mountDataTable(canvas, bar) {
    const details = document.createElement("details");
    details.className = "chart-data-table";
    details.dataset.canvas = canvas.id;
    const summary = document.createElement("summary");
    summary.textContent = "View data as a table";
    details.appendChild(summary);
    const host = document.createElement("div");
    host.className = "chart-data-wrap";
    details.appendChild(host);

    details.addEventListener("toggle", () => {
      if (!details.open) return;
      if (host.dataset.built === "1" && bar.dataset.stale !== "1") return;
      buildTable(canvas.id, host);
      host.dataset.built = "1";
      bar.dataset.stale = "";
    });

    bar.insertAdjacentElement("afterend", details);
  }

  function buildTable(canvasId, host) {
    host.textContent = "";
    const chart = getChart(canvasId);
    const rows = chart ? chartToRows(chart) : [];
    if (rows.length < 2) {
      host.textContent = "No data available for this chart.";
      return;
    }
    const table = document.createElement("table");
    const thead = document.createElement("thead");
    const htr = document.createElement("tr");
    rows[0].forEach((h) => {
      const th = document.createElement("th");
      th.scope = "col";
      th.textContent = h;
      htr.appendChild(th);
    });
    thead.appendChild(htr);
    table.appendChild(thead);

    const tbody = document.createElement("tbody");
    const body = rows.slice(1);
    body.slice(0, TABLE_ROW_CAP).forEach((r) => {
      const tr = document.createElement("tr");
      r.forEach((cell, i) => {
        const td = document.createElement(i === 0 ? "th" : "td");
        if (i === 0) td.scope = "row";
        td.textContent = cell;
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    host.appendChild(table);

    if (body.length > TABLE_ROW_CAP) {
      const note = document.createElement("p");
      note.className = "table-note";
      note.textContent = "Showing the first " + TABLE_ROW_CAP + " of " +
        body.length.toLocaleString() + " rows — use CSV for the full data.";
      host.appendChild(note);
    }
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

  // ------------------------------------------------------------- citation

  /* Mirrors CITATION.cff at the repo root. That file is NOT published under
   * docs/, so it cannot be fetched at runtime — this is a manual copy and will
   * drift if CITATION.cff is updated without updating here. */
  const CITATION = {
    authors: "Szoszkiewicz, Ł., & Marcisz, S.",
    year: "2026",
    title: "HUDOC Researcher — ECtHR Case-Law Search & RAG",
    version: "1.0.0",
    doi: "10.5281/zenodo.21319703",
    url: "https://lszoszk.github.io/ECHR-Dashboard/",
  };

  function sectionAnchorFor(canvas) {
    const section = canvas.closest(".chart-section");
    return section && section.id ? section.id : "";
  }

  function chartPermalink(canvas) {
    const anchor = sectionAnchorFor(canvas);
    const u = new URL(window.location.href);
    u.search = "";
    u.hash = anchor ? "#" + anchor : "";
    return u.toString();
  }

  function citationText(canvas) {
    const chartTitle = chartTitleFor(canvas);
    const snapshot = snapshotDate();
    return `${CITATION.authors} (${CITATION.year}). ${CITATION.title} ` +
      `(Version ${CITATION.version}) [Software]. Zenodo. ` +
      `https://doi.org/${CITATION.doi}. ` +
      `Figure: “${chartTitle}”, data snapshot ${snapshot}. ` +
      `Retrieved from ${chartPermalink(canvas)}`;
  }

  function bibtexText(canvas) {
    const snapshot = snapshotDate();
    return `@software{hudoc_researcher,\n` +
      `  author  = {Szoszkiewicz, Łukasz and Marcisz, Sebastian},\n` +
      `  title   = {${CITATION.title}},\n` +
      `  year    = {${CITATION.year}},\n` +
      `  version = {${CITATION.version}},\n` +
      `  doi     = {${CITATION.doi}},\n` +
      `  url     = {${CITATION.url}},\n` +
      `  note    = {Figure: ${chartTitleFor(canvas)}; data snapshot ${snapshot}}\n` +
      `}`;
  }

  function copyText(text, btn) {
    const done = () => {
      const old = btn.textContent;
      btn.textContent = "Copied";
      setTimeout(() => { btn.textContent = old; }, 1400);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done, () => fallbackCopy(text, done));
    } else {
      fallbackCopy(text, done);
    }
  }

  function fallbackCopy(text, done) {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand("copy"); done(); } catch (e) { /* ignore */ }
    ta.remove();
  }

  function openCiteDialog(canvas) {
    const existing = document.getElementById("echr-cite-dialog");
    if (existing) existing.remove();

    const supportsDialog = typeof window.HTMLDialogElement !== "undefined";
    const box = document.createElement(supportsDialog ? "dialog" : "div");
    box.id = "echr-cite-dialog";
    box.className = "echr-cite";
    if (!supportsDialog) box.setAttribute("role", "dialog");
    box.setAttribute("aria-label", "Cite this chart");

    const h = document.createElement("h3");
    h.textContent = "Cite this chart";

    const pre = document.createElement("pre");
    pre.className = "echr-cite-text";
    pre.textContent = citationText(canvas);

    const actions = document.createElement("div");
    actions.className = "echr-cite-actions";

    const copyCit = document.createElement("button");
    copyCit.type = "button";
    copyCit.className = "export-btn";
    copyCit.textContent = "Copy citation";
    copyCit.addEventListener("click", () => copyText(pre.textContent, copyCit));

    const copyLink = document.createElement("button");
    copyLink.type = "button";
    copyLink.className = "export-btn";
    copyLink.textContent = "Copy link";
    copyLink.addEventListener("click", () => copyText(chartPermalink(canvas), copyLink));

    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "export-btn";
    toggle.textContent = "BibTeX";
    let showingBibtex = false;
    toggle.addEventListener("click", () => {
      showingBibtex = !showingBibtex;
      pre.textContent = showingBibtex ? bibtexText(canvas) : citationText(canvas);
      toggle.textContent = showingBibtex ? "Plain" : "BibTeX";
    });

    const close = document.createElement("button");
    close.type = "button";
    close.className = "export-btn";
    close.textContent = "Close";
    close.addEventListener("click", () => {
      if (supportsDialog && box.close) box.close();
      box.remove();
    });

    actions.appendChild(copyCit);
    actions.appendChild(copyLink);
    actions.appendChild(toggle);
    actions.appendChild(close);
    box.appendChild(h);
    box.appendChild(pre);
    box.appendChild(actions);
    document.body.appendChild(box);

    if (supportsDialog && box.showModal) {
      box.addEventListener("close", () => box.remove());
      box.showModal();
    }
    copyCit.focus();
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

    // Chart.js animates by default. Honour the OS setting.
    try {
      if (window.matchMedia &&
          window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
        window.Chart.defaults.animation = false;
      }
    } catch (e) { /* ignore */ }

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
          // Only the data-dependent buttons; CITE works with or without data.
          bar.querySelectorAll('button[data-needs-data="1"]')
             .forEach((b) => { b.disabled = !hasData; });
          bar.dataset.stale = "1"; // consumed by the a11y data table

          // Refresh the accessible name now that the data exists, and again
          // whenever the chart is rebuilt from a dropdown change.
          chart.canvas.setAttribute("aria-label", summarise(chart));

          // If the table is open while the chart changes underneath it, rebuild
          // in place rather than leaving stale numbers on screen.
          const details = document.querySelector(
            '.chart-data-table[data-canvas="' + CSS.escape(id) + '"]'
          );
          if (details && details.open) {
            const host = details.querySelector(".chart-data-wrap");
            if (host) { buildTable(id, host); bar.dataset.stale = ""; }
          }
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
