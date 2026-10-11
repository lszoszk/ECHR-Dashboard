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

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-cite-text]").forEach((n) => { n.textContent = CITATION[n.dataset.citeText] || ""; });
    document.addEventListener("click", (e) => {
      const b = e.target.closest("#citeSiteBtn, [data-copy-cite]");
      if (!b) return;
      copy(CITATION[b.dataset.copyCite || "apa"], b);
    });
  });
})();
