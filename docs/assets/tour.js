/* A one-minute tour of HUDOC Researcher (five slides; six, in Polish, on the Polish page), as on the HRC voting dashboard.
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
  // The Polish beta page (docs/pl/, <html lang="pl">) gets the tour in Polish, with a step on the communicated
  // cases where that page offers them (data-comm="1"); its own "seen" key, and links back to the Polish page.
  const PL = document.documentElement.lang === "pl";
  const COMM = PL && document.documentElement.dataset.comm === "1";
  const T = (en, pl) => (PL ? pl : en);
  const DONE_KEY = PL ? "echr-tour-done-pl" : "echr-tour-done";
  const HOME = PL ? "pl/" : "./";   // the Search page; the Polish page's <base> is the site root
  const onSearchPage = !!document.getElementById("searchInput");
  const fmt = (n) => Number(n).toLocaleString(PL ? "pl-PL" : "en-GB");
  // Polish noun after a number: 1 sprawa, 2–4 sprawy (but 12–14 spraw), otherwise spraw
  const plN = (n, one, few, many) => (n === 1 ? one : [2, 3, 4].includes(n % 10) && ![12, 13, 14].includes(n % 100) ? few : many);
  // the film plays from the author's site (GitHub Pages, as this site), only when pressed
  const FILM = { src: "https://lszoszk.github.io/assets/video/hudoc-researcher-film.mp4",
                 poster: new URL("film-poster.jpg", document.currentScript.src).href };
  const EXAMPLES = ["surveillance OR interception NOT terrorism", "environment* pollution", '"margin of appreciation" article:10'];

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
  .tour-film{margin-top:16px}
  .tour-film button{display:flex;align-items:center;gap:14px;cursor:pointer;background:none;border:1px solid var(--rule,#d8d0c3);padding:6px 14px 6px 6px;
    text-align:left;color:var(--ink,#242328)}
  .tour-film button:hover{border-color:var(--garnet,#8d2f2f)}
  .tour-film img{display:block;width:160px;height:90px;object-fit:cover}
  .tour-film b{display:block;font-family:var(--font-serif,'Source Serif 4',Georgia,serif);font-weight:600;color:var(--garnet,#8d2f2f)}
  .tour-film span span{font-family:var(--font-mono,monospace);font-size:.66rem;letter-spacing:.06em;text-transform:uppercase;color:var(--ink-3,#706d72)}
  .tour-film video{display:block;width:100%;height:auto;aspect-ratio:16/9;background:var(--paper-3,#ebe6dc)}
  .tour-views .s{display:none}
  @media (max-width:600px){.tour-slides{padding:22px 18px 14px}.tour-h{font-size:1.35rem}.tour-nav{padding:10px 18px}}
  /* phones: every slide fits a 375 x 667 screen without scrolling, Skip / Next always in view */
  @media (max-width:860px){.tour-nav button:not(.tdot){min-height:36px;padding:0 4px}
    .tour-dots{gap:0}.tour-dots .tdot{width:28px;height:32px;padding:12px 10px;background-clip:content-box}}
  @media (max-width:600px){
    .tourwrap{padding:10px}
    .tour-box{max-height:calc(100vh - 20px);max-height:calc(100dvh - 20px)}
    .tour-slides{padding:16px 16px 12px}
    .tour-kicker{font-size:.6rem;margin-bottom:6px}
    .tour-h{font-size:1.2rem;margin-bottom:8px}
    .tour-lead{font-size:.88rem;line-height:1.45}
    .tour-stats{display:grid;grid-template-columns:1fr 1fr;gap:8px 16px;margin:12px 0 4px}
    .tour-stats b{font-size:1.15rem}
    .tour-spark{height:34px}
    .tour-list{margin-top:8px}
    .tour-list li{grid-template-columns:22px 1fr;padding:6px 0;font-size:.88rem;line-height:1.4}
    .tour-views .d{display:none}.tour-views .s{display:inline}
    .tour-film{margin-top:10px}.tour-film button{gap:10px;padding:4px 10px 4px 4px}
    .tour-film img{width:80px;height:45px}.tour-film span span{display:none}
    .tour-spark,.tour-spark+.tour-cap{display:none}  /* on a phone the year chart makes room for the film */
    .tour-chips{margin-top:10px;gap:6px}
    .tour-chips button{padding:6px 8px;font-size:.7rem}
    .tour-go{gap:8px;margin-top:12px}
    .tour-nav{padding:6px 14px}
  }`;

  function slides(stats, years) {
    const s = stats || {};
    const from = /(\d{4})$/.exec(s.date_from || "")?.[1] || "1960";
    const to = /(\d{4})$/.exec(s.date_to || "")?.[1] || "2026";
    const frN = s.french_originals ?? 9284;     // French originals (0 where the server does not hold them)
    let spark = "";
    if (years && years.length) {
      const counts = years.filter((y) => Number(y.year) > 1900);
      const max = Math.max(...counts.map((y) => y.count));
      spark = `<div class="tour-spark" aria-hidden="true">${counts.map((y) =>
        `<i style="height:${Math.max(2, Math.round((y.count / max) * 100))}%" title="${y.year}: ${fmt(y.count)}"></i>`).join("")}</div>
        <div class="tour-cap">${T("Judgments per year", "Wyroki w kolejnych latach")}, ${counts[0].year}–${counts[counts.length - 1].year}.</div>`;
    }
    if (PL) return slidesPl(s, frN, from, to, spark);
    return [
      `<div class="tour-kicker">First time here · a one-minute tour</div>
       <h2 class="tour-h">The Court's judgments, paragraph by paragraph.</h2>
       <div class="tour-lead">Every judgment of the European Court of Human Rights in English${frN ? `, and the ${fmt(frN)} that HUDOC
         publishes only in French, in their French text` : ""}, split into the Court's own numbered paragraphs — so a search lands on
         the paragraph you will cite, with a link to HUDOC, the authoritative source. Unofficial English translations of
         ${fmt(s.total_machine_translations || 2460)} French-only judgments can be switched on in the English search${s.total_decisions ? `, and so can
         ${fmt(s.total_decisions)} of the Court's decisions` : ""}.</div>
       <div class="tour-stats">
         <div><b>${fmt(s.total_judgments || 20073)}</b><span>judgments in English</span></div>
         ${s.total_decisions ? `<div><b>${fmt(s.total_decisions)}</b><span>decisions, a selection</span></div>` : ""}
         ${frN ? `<div><b>${fmt(frN)}</b><span>only in French, in French</span></div>` : ""}
         <div><b>${fmt(s.citable_paragraphs || 1404444)}</b><span>numbered paragraphs</span></div>
         <div><b>${fmt(s.total_countries || 47)}</b><span>respondent States</span></div>
         <div><b>${from}–${to}</b><span>years covered</span></div>
       </div>${spark}
       <div class="tour-film"><button type="button" data-tour-film>
         <img src="${FILM.poster}" alt="" width="160" height="90"><span><b>▶ HUDOC Researcher in 100 seconds</b><span>a short film, with subtitles</span></span>
       </button></div>`,
      `<div class="tour-kicker">The views</div>
       <h2 class="tour-h">Six ways in.</h2>
       <ul class="tour-list tour-views">
         <li><span class="n">01</span><div><b>Search</b> <span class="s">— full text, paragraph by paragraph</span> <span class="d">— full text at paragraph level${frN ? ", in English or in French" : ""}, with HUDOC's operators, the parts of
           the judgment to search in, filters, and each judgment's Cites / Cited by; a case name or application number finds the case itself.</span></div></li>
         <li><span class="n">02</span><div><b>Semantic Search</b> <span class="x">experimental</span> <span class="s">— describe a case in plain words</span> <span class="d">— describe a case in plain language;
           it runs on its own index of English judgments, and adds the judgments only in French when you tick the box under the query.</span></div></li>
         <li><span class="n">03</span><div><b>Check</b> <span class="s">— verify the citations in a text</span> <span class="d">— paste a text: every citation, paragraph number and quotation is checked
           against the judgments.</span></div></li>
         <li><span class="n">04</span><div><b>Workspace</b> <span class="s">— your saved paragraphs and searches</span> <span class="d">— the paragraphs you save (☆), with your notes, and your saved searches,
           each with an RSS feed of new judgments; kept in your browser only, exportable.</span></div></li>
         <li><span class="n">05</span><div><b>Statistics</b> <span class="s">— the corpus in charts</span> <span class="d">— the corpus in charts: judgments and outcomes by year, article and State, the most cited judgments, HUDOC topics.</span></div></li>
         <li><span class="n">06</span><div><b>AI assistant</b> <span class="s">— the same search from Claude</span> <span class="d">— a connector (MCP) for Claude or another assistant:
           it searches these judgments and quotes paragraphs verbatim with their § numbers.</span></div></li>
       </ul>
       <div class="tour-cap" style="margin-top:12px">How the texts were split, labelled and checked: Methodology, in the bottom bar.</div>`,
      `<div class="tour-kicker">Search</div>
       <h2 class="tour-h">From a phrase to the paragraph.</h2>
       <div class="tour-lead">Type words or a <code>"phrase"</code>, combine them with <code>OR</code> and <code>NOT</code>, and end a word
         with <code>*</code> for every word that begins so (<code>environment*</code>); HUDOC's own operators work too
         (<code>article:8</code>, <code>cites:hatton</code>, <code>NEAR</code>). Every result opens at the paragraph, with its
         number and the judgment's other matches; Cite copies an OSCOLA citation and ☆ Bookmark saves it to your Workspace.${frN ? `
         <b>Français</b>, above the filters, searches the ${fmt(frN)} judgments HUDOC publishes only in French, in their French
         text (accents optional).` : ""} <b>Decisions</b>, in the left pane, adds the Court's decisions to the results. Try one:</div>
       <div class="tour-chips">${EXAMPLES.map((q) => `<button type="button" data-tour-q="${q.replace(/"/g, "&quot;")}">${q.replace(/</g, "&lt;")}</button>`).join("")}</div>`,
      `<div class="tour-kicker">Built for research</div>
       <h2 class="tour-h">Honest about what it holds.</h2>
       <ul class="tour-list">
         <li><span class="n">·</span><div><span><b>Judgments, in English${frN ? " and in French" : ""}.</b> ${frN ? `The ${fmt(frN)} judgments HUDOC publishes only in French
           are searched in their authentic French text; unofficial English translations of all of them can be switched on in the English search.`
           : "Judgments that HUDOC publishes only in French are left out, except unofficial machine translations of those other judgments cite, which you can switch on."}
           Decisions of the Grand Chamber, the Chambers and the Committees are shown when <i>Decisions</i> is ticked.</span></div></li>
         <li><span class="n">·</span><div><span><b>The Court's own paragraph numbers</b>, as in HUDOC's text of each judgment, so a result can be cited as it stands.</span></div></li>
         <li><span class="n">·</span><div><span><b>Cites / Cited by</b> count judgments and decisions, found in their text and in HUDOC's metadata; every matching
           rule is documented in Methodology.</span></div></li>
         <li><span class="n">·</span><div><span><b>HUDOC remains the authoritative source</b>: open the judgment there before you rely on a paragraph.
           Every download (Excel, CSV, PNG) says where it came from and how to cite it.</span></div></li>
       </ul>`,
      `<div class="tour-kicker">Start anywhere</div>
       <h2 class="tour-h">Where to first?</h2>
       <div class="tour-go">
         <a href="./" data-tour-go="search">→ Search a phrase</a>
         <a href="check.html">→ Check the citations in a text</a>
         <a href="analytics.html">→ See the corpus in charts</a>
         <a href="about.html#mcp">→ Use it from Claude or another AI assistant (connector + skill)</a>
       </div>
       <div class="tour-cap" style="margin-top:18px">Reopen this tour any time: bottom bar → ✦ tour.</div>`,
    ];
  }

  /* The same tour in Polish (the Polish beta page), with the communicated cases as its second step. Links to the
     Search page go to pl/; the other pages are in English, marked (EN). */
  function slidesPl(s, frN, from, to, spark) {
    const mtN = s.total_machine_translations || 2460;
    const commN = Number(s.communicated_cases) || 0;
    const asOfDate = new Date(`${s.communicated_as_of}T00:00:00Z`);
    const asOf = Number.isNaN(asOfDate.getTime()) ? ""
      : asOfDate.toLocaleDateString("pl-PL", { day: "2-digit", month: "2-digit", year: "numeric", timeZone: "UTC" });
    const stat = (n, one, few, many) => `<div><b>${fmt(n)}</b><span>${plN(Number(n), one, few, many)}</span></div>`;
    const comm = !COMM ? [] : [
      `<div class="tour-kicker">Nowa kolekcja</div>
       <h2 class="tour-h">Sprawy zakomunikowane.</h2>
       <div class="tour-lead">Komunikacje skarg opublikowane przez Trybunał w HUDOC (kolekcja „Communicated cases”): przedmiot
         sprawy lub stan faktyczny w ujęciu skarżącego, zarzuty i pytania Trybunału do stron. To nie są orzeczenia;
         zakomunikowanie nie przesądza o dopuszczalności skargi.</div>
       <ul class="tour-list">
         <li><span class="n">·</span><div><span><b>Jak korzystać.</b> Przełącznik „Sprawy zakomunikowane” w bloku <i>Kolekcja</i>.
           Status: w toku (według HUDOC na dzień pobrania) albo zakończona wyrokiem lub decyzją, z odnośnikiem;
           filtr „Status sprawy”.</span></div></li>
         <li><span class="n">·</span><div><span><b>Numeracja.</b> Numery mają tylko pytania Trybunału („Pyt. 2”), według
           jego numeracji.</span></div></li>
         <li><span class="n">·</span><div><span><b>Zastrzeżenia.</b> Teksty francuskie przetłumaczono maszynowo (nieoficjalnie);
           HUDOC nie publikuje wszystkich komunikacji.</span></div></li>
       </ul>
       ${commN > 0 ? `<div class="tour-stats">${stat(commN, "sprawa zakomunikowana", "sprawy zakomunikowane", "spraw zakomunikowanych")}
         ${asOf ? `<div><b>${asOf}</b><span>status według HUDOC</span></div>` : ""}</div>
       <div class="tour-go"><a href="${HOME}?collection=communicated&amp;state=Poland" data-tour-go="comm">→ Pokaż sprawy przeciwko Polsce</a></div>`
         : `<div class="tour-cap" style="margin-top:14px">Kolekcja jest w przygotowaniu.</div>`}`,
    ];
    return [
      `<div class="tour-kicker">Pierwsza wizyta · minutowy przewodnik</div>
       <h2 class="tour-h">Wyroki Trybunału, paragraf po paragrafie.</h2>
       <div class="tour-lead">Wszystkie wyroki Europejskiego Trybunału Praw Człowieka po angielsku${frN ? `, a także francuskie
         teksty ${fmt(frN)} wyroków, które HUDOC publikuje tylko po francusku` : ""}, podzielone na numerowane paragrafy Trybunału:
         wynik wyszukiwania prowadzi wprost do paragrafu, który można zacytować, z odnośnikiem do HUDOC, źródła miarodajnego.
         W wyszukiwaniu angielskim można włączyć nieoficjalne tłumaczenia angielskie ${fmt(mtN)} wyroków dostępnych tylko
         po francusku${s.total_decisions ? `, a także zbiór ${fmt(s.total_decisions)} decyzji` : ""}.</div>
       <div class="tour-stats">
         ${stat(s.total_judgments || 20073, "wyrok po angielsku", "wyroki po angielsku", "wyroków po angielsku")}
         ${s.total_decisions ? stat(s.total_decisions, "wybrana decyzja", "wybrane decyzje", "wybranych decyzji") : ""}
         ${frN ? `<div><b>${fmt(frN)}</b><span>tylko po francusku</span></div>` : ""}
         ${stat(s.citable_paragraphs || 1404444, "numerowany paragraf", "numerowane paragrafy", "numerowanych paragrafów")}
         ${stat(s.total_countries || 47, "pozwane państwo", "pozwane państwa", "pozwanych państw")}
         <div><b>${from}–${to}</b><span>zakres lat</span></div>
       </div>${spark}
       <div class="tour-film"><button type="button" data-tour-film>
         <img src="${FILM.poster}" alt="" width="160" height="90"><span><b>▶ HUDOC Researcher w 100 sekund</b><span>krótki film, napisy po angielsku</span></span>
       </button></div>`,
      ...comm,
      `<div class="tour-kicker">Widoki</div>
       <h2 class="tour-h">Sześć sposobów pracy.</h2>
       <ul class="tour-list tour-views">
         <li><span class="n">01</span><div><b>Wyszukiwanie</b> <span class="s">— pełny tekst, paragraf po paragrafie</span> <span class="d">— pełny tekst na poziomie paragrafów${frN ? ", po angielsku lub po francusku" : ""}, z operatorami HUDOC,
           wyborem przeszukiwanych części wyroku, filtrami oraz listami Cytuje / Cytowany w dla każdego wyroku; nazwa sprawy lub numer skargi prowadzi wprost do sprawy.</span></div></li>
         <li><span class="n">02</span><div><b>Semantyczne</b> (EN) <span class="x">eksperymentalne</span> <span class="s">— opisz sprawę własnymi słowami</span> <span class="d">— opisz sprawę zwykłym językiem;
           działa na osobnym indeksie wyroków angielskich, a wyroki dostępne tylko po francusku dołącza po zaznaczeniu pola pod zapytaniem.</span></div></li>
         <li><span class="n">03</span><div><b>Weryfikacja</b> (EN) <span class="s">— sprawdzanie cytowań w tekście</span> <span class="d">— wklej tekst: każde cytowanie, numer paragrafu i cytat
           zostaną sprawdzone z treścią wyroków.</span></div></li>
         <li><span class="n">04</span><div><b>Obszar roboczy</b> (EN) <span class="s">— zapisane paragrafy i wyszukiwania</span> <span class="d">— zapisane paragrafy (☆) z Twoimi notatkami
           oraz zapisane wyszukiwania, każde z kanałem RSS nowych wyroków; przechowywane tylko w Twojej przeglądarce, z możliwością eksportu.</span></div></li>
         <li><span class="n">05</span><div><b>Statystyki</b> (EN) <span class="s">— zbiór na wykresach</span> <span class="d">— zbiór na wykresach: wyroki i rozstrzygnięcia według lat, artykułów i państw, najczęściej cytowane wyroki, tematy HUDOC.</span></div></li>
         <li><span class="n">06</span><div><b>Asystent AI</b> <span class="s">— to samo wyszukiwanie z poziomu Claude</span> <span class="d">— konektor (MCP) dla Claude lub innego asystenta:
           przeszukuje te wyroki i cytuje paragrafy dosłownie, z ich numerami §.</span></div></li>
       </ul>
       <div class="tour-cap" style="margin-top:12px">Jak teksty podzielono, opisano i sprawdzono: Metodologia (EN), na dolnym pasku.</div>`,
      `<div class="tour-kicker">Wyszukiwanie</div>
       <h2 class="tour-h">Od frazy do paragrafu.</h2>
       <div class="tour-lead">Wpisz słowa lub <code>"frazę"</code> (w języku tekstów, czyli po angielsku), połącz je operatorami
         <code>OR</code> i <code>NOT</code>, a gwiazdka na końcu słowa obejmie wszystkie słowa o tym początku (<code>environment*</code>);
         działają też operatory HUDOC (<code>article:8</code>, <code>cites:hatton</code>, <code>NEAR</code>). Każdy wynik otwiera się
         na paragrafie, z jego numerem i pozostałymi trafieniami w wyroku; <b>Cytuj</b> kopiuje cytowanie OSCOLA, a <b>☆ Zapisz</b>
         dodaje paragraf do Obszaru roboczego.${frN ? `
         <b>Français</b>, w bloku Kolekcja, przeszukuje francuskie teksty ${fmt(frN)} wyroków, które HUDOC publikuje tylko po francusku
         (akcenty są opcjonalne).` : ""} <b>Decyzje</b>, w lewym panelu, dołączają do wyników decyzje Trybunału. Wypróbuj:</div>
       <div class="tour-chips">${EXAMPLES.map((q) => `<button type="button" data-tour-q="${q.replace(/"/g, "&quot;")}">${q.replace(/</g, "&lt;")}</button>`).join("")}</div>`,
      `<div class="tour-kicker">Do pracy z orzecznictwem</div>
       <h2 class="tour-h">Co obejmuje zbiór.</h2>
       <ul class="tour-list">
         <li><span class="n">·</span><div><span><b>Wyroki po angielsku${frN ? " i po francusku" : ""}.</b> ${frN ? `Francuskie teksty ${fmt(frN)} wyroków, które HUDOC
           publikuje tylko po francusku, przeszukuje się w autentycznym brzmieniu; ich nieoficjalne tłumaczenia angielskie można włączyć w wyszukiwaniu angielskim.`
           : "Wyroki, które HUDOC publikuje tylko po francusku, są pominięte, z wyjątkiem nieoficjalnych tłumaczeń maszynowych tych, które cytują inne wyroki; można je włączyć."}
           Decyzje Wielkiej Izby, Izb i Komitetów pojawiają się po zaznaczeniu pola <i>Decyzje</i>.</span></div></li>
         <li><span class="n">·</span><div><span><b>Numeracja paragrafów Trybunału</b>, jak w tekście każdego wyroku w HUDOC, więc wynik można zacytować bez zmian.</span></div></li>
         <li><span class="n">·</span><div><span><b>Cytuje / Cytowany w</b> obejmują wyroki i decyzje, odnalezione w ich tekście i w metadanych HUDOC;
           każdą regułę dopasowania opisano w Metodologii (EN).</span></div></li>
         <li><span class="n">·</span><div><span><b>Źródłem miarodajnym pozostaje HUDOC</b>: przed powołaniem się na paragraf należy otworzyć wyrok w HUDOC.
           Każdy plik do pobrania (Excel, CSV, PNG) wskazuje swoje źródło i sposób cytowania.</span></div></li>
       </ul>`,
      `<div class="tour-kicker">Od czego zacząć</div>
       <h2 class="tour-h">Dokąd najpierw?</h2>
       <div class="tour-go">
         <a href="${HOME}" data-tour-go="search">→ Wyszukaj frazę</a>
         <a href="check.html">→ Sprawdź cytowania w tekście (EN)</a>
         <a href="analytics.html">→ Zobacz zbiór na wykresach (EN)</a>
         <a href="about.html#mcp">→ Korzystaj z Claude lub innego asystenta AI: konektor i skill (EN)</a>
       </div>
       <div class="tour-cap" style="margin-top:18px">Przewodnik można otworzyć ponownie w każdej chwili: dolny pasek → ✦ przewodnik.</div>`,
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
    wrap.setAttribute("aria-label", T("Introduction tour", "Przewodnik wprowadzający"));
    wrap.innerHTML = `<div class="tour-box" tabindex="-1">
      <div class="tour-slides">${html.map((h, i) => `<div class="tslide" data-i="${i}">${h}</div>`).join("")}</div>
      <div class="tour-nav"><button type="button" id="tour-skip">${T("Skip tour", "Pomiń")}</button>
        <div class="tour-dots">${html.map((_, i) => `<button type="button" class="tdot" data-i="${i}" aria-label="${T("Slide", "Slajd")} ${i + 1}"></button>`).join("")}</div>
        <button type="button" id="tour-next">${T("Next →", "Dalej →")}</button></div></div>`;
    document.body.appendChild(wrap);
    wrap.addEventListener("click", (e) => {
      if (e.target === wrap) return close();
      const dot = e.target.closest(".tdot");
      if (dot) return go(Number(dot.dataset.i));
      if (e.target.id === "tour-skip") return close();
      if (e.target.id === "tour-next") return index >= html.length - 1 ? close() : go(index + 1);
      const film = e.target.closest("[data-tour-film]");
      if (film) {
        film.parentElement.innerHTML = `<video controls autoplay playsinline poster="${FILM.poster}" src="${FILM.src}"></video>`;
        return;
      }
      const q = e.target.closest("[data-tour-q]");
      if (q) return runQuery(q.dataset.tourQ);
      // the link reloads the Search page in that collection: mark the tour seen, or it would open again
      if (e.target.closest('[data-tour-go="comm"]')) return close();
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
    wrap.querySelectorAll("video").forEach((v) => v.pause());
    wrap.querySelectorAll(".tslide").forEach((s, k) => s.classList.toggle("on", k === index));
    wrap.querySelectorAll(".tdot").forEach((d, k) => d.classList.toggle("on", k === index));
    wrap.querySelector("#tour-next").textContent = index === n - 1 ? T("Start exploring", "Zaczynamy") : T("Next →", "Dalej →");
  }

  function runQuery(q) {
    close();
    const input = document.getElementById("searchInput");
    if (onSearchPage && input && !input.disabled) {
      input.value = q;
      document.getElementById("searchForm")?.requestSubmit();
    } else {
      location.href = `${HOME}?q=${encodeURIComponent(q)}`;
    }
  }

  async function open() {
    lastFocus = document.activeElement;
    const get = (path) => fetch(`${API}/${path}`, { signal: AbortSignal.timeout(4000) }).then((r) => (r.ok ? r.json() : null)).catch(() => null);
    const [stats, facets] = await Promise.all([get("stats"), get("facets")]);
    build(stats, facets && facets.years);
    go(0);
    wrap.classList.add("open");
    document.documentElement.style.overflow = "hidden";
    wrap.querySelector(".tour-box").focus();
  }

  function close() {
    if (!wrap) return;
    wrap.classList.remove("open");
    wrap.querySelectorAll("video").forEach((v) => v.pause());
    document.documentElement.style.overflow = "";
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

/* "Use with AI" in the bottom bar, before the tour: a card on using HUDOC Researcher from an AI
   assistant (the hosted MCP connector and the Claude skill). It was a pulsing ✦ in the corner, which
   drew the eye from the results; the bar keeps it at hand without that. × or Esc closes the card. */
(function () {
  "use strict";
  const MCP_URL = "https://150.254.115.204/echr-api/mcp";
  const SKILL_URL = "https://github.com/lszoszk/mcp-echr/raw/main/skills/echr-research.zip";
  const PL = document.documentElement.lang === "pl";   // the Polish beta page: the card in Polish
  const T = (en, pl) => (PL ? pl : en);

  const CSS = `
  html.filters-sheet-open .ai-card{display:none}
  @media (max-width:860px){body.casenote-open .ai-card,body.dossier-open .ai-card{display:none}}
  .ai-card{position:fixed;right:14px;bottom:calc(var(--bar-h,30px) + 10px);z-index:151;width:min(360px,calc(100vw - 28px));
    max-height:calc(100vh - var(--bar-h,30px) - 90px);overflow:auto;padding:16px 18px 14px;
    background:var(--paper,#faf8f3);color:var(--ink,#242328);border:1px solid var(--ink,#242328);
    box-shadow:0 10px 30px rgba(36,35,40,.22);font-family:var(--font-serif,Georgia,serif);font-size:.92rem;line-height:1.5}
  .ai-card[hidden]{display:none}
  .ai-card h2{margin:0 26px 6px 0;font-size:1.05rem;font-weight:600}
  .ai-card p{margin:0 0 10px}
  .ai-card ol{margin:0 0 10px;padding-left:1.2em}
  .ai-card li{margin:0 0 8px}
  .ai-card code{font-family:var(--font-mono,monospace);font-size:.72rem;word-break:break-all}
  .ai-card .ai-url{display:flex;gap:6px;align-items:center;margin-top:4px;padding:5px 8px;background:var(--paper-2,#f4f1ea);border:1px solid var(--rule,#d8d0c3)}
  .ai-card button.ai-copy,.ai-card a.ai-btn{flex:0 0 auto;padding:3px 8px;cursor:pointer;font:600 .62rem var(--font-mono,monospace);letter-spacing:.05em;
    text-transform:uppercase;color:var(--ink-2,#48464c);background:var(--paper,#faf8f3);border:1px solid var(--rule,#d8d0c3);text-decoration:none}
  .ai-card button.ai-copy:hover,.ai-card a.ai-btn:hover{color:var(--garnet,#8d2f2f);border-color:var(--garnet,#8d2f2f)}
  .ai-card .ai-x{position:absolute;top:8px;right:10px;width:30px;height:30px;cursor:pointer;font-size:20px;line-height:1;
    color:var(--ink-3,#706d72);background:none;border:0}
  .ai-card .ai-foot{display:flex;justify-content:space-between;gap:10px;margin-top:6px;font-size:.78rem}
  .ai-card .ai-foot a,.ai-card .ai-foot button{color:var(--ink-3,#706d72);background:none;border:0;padding:0;cursor:pointer;font:inherit;text-decoration:underline}
  .ai-card a{color:var(--garnet,#8d2f2f)}
  @media (max-width:600px){.ai-card{right:10px;font-size:.88rem}.sf-btn.sf-ai{display:none}}`;  /* the bar has no room on a phone; About has the setup */

  function build() {
    const st = document.createElement("style"); st.textContent = CSS; document.head.appendChild(st);
    const tour = document.getElementById("tourBtn");
    if (!tour) return;
    const fab = document.createElement("button");
    fab.type = "button"; fab.className = "sf-btn sf-ai"; fab.textContent = T("Use with AI", "Użyj z AI");
    fab.setAttribute("aria-label", T("Use HUDOC Researcher from your AI assistant", "Korzystaj z HUDOC Researcher przez asystenta AI"));
    fab.setAttribute("aria-expanded", "false"); fab.setAttribute("aria-controls", "aiCard");
    fab.title = T("Use it from your AI assistant", "Korzystaj z asystenta AI");
    const card = document.createElement("section");
    card.className = "ai-card"; card.id = "aiCard"; card.hidden = true;
    card.setAttribute("role", "dialog"); card.setAttribute("aria-label", T("Use HUDOC Researcher from your AI assistant", "Korzystaj z HUDOC Researcher przez asystenta AI"));
    card.innerHTML = PL ? `
      <button type="button" class="ai-x" aria-label="Zamknij">×</button>
      <h2>Korzystaj z asystenta AI</h2>
      <p>Claude lub inny asystent obsługujący konektory MCP może przeszukiwać te wyroki, cytować paragrafy dosłownie,
        z numerami §, i sprawdzać cytowania z orzecznictwa strasburskiego.</p>
      <ol>
        <li><b>Dodaj konektor</b> — w Claude: Settings → Connectors → Add custom connector, z adresem:
          <span class="ai-url"><code>${MCP_URL}</code><button type="button" class="ai-copy">Kopiuj</button></span></li>
        <li><b>Dodaj skill</b> (opcjonalnie, dla Claude) — uczy kolejnych kroków wyszukiwania i cytowania OSCOLA:
          <a class="ai-btn" href="${SKILL_URL}">Pobierz</a>, następnie Settings → Capabilities → Skills → Upload.</li>
      </ol>
      <p>Nie trzeba niczego instalować ani zakładać u nas konta. Odpowiedzi asystenta nie są poradą prawną — każdy
        fragment należy sprawdzić w HUDOC.</p>
      <div class="ai-foot"><a href="about.html#mcp">Konfiguracja dla Claude Code i innych klientów (EN)</a></div>` : `
      <button type="button" class="ai-x" aria-label="Close">×</button>
      <h2>Use it from your AI assistant</h2>
      <p>Ask Claude, or another assistant that takes MCP connectors, about Strasbourg case-law: it searches these
        judgments, quotes paragraphs verbatim with their § numbers and checks citations.</p>
      <ol>
        <li><b>Add the connector</b> — in Claude: Settings → Connectors → Add custom connector, with the address:
          <span class="ai-url"><code>${MCP_URL}</code><button type="button" class="ai-copy">Copy</button></span></li>
        <li><b>Add the skill</b> (optional, for Claude) — it teaches the research steps and OSCOLA citations:
          <a class="ai-btn" href="${SKILL_URL}">Download</a>, then Settings → Capabilities → Skills → Upload.</li>
      </ol>
      <p>Nothing to install; no account with us. The assistant's answers are not legal advice — check every
        passage on HUDOC.</p>
      <div class="ai-foot"><a href="about.html#mcp">Setup for Claude Code and other clients</a></div>`;
    tour.before(fab);
    document.body.append(card);

    const setOpen = (open) => {
      card.hidden = !open; fab.setAttribute("aria-expanded", String(open));
      if (open) card.querySelector(".ai-copy").focus(); else fab.focus();
    };
    fab.addEventListener("click", () => setOpen(card.hidden));
    card.querySelector(".ai-x").addEventListener("click", () => setOpen(false));
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !card.hidden) setOpen(false); });
    card.querySelector(".ai-copy").addEventListener("click", (e) => {
      const b = e.currentTarget;
      navigator.clipboard?.writeText(MCP_URL).then(() => { b.textContent = T("Copied", "Skopiowano"); setTimeout(() => { b.textContent = T("Copy", "Kopiuj"); }, 1400); },
        () => window.prompt(T("Copy the connector address:", "Skopiuj adres konektora:"), MCP_URL));
    });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", build); else build();
})();
