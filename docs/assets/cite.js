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
