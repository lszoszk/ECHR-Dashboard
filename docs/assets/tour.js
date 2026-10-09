/* A one-minute tour of HUDOC Researcher (five slides), as on the HRC voting dashboard.
   Opens by itself on the first visit to the Search page; the "✦ tour" button of the bottom
   bar (#tourBtn) reopens it on any page. Self-contained: its own styles, live figures from the
   API with static fallbacks. */
(function () {
  "use strict";
  const API = (() => {
    const PRODUCTION = "https://150.254.115.204/echr-api/api";
    try {
      if (location.hostname !== "127.0.0.1" && location.hostname !== "localhost") return PRODUCTION;
      const qp = new URLSearchParams(location.search).get("api");
      if (qp) return qp.replace(/\/+$/, "");
      const ls = localStorage.getItem("echrApiBase");
      return ls ? ls.replace(/\/+$/, "") : `http://${location.hostname}:8000/api`;
    } catch (_) { return PRODUCTION; }
  })();
  const DONE_KEY = "echr-tour-done";
  const onSearchPage = !!document.getElementById("searchInput");
  const fmt = (n) => Number(n).toLocaleString("en-GB");
  const EXAMPLES = ['"margin of appreciation" article:10', 'violation:3 "police custody"', "cites:hatton"];

  const CSS = `
  .tourwrap{position:fixed;inset:0;z-index:400;display:none;align-items:center;justify-content:center;padding:16px;
    background:color-mix(in srgb,var(--ink,#242328) 38%,transparent)}
  .tourwrap.open{display:flex}
  .tour-box{width:min(720px,100%);max-height:calc(100vh - 32px);display:flex;flex-direction:column;overflow:hidden;
    background:var(--paper,#faf8f3);color:var(--ink,#242328);border:1px solid var(--ink,#242328);box-shadow:0 3px 0 rgba(36,35,40,.18)}
  .tour-slides{position:relative;flex:1;overflow:auto;padding:28px 30px 18px}
  .tslide{display:none}.tslide.on{display:block}
  .tour-kicker{font-family:var(--font-mono,'JetBrains Mono',ui-monospace,monospace);font-size:.68rem;letter-spacing:.1em;
    text-transform:uppercase;color:var(--garnet,#8d2f2f);margin-bottom:10px}
  .tour-h{margin:0 0 12px;font-family:var(--font-serif,'Source Serif 4',Georgia,serif);font-weight:500;font-size:1.7rem;line-height:1.2}
  .tour-lead{font-family:var(--font-serif,'Source Serif 4',Georgia,serif);font-size:1rem;line-height:1.6;color:var(--ink-2,#3d3c42);max-width:600px}
  .tour-stats{display:flex;flex-wrap:wrap;gap:12px 30px;margin:18px 0 10px}
  .tour-stats b{display:block;font-family:var(--font-serif,'Source Serif 4',Georgia,serif);font-weight:500;font-size:1.5rem}
  .tour-stats span{font-family:var(--font-mono,'JetBrains Mono',monospace);font-size:.62rem;letter-spacing:.08em;text-transform:uppercase;color:var(--ink-3,#706d72)}
  .tour-spark{display:flex;align-items:flex-end;gap:1px;height:56px;margin-top:8px}
  .tour-spark i{flex:1;background:var(--garnet,#8d2f2f);opacity:.75;min-height:1px}
  .tour-cap{margin-top:6px;font-family:var(--font-mono,monospace);font-size:.64rem;color:var(--ink-3,#706d72)}
  .tour-list{list-style:none;margin:14px 0 0;padding:0}
  .tour-list li{display:grid;grid-template-columns:34px 1fr;gap:2px 10px;padding:8px 0;border-top:1px solid var(--rule,#d8d0c3)}
  .tour-list li:first-child{border-top:0}
  .tour-list .n{font-family:var(--font-mono,monospace);font-size:.7rem;color:var(--ink-3,#706d72);padding-top:3px}
  .tour-list b{font-family:var(--font-serif,'Source Serif 4',Georgia,serif);font-weight:600}
  .tour-list span{font-family:var(--font-serif,'Source Serif 4',Georgia,serif);color:var(--ink-2,#3d3c42)}
  .tour-list .x{font-family:var(--font-mono,monospace);font-size:.6rem;letter-spacing:.08em;text-transform:uppercase;color:var(--garnet,#8d2f2f)}
  .tour-chips{display:flex;flex-wrap:wrap;gap:8px;margin-top:16px}
  .tour-chips button,.tour-go a{cursor:pointer;font-family:var(--font-mono,monospace);font-size:.76rem;color:var(--ink-2,#3d3c42);
    background:var(--paper-3,#ebe6dc);border:1px solid var(--rule,#d8d0c3);padding:4px 9px;text-decoration:none}
  .tour-chips button:hover,.tour-go a:hover{color:var(--garnet,#8d2f2f);border-color:var(--garnet,#8d2f2f)}
  .tour-go{display:flex;flex-direction:column;align-items:flex-start;gap:10px;margin-top:18px}
  .tour-go a{font-size:.86rem;padding:7px 12px}
  .tour-nav{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 30px;border-top:1px solid var(--rule,#d8d0c3);
    background:var(--paper-2,#f4f1ea)}
  .tour-nav button{cursor:pointer;background:none;border:0;font-family:var(--font-mono,monospace);font-size:.72rem;letter-spacing:.08em;
    text-transform:uppercase;color:var(--ink-2,#3d3c42)}
  .tour-nav #tour-next{color:var(--garnet,#8d2f2f);font-weight:600}
  .tour-dots{display:flex;gap:8px}
  .tour-dots .tdot{width:7px;height:7px;padding:0;border-radius:50%;background:var(--rule,#d8d0c3)}
  .tour-dots .tdot.on{background:var(--garnet,#8d2f2f)}
  @media (max-width:600px){.tour-slides{padding:22px 18px 14px}.tour-h{font-size:1.35rem}.tour-nav{padding:10px 18px}}`;

  function slides(stats, years) {
    const s = stats || {};
    const from = /(\d{4})$/.exec(s.date_from || "")?.[1] || "1960";
    const to = /(\d{4})$/.exec(s.date_to || "")?.[1] || "2026";
    let spark = "";
    if (years && years.length) {
      const counts = years.filter((y) => Number(y.year) > 1900);
      const max = Math.max(...counts.map((y) => y.count));
      spark = `<div class="tour-spark" aria-hidden="true">${counts.map((y) =>
        `<i style="height:${Math.max(2, Math.round((y.count / max) * 100))}%" title="${y.year}: ${fmt(y.count)}"></i>`).join("")}</div>
        <div class="tour-cap">Judgments per year, ${counts[0].year}–${counts[counts.length - 1].year}.</div>`;
    }
    return [
      `<div class="tour-kicker">First time here · a one-minute tour</div>
       <h2 class="tour-h">The Court's judgments, paragraph by paragraph.</h2>
       <div class="tour-lead">Every judgment of the European Court of Human Rights in English, split into the Court's own
         numbered paragraphs — so a search lands on the paragraph you will cite, with a link to HUDOC, the authoritative source.</div>
       <div class="tour-stats">
         <div><b>${fmt(s.total_judgments || 20086)}</b><span>judgments</span></div>
         <div><b>${fmt(s.citable_paragraphs || 1343080)}</b><span>numbered paragraphs</span></div>
         <div><b>${fmt(s.total_countries || 46)}</b><span>respondent States</span></div>
         <div><b>${from}–${to}</b><span>years covered</span></div>
       </div>${spark}`,
      `<div class="tour-kicker">The views</div>
       <h2 class="tour-h">Five ways in.</h2>
       <ul class="tour-list">
         <li><span class="n">01</span><div><b>Search</b> <span>— full text at paragraph level, with HUDOC's operators, the parts of
           the judgment to search in, filters, and each judgment's Cites / Cited by.</span></div></li>
         <li><span class="n">02</span><div><b>Semantic Search</b> <span class="x">experimental</span> <span>— describe a case in plain language;
           it runs on its own index of English judgments.</span></div></li>
         <li><span class="n">03</span><div><b>Check</b> <span>— paste a text: every citation, paragraph number and quotation is checked
           against the judgments.</span></div></li>
         <li><span class="n">04</span><div><b>Workspace</b> <span>— the paragraphs you save (☆), with your notes, and your saved searches;
           kept in your browser only, exportable.</span></div></li>
         <li><span class="n">05</span><div><b>Statistics</b> <span>— the corpus in charts: judgments and outcomes by year, article and State, the most cited judgments, HUDOC topics.</span></div></li>
       </ul>
       <div class="tour-cap" style="margin-top:12px">How the texts were split, labelled and checked: Methodology, in the bottom bar.</div>`,
      `<div class="tour-kicker">Search</div>
       <h2 class="tour-h">From a phrase to the paragraph.</h2>
       <div class="tour-lead">Type a phrase, or use HUDOC's operators — <code>article:8</code>, <code>violation:3</code>,
         <code>state:Poland</code>, <code>cites:hatton</code>, <code>NEAR</code>. Every result opens at the paragraph, with its
         number and the judgment's other matches; the Cite menu copies the citation. Try one:</div>
       <div class="tour-chips">${EXAMPLES.map((q) => `<button type="button" data-tour-q="${q.replace(/"/g, "&quot;")}">${q.replace(/</g, "&lt;")}</button>`).join("")}</div>`,
      `<div class="tour-kicker">Built for research</div>
       <h2 class="tour-h">Honest about what it holds.</h2>
       <ul class="tour-list">
         <li><span class="n">·</span><div><span><b>Judgments, in English.</b> Admissibility decisions are not included, and judgments that HUDOC
           publishes only in French are not in the search.</span></div></li>
         <li><span class="n">·</span><div><span><b>The Court's own paragraph numbers</b>, as in HUDOC's text of each judgment, so a result can be cited as it stands.</span></div></li>
         <li><span class="n">·</span><div><span><b>Cites / Cited by</b> come from the judgments' text and HUDOC's case-law lists; every matching
           rule is documented in Methodology.</span></div></li>
         <li><span class="n">·</span><div><span><b>HUDOC remains the authoritative source</b>: open the judgment there before you rely on a paragraph.</span></div></li>
       </ul>`,
      `<div class="tour-kicker">Start anywhere</div>
       <h2 class="tour-h">Where to first?</h2>
       <div class="tour-go">
         <a href="./" data-tour-go="search">→ Search a phrase</a>
         <a href="check.html">→ Check the citations in a text</a>
         <a href="analytics.html">→ See the corpus in charts</a>
       </div>
       <div class="tour-cap" style="margin-top:18px">Reopen this tour any time: bottom bar → ✦ tour.</div>`,
    ];
  }

  let wrap = null, index = 0, lastFocus = null;

  function build(stats, years) {
    if (!document.getElementById("tour-style")) {
      const st = document.createElement("style");
      st.id = "tour-style";
      st.textContent = CSS;
      document.head.appendChild(st);
    }
    wrap?.remove();
    const html = slides(stats, years);
    wrap = document.createElement("div");
    wrap.className = "tourwrap";
    wrap.id = "tour-wrap";
    wrap.setAttribute("role", "dialog");
    wrap.setAttribute("aria-modal", "true");
    wrap.setAttribute("aria-label", "Introduction tour");
    wrap.innerHTML = `<div class="tour-box" tabindex="-1">
      <div class="tour-slides">${html.map((h, i) => `<div class="tslide" data-i="${i}">${h}</div>`).join("")}</div>
      <div class="tour-nav"><button type="button" id="tour-skip">Skip tour</button>
        <div class="tour-dots">${html.map((_, i) => `<button type="button" class="tdot" data-i="${i}" aria-label="Slide ${i + 1}"></button>`).join("")}</div>
        <button type="button" id="tour-next">Next →</button></div></div>`;
    document.body.appendChild(wrap);
    wrap.addEventListener("click", (e) => {
      if (e.target === wrap) return close();
      const dot = e.target.closest(".tdot");
      if (dot) return go(Number(dot.dataset.i));
      if (e.target.id === "tour-skip") return close();
      if (e.target.id === "tour-next") return index >= html.length - 1 ? close() : go(index + 1);
      const q = e.target.closest("[data-tour-q]");
      if (q) return runQuery(q.dataset.tourQ);
      const goSearch = e.target.closest('[data-tour-go="search"]');
      if (goSearch && onSearchPage) {
        e.preventDefault();
        close();
        document.getElementById("searchInput")?.focus();
      }
    });
  }

  function go(i) {
    const n = wrap.querySelectorAll(".tslide").length;
    index = Math.max(0, Math.min(n - 1, i));
    wrap.querySelectorAll(".tslide").forEach((s, k) => s.classList.toggle("on", k === index));
    wrap.querySelectorAll(".tdot").forEach((d, k) => d.classList.toggle("on", k === index));
    wrap.querySelector("#tour-next").textContent = index === n - 1 ? "Start exploring" : "Next →";
  }

  function runQuery(q) {
    close();
    const input = document.getElementById("searchInput");
    if (onSearchPage && input && !input.disabled) {
      input.value = q;
      document.getElementById("searchForm")?.requestSubmit();
    } else {
      location.href = `./?q=${encodeURIComponent(q)}`;
    }
  }

  async function open() {
    lastFocus = document.activeElement;
    const get = (path) => fetch(`${API}/${path}`, { signal: AbortSignal.timeout(4000) }).then((r) => (r.ok ? r.json() : null)).catch(() => null);
    const [stats, facets] = await Promise.all([get("stats"), get("facets")]);
    build(stats, facets && facets.years);
    go(0);
    wrap.classList.add("open");
    document.body.style.overflow = "hidden";
    wrap.querySelector(".tour-box").focus();
  }

  function close() {
    if (!wrap) return;
    wrap.classList.remove("open");
    document.body.style.overflow = "";
    try { localStorage.setItem(DONE_KEY, "1"); } catch (_) { /* private mode */ }
    lastFocus?.focus?.();
  }

  document.addEventListener("keydown", (e) => {
    if (!wrap || !wrap.classList.contains("open")) return;
    if (e.key === "Escape") close();
    else if (e.key === "ArrowRight") go(index + 1);
    else if (e.key === "ArrowLeft") go(index - 1);
  });

  document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("tourBtn")?.addEventListener("click", open);
    const params = new URLSearchParams(location.search);
    let done = false;
    try { done = !!localStorage.getItem(DONE_KEY); } catch (_) { /* private mode */ }
    // first visit to Search (not a shared link to a search), or ?tour on any page
    if (params.has("tour") || (onSearchPage && !done && !params.has("q"))) setTimeout(open, 600);
  });
})();
