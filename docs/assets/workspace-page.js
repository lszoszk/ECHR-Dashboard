/* Workspace page: lists the saved paragraphs (with their notes) and saved searches kept by
   assets/workspace.js, and exports or imports them. */
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const day = (iso) => (iso ? new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }) : "");

  function download(name, text, type) {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([text], { type }));
    a.download = name;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 0);
  }

  function paragraphCard(p) {
    const head = `${esc(p.title)}${p.paraNo != null ? `, § ${esc(p.paraNo)}` : ""}`;
    return `<li class="ws-item" data-key="${esc(p.key)}">
      <div class="ws-item-head"><span class="ws-item-title">${head}</span>
        <button type="button" class="ws-del" data-del-para="${esc(p.key)}" title="Remove from the Workspace" aria-label="Remove">×</button></div>
      <div class="ws-meta">${[p.section, p.date, p.appnos ? `no. ${p.appnos}` : "", `saved ${day(p.addedAt)}`].filter(Boolean).map(esc).join(" · ")}</div>
      ${p.machineTranslation ? `<div class="ws-mt">Only in French on HUDOC · machine translation, unofficial</div>` : ""}
      <blockquote class="ws-text">${esc(p.text)}</blockquote>
      <div class="ws-cite"><code>${esc((p.citation || "").split("\n")[0])}</code>
        <button type="button" class="ws-btn" data-copy-cite="${esc(p.key)}">Copy citation</button>
        ${p.url ? `<a class="ws-btn" href="${esc(p.url)}" target="_blank" rel="noopener">HUDOC ↗</a>` : ""}
        <a class="ws-btn" href="./?q=${encodeURIComponent("hudoc:" + p.caseId)}">Open in Search</a></div>
      <label class="ws-note-label" for="note-${esc(p.key)}">Note</label>
      <textarea class="ws-note" id="note-${esc(p.key)}" data-note-for="${esc(p.key)}" rows="2"
        placeholder="Your note on this paragraph — saved as you type">${esc(p.note || "")}</textarea>
    </li>`;
  }

  function searchRow(s) {
    return `<li class="ws-item ws-search">
      <div class="ws-item-head"><a class="ws-item-title" href="./?q=${encodeURIComponent(s.q || "")}&run=${encodeURIComponent(s.id)}">${esc(s.name)}</a>
        <button type="button" class="ws-del" data-del-search="${esc(s.id)}" title="Remove from the Workspace" aria-label="Remove">×</button></div>
      <div class="ws-meta"><code>${esc(s.q || "(no query)")}</code>${s.summary ? ` · ${esc(s.summary)}` : ""} · saved ${esc(day(s.savedAt))}</div>
      <a class="ws-btn ws-run" href="./?q=${encodeURIComponent(s.q || "")}&run=${encodeURIComponent(s.id)}">Run this search →</a>
    </li>`;
  }

  function render() {
    const ws = window.ECHRWorkspace;
    const d = ws.data();
    const n = d.paragraphs.length + d.searches.length;
    $("wsCount").textContent = `${n} item${n === 1 ? "" : "s"} in your workspace`;
    $("wsExportMd").disabled = $("wsExportJson").disabled = !n;
    $("wsParaCount").textContent = `(${d.paragraphs.length})`;
    $("wsSearchCount").textContent = `(${d.searches.length})`;
    $("wsParagraphs").innerHTML = d.paragraphs.length
      ? `<ol class="ws-list">${d.paragraphs.slice().reverse().map(paragraphCard).join("")}</ol>`
      : `<p class="ws-empty">Click ☆ next to a paragraph in the <a href="./">search results</a> to keep it here, with its citation and a note.</p>`;
    $("wsSearches").innerHTML = d.searches.length
      ? `<ol class="ws-list">${d.searches.slice().reverse().map(searchRow).join("")}</ol>`
      : `<p class="ws-empty">Use “☆ Save search” above the search results to keep a query together with its filters.</p>`;
  }

  document.addEventListener("DOMContentLoaded", () => {
    const ws = window.ECHRWorkspace;
    if (!ws) return;
    render();
    ws.onChange(() => { if (!document.activeElement || !document.activeElement.classList.contains("ws-note")) render(); });

    document.querySelector(".ws-shell").addEventListener("click", (e) => {
      const t = e.target;
      if (t.dataset.delPara) { ws.removeParagraph(t.dataset.delPara); return; }
      if (t.dataset.delSearch) { ws.removeSearch(t.dataset.delSearch); return; }
      if (t.dataset.copyCite) {
        const p = ws.data().paragraphs.find((x) => x.key === t.dataset.copyCite);
        if (p) navigator.clipboard?.writeText(p.citation || "").then(() => {
          t.textContent = "Copied"; setTimeout(() => { t.textContent = "Copy citation"; }, 1400);
        });
      }
    });
    let timer;
    document.querySelector(".ws-shell").addEventListener("input", (e) => {
      const ta = e.target.closest("[data-note-for]");
      if (!ta) return;
      clearTimeout(timer);
      timer = setTimeout(() => ws.setNote(ta.dataset.noteFor, ta.value), 500);
    });
    document.querySelector(".ws-shell").addEventListener("focusout", (e) => {
      const ta = e.target.closest && e.target.closest("[data-note-for]");
      if (ta) { clearTimeout(timer); ws.setNote(ta.dataset.noteFor, ta.value); }
    });

    const stamp = () => new Date().toISOString().slice(0, 10);
    $("wsExportMd").addEventListener("click", () => download(`hudoc-researcher-workspace-${stamp()}.md`, ws.exportMarkdown(), "text/markdown"));
    $("wsExportJson").addEventListener("click", () => download(`hudoc-researcher-workspace-${stamp()}.json`, ws.exportJSON(), "application/json"));
    $("wsImport").addEventListener("click", () => $("wsImportFile").click());
    $("wsImportFile").addEventListener("change", async () => {
      const file = $("wsImportFile").files[0];
      $("wsImportFile").value = "";
      if (!file) return;
      try {
        const added = ws.importJSON(await file.text());
        ws.toast(`Imported ${added.paragraphs} paragraph${added.paragraphs === 1 ? "" : "s"} and ${added.searches} search${added.searches === 1 ? "" : "es"}.`);
      } catch (err) {
        ws.toast(`Could not import this file: ${err.message}`);
      }
    });
  });
})();
