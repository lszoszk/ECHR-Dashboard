/* How to cite HUDOC Researcher: one source for the bottom bar's "Cite" button (#citeSiteBtn) and
   the About page's citation box ([data-cite-text] fills, [data-copy-cite="apa|bibtex"] copies).
   The DOI is Zenodo's concept DOI, which resolves to the latest archived version. */
(function () {
  "use strict";
  const DOI = "10.5281/zenodo.21319703";
  const CITATION = {
    doi: DOI,
    apa: `Szoszkiewicz, Ł., & Marcisz, S. (2026). HUDOC Researcher — ECtHR case-law search and RAG [Computer software]. Zenodo. https://doi.org/${DOI}`,
    bibtex: `@software{szoszkiewicz_marcisz_hudoc_researcher,
  author    = {Szoszkiewicz, {\\L}ukasz and Marcisz, Sebastian},
  title     = {{HUDOC Researcher} --- {ECtHR} Case-Law Search and {RAG}},
  year      = {2026},
  publisher = {Zenodo},
  doi       = {${DOI}},
  url       = {https://lszoszk.github.io/ECHR-Dashboard/}
}`,
  };
  window.HR_CITATION = CITATION;

  /* "About this file": what an export holds, when and where it came from, how to cite it and on what
     terms, as [label, value] rows. Excel exports put them on a second sheet, CSV files after the data;
     a PNG chart carries the one-line credit. info: {what, details: [[label, value]], url, data, notes}. */
  const SITE = "https://lszoszk.github.io/ECHR-Dashboard/";
  function exportedAt(d = new Date()) {
    const local = d.toLocaleString("en-GB", { day: "numeric", month: "long", year: "numeric",
      hour: "2-digit", minute: "2-digit", timeZoneName: "short" });
    return `${local} (${d.toISOString().slice(0, 16).replace("T", " ")} UTC)`;
  }
  function aboutRows(info = {}) {
    return [
      ["HUDOC Researcher \u2014 about this file", ""],
      ["", ""],
      ["Contents", info.what || ""],
      ...(info.details || []),
      ["Exported", exportedAt()],
      ["From", info.url || location.href],
      ...(info.data ? [["Data", info.data]] : []),
      ["", ""],
      ["How to cite this tool", CITATION.apa],
      ["How to cite the judgments", "From HUDOC (https://hudoc.echr.coe.int), the authoritative text, with the paragraph number, e.g. " +
        "Kud\u0142a v Poland [GC] App no 30210/96 (ECtHR, 26 October 2000), para 152 (OSCOLA)."],
      ...(info.notes || []),
      ["Source of the texts", "Judgments and their metadata: HUDOC, the database of the European Court of Human Rights. " +
        "\u00a9 Council of Europe / European Court of Human Rights, under the Court's terms for HUDOC content " +
        "(https://www.echr.coe.int/disclaimer); this project does not re-license them."],
      ["Licence of the curated data", "Segmentation into paragraphs, paragraph numbers, section labels, normalised metadata " +
        "and citation links: HUDOC Researcher, CC BY-NC-SA 4.0 (https://creativecommons.org/licenses/by-nc-sa/4.0/). " +
        "Reuse with attribution as above, non-commercial, under the same licence."],
      ["Disclaimer", "An independent research tool, not affiliated with the European Court of Human Rights, and not legal advice. " +
        "Check every passage on HUDOC before relying on it."],
      ["Authors and contact", "\u0141ukasz Szoszkiewicz and Sebastian Marcisz, Adam Mickiewicz University, Pozna\u0144 \u00b7 " +
        "l.szoszkiewicz@amu.edu.pl \u00b7 " + SITE],
    ];
  }
  /** The same rows after a CSV table, below an empty row. */
  function csvFooter(info) {
    return [[], ...aboutRows(info)];
  }
  /** One line for an image: the source as it is cited. */
  function creditLine(info = {}) {
    return `Source: Szoszkiewicz, \u0141., & Marcisz, S. (2026). HUDOC Researcher. https://doi.org/${DOI}` +
      ` \u00b7 Data: HUDOC, \u00a9 Council of Europe / ECtHR${info.data ? ` \u00b7 ${info.data}` : ""}`;
  }
  window.HR_EXPORT = { aboutRows, csvFooter, creditLine, site: SITE };

  function copy(text, button) {
    const done = () => {
      const label = button.textContent;
      button.textContent = "Copied";
      setTimeout(() => { button.textContent = label; }, 1400);
    };
    if (navigator.clipboard) navigator.clipboard.writeText(text).then(done, () => window.prompt("Copy the citation:", text));
    else window.prompt("Copy the citation:", text);
  }

  /* A HUDOC link to a paragraph carries the passage as a full-text term: HUDOC highlights it, but in
     recent judgments it does not scroll there. Following such a link also copies the passage, so that
     Find (Cmd/Ctrl+F) and paste reaches it; a short notice says so. */
  function passageOf(href) {
    const i = href.indexOf("#");
    if (i < 0 || !/^https:\/\/hudoc\.echr\.coe\.int\//.test(href)) return "";
    try {
      const hash = JSON.parse(decodeURI(href.slice(i + 1)));
      return String((hash.fulltext || [])[0] || "").replace(/^"|"$/g, "");
    } catch (_) { return ""; }
  }
  let noticeTimer = null;
  function notice(text) {
    let n = document.getElementById("hrNotice");
    if (!n) {
      n = document.createElement("div");
      n.id = "hrNotice";
      n.setAttribute("role", "status");
      n.style.cssText = "position:fixed;left:50%;bottom:calc(var(--bar-h,30px) + 16px);transform:translateX(-50%);" +
        "z-index:500;max-width:min(560px,calc(100vw - 32px));padding:10px 14px;background:var(--ink,#242328);" +
        "color:var(--paper,#faf8f3);font:0.85rem/1.45 var(--font-serif,Georgia,serif);box-shadow:0 6px 20px rgba(0,0,0,.2)";
      document.body.appendChild(n);
    }
    n.textContent = text;
    n.hidden = false;
    clearTimeout(noticeTimer);
    noticeTimer = setTimeout(() => { n.hidden = true; }, 6000);
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.addEventListener("click", (e) => {
      const a = e.target.closest && e.target.closest('a[href^="https://hudoc.echr.coe.int/"]');
      const passage = a ? passageOf(a.href) : "";
      if (!passage || !navigator.clipboard) return;
      const keys = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent) ? "\u2318F" : "Ctrl+F";
      navigator.clipboard.writeText(passage).then(() => notice(
        `The paragraph's opening words are copied. If HUDOC opens the judgment at the top, press ${keys} and paste: ` +
        "the passage is highlighted in yellow."), () => {});
    });
    document.querySelectorAll("[data-cite-text]").forEach((n) => { n.textContent = CITATION[n.dataset.citeText] || ""; });
    document.addEventListener("click", (e) => {
      const b = e.target.closest("#citeSiteBtn, [data-copy-cite]");
      if (!b) return;
      copy(CITATION[b.dataset.copyCite || "apa"], b);
    });
  });
})();
