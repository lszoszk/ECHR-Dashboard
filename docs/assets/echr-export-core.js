/* HUDOC Researcher — shared export primitives
 * ---------------------------------------------------------------------------
 * These three helpers are lifted from docs/assets/search-app.js, which is NOT
 * loaded on analytics.html (that page pulls only Chart.js and
 * pages-dashboard.js). Rather than load 280 KB of search-page runtime — it
 * self-bootstraps against DOM that does not exist there — the ~15 generic
 * lines are duplicated here.
 *
 * search-app.js is deliberately left alone. Refactoring it to consume this
 * file touches the search app's entire runtime and belongs in its own commit
 * with its own verification; accepting the duplication now is the smaller risk.
 *
 * Originals: _triggerDownload at search-app.js:5988, and the CSV serializer
 * inlined in the SheetJS catch block at :5959-5967.
 */
(function () {
  "use strict";

  /** Verbatim from search-app.js:5988. */
  function triggerDownload(blob, filename) {
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  /**
   * Array-of-arrays → CSV Blob. Same rules as the search export: quote every
   * cell, double internal quotes, prepend a BOM so Excel reads UTF-8 rather
   * than guessing a local codepage.
   */
  function rowsToCsvBlob(rows) {
    const csv = rows
      .map((row) =>
        row
          .map((cell) => `"${String(cell ?? "").replaceAll('"', '""')}"`)
          .join(",")
      )
      .join("\n");
    return new Blob([`﻿${csv}`], { type: "text/csv;charset=utf-8" });
  }

  function slugify(text) {
    return String(text || "")
      .toLowerCase()
      .trim()
      .replace(/[^\w\s-]/g, "")
      .replace(/\s+/g, "-")
      .replace(/-+/g, "-")
      .replace(/^-|-$/g, "");
  }

  window.EchrExport = {
    triggerDownload: triggerDownload,
    rowsToCsvBlob: rowsToCsvBlob,
    slugify: slugify,
  };
})();
