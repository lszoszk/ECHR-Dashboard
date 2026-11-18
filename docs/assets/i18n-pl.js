/* HUDOC Researcher: Polish interface strings for docs/pl/index.html.
 *
 * The static page is already in Polish; this file translates what assets/search-app.js (and the small
 * helpers it loads) render at run time: exact strings (EXACT), templated strings (RULES) and a few labels
 * whose form depends on a count next to them (Polish plurals). It never touches the Court's texts: text
 * inside SKIP (judgment and notice text, snippets, case titles, HUDOC metadata lists, code) is left alone.
 * Loaded before search-app.js; does nothing unless <html lang="pl">. Exposes window.I18N_PL.t(text). */
(function () {
  "use strict";
  if (document.documentElement.lang !== "pl") return;

  /* ── Helpers: numbers, plurals, dates ───────────────────────────────── */
  var NBSP = " ";
  function plNum(s) { return String(s).replace(/\d{1,3}(?:,\d{3})+/g, function (m) { return m.replace(/,/g, NBSP); }); }
  function toInt(s) { var n = parseInt(String(s == null ? "" : s).replace(/[^\d]/g, ""), 10); return isNaN(n) ? null : n; }
  function plural(n, one, few, many) {
    if (n === 1) return one;
    var d = n % 10, h = n % 100;
    return d >= 2 && d <= 4 && !(h >= 12 && h <= 14) ? few : many;
  }
  function pick(forms, n) { return n == null ? forms[2] : plural(n, forms[0], forms[1], forms[2]); }

  var LONG = "January|February|March|April|May|June|July|August|September|October|November|December";
  var SHORT = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec";
  var MONTH_GEN = { January: "stycznia", February: "lutego", March: "marca", April: "kwietnia", May: "maja", June: "czerwca",
    July: "lipca", August: "sierpnia", September: "września", October: "października", November: "listopada", December: "grudnia" };
  var MONTH_NOM = { January: "styczeń", February: "luty", March: "marzec", April: "kwiecień", May: "maj", June: "czerwiec",
    July: "lipiec", August: "sierpień", September: "wrzesień", October: "październik", November: "listopad", December: "grudzień" };
  var MONTH_SHORT = { Jan: "sty", Feb: "lut", Mar: "mar", Apr: "kwi", May: "maj", Jun: "cze", Jul: "lip", Aug: "sie",
    Sep: "wrz", Sept: "wrz", Oct: "paź", Nov: "lis", Dec: "gru" };
  var RX_DAY_LONG = new RegExp("\\b(\\d{1,2}) (" + LONG + ") (\\d{4})\\b", "g");
  var RX_DAY_SHORT = new RegExp("\\b(\\d{1,2}) (" + SHORT + ")\\.? (\\d{4})\\b", "g");
  var RX_MON_LONG = new RegExp("\\b(" + LONG + ") (\\d{4})\\b", "g");
  var RX_MON_SHORT = new RegExp("\\b(" + SHORT + ")\\.? (\\d{4})\\b", "g");
  /* "12 March 2024" -> "12 marca 2024", "12 Mar 2024" -> "12 mar 2024", "March 2024" -> "marzec 2024". */
  function plDates(s) {
    return String(s)
      .replace(RX_DAY_LONG, function (m, d, mo, y) { return d + " " + MONTH_GEN[mo] + " " + y; })
      .replace(RX_DAY_SHORT, function (m, d, mo, y) { return d + " " + MONTH_SHORT[mo] + " " + y; })
      .replace(RX_MON_LONG, function (m, mo, y) { return MONTH_NOM[mo] + " " + y; })
      .replace(RX_MON_SHORT, function (m, mo, y) { return MONTH_SHORT[mo] + " " + y; });
  }

  /* Nouns after a count (nominative: 1 / 2-4 / 5+) and after "z" (genitive: 1 / other). */
  var NOM = {
    passages: ["fragment", "fragmenty", "fragmentów"],
    cases: ["sprawa", "sprawy", "spraw"],
    "recent cases": ["najnowsza sprawa", "najnowsze sprawy", "najnowszych spraw"],
    "cases shown": ["pokazana sprawa", "pokazane sprawy", "pokazanych spraw"],
    "¶ matched": ["¶ trafienie", "¶ trafienia", "¶ trafień"],
    hit: ["trafienie", "trafienia", "trafień"],
    hits: ["trafienie", "trafienia", "trafień"],
    para: ["paragraf", "paragrafy", "paragrafów"],
    paras: ["paragraf", "paragrafy", "paragrafów"],
    "case": ["sprawa", "sprawy", "spraw"],
    "communicated cases": ["sprawa zakomunikowana", "sprawy zakomunikowane", "spraw zakomunikowanych"],
    notices: ["komunikacja", "komunikacje", "komunikacji"],
  };
  var GEN = {
    judgments: ["wyroku", "wyroków"], judgment: ["wyroku", "wyroków"],
    decisions: ["decyzji", "decyzji"], decision: ["decyzji", "decyzji"],
    "advisory opinions": ["opinii doradczej", "opinii doradczych"], "advisory opinion": ["opinii doradczej", "opinii doradczych"],
    documents: ["dokumentu", "dokumentów"], document: ["dokumentu", "dokumentów"],
    "records in the corpus": ["dokumentu w korpusie", "dokumentów w korpusie"],
    cases: ["sprawy", "spraw"], "case": ["sprawy", "spraw"],
    "communicated cases": ["sprawy zakomunikowanej", "spraw zakomunikowanych"],
    "communicated case": ["sprawy zakomunikowanej", "spraw zakomunikowanych"],
    notices: ["komunikacji", "komunikacji"], notice: ["komunikacji", "komunikacji"],
    "the French originals": ["oryginałów francuskich", "oryginałów francuskich"],
    "the judgments": ["wyroków", "wyroków"],
  };
  /* "judgments, decisions and advisory opinions" -> "wyroków, decyzji i opinii doradczych". */
  function genLabel(key, n) {
    if (GEN[key]) return GEN[key][n === 1 ? 0 : 1];
    var parts = key.split(/, | and /);
    if (parts.length < 2) return undefined;
    for (var i = 0; i < parts.length; i++) if (!GEN[parts[i]]) return undefined;
    var pl = parts.map(function (p) { return GEN[p][1]; });
    return pl.slice(0, -1).join(", ") + " i " + pl[pl.length - 1];
  }

  /* ── EXACT: the trimmed text of a text node or attribute (whitespace collapsed) ── */
  var EXACT_OBJ = {
    // Connection and loading
    "Live": "Połączono",
    "Offline": "Bez połączenia",
    "Connecting": "Łączenie",
    "Connected": "Połączono",
    "Connected to the search server: full-text search across all judgments": "Połączono z serwerem wyszukiwania: wyszukiwanie pełnotekstowe we wszystkich wyrokach",
    "The search server cannot be reached: showing a small sample dataset": "Brak połączenia z serwerem wyszukiwania: wyświetlana jest niewielka próbka danych",
    "Connecting to the search server…": "Łączenie z serwerem wyszukiwania…",
    "Connected to HUDOC Researcher API — full-text search across all judgments (English texts).": "Połączono z API HUDOC Researcher — wyszukiwanie pełnotekstowe we wszystkich wyrokach (teksty angielskie).",
    "Server unavailable — using local sample dataset.": "Serwer niedostępny — używana jest lokalna próbka danych.",
    "Server search failed and no local data loaded.": "Wyszukiwanie na serwerze nie powiodło się, a dane lokalne nie zostały wczytane.",
    "Loading sample dataset...": "Wczytywanie przykładowego zbioru...",
    "Dataset: load failed": "Zbiór danych: błąd wczytywania",
    "Dataset: upload failed": "Zbiór danych: błąd przesyłania",
    "[collapse]": "[zwiń]",
    "[expand]": "[rozwiń]",
    "Loading…": "Wczytywanie…",
    "Run search": "Szukaj",
    "Searching…": "Szukam…",
    "Loading 100 most recent cases…": "Wczytywanie 100 najnowszych spraw…",
    "Browsing cases…": "Przeglądanie spraw…",
    "Common words take a few seconds; a filter (Article, State, years) narrows the search.": "Częste słowa wymagają kilku sekund; filtr (artykuł, państwo, lata) zawęża wyszukiwanie.",
    "(loading recent cases…)": "(wczytywanie najnowszych spraw…)",
    "(searching server…)": "(wyszukiwanie na serwerze…)",
    "No data": "Brak danych",
    "Copied!": "Skopiowano!",
    "Copied": "Skopiowano",
    "Compact view": "Widok zwarty",
    "Detailed view": "Widok szczegółowy",
    "⏳ Exporting…": "⏳ Eksportowanie…",
    "Export Excel": "Eksport do Excela",

    // Filter rail
    "Search countries…": "Szukaj państwa…",
    "Search articles…": "Szukaj artykułu…",
    "Search keywords…": "Szukaj słowa kluczowego…",
    "No matches.": "Brak dopasowań.",
    "Clear": "Wyczyść",
    "Clear selections in this group": "Wyczyść zaznaczenia w tej grupie",
    "Show all years": "Pokaż wszystkie lata",
    "From year": "Od roku",
    "To year": "Do roku",
    "The 7-judge Chamber — the typical post-1998 bench. Narrows whichever collections are switched on, decisions included.": "Izba w składzie 7 sędziów — typowy skład orzekający po 1998 r. Zawęża wszystkie włączone kolekcje, także decyzje.",
    "The 17-judge Grand Chamber — major principles and inter-state cases. Narrows decisions too when they are switched on.": "Wielka Izba w składzie 17 sędziów — kwestie zasadnicze i sprawy międzypaństwowe. Zawęża także decyzje, gdy są włączone.",
    "The 3-judge Committee — repetitive cases following well-established case-law. Narrows decisions too when they are switched on.": "Komitet w składzie 3 sędziów — sprawy powtarzalne, rozstrzygane na podstawie utrwalonego orzecznictwa. Zawęża także decyzje, gdy są włączone.",
    "The 3-judge Committee — repetitive cases following well-established case-law. Narrows decisions too when they are switched on; most published decisions are its.": "Komitet w składzie 3 sędziów — sprawy powtarzalne, rozstrzygane na podstawie utrwalonego orzecznictwa. Zawęża także decyzje, gdy są włączone; większość opublikowanych decyzji wydają Komitety.",
    "Judgments": "Wyroki",
    "Decisions": "Decyzje",
    "Press Releases": "Komunikaty prasowe",
    "Has Strasbourg citations": "Zawiera orzecznictwo strasburskie",
    "Has domestic law": "Zawiera prawo krajowe",
    "Has international law": "Zawiera prawo międzynarodowe",
    "Has rules of court": "Zawiera Regulamin Trybunału",
    "Back to the official English texts only": "Powrót do samych oficjalnych tekstów angielskich",
    "Only English machine translations of French-only judgments (unofficial)": "Tylko angielskie tłumaczenia maszynowe wyroków dostępnych wyłącznie po francusku (nieoficjalne)",
    "+ English machine translations of French-only judgments (unofficial)": "+ angielskie tłumaczenia maszynowe wyroków dostępnych wyłącznie po francusku (nieoficjalne)",
    "Back to judgments only": "Powrót do samych wyroków",
    "Only decisions": "Tylko decyzje",
    "+ decisions": "+ decyzje",
    "Leave the advisory opinions out": "Pomiń opinie doradcze",
    "+ advisory opinions": "+ opinie doradcze",
    "Search all parts of the judgments again": "Przeszukuj ponownie wszystkie części wyroków",
    "HUDOC keyword": "Słowo kluczowe HUDOC",

    // Formations and bodies (getChamberLabel, formationLabel, BODY_CODE_LABELS)
    "Grand Chamber": "Wielka Izba",
    "Chamber": "Izba",
    "Committee": "Komitet",
    "Plenary": "Plenum",
    "Commission": "Komisja",
    "Decision": "Decyzja",
    "Judgment": "Wyrok",
    "Other": "Inne",
    "Court (Grand Chamber)": "Trybunał (Wielka Izba)",
    "Court (Chamber)": "Trybunał (Izba)",
    "Court (Committee)": "Trybunał (Komitet)",
    "Court (Plenary)": "Trybunał (plenum)",
    "Court (Panel of the Grand Chamber)": "Trybunał (kolegium Wielkiej Izby)",
    "Panel of the Grand Chamber": "Kolegium Wielkiej Izby",
    "Commission (Plenary)": "Komisja (plenum)",
    "Committee of Ministers": "Komitet Ministrów",

    // Document types (HUDOC)
    "Judgment (Merits and Just Satisfaction)": "Wyrok (meritum i słuszne zadośćuczynienie)",
    "Judgment (Chamber)": "Wyrok (Izba)",
    "Judgment (Committee)": "Wyrok (Komitet)",
    "Judgment (Grand Chamber)": "Wyrok (Wielka Izba)",
    "Judgment (Merits)": "Wyrok (meritum)",
    "Judgment (Struck out of the List)": "Wyrok (skreślenie z listy)",
    "Judgment (Just Satisfaction)": "Wyrok (słuszne zadośćuczynienie)",
    "Judgment (Revision)": "Wyrok (rewizja)",
    "Judgment (Preliminary Objection)": "Wyrok (zarzut wstępny)",
    "Judgment (Lack of Jurisdiction)": "Wyrok (brak jurysdykcji)",
    "Judgment (Interpretation)": "Wyrok (wykładnia)",
    "Judgment (Questions of Procedure)": "Wyrok (kwestie proceduralne)",
    "Judgment (Article 46 § 4)": "Wyrok (art. 46 § 4)",
    "Decision (Final)": "Decyzja (ostateczna)",
    "Advisory Opinion - Protocol 16": "Opinia doradcza – Protokół nr 16",
    "Advisory Opinion - Protocol 16 (Refused)": "Opinia doradcza – Protokół nr 16 (odmowa)",
    "Advisory Opinion - Article 47": "Opinia doradcza – art. 47",
    "Press Release": "Komunikat prasowy",
    "Press Release - Chamber Judgments": "Komunikat prasowy – wyroki Izby",
    "Communicated Case": "Sprawa zakomunikowana",

    // Sections of a judgment (SECTION_LABELS, SECTION_BUCKETS, raw section names)
    "Judgment Header": "Nagłówek wyroku",
    "Header": "Nagłówek",
    "Summary": "Streszczenie",
    "Introduction": "Wprowadzenie",
    "Procedure": "Postępowanie",
    "Circumstances of the Case": "Okoliczności sprawy",
    "Circumstances": "Okoliczności sprawy",
    "Subject Matter of the Case": "Przedmiot sprawy",
    "Subject Matter": "Przedmiot sprawy",
    "Facts (unsegmented)": "Stan faktyczny (bez podziału)",
    "Facts": "Stan faktyczny",
    "Facts Background": "Stan faktyczny – tło",
    "Facts Proceedings": "Stan faktyczny – postępowanie",
    "Relevant legal framework": "Właściwe ramy prawne",
    "Legal Framework": "Właściwe ramy prawne",
    "Legal Context": "Kontekst prawny",
    "Commission Proceedings": "Postępowanie przed Komisją",
    "Final Submissions": "Końcowe wnioski stron",
    "Admissibility": "Dopuszczalność",
    "Merits": "Meritum",
    "Admissibility + Merits": "Dopuszczalność + meritum",
    "Just Satisfaction": "Słuszne zadośćuczynienie",
    "Article 46 (Execution)": "Artykuł 46 (wykonanie)",
    "Article 46": "Artykuł 46",
    "Operative Part": "Sentencja",
    "Operative part": "Sentencja",
    "Separate Opinion": "Zdanie odrębne",
    "Individual Opinions": "Zdania odrębne",
    "Individual opinions": "Zdania odrębne",
    "Appendix": "Załącznik",
    "In Committee and joined cases, this section may contain applicant name lists rather than procedural history.": "W sprawach Komitetu i sprawach połączonych ta część może zawierać listy skarżących zamiast przebiegu postępowania.",
    "In Committee cases, this section may also contain legal analysis (ALLEGED VIOLATION headings).": "W sprawach Komitetu ta część może zawierać także analizę prawną (nagłówki ALLEGED VIOLATION).",
    "Pre-Protocol-11 only (1959–~1998): procedural history before the European Commission. Older cases only.": "Tylko sprzed Protokołu nr 11 (1959–ok. 1998): przebieg postępowania przed Europejską Komisją Praw Człowieka. Wyłącznie starsze sprawy.",
    "Pre-Protocol-11 only: parties' formal final arguments to the Court before the Merits.": "Tylko sprzed Protokołu nr 11: formalne końcowe wnioski stron przed Trybunałem, poprzedzające część dotyczącą meritum.",
    "Article 46 supervisory measures — rare; only in cases ordering structural change.": "Środki na podstawie art. 46 — rzadkie; tylko w sprawach wymagających zmian systemowych.",
    "Annexes and applicant data tables (mostly Committee-format mass cases).": "Załączniki i tabele z danymi skarżących (głównie masowe sprawy rozpatrywane przez Komitety).",
    // Notices of communication (communicated cases)
    "Communicated case": "Sprawa zakomunikowana",
    "Communicated cases": "Sprawy zakomunikowane",
    "Pending": "W toku",
    "Question": "Pytanie",
    "Statement of Facts": "Stan faktyczny",
    "Relevant Law": "Właściwe prawo",
    "Complaints": "Zarzuty",
    "Questions to the Parties": "Pytania do stron",
    "Status": "Status",
    "Pending (as of HUDOC)": "W toku (według HUDOC)",
    "Decided by judgment": "Zakończona wyrokiem",
    "Decided by decision": "Zakończona decyzją",

    // Outcomes (OUTCOME_LABELS, OUTCOME_SHORT, OUTCOME_OPTIONS)
    "Violation only": "Wyłącznie naruszenie",
    "Non-violation only": "Wyłącznie brak naruszenia",
    "Mixed (violation + non-violation)": "Mieszane (naruszenie + brak naruszenia)",
    "No finding": "Brak rozstrzygnięcia",
    "Inadmissible (in whole or in part)": "Niedopuszczalna (w całości lub w części)",
    "Struck out": "Skreślona z listy",
    "Violation found": "Stwierdzono naruszenie",
    "No violation": "Brak naruszenia",
    "Non-violation": "Brak naruszenia",
    "Violation": "Naruszenie",
    "Mixed": "Mieszane",
    "Inadmissible": "Niedopuszczalna",
    "Partly admissible": "Częściowo dopuszczalna",
    "Partly inadmissible": "Częściowo niedopuszczalna",
    "Struck out / inadmissible": "Skreślona / niedopuszczalna",
    "Admissible": "Dopuszczalna",
    "Decision: inadmissible": "Decyzja: niedopuszczalna",
    "Decision: partly admissible, partly inadmissible": "Decyzja: częściowo dopuszczalna, częściowo niedopuszczalna",
    "Decision: partly inadmissible (the rest not decided in it)": "Decyzja: częściowo niedopuszczalna (w pozostałym zakresie nierozstrzygnięta)",
    "Decision: partly struck out of the list, partly inadmissible": "Decyzja: częściowo skreślona z listy, częściowo niedopuszczalna",
    "Decision: admissible": "Decyzja: dopuszczalna",
    "Decision: struck out of the list": "Decyzja: skreślona z listy",
    "The Court found at least one violation (possibly alongside no-violation findings on other complaints).": "Trybunał stwierdził co najmniej jedno naruszenie (ewentualnie obok braku naruszenia co do innych zarzutów).",
    "The Court found no violation on any complaint it examined.": "Trybunał nie stwierdził naruszenia co do żadnego z rozpatrzonych zarzutów.",
    "Application declared inadmissible in whole or in part.": "Skarga uznana za niedopuszczalną w całości lub w części.",
    "Case struck out of the list (friendly settlement, withdrawal, etc.).": "Skarga skreślona z listy (ugoda, wycofanie skargi itp.).",

    // Importance (IMPORTANCE_LABELS, IMPORTANCE_TOOLTIPS)
    "Key cases": "Sprawy kluczowe",
    "Key case": "Sprawa kluczowa",
    "KEY": "KLUCZOWA",
    "1 — High": "1 — wysokie",
    "2 — Medium": "2 — średnie",
    "3 — Low": "3 — niskie",
    "Unspecified": "Nieokreślone",
    "The Court's most significant judgments since 1998 — published in the official Reports (1998–2015) or selected as key cases by the Bureau (2016 on). Pre-1998 (old Court) judgments are classified by levels 1–3 only.": "Najważniejsze wyroki Trybunału od 1998 r. — opublikowane w oficjalnym zbiorze Reports (1998–2015) lub wybrane przez Prezydium jako sprawy kluczowe (od 2016 r.). Wyroki sprzed 1998 r. (dawny Trybunał) mają wyłącznie poziomy 1–3.",
    "High importance — judgments that make a significant contribution to the development, clarification or modification of the case-law. Provisional until the Bureau decides on Key-case selection.": "Wysokie znaczenie — wyroki, które w istotny sposób przyczyniają się do rozwoju, wyjaśnienia lub zmiany orzecznictwa. Kwalifikacja tymczasowa do czasu decyzji Prezydium o wyborze spraw kluczowych.",
    "Medium importance — judgments that, while not significantly contributing to the case-law, go beyond merely applying existing case-law. Provisional until the Bureau decides on Key-case selection.": "Średnie znaczenie — wyroki, które nie wnoszą istotnego wkładu do orzecznictwa, ale wykraczają poza samo zastosowanie dotychczasowego orzecznictwa. Kwalifikacja tymczasowa do czasu decyzji Prezydium o wyborze spraw kluczowych.",
    "Low importance — judgments of little legal interest (apply existing case-law, friendly settlements, strike-outs)": "Niskie znaczenie — wyroki o niewielkim znaczeniu prawnym (stosujące dotychczasowe orzecznictwo, ugody, skreślenia z listy)",
    "Importance level not assigned in HUDOC metadata": "Poziom znaczenia nieprzypisany w metadanych HUDOC",

    // Result cards
    "in heading": "w nagłówku",
    "in quote": "w cytacie",
    "operative": "sentencja",
    "The query matched in a section heading attached to this paragraph": "Zapytanie pasuje do nagłówka części, do której należy ten paragraf",
    "The query matched in a quote nested inside this paragraph": "Zapytanie pasuje do cytatu zawartego w tym paragrafie",
    "The query matched in an operative-part clause": "Zapytanie pasuje do punktu sentencji",
    "The query matched inside quoted material — a Convention article, domestic law or other source — not the Court's own reasoning": "Zapytanie pasuje do cytowanego materiału — artykułu Konwencji, prawa krajowego lub innego źródła — a nie do własnego rozumowania Trybunału",
    "Open on HUDOC at this paragraph (its opening words are copied, for Find)": "Otwórz w HUDOC przy tym paragrafie (jego pierwsze słowa są kopiowane, by odszukać je na stronie)",
    "Open this judgment on HUDOC": "Otwórz ten wyrok w HUDOC",
    "Copy an OSCOLA citation of this paragraph": "Kopiuj cytowanie OSCOLA tego paragrafu",
    "Copy an OSCOLA citation of the judgment": "Kopiuj cytowanie OSCOLA wyroku",
    "Copy an OSCOLA citation": "Kopiuj cytowanie OSCOLA",
    "Copy an OSCOLA citation with the paragraph shown": "Kopiuj cytowanie OSCOLA z pokazanym paragrafem",
    "Copy the text of this paragraph": "Kopiuj tekst tego paragrafu",
    "Copy paragraph citation": "Kopiuj cytowanie paragrafu",
    "Copy paragraph text": "Kopiuj tekst paragrafu",
    "Cite": "Cytuj",
    "Cite ¶": "Cytuj ¶",
    "Copy": "Kopiuj",
    "Remove from your Workspace": "Usuń z obszaru roboczego",
    "Save to your Workspace": "Zapisz w obszarze roboczym",
    "Save this paragraph to your Workspace": "Zapisz ten paragraf w obszarze roboczym",
    "★ Saved": "★ Zapisano",
    "★ Bookmarked": "★ Zapisano",
    "☆ Bookmark": "☆ Zapisz",
    "Show this paragraph in the Case Note": "Pokaż ten paragraf w szczegółach sprawy",
    "Only in French on HUDOC · machine translation, unofficial": "Tylko po francusku w HUDOC · tłumaczenie maszynowe, nieoficjalne",
    "Only in French on HUDOC · third-party translation, unofficial": "Tylko po francusku w HUDOC · tłumaczenie podmiotu zewnętrznego, nieoficjalne",
    "HUDOC publishes this judgment only in French. This English text is a machine translation made for this tool, not a translation by the Court.": "HUDOC publikuje ten wyrok tylko po francusku. Tekst angielski to tłumaczenie maszynowe wykonane na potrzeby tego narzędzia, a nie tłumaczenie Trybunału.",
    "HUDOC publishes this judgment only in French. This English text is a translation by a third party, which HUDOC also publishes; it is not the Court's text.": "HUDOC publikuje ten wyrok tylko po francusku. Tekst angielski to tłumaczenie podmiotu zewnętrznego, również opublikowane w HUDOC; nie jest to tekst Trybunału.",
    "An unofficial English machine translation of this judgment is available: switch to it in the case details.": "Dostępne jest nieoficjalne angielskie tłumaczenie maszynowe tego wyroku: można je włączyć w szczegółach sprawy.",
    "EN translation": "tłumaczenie EN",
    "The authentic French text on HUDOC": "Autentyczny tekst francuski w HUDOC",
    "French original ↗": "Oryginał francuski ↗",
    "Show or hide matched paragraphs": "Pokaż lub ukryj pasujące paragrafy",
    "Influence": "Cytowania",
    "What Influence shows": "Co pokazują cytowania",
    "cites": "cytuje",
    "cited by": "cytowany przez",
    "only in French": "tylko po francusku",
    "Citation-graph coverage is partial — no citation data recorded for this case": "Graf cytowań jest niepełny — brak danych o cytowaniach tej sprawy",
    "Only in French on HUDOC — not in this corpus": "Tylko po francusku w HUDOC — poza tym korpusem",
    "No cited judgments recorded.": "Brak zarejestrowanych orzeczeń cytowanych.",
    "No citing judgments recorded.": "Brak zarejestrowanych orzeczeń cytujących.",
    "Cites": "Cytuje",
    "Cited by": "Cytowany przez",
    "— other judgments and decisions this one refers to.": "— inne wyroki i decyzje, na które powołuje się to orzeczenie.",
    "— later judgments and decisions that refer to this one, including judgments HUDOC has only in French.": "— późniejsze wyroki i decyzje, które powołują się na to orzeczenie, w tym wyroki dostępne w HUDOC tylko po francusku.",
    "Cites and Cited by count documents, not mentions: a judgment that refers to the case in ten paragraphs counts once.": "„Cytuje” i „Cytowany przez” liczą dokumenty, a nie wzmianki: wyrok, który powołuje się na sprawę w dziesięciu paragrafach, liczy się raz.",
    "The bars compare the two numbers of this judgment. A dash means no citation data.": "Paski porównują obie liczby dla tego wyroku. Kreska oznacza brak danych o cytowaniach.",
    "How citations are found": "Jak ustalane są cytowania (EN)",
    "Run a full-text query to load matched paragraphs for this case.": "Wpisz zapytanie pełnotekstowe, aby wczytać pasujące paragrafy tej sprawy.",
    "No paragraphs for current filters.": "Brak paragrafów przy bieżących filtrach.",
    "Case record only in recent-cases browse mode. Enter a full-text query to surface matched paragraphs from this judgment.": "W trybie przeglądania najnowszych spraw widoczna jest tylko metryka sprawy. Wpisz zapytanie pełnotekstowe, aby zobaczyć pasujące paragrafy tego wyroku.",
    "Case record": "Metryka sprawy",
    "CASE": "SPRAWA",
    "No articles listed": "Brak wskazanych artykułów",
    "Inadmissibility": "Niedopuszczalność",
    "Procedural aspect": "Aspekt proceduralny",
    "Substantive aspect": "Aspekt materialny",
    "No procedural flags": "Brak oznaczeń proceduralnych",
    "Unnumbered fragment (no HUDOC paragraph number)": "Fragment bez numeru (brak numeru paragrafu w HUDOC)",
    "Prev": "Poprzednia",
    "Next": "Następna",

    // Case details (Case Note)
    "Case details": "Szczegóły sprawy",
    "Awaiting results": "Oczekiwanie na wyniki",
    "Run a search or select a result to see judgment context here.": "Uruchom wyszukiwanie lub wybierz wynik, aby zobaczyć tu kontekst orzeczenia.",
    "Case Note text size": "Rozmiar tekstu w szczegółach sprawy",
    "Smaller text": "Mniejszy tekst",
    "Larger text": "Większy tekst",
    "Decrease Case Note text size": "Zmniejsz tekst w szczegółach sprawy",
    "Increase Case Note text size": "Powiększ tekst w szczegółach sprawy",
    "Close case details (Esc)": "Zamknij szczegóły sprawy (Esc)",
    "Close case details": "Zamknij szczegóły sprawy",
    "More about this case": "Więcej o sprawie",
    "Respondent State": "Pozwane państwo",
    "Applications": "Skargi",
    "Formation": "Skład orzekający",
    "Outcome": "Rozstrzygnięcie",
    "Document": "Dokument",
    "Importance": "Znaczenie",
    "Articles": "Artykuły",
    "Type": "Rodzaj",
    "Separate opinions": "Zdania odrębne",
    "yes": "tak",
    "none": "brak",
    "Strasbourg case-law cited": "Cytowane orzecznictwo strasburskie",
    "HUDOC conclusion": "Konkluzja w HUDOC",
    "Keywords": "Słowa kluczowe",
    "Domestic law": "Prawo krajowe",
    "International law": "Prawo międzynarodowe",
    "Rules of Court": "Regulamin Trybunału",
    "Registry summary": "Streszczenie Kancelarii",
    "Search this case": "Wyszukaj tę sprawę",
    "No citations recorded. HUDOC does not analyse cited case-law for importance-3 judgments (HUDOC FAQ §12); our text-extracted graph also found none here": "Brak zarejestrowanych cytowań. HUDOC nie analizuje cytowanego orzecznictwa w wyrokach o znaczeniu 3 (HUDOC FAQ §12); nasz graf oparty na tekście również ich tu nie znalazł",
    "This browse result is a case record. Run a full-text query to see matched paragraphs in this note.": "Ten wynik przeglądania to metryka sprawy. Wpisz zapytanie pełnotekstowe, aby zobaczyć tu pasujące paragrafy.",
    "No paragraph preview is available for this result.": "Podgląd paragrafu nie jest dostępny dla tego wyniku.",
    "Loading paragraph context…": "Wczytywanie kontekstu paragrafu…",
    "Paragraph context unavailable.": "Kontekst paragrafu jest niedostępny.",
    "Version of the text": "Wersja tekstu",
    "Français · original": "Français · oryginał",
    "English · machine translation": "English · tłumaczenie maszynowe",
    "Unofficial machine translation, not the Court’s text: quote the French original (": "Nieoficjalne tłumaczenie maszynowe, a nie tekst Trybunału: cytuj oryginał francuski (",
    "Unofficial machine translation, not the Court’s text: quote the French original.": "Nieoficjalne tłumaczenie maszynowe, a nie tekst Trybunału: cytuj oryginał francuski.",
    "Unofficial translation by a third party, published on HUDOC, not the Court’s text: quote the French original (": "Nieoficjalne tłumaczenie podmiotu zewnętrznego, opublikowane w HUDOC, a nie tekst Trybunału: cytuj oryginał francuski (",
    "Unofficial translation by a third party, published on HUDOC, not the Court’s text: quote the French original.": "Nieoficjalne tłumaczenie podmiotu zewnętrznego, opublikowane w HUDOC, a nie tekst Trybunału: cytuj oryginał francuski.",

    // Paragraph in context (dossier drawer)
    "Close (Esc)": "Zamknij (Esc)",
    "Close dossier": "Zamknij panel",
    "Close": "Zamknij",
    "Could not load this judgment.": "Nie udało się wczytać tego wyroku.",
    "Paragraph not found in this judgment.": "Nie znaleziono tego paragrafu w wyroku.",

    // Name matches
    "Case name match": "Sprawa o tej nazwie",
    "Show this case": "Pokaż tę sprawę",
    "Open in HUDOC ↗": "Otwórz w HUDOC ↗",
    "The judgments below are the full-text hits: the named case first when it is among them, then those that cite or discuss it.": "Poniższe wyroki to trafienia pełnotekstowe: najpierw wskazana sprawa, jeśli jest wśród nich, a następnie orzeczenia, które ją cytują lub omawiają.",

    // Footnotes
    "In footnotes": "W przypisach",
    "Matches in the judgments' footnotes, under the same filters. They are listed apart and do not change the ranking above.": "Trafienia w przypisach do wyroków, przy tych samych filtrach. Są wyświetlane osobno i nie zmieniają kolejności wyników powyżej.",
    "The reference to these notes could not be located in the text": "Nie udało się ustalić miejsca odesłania do tych przypisów w tekście",
    "Note:": "Przypis:",
    "Notes:": "Przypisy:",

    // No results
    "No results found": "Brak wyników",
    "Try different search terms, broader filters, or check your spelling.": "Spróbuj innych słów lub szerszych filtrów albo sprawdź pisownię.",
    "← Back to search": "← Powrót do wyszukiwania",
    "A very common search": "Bardzo ogólne wyszukiwanie",
    "or a filter (Article, State, years) to narrow it down.": "lub filtr (artykuł, państwo, lata), aby zawęzić wyszukiwanie.",
    "Show the results anyway": "Mimo to pokaż wyniki",
    "(this takes about 20 seconds).": "(potrwa to około 20 sekund).",
    "No judgment contains": "Żaden wyrok nie zawiera słowa",
    ". Did you mean": ". Czy chodziło o",
    "search in French": "szukaj po francusku",
    "The judgments are in English.": "Wyroki są w języku angielskim.",
    "Semantic Search": "Wyszukiwanie semantyczne",
    "also understands a description in another language.": "rozumie też opis w innym języku.",
    "No paragraph of the text matches, but the footnotes below do.": "Żaden paragraf tekstu nie pasuje, ale pasują przypisy poniżej.",
    "Include the advisory opinions": "Uwzględnij opinie doradcze",
    "Search the footnotes too": "Przeszukaj także przypisy",
    "No paragraph contains all of your words.": "Żaden paragraf nie zawiera wszystkich słów zapytania.",
    "Search for any of them": "Szukaj któregokolwiek z nich",
    "Your words occur in the judgments, but no paragraph passes the current filters or operators.": "Słowa występują w wyrokach, ale żaden paragraf nie spełnia bieżących filtrów lub operatorów.",
    "Search without filters": "Szukaj bez filtrów",
    "There is no search field called": "Nie ma pola wyszukiwania o nazwie",
    ", so it was searched as ordinary words. The common ones are": ", więc wyszukano je jako zwykłe słowa. Najczęściej używane pola to",
    ", and there are": "; jest też",
    "seven others": "siedem innych",
    "Search without it": "Szukaj bez niego",
    "No paragraph contains that exact wording.": "Żaden paragraf nie zawiera dokładnie tego sformułowania.",
    "Search the same words without the quotation marks": "Szukaj tych samych słów bez cudzysłowu",
    "Nothing here matches those words.": "Nic tu nie pasuje do tych słów.",
    "Describe the case in Semantic Search": "Opisz sprawę w wyszukiwaniu semantycznym (EN)",
    "instead — it ranks by meaning, so it always returns something.": "— szereguje wyniki według znaczenia, więc zawsze coś zwraca.",
    "Include them": "Uwzględnij je",
    "No case contains every word of your query — showing the closest matches (any of your terms, best first). Tip: quote a phrase to make it mandatory.": "Żadna sprawa nie zawiera wszystkich słów zapytania — wyświetlane są najbliższe dopasowania (którekolwiek ze słów, najlepsze najpierw). Wskazówka: ujmij frazę w cudzysłów, aby była obowiązkowa.",

    // Semantic Search nudge
    "Looking for the": "Szukasz",
    "concept": "pojęcia",
    "rather than the exact word?": "zamiast dokładnego słowa?",
    "Try": "Spróbuj",
    "matches by legal substance — the Court may phrase it differently (e.g. “private life”)": "dopasowuje według treści prawnej — Trybunał może ująć to innymi słowami (np. „private life”)",

    // Workspace toasts (assets/workspace.js) and the consent bar (assets/analytics-consent.js)
    "Name this search": "Nazwij to wyszukiwanie",
    "The workspace could not be saved: this browser's storage is full or switched off.": "Nie udało się zapisać obszaru roboczego: pamięć tej przeglądarki jest pełna lub wyłączona.",
    "Saved in this browser only. Clearing browser data deletes your workspace — Workspace → Export keeps a copy.": "Zapisano tylko w tej przeglądarce. Wyczyszczenie danych przeglądarki usuwa obszar roboczy — kopię zachowasz przez Obszar roboczy → Eksport.",
    "The note could not be saved.": "Nie udało się zapisać notatki.",
    "RSS address copied. Paste it into a feed reader (Feedly, Inoreader, Thunderbird…) to be told of new judgments that match this search.": "Skopiowano adres RSS. Wklej go do czytnika kanałów (Feedly, Inoreader, Thunderbird…), aby dostawać informacje o nowych wyrokach pasujących do tego wyszukiwania.",
    "A cookie-free counter records which page is opened. We’d also like to use Google Analytics to see which views get used; it stays off unless you allow it. Neither ever receives your searches, your filters, or the judgments you open.": "Licznik bez plików cookie rejestruje, która strona została otwarta. Chcielibyśmy też korzystać z Google Analytics, by sprawdzać, które widoki są używane; pozostaje wyłączony, dopóki na to nie zezwolisz. Żadne z tych narzędzi nie otrzymuje Twoich zapytań, filtrów ani otwieranych wyroków.",
    "What this means": "Co to oznacza",
    "Reject": "Odrzuć",
    "Allow": "Zezwól",
    "Reset analytics choice": "Zmień decyzję w sprawie analityki",
    // "Use with AI" button (assets/tour.js); the card's help text stays in English
    "Use with AI": "Użyj z asystentem AI",
    "Use HUDOC Researcher from your AI assistant": "Korzystaj z HUDOC Researcher przez asystenta AI",
    "Use it from your AI assistant": "Korzystaj z narzędzia przez asystenta AI",

    // Respondent States (COUNTRY_NAMES and the names HUDOC sends)
    "Albania": "Albania", "Andorra": "Andora", "Armenia": "Armenia", "Austria": "Austria", "Azerbaijan": "Azerbejdżan",
    "Belgium": "Belgia", "Bosnia and Herzegovina": "Bośnia i Hercegowina", "Bulgaria": "Bułgaria", "Croatia": "Chorwacja",
    "Cyprus": "Cypr", "Czech Republic": "Czechy", "Czechia": "Czechy", "Denmark": "Dania", "Estonia": "Estonia",
    "Finland": "Finlandia", "France": "Francja", "Georgia": "Gruzja", "Germany": "Niemcy", "Greece": "Grecja",
    "Hungary": "Węgry", "Iceland": "Islandia", "Ireland": "Irlandia", "Italy": "Włochy", "Latvia": "Łotwa",
    "Liechtenstein": "Liechtenstein", "Lithuania": "Litwa", "Luxembourg": "Luksemburg", "Malta": "Malta",
    "Moldova": "Mołdawia", "Republic of Moldova": "Mołdawia", "the Republic of Moldova": "Mołdawia", "Monaco": "Monako",
    "Montenegro": "Czarnogóra", "Netherlands": "Niderlandy", "the Netherlands": "Niderlandy",
    "North Macedonia": "Macedonia Północna", "the former Yugoslav Republic of Macedonia": "Macedonia Północna",
    "Norway": "Norwegia", "Poland": "Polska", "Portugal": "Portugalia", "Romania": "Rumunia", "Russia": "Rosja",
    "Russian Federation": "Rosja", "San Marino": "San Marino", "Serbia": "Serbia", "Serbia and Montenegro": "Serbia i Czarnogóra",
    "Slovakia": "Słowacja", "Slovak Republic": "Słowacja", "Slovenia": "Słowenia", "Spain": "Hiszpania", "Sweden": "Szwecja",
    "Switzerland": "Szwajcaria", "Turkey": "Turcja", "Türkiye": "Turcja", "Ukraine": "Ukraina",
    "United Kingdom": "Wielka Brytania", "the United Kingdom": "Wielka Brytania",
  };

  // The five Sections, their Committees, and HUDOC's "Court (…)" forms of each.
  var ORD = { First: "Pierwsza", Second: "Druga", Third: "Trzecia", Fourth: "Czwarta", Fifth: "Piąta" };
  Object.keys(ORD).forEach(function (o) {
    var p = ORD[o];
    EXACT_OBJ[o + " Section"] = "Sekcja " + p;
    EXACT_OBJ[o + " Section Committee"] = "Komitet (Sekcja " + p + ")";
    EXACT_OBJ["Court (" + o + " Section)"] = "Trybunał (Sekcja " + p + ")";
    EXACT_OBJ["Court (" + o + " Section Committee)"] = "Trybunał (Komitet, Sekcja " + p + ")";
  });

  var EXACT = new Map(Object.keys(EXACT_OBJ).map(function (k) { return [k, EXACT_OBJ[k]]; }));

  /* "Chamber decision" (result card, case details): the decision of a formation. */
  var DECISION_OF = { "Chamber": "Decyzja Izby", "Grand Chamber": "Decyzja Wielkiej Izby", "Committee": "Decyzja Komitetu",
    "Plenary": "Decyzja plenum", "Commission": "Decyzja Komisji" };
  var MODE = { browse: "przeglądanie", search: "wyszukiwanie", server: "serwer", "100 most recent": "100 najnowszych",
    "full dataset": "pełny zbiór" };
  function modePl(mode) {
    return mode.split(" · ").map(function (p) {
      var m = /^limited to (\d+) hits$/.exec(p);
      return m ? "ograniczone do " + m[1] + " trafień" : (MODE[p] || p);
    }).join(" · ");
  }
  function sub(s) { var r = tr(s); return r == null ? s : r; }   // translate a fragment, or keep it

  /* ── RULES: templated strings (regex on the whole trimmed text) ───────── */
  var RULES = [
    // Plain numbers (counts) and dates in chips and labels
    [/^\d{1,3}(?:,\d{3})+$/, function (m) { return plNum(m); }],
    [new RegExp("^(?:\\d{1,2} )?(?:" + LONG + "|" + SHORT + ")\\.? \\d{4}$"), function (m) { return plDates(m); }],
    // How current the data is (#dataAsOf)
    [/^Case-law to (.+)$/, function (m, d) { return "Orzecznictwo do " + plDates(d); }],
    [/^Newest judgment in the corpus: (.+?)(?:; checked against HUDOC on (.+?))?\. Later judgments and decisions are not here yet: check HUDOC for them\.$/,
      function (m, a, b) { return "Najnowszy wyrok w korpusie: " + plDates(a) + (b ? "; sprawdzono w HUDOC " + plDates(b) : "") + ". Późniejszych wyroków i decyzji jeszcze tu nie ma: należy ich szukać w HUDOC."; }],
    // Results header and status line
    [/^\(([\d.]+)s · page (\d+)\/(\d+) · (.+)\)$/, function (m, s, a, b, mode) { return "(" + s.replace(".", ",") + " s · strona " + a + "/" + b + " · " + modePl(mode) + ")"; }],
    [/^(\S+) (passages|cases|recent cases) (?:from|z) (\S+) (.+)$/, function (m, a, b, c, d) {
      return plNum(a) + " " + pick(NOM[b], toInt(a)) + " z " + plNum(c) + " " + (genLabel(d, toInt(c)) || d); }],
    [/^Searching (.+)…$/, function (m, what) {
      var r = /^([\d,]+) (.+)$/.exec(what);
      var g = r ? genLabel(r[2], 2) : genLabel(what, 2);
      return g ? "Przeszukiwanie " + (r ? plNum(r[1]) + " " : "") + g + "…" : "Przeszukiwanie: " + what + "…"; }],
    [/^Also in ([\d,]+) advisory opinions? of the Court\.$/, function (m, n) {
      return "Także w " + plNum(n) + " " + (toInt(n) === 1 ? "opinii doradczej" : "opiniach doradczych") + " Trybunału."; }],
    [/^([\d,]+) judgments that HUDOC publishes only in French, in their authentic French text\.$/, function (m, n) {
      return plNum(n) + " " + pick(["wyrok", "wyroki", "wyroków"], toInt(n)) + ", które HUDOC publikuje tylko po francusku, w autentycznym tekście francuskim."; }],
    [/^(\S+ judgments in English(?: · .+?)?)(?: — (.+) are left out of the search until you switch them on)?\.$/, function (m, parts, off) {
      var P = { "judgments in English": ["wyrok po angielsku", "wyroki po angielsku", "wyroków po angielsku"],
        decisions: ["decyzja", "decyzje", "decyzji"], "advisory opinions": ["opinia doradcza", "opinie doradcze", "opinii doradczych"],
        "unofficial translations of French-only judgments": ["nieoficjalne tłumaczenie wyroku dostępnego tylko po francusku",
          "nieoficjalne tłumaczenia wyroków dostępnych tylko po francusku", "nieoficjalnych tłumaczeń wyroków dostępnych tylko po francusku"] };
      var OFF = { "the decisions": "decyzje", "the advisory opinions": "opinie doradcze", "the translations": "tłumaczenia" };
      var out = parts.split(" · ").map(function (p) {
        var r = /^([\d,]+) (.+)$/.exec(p);
        return r && P[r[2]] ? plNum(r[1]) + " " + pick(P[r[2]], toInt(r[1])) : p;
      }).join(" · ");
      if (off) {
        var list = off.split(/, | and /).map(function (x) { return OFF[x] || x; });
        out += " — " + (list.length > 1 ? list.slice(0, -1).join(", ") + " i " + list[list.length - 1] : list[0])
          + " są pomijane w wyszukiwaniu, dopóki ich nie włączysz";
      }
      return out + "."; }],
    [/^Counts are for the whole corpus: this search matches more than ([\d,]+) passages, too many to count by filter quickly\. The filters still apply\.$/,
      function (m, n) { return "Liczby dotyczą całego korpusu: to wyszukiwanie obejmuje ponad " + plNum(n) + " fragmentów — zbyt wiele, by szybko policzyć je według filtrów. Filtry nadal działają."; }],
    // Filter rail
    [/^Clear \((\d+)\)$/, "Wyczyść ($1)"],
    [/^(\d{4}): ([\d,]+) judgments?$/, function (m, y, n) { return y + ": " + plNum(n) + " " + pick(["wyrok", "wyroki", "wyroków"], toInt(n)); }],
    [/^(\d{4}), ([\d,]+) judgments?$/, function (m, y, n) { return y + ", " + plNum(n) + " " + pick(["wyrok", "wyroki", "wyroków"], toInt(n)); }],
    [/^([\d,]+) judgments?$/, function (m, n) { return plNum(n) + " " + pick(["wyrok", "wyroki", "wyroków"], toInt(n)); }],
    // Active filter chips and the sidebar
    [/^Search in: (.+)$/, function (m, list) { return "Szukaj w: " + list.split(", ").map(sub).join(", "); }],
    [/^Importance:? (.+)$/, function (m, v) { return "Znaczenie: " + sub(v); }],
    [/^From: (.+)$/, "Od: $1"],
    [/^To: (.+)$/, "Do: $1"],
    // Formations
    [/^((?:Grand )?Chamber|Committee|Plenary|Commission|(?:First|Second|Third|Fourth|Fifth) Section(?: Committee)?|Panel of the Grand Chamber|Court \(.+\)) decision$/,
      function (m, f) { return DECISION_OF[f] || "Decyzja (" + sub(f) + ")"; }],
    [/^no\. (.+)$/, "nr $1"],
    // Article chips
    [/^Art\. .* of Prot\. \d+.*$/, function (m) { return m.replace(/ of Prot\. (\d+)/g, " Protokołu nr $1"); }],
    [/^View ECHR Guide on Article (.+)$/, "Przewodnik ETPC po art. $1 (EN)"],
    [/^Procedural references: (.+)$/, "Przepisy proceduralne: $1"],
    [/^\+([\d,]+) more substantive$/, "+$1 więcej (materialne)"],
    [/^\+([\d,]+) procedural$/, "+$1 proceduralne"],
    [/^\+([\d,]+) more$/, "+$1 więcej"],
    // Paragraph numbers and their tooltips
    [/^HUDOC paragraph (\S+)$/, "Paragraf $1 w HUDOC"],
    [/^Internal index ¶(\d+) \(no HUDOC number\)$/, "Indeks wewnętrzny ¶$1 (bez numeru w HUDOC)"],
    [/^Continuation of HUDOC paragraph (\S+) — typically a quoted statute or treaty article that appears as a sub-block within ¶ (\S+)$/,
      "Ciąg dalszy paragrafu $1 w HUDOC — zwykle cytowany przepis ustawy lub umowy międzynarodowej, wyodrębniony w ¶ $2"],
    [/^Operative Part dispositif clause (.+)$/, function (m, n) { return "Sentencja, punkt " + (n === "(no number)" ? "(bez numeru)" : n); }],
    [/^(\d+)(?:st|nd|rd|th) separate opinion, (.+)$/, function (m, n, rest) {
      var r = /^hudoc paragraph (\S+)$/.exec(rest);
      return "Zdanie odrębne nr " + n + ", " + (r ? "paragraf " + r[1] + " w HUDOC" : rest); }],
    [/^Op\. (.+)$/, "Sent. $1"],
    [/^SO (\d+)$/, "ZO $1"],
    [/^Open on HUDOC at (.+)$/, "Otwórz w HUDOC przy: $1"],
    [/^Opening of (.+) — the paragraph this excerpt belongs to$/, "Początek $1 — paragrafu, do którego należy ten fragment"],
    [/^(\d+) match(?:es)? in same quote block$/, function (m, n) {
      return n + " " + pick(["trafienie", "trafienia", "trafień"], +n) + " w tym samym bloku cytatu"; }],
    [/^Hide the ([\d,]+) (hits?|paras?|case) ▲$/, function (m, n, w) {
      return w === "case" ? "Zwiń ▲" : "Zwiń " + (w.indexOf("hit") === 0 ? "trafienia" : "paragrafy") + " (" + plNum(n) + ") ▲"; }],
    // Citations (Influence)
    [/^Cited by ([\d,]+) other judgments and decisions, ([\d,]+) of them published by HUDOC only in French\. Each counts once, however many paragraphs refer to the case$/,
      function (m, n, f) { return "Cytowany w innych wyrokach i decyzjach: " + plNum(n) + ", w tym " + plNum(f) + " opublikowanych w HUDOC tylko po francusku. Każde orzeczenie liczy się raz, niezależnie od liczby paragrafów odsyłających do sprawy"; }],
    [/^Cited by ([\d,]+) other judgments and decisions in this dataset\. Each counts once, however many paragraphs refer to the case$/,
      function (m, n) { return "Cytowany w innych wyrokach i decyzjach w tym zbiorze: " + plNum(n) + ". Każde orzeczenie liczy się raz, niezależnie od liczby paragrafów odsyłających do sprawy"; }],
    [/^([\d,]+) only in French$/, function (m, n) { return "w tym " + plNum(n) + " tylko po francusku"; }],
    [/^Show the ([\d,]+) (cites|cited by)$/, function (m, n, d) { return "Pokaż orzeczenia " + (d === "cites" ? "cytowane" : "cytujące") + " (" + plNum(n) + ")"; }],
    [/^Showing the ([\d,]+) (most often referred to|most recent) of ([\d,]+)\.$/, function (m, n, k, t) {
      return "Pokazano " + plNum(n) + " " + (k === "most recent" ? "najnowszych" : "najczęściej przywoływanych") + " z " + plNum(t) + "."; }],
    [/^(\d+) paragraphs? refers? to it$/, "Paragrafy odsyłające do tego orzeczenia: $1"],
    [/^Could not load the citations \((.*)\)\.$/, "Nie udało się wczytać cytowań ($1)."],
    // Case details and the paragraph drawer
    [/^(↑|↓) show (\d+) (earlier|later)(?: · (\d+) more in section)?$/, function (m, a, n, w, more) {
      var forms = w === "earlier" ? ["wcześniejszy", "wcześniejsze", "wcześniejszych"] : ["późniejszy", "późniejsze", "późniejszych"];
      return a + " pokaż " + n + " " + pick(forms, +n) + (more ? " · jeszcze " + more + " w tej części" : ""); }],
    [/^Show entire section \((\d+) ¶\)$/, "Pokaż całą część ($1 ¶)"],
    [/^Collapse to ±(\d+)$/, "Zwiń do ±$1"],
    [/^Dossier · (.+)$/, "Kontekst · $1"],
    // Footnotes
    [/^([\d,]+) notes? in ([\d,]+) judgments?(?: · the first (\d+) shown)?$/, function (m, n, c, first) {
      return plNum(n) + " " + pick(["przypis", "przypisy", "przypisów"], toInt(n)) + " w " + plNum(c) + " "
        + (toInt(c) === 1 ? "wyroku" : "wyrokach") + (first ? " · pokazano pierwsze " + first : ""); }],
    [/^Footnote (\S+)$/, "Przypis $1"],
    [/^Endnote (\S+)$/, "Przypis końcowy $1"],
    // No results
    [/^Your words occur in (.+?) paragraphs, in nearly every judgment, so a ranking of them says little\. Add another word, a$/,
      function (m, n) { return "Słowa występują w " + plNum(n.replace(/^(\d+)\.(\d) million$/, "$1,$2 mln")) + " paragrafach, niemal w każdym wyroku, więc ich ranking niewiele mówi. Dodaj kolejne słowo, frazę"; }],
    [/^([.?]) It occurs in (.+?) paragraphs of the French originals:$/, function (m, p, n) {
      return p + " Występuje w " + plNum(n) + " paragrafach oryginałów francuskich:"; }],
    [/^Your words occur in ([\d,]+) advisory opinions? of the Court\.$/, function (m, n) {
      return "Słowa występują w " + plNum(n) + " " + (toInt(n) === 1 ? "opinii doradczej" : "opiniach doradczych") + " Trybunału."; }],
    [/^Your words occur in the footnotes of ([\d,]+) judgments?\.$/, function (m, n) {
      return "Słowa występują w przypisach " + plNum(n) + " " + (toInt(n) === 1 ? "wyroku" : "wyroków") + "."; }],
    // Semantic Search nudge, workspace toast
    [/^for “(.*)” →$/, "dla „$1” →"],
    [/^Saved to your Workspace: “(.*)”\.$/, "Zapisano w obszarze roboczym: „$1”."],
  ];

  /* ── Lookup ───────────────────────────────────────────────────────────── */
  var CACHE = new Map();
  function norm(s) { return String(s).replace(/\s+/g, " ").trim(); }
  /* The Polish form of a trimmed English string, or null. */
  function tr(key) {
    if (!key) return null;
    var hit = EXACT.get(key);
    if (hit !== undefined) return hit;
    if (key.length > 700 || !/[A-Za-z0-9]/.test(key)) return null;
    if (CACHE.has(key)) return CACHE.get(key);
    var out = null;
    for (var i = 0; i < RULES.length && out == null; i++) {
      var rx = RULES[i][0];
      if (rx.test(key)) out = key.replace(rx, RULES[i][1]);
    }
    // "Poland · 12 Mar 2024 · no. 12345/06", "¶ 12 · Merits": translate the parts that are known.
    if (out == null && key.indexOf(" · ") > 0) {
      var parts = key.split(" · "), changed = false;
      var mapped = parts.map(function (p) { var r = tr(p); if (r != null && r !== p) changed = true; return r == null ? p : r; });
      if (changed) out = mapped.join(" · ");
    }
    if (key.length < 200) {
      if (CACHE.size > 5000) CACHE.clear();
      CACHE.set(key, out);
    }
    return out;
  }
  function t(text) {
    var s = String(text == null ? "" : text);
    var out = tr(norm(s));
    if (out == null) return s;
    return /^\s*/.exec(s)[0] + out + /\s*$/.exec(s)[0];
  }

  /* ── What is never translated ─────────────────────────────────────────── */
  // The Court's texts and anything quoted from HUDOC: paragraph text and snippets (search-app.js
  // serverSnippetToHtml, paraTextHtml), lead-ins, case titles in cards / case details / drawer / name
  // matches / citation lists / footnote results, HUDOC metadata lists, the user's own labels, code.
  var HARD = "[data-no-i18n],[translate='no'],code,pre,script,style,textarea";
  var SKIP = [HARD, "mark", ".hl",
    ".para-text", ".researcher-primary-text", ".para-context-lead", ".para-context-lead-inline", ".pr-snippet-quote",
    ".case-title", ".pr-case", ".dossier-case-title", ".cn-zoom-wrap > h3",
    ".dossier-ctx-para", ".dossier-ctx-body", ".dossier-ctx-quote",
    ".nm-title", ".cite-graph-rows a", ".cite-graph-rows button",
    ".fn-res-title", ".fn-res-snippet", ".fn-popover-text", ".fn-marker",
    ".registry-detail p", ".rs-conclusions", ".cn-meta-sec ul",
    ".word-cloud", "#keywordsFilters label", ".filter-chip[title='HUDOC keyword']",
    ".classifier-sample-card", ".para-label-badges", ".classifier-chip-list"].join(",");
  // Interface bits that sit inside those containers.
  var ALLOW = ".nm-key,.case-only-note,.fn-loose,.dossier-ctx-num,.dossier-para-actions a,.dossier-para-actions button,"
    + ".match-source-badge,.filter-count,.cn-key";
  // Attributes: skip only where an attribute can carry the Court's text (a note's opening words, HUDOC conclusions).
  var ATTR_SKIP = HARD + ",.fn-marker,.cn-art,#searchInput";
  // Interface strings that search-app.js writes straight into a text container.
  var SAFE = new Set(["No paragraphs for current filters.", "Run a full-text query to load matched paragraphs for this case.",
    "Awaiting results", "No data"]);
  // Subtrees not walked at all (a speed-up only; SKIP is the safety net).
  var REJECT = "script,style,code,pre,textarea,svg,mark,.case-title,.pr-case,.dossier-case-title,.para-context-lead,"
    + ".para-context-lead-inline,.pr-snippet-quote,.fn-res-snippet,.fn-popover-text,.rs-conclusions,.word-cloud,"
    + "[data-no-i18n],[translate='no']";

  function skipped(node, parent, key) {
    if (parent.closest(HARD)) return true;
    if (SAFE.has(key) || parent.matches(ALLOW)) return false;
    if (parent.closest(SKIP)) return true;
    // Breadcrumbs: the drawer's starts with the section label, then the judgment's own heading; the
    // Case Note's are the judgment's headings verbatim unless it shows the section label alone.
    if (parent.classList.contains("dossier-breadcrumb")) {
      if (parent.closest(".dossier-body")) return node !== parent.firstChild;
      return !!parent.querySelector(".dossier-bc-sep");
    }
    return false;
  }

  /* ── Labels whose form depends on a count beside them ─────────────────── */
  var COUNT_FOR = { resultsHitsLabel: "resultsHits", resultsCasesLabel: "resultsCases", queryMatchLabel: "queryMatchCount" };
  var LABEL_FOR = { resultsHits: "resultsHitsLabel", resultsCases: "resultsCasesLabel", queryMatchCount: "queryMatchLabel" };
  var SRC = new WeakMap();   // text node -> the English it was translated from
  function countOf(id) { var e = document.getElementById(id); return e ? toInt(e.textContent) : null; }
  function contextual(parent, key) {
    var id = parent.id;
    if (id === "resultsHitsLabel" || id === "queryMatchLabel") return NOM[key] ? pick(NOM[key], countOf(COUNT_FOR[id])) : undefined;
    if (id === "resultsCasesLabel") {
      // Communicated-cases mode: the results are notices, whatever noun search-app.js picked.
      var comm = document.body.classList.contains("comm-mode") && /^(judgments?|documents?)$/.test(key);
      return genLabel(comm ? "communicated cases" : key, countOf("resultsCases"));
    }
    if (parent.classList.contains("hit-label")) {
      var prev = parent.previousElementSibling;
      return NOM[key] ? pick(NOM[key], prev ? toInt(prev.textContent) : null) : undefined;
    }
    if (key === "Semantic Search" && parent.tagName === "STRONG" && parent.closest(".semantic-hint")) return "wyszukiwania semantycznego";
    return undefined;
  }
  function relabel(labelId) {
    var lab = document.getElementById(labelId);
    var node = lab && lab.firstChild;
    if (!node || node.nodeType !== 3 || !SRC.has(node)) return;
    var out = contextual(lab, SRC.get(node));
    if (out && node.data !== out) node.data = out;
  }

  /* ── Applying it ──────────────────────────────────────────────────────── */
  var ATTRS = ["title", "aria-label", "placeholder", "data-tooltip"];
  function doText(node) {
    var parent = node.parentElement;
    if (!parent) return;
    if (LABEL_FOR[parent.id]) relabel(LABEL_FOR[parent.id]);   // a count changed: its noun may change form
    var s = node.data;
    if (!s || s.length > 700 || !/[A-Za-z0-9]/.test(s)) return;
    var key = norm(s);
    var out = contextual(parent, key);
    if (out === undefined) out = tr(key);
    if (out == null || out === key || skipped(node, parent, key)) return;
    var next = /^\s*/.exec(s)[0] + out + /\s*$/.exec(s)[0];
    if (next !== s) { SRC.set(node, key); node.data = next; }
  }
  function doAttr(el, name) {
    var v = el.getAttribute(name);
    if (!v || v.length > 700 || !/[A-Za-z0-9]/.test(v)) return;
    var out = tr(norm(v));
    if (out == null || out === v || el.closest(ATTR_SKIP)) return;
    el.setAttribute(name, out);
  }
  function doAttrs(el) {
    for (var i = 0; i < ATTRS.length; i++) if (el.hasAttribute(ATTRS[i])) doAttr(el, ATTRS[i]);
  }
  function walk(root) {
    if (root.nodeType === 3) { doText(root); return; }
    if (root.nodeType !== 1 || root.matches(REJECT)) return;
    doAttrs(root);
    var w = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT, {
      acceptNode: function (n) { return n.nodeType === 1 && n.matches(REJECT) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT; },
    });
    var n;
    while ((n = w.nextNode())) { if (n.nodeType === 3) doText(n); else doAttrs(n); }
  }

  var observer = new MutationObserver(function (records) {
    for (var i = 0; i < records.length; i++) {
      var r = records[i];
      if (r.type === "childList") for (var j = 0; j < r.addedNodes.length; j++) walk(r.addedNodes[j]);
      else if (r.type === "characterData") doText(r.target);
      else if (r.type === "attributes" && r.target.nodeType === 1) doAttr(r.target, r.attributeName);
    }
  });
  function start() {
    walk(document.body);
    observer.observe(document.body, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ATTRS });
  }
  if (document.body) start();
  else document.addEventListener("DOMContentLoaded", start);
  document.addEventListener("DOMContentLoaded", function () { walk(document.body); });

  // "Save search" asks for a name with window.prompt, which no observer can reach.
  var nativePrompt = window.prompt;
  if (typeof nativePrompt === "function") {
    window.prompt = function (message, def) {
      var d = typeof def === "string" ? def.replace(/^All judgments(?= — |$)/, "Wszystkie wyroki") : def;
      return nativePrompt.call(window, t(message), d);
    };
  }

  window.I18N_PL = { t: t };
})();
