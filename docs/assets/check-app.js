/* Check page: find the ECtHR citations in a pasted text, resolve them against the corpus and check
   the pinpointed paragraphs and the quotations against the judgments' own text.

   Only what identifies a cited judgment (application numbers, "X v. State", a date, [GC], (dec.)) is
   sent to /api/check/resolve; the judgments are then fetched by id and every comparison runs here,
   so the text being checked never leaves the browser. */
(function () {
  "use strict";

  // ── Citation finding (pure; exported for tests) ──────────────────────────────────────────────
  const MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december"];
  // Respondent States as the Court writes them in English case names.
  const STATES = ["Albania", "Andorra", "Armenia", "Austria", "Azerbaijan", "Belgium", "Bosnia and Herzegovina",
    "Bulgaria", "Croatia", "Cyprus", "Czech Republic", "Czechia", "Denmark", "Estonia", "Finland", "France", "Georgia",
    "Germany", "Federal Republic of Germany", "Greece", "Hungary", "Iceland", "Ireland", "Italy", "Latvia",
    "Liechtenstein", "Lithuania", "Luxembourg", "Malta", "Republic of Moldova", "Moldova", "Monaco", "Montenegro",
    "Netherlands", "North Macedonia", "former Yugoslav Republic of Macedonia", "Norway", "Poland", "Portugal",
    "Romania", "Russia", "Russian Federation", "San Marino", "Serbia", "Serbia and Montenegro", "Slovak Republic",
    "Slovakia", "Slovenia", "Spain", "Sweden", "Switzerland", "Turkey", "Türkiye", "Ukraine", "United Kingdom"];
  const escRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const STATE = "(?:the\\s+)?(?:" + STATES.slice().sort((a, b) => b.length - a.length).map(escRe).join("|") + ")";
  const RESP = `${STATE}(?:\\s*,\\s*${STATE})*(?:\\s+and\\s+(?:${STATE}|Others))?`;
  const NAME_TOKEN = "(?:\\p{Lu}[\\p{L}\\p{M}'’.\\-]*|and|of|de|del|della|di|da|do|dos|das|du|van|von|der|den|la|le|" +
    "el|al|bin|ibn|ben|y|e|d['’]\\p{L}+)";
  const CASE_RE = new RegExp(`(\\p{Lu}[\\p{L}\\p{M}'’.\\-]*(?:\\s+${NAME_TOKEN})*?)\\s+v\\.\\s+(${RESP})(?![\\p{L}])`, "gu");
  const SHORT_RE = /(\p{Lu}[\p{L}\p{M}'’\-]+(?:\s+and\s+Others)?)(?:\s*\[GC\])?,\s+cited\s+above/gu;
  const APPNO_RE = /(?<![\d/])(\d{1,7})\/(\d{4}|\d{2})(?![\d/])/g;
  const STANDALONE_RE = /\b(?:[Aa]pplication\s+)?[Nn]os?\.\s*\d{1,7}\/\d{2,4}(?:\s*(?:,|and)\s*(?:no\.\s*)?\d{1,7}\/\d{2,4})*/g;
  // Words that start a sentence or a reference, not a name ("In Kudła v. Poland", "See also ...").
  const LEAD_WORDS = new Set(("see also in the cf cf. compare as and but thus moreover however similarly accordingly " +
    "following unlike under per since contrast notably instead likewise indeed further furthermore although while " +
    "when where whereas before after this that these those then here recall recalls judgment judgments case cases " +
    "e.g. i.e. for example by on at from with to whereby there it its their our his her").split(" "));
  // Words a full stop follows without ending the citation.
  const ABBR = new Set("no nos v dec p pp para paras rep vol ed eds cf eg ie etc art arts ch sect s ser seq al op".split(" "));

  function appnosIn(s) {
    const out = [];
    for (const m of s.matchAll(APPNO_RE)) out.push(`${Number(m[1])}/${String(Number(m[2]) % 100).padStart(2, "0")}`);
    return [...new Set(out)];
  }

  function dateIn(s) {
    const m = /\b(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})\b/.exec(s);
    if (!m) return null;
    return `${m[3]}-${String(MONTHS.indexOf(m[2].toLowerCase()) + 1).padStart(2, "0")}-${m[1].padStart(2, "0")}`;
  }

  /** "§§ 45-47 and 50" -> [45, 46, 47, 50] (not "Article 6 § 1"). */
  function pinsIn(s) {
    // a number followed by a month is the date that follows the pinpoint ("§ 51, 17 December 2020")
    const num = "\\d+(?!\\d|\\s+(?:January|February|March|April|May|June|July|August|September|October|November|December))";
    const re = new RegExp(`(?:§§?|\\bparas?\\.|\\bparagraphs?)\\s*((?:${num}(?:\\s*(?:-|–|—|to)\\s*${num})?)` +
      `(?:\\s*(?:,|and|&)\\s*${num}(?:\\s*(?:-|–|—|to)\\s*${num})?)*)`, "gu");
    const out = [];
    let text = "";
    for (const m of s.matchAll(re)) {
      if (/Art(?:icle|s?\.)?\s*\d+\s*$/i.test(s.slice(Math.max(0, m.index - 14), m.index))) continue;
      text = text || m[0];
      for (const part of m[1].split(/\s*(?:,|and|&)\s*/)) {
        const r = /^(\d+)(?:\s*(?:-|–|—|to)\s*(\d+))?$/.exec(part.trim());
        if (!r) continue;
        const a = Number(r[1]), b = r[2] ? Number(r[2]) : a;
        for (let n = a; n <= Math.min(b, a + 40); n++) out.push(n);
      }
      break;  // the first pinpoint of a citation is its pinpoint
    }
    return { pins: [...new Set(out)], pinText: text };
  }

  /** The rest of a citation after the case name: up to ";", a new line, an unbalanced ")" or the end of the sentence. */
  function cutTail(t) {
    let depth = 0;
    const open = t.search(/\S/);  // "Handyside v. the United Kingdom (7 December 1976, § 49, ...)": ends with its bracket
    for (let i = 0; i < t.length; i++) {
      const ch = t[i];
      if (ch === "(" || ch === "[") depth++;
      else if (ch === ")" || ch === "]") {
        if (depth === 0) return t.slice(0, i);
        depth--;
        if (depth === 0 && t[open] === "(" && ch === ")" && /\d{4}|§|Series/.test(t.slice(open, i))) return t.slice(0, i + 1);
      }
      else if (ch === ";" || ch === "\n") return t.slice(0, i);
      else if (ch === "." && /^\s+[\p{Lu}“"‘(]/u.test(t.slice(i + 1, i + 4))) {
        const word = (/(\p{L}+)$/u.exec(t.slice(0, i)) || ["", ""])[1].toLowerCase();
        if (!ABBR.has(word)) return t.slice(0, i);
      }
    }
    return t;
  }

  // The comma-separated parts of a citation after the name: [GC], no., a date, §, ECHR, Series A ...
  const DETAIL = /^\s*(?:$|\(|\[|§|paras?\.|paragraphs?\b|nos?\.|[Aa]pplication|\d{1,2}\s+\p{Lu}\p{Ll}+\s+\d{4}|ECHR\b|Series\b|Reports\b|\d+(?:\s*[-–]\s*\d+)?\s*\)?\s*$|and\s+(?:no\.\s*)?\d)/u;
  function detailTail(t) {
    const kept = [];
    for (const part of t.split(",")) { if (!DETAIL.test(part)) break; kept.push(part); }
    return kept.join(",");
  }
  const trimEnd = (s) => s.replace(/[\s,;.]+$/, "");

  function cleanApplicant(raw) {
    // keep what follows the last full stop after a word ("Court. Kudła" -> "Kudła"; "M.S.S." stays)
    let s = raw.split(/(?<=\p{L}{2})\.\s+/u).pop();
    const words = s.split(/\s+/);
    while (words.length > 1 && LEAD_WORDS.has(words[0].toLowerCase())) words.shift();
    return words.join(" ");
  }

  function findCitations(text) {
    const cites = [];
    const taken = [];  // [start, end) spans already used
    const overlaps = (a, b) => taken.some(([s, e]) => a < e && b > s);
    const fullMatches = [...text.matchAll(CASE_RE)].map((m) => {
      const applicant = cleanApplicant(m[1]);
      return { m, applicant, start: m.index + m[1].length - applicant.length };
    });
    fullMatches.forEach(({ m, applicant, start }, i) => {
      const nameEnd = m.index + m[0].length;
      const limit = Math.min(text.length, nameEnd + 320, i + 1 < fullMatches.length ? fullMatches[i + 1].start : text.length);
      const tail = detailTail(cutTail(text.slice(nameEnd, limit)));
      let name = `${applicant} v. ${m[2]}`;
      const no = /^\s*\((no\.?\s*\d+)\)/i.exec(tail);
      if (no) name += ` (${no[1]})`;
      const { pins, pinText } = pinsIn(tail);
      const end = nameEnd + trimEnd(tail).length;
      cites.push({
        kind: "full", start, end, raw: text.slice(start, end), name,
        appnos: appnosIn(tail.split(/§|\bparas?\./)[0]), date: dateIn(tail),
        gc: /\[GC\]/.test(tail), dec: /\(dec\.?\)/i.test(tail), pins, pinText,
      });
      taken.push([start, end]);
    });
    for (const m of text.matchAll(SHORT_RE)) {
      const short = cleanApplicant(m[1]);
      if (overlaps(m.index, m.index + m[0].length)) continue;
      const after = detailTail(cutTail(text.slice(m.index + m[0].length, m.index + m[0].length + 120)));
      const { pins, pinText } = pinsIn(after);
      const end = m.index + m[0].length + trimEnd(after).length;
      cites.push({ kind: "short", start: m.index, end, raw: text.slice(m.index, end), shortName: short,
        name: "", appnos: [], date: null, gc: /\[GC\]/.test(m[0]), dec: false, pins, pinText });
      taken.push([m.index, end]);
    }
    for (const m of text.matchAll(STANDALONE_RE)) {
      if (overlaps(m.index, m.index + m[0].length)) continue;
      const after = detailTail(cutTail(text.slice(m.index + m[0].length, m.index + m[0].length + 160)));
      const { pins, pinText } = pinsIn(after);
      const end = m.index + m[0].length + trimEnd(after).length;
      cites.push({ kind: "appno", start: m.index, end, raw: text.slice(m.index, end), name: "",
        appnos: appnosIn(m[0]), date: dateIn(after), gc: /\[GC\]/.test(after), dec: /\(dec\.?\)/i.test(after), pins, pinText });
      taken.push([m.index, end]);
    }
    cites.sort((a, b) => a.start - b.start);
    cites.forEach((c, i) => { c.n = i + 1; c.key = `c${i + 1}`; c.quotes = []; });
    return cites;
  }

  /** Quotations of four words or more, each given to the citation that follows it (or else precedes it) nearby. */
  function findQuotes(text, cites) {
    const quotes = [];
    for (const m of text.matchAll(/“([^”]{10,2500})”|"([^"\n]{10,2500})"/g)) {
      const body = m[1] || m[2];
      if ((body.match(/[\p{L}\p{N}]+/gu) || []).length < 4) continue;
      quotes.push({ start: m.index, end: m.index + m[0].length, text: body });
    }
    const sameBlock = (a, b) => !/\n\s*\n/.test(text.slice(Math.min(a, b), Math.max(a, b)));
    for (const q of quotes) {
      let target = cites.find((c) => c.start >= q.end && c.start - q.end <= 400 && sameBlock(q.end, c.start)
        && !quotes.some((o) => o !== q && o.start > q.end && o.start < c.start));
      if (!target) {
        const before = cites.filter((c) => c.end <= q.start && q.start - c.end <= 300 && sameBlock(c.end, q.start));
        target = before[before.length - 1];
      }
      if (target) { target.quotes.push(q); q.cite = target.n; }
    }
    return quotes;
  }

  // ── Quotation matching (pure) ───────────────────────────────────────────────────────────────
  function normText(s) {
    return String(s || "").normalize("NFKC").toLowerCase()
      .replace(/[‘’‚‛`´]/g, "'").replace(/[“”„‟]/g, '"').replace(/[–—]/g, "-");
  }
  const tokens = (s) => normText(s).match(/[\p{L}\p{N}]+/gu) || [];

  /** A quotation split at ellipses and editorial brackets: the parts that must each appear in the source. */
  function fragments(quote) {
    return quote.split(/\s*(?:\[\s*(?:\.\.\.|…)\s*\]|\.\.\.|…|\[[^\]]{0,60}\])\s*/u)
      .map((f) => tokens(f)).filter((t) => t.length >= 3);
  }

  /** Local alignment of a fragment on target tokens: matched share of the fragment, where it ends, which words matched. */
  function align(frag, target) {
    const n = frag.length, m = target.length;
    if (!n || !m) return { score: 0, coverage: 0, end: -1, matched: new Set() };
    const H = new Int16Array((n + 1) * (m + 1));
    let best = 0, bi = 0, bj = 0;
    for (let i = 1; i <= n; i++) {
      for (let j = 1; j <= m; j++) {
        const diag = H[(i - 1) * (m + 1) + j - 1] + (frag[i - 1] === target[j - 1] ? 2 : -1);
        const v = Math.max(0, diag, H[(i - 1) * (m + 1) + j] - 1, H[i * (m + 1) + j - 1] - 1);
        H[i * (m + 1) + j] = v;
        if (v > best) { best = v; bi = i; bj = j; }
      }
    }
    const matched = new Set();
    let i = bi, j = bj;
    while (i > 0 && j > 0 && H[i * (m + 1) + j] > 0) {
      const v = H[i * (m + 1) + j];
      if (frag[i - 1] === target[j - 1] && v === H[(i - 1) * (m + 1) + j - 1] + 2) { matched.add(i - 1); i--; j--; }
      else if (v === H[(i - 1) * (m + 1) + j - 1] - 1) { i--; j--; }
      else if (v === H[(i - 1) * (m + 1) + j] - 1) i--;
      else j--;
    }
    return { score: best, coverage: matched.size / n, end: bj - 1, matched };
  }

  /** Paragraph number -> its text (a numbered paragraph and the unnumbered rows that follow it). */
  function segmentsOf(paragraphs) {
    const seg = new Map();
    let cur = null;
    for (const p of paragraphs || []) {
      if (p.numbering_block === "separate_opinion" || p.section === "Separate Opinion") { cur = null; continue; }
      if (String(p.row_role || "").startsWith("heading")) continue;
      if (p.hudoc_para_no != null) { cur = p.hudoc_para_no; if (!seg.has(cur)) seg.set(cur, []); }
      if (cur != null && p.text) seg.get(cur).push(p.text);
    }
    const out = new Map();
    for (const [k, v] of seg) out.set(k, v.join("\n"));
    return out;
  }

  function tokenIndex(segments, only) {
    const toks = [], para = [];
    for (const [no, text] of segments) {
      if (only && !only.has(no)) continue;
      for (const t of tokens(text)) { toks.push(t); para.push(no); }
    }
    return { toks, para };
  }

  /** verbatim / near / differs / none, with the paragraph where the quotation is and the words that differ. */
  function compareQuote(quote, idx) {
    const frags = fragments(quote);
    if (!frags.length || !idx.toks.length) return { verdict: "none", paras: [], missing: [] };
    const hay = " " + idx.toks.join(" ") + " ";
    let total = 0, matchedWords = 0;
    const paras = new Set(), missing = [];
    let allExact = true;
    for (const f of frags) {
      total += f.length;
      const needle = " " + f.join(" ") + " ";
      const at = hay.indexOf(needle);
      if (at >= 0) {
        matchedWords += f.length;
        paras.add(idx.para[hay.slice(0, at + 1).split(" ").length - 2]);  // index of the first matched token
        continue;
      }
      allExact = false;
      const a = align(f, idx.toks);
      matchedWords += a.matched.size;
      if (a.end >= 0) paras.add(idx.para[a.end]);
      f.forEach((w, k) => { if (!a.matched.has(k)) missing.push(w); });
    }
    const coverage = matchedWords / total;
    const verdict = allExact ? "verbatim" : coverage >= 0.85 ? "near" : coverage >= 0.6 ? "differs" : "none";
    return { verdict, paras: [...paras].filter((p) => p != null), missing: [...new Set(missing)], coverage };
  }

  // ── Page ─────────────────────────────────────────────────────────────────────────────────────
  if (typeof document === "undefined") {
    if (typeof module !== "undefined") {
      module.exports = { findCitations, findQuotes, pinsIn, cutTail, cleanApplicant, compareQuote, segmentsOf,
        tokenIndex, fragments, dateIn, appnosIn };
    }
    return;
  }

  const API_BASE_URL = (() => {
    const PRODUCTION = "https://150.254.115.204/echr-api/api";
    try {
      if (location.hostname !== "127.0.0.1" && location.hostname !== "localhost") return PRODUCTION;
      const qp = new URLSearchParams(location.search).get("api");
      if (qp) return qp.replace(/\/+$/, "");
      const ls = localStorage.getItem("echrApiBase");
      if (ls) return ls.replace(/\/+$/, "");
      return `http://${location.hostname}:8000/api`;
    } catch (_) { return PRODUCTION; }
  })();

  const SAMPLE = `The Court has held that Article 13 “guarantees an effective remedy before a national authority for an alleged breach of the requirement under Article 6 § 1 to hear a case within a reasonable time” (Kudła v. Poland [GC], no. 30210/96, § 156, ECHR 2000-XI). The national authorities “have direct democratic legitimation” and are better placed to evaluate local needs (Hatton and Others v. the United Kingdom [GC], no. 36022/97, § 98, ECHR 2003-VIII). “Freedom of expression constitutes one of the essential foundations of a democratic society, one of the basic conditions for its progress” (Handyside v. the United Kingdom, 7 December 1976, § 49, Series A no. 24).

The obligation was confirmed in Smith v. Poland, no. 30210/96, 12 May 2015, and in Kowalski v. Poland, no. 99999/19, § 41, 3 March 2021. See also Saber v. Norway [GC], no. 459/18, § 51, 17 December 2020, and the Chamber's view in Hatton and Others v. the United Kingdom, no. 36022/97, 2 October 2001. On the length of proceedings, see Lunari v. Italy, no. 21463/93, 11 January 2001; on jurisdiction, Banković and Others v. Belgium and Others (dec.) [GC], no. 52207/99, ECHR 2001-XII. The remedy must be effective in practice (Kudła, cited above, § 200).`;

  const STATUS = {
    found: { label: "found", icon: "✓" },
    check: { label: "check", icon: "⚠" },
    not_found: { label: "not found", icon: "✖" },
    ambiguous: { label: "ambiguous", icon: "?" },
    outside: { label: "outside this database", icon: "○" },
  };
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const caseCache = new Map();

  async function fetchCase(caseId) {
    if (!caseCache.has(caseId)) {
      caseCache.set(caseId, fetch(`${API_BASE_URL}/cases/${encodeURIComponent(caseId)}`)
        .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
        .then((c) => { const segments = segmentsOf(c.paragraphs); return { segments, all: tokenIndex(segments) }; }));
    }
    return caseCache.get(caseId);
  }

  const raise = (cite, status) => {
    const order = ["found", "outside", "ambiguous", "check", "not_found"];
    if (order.indexOf(status) > order.indexOf(cite.result.status)) cite.result.status = status;
  };

  async function checkText(text, compareQuotes) {
    const cites = findCitations(text);
    const quotes = findQuotes(text, cites);
    const full = cites.filter((c) => c.kind !== "short");
    let resolved = [];
    if (full.length) {
      const r = await fetch(`${API_BASE_URL}/check/resolve`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ items: full.map((c) => ({ key: c.key, appnos: c.appnos, name: c.name, date: c.date, gc: c.gc, dec: c.dec })) }),
      });
      if (!r.ok) throw new Error(`The check service answered HTTP ${r.status}`);
      resolved = (await r.json()).items || [];
    }
    const byKey = new Map(resolved.map((x) => [x.key, x]));
    for (const c of cites) {
      if (c.kind !== "short") { c.result = byKey.get(c.key) || { status: "not_found", notes: ["No answer."], candidates: [] }; continue; }
      const first = tokens(c.shortName)[0];
      const earlier = cites.filter((o) => o.kind === "full" && o.start < c.start && tokens(o.name.split(" v. ")[0]).includes(first));
      const ref = earlier[earlier.length - 1];
      c.result = ref && ref.result && ref.result.match
        ? { status: "found", match: ref.result.match, candidates: [], notes: [`Short form of citation № ${String(ref.n).padStart(2, "0")}.`] }
        : { status: "check", match: null, candidates: [], notes: [`“${c.shortName}, cited above”: no full citation of ${c.shortName} earlier in this text.`] };
    }
    // Pinpoints and quotations, against the text of each found judgment.
    await Promise.all(cites.map(async (c) => {
      const m = c.result.match;
      c.checks = { pins: [], quotes: [] };
      if (!m || m.french_only || !["found", "check"].includes(c.result.status)) return;
      if (!c.pins.length && !(compareQuotes && c.quotes.length)) return;
      let doc;
      try { doc = await fetchCase(m.case_id); } catch (e) { c.result.notes.push("The judgment's text could not be loaded."); return; }
      const nos = [...doc.segments.keys()];
      const maxNo = nos.length ? Math.max(...nos) : 0;
      for (const p of c.pins) {
        const ok = doc.segments.has(p);
        c.checks.pins.push({ no: p, ok, text: ok ? doc.segments.get(p) : null });
        if (!ok) {
          raise(c, "check");
          c.result.notes.push(maxNo ? `§ ${p} is not in this judgment: its paragraphs run § 1–${maxNo}.` : `§ ${p} could not be found.`);
        }
      }
      if (!compareQuotes) return;
      const pinned = c.pins.filter((p) => doc.segments.has(p));
      for (const q of c.quotes) {
        const inPins = pinned.length ? compareQuote(q.text, tokenIndex(doc.segments, new Set(pinned))) : null;
        const anywhere = compareQuote(q.text, doc.all);
        const res = { text: q.text, inPins, anywhere };
        c.checks.quotes.push(res);
        const where = (r) => r.paras.length ? r.paras.map((n) => `§ ${n}`).join(", ") : "";
        if (inPins && inPins.verdict === "verbatim") res.message = `Quotation verbatim in ${where(inPins) || "the cited paragraph"}.`;
        else if (inPins && inPins.verdict === "near") { raise(c, "check"); res.message = `Quotation almost verbatim in ${where(inPins)}: the words marked differ from the judgment.`; res.show = inPins; }
        else if (["verbatim", "near"].includes(anywhere.verdict)) {
          if (pinned.length) { raise(c, "check"); res.message = `The quotation is in ${where(anywhere)}, not in § ${pinned.join(", ")}.`; }
          else res.message = `Quotation found in ${where(anywhere)}${anywhere.verdict === "near" ? " (almost verbatim)" : ""}.`;
          if (anywhere.verdict === "near") { raise(c, "check"); res.show = anywhere; }
        } else if (anywhere.verdict === "differs") { raise(c, "check"); res.message = `The judgment says something similar in ${where(anywhere)}, but the words differ.`; res.show = anywhere; }
        else { raise(c, "check"); res.message = "The quotation is not in this judgment."; }
      }
    }));
    return { cites, quotes };
  }

  // ── Rendering ────────────────────────────────────────────────────────────────────────────────
  function annotated(text, cites, quotes) {
    const spans = [];
    cites.forEach((c) => spans.push({ start: c.start, end: c.end, cite: c }));
    quotes.forEach((q) => { if (!cites.some((c) => q.start < c.end && q.end > c.start)) spans.push({ start: q.start, end: q.end, quote: q }); });
    spans.sort((a, b) => a.start - b.start);
    let html = "", at = 0;
    for (const s of spans) {
      if (s.start < at) continue;
      html += esc(text.slice(at, s.start));
      const inner = esc(text.slice(s.start, s.end));
      if (s.cite) html += `<a class="ck-hl st-${s.cite.result.status}" href="#ck-${s.cite.n}">${inner}<sup>${s.cite.n}</sup></a>`;
      else html += `<span class="ck-q">${inner}</span>`;
      at = s.end;
    }
    return html + esc(text.slice(at));
  }

  function quoteHtml(q) {
    if (!q.show || !q.show.missing.length) return esc(q.text);
    const missing = new Set(q.show.missing);
    return q.text.replace(/[\p{L}\p{N}]+/gu, (w) => (missing.has(normText(w)) ? `<mark>${esc(w)}</mark>` : esc(w)));
  }

  function matchLine(m) {
    const kind = m.french_only ? "French-only judgment" : m.decision ? "Decision" : m.gc ? "Grand Chamber" : (m.body || m.document_type || "");
    const url = m.hudoc_url || `https://hudoc.echr.coe.int/eng?i=${encodeURIComponent(m.case_id)}`;
    return `<div class="ck-match"><span class="ck-title">${esc(m.title)}</span>
      <span class="ck-meta">${esc(kind)} · ${esc(m.date || "")} · no. ${esc((m.appnos || []).join(", "))}</span>
      <span class="ck-links"><a href="${esc(url)}" target="_blank" rel="noopener">HUDOC ↗</a>${m.french_only ? "" :
        ` · <a href="./?q=${encodeURIComponent("hudoc:" + m.case_id)}">Open in Search</a>`}</span></div>`;
  }

  function card(c) {
    const r = c.result, st = STATUS[r.status] || STATUS.not_found;
    const pins = (c.checks && c.checks.pins) || [];
    const quotes = (c.checks && c.checks.quotes) || [];
    return `<article class="ck-card st-${r.status}" id="ck-${c.n}">
      <header><span class="ck-num">№ ${String(c.n).padStart(2, "0")}</span><span class="ck-status">${st.icon} ${st.label}</span>
        <span class="ck-raw">${esc(c.raw)}</span></header>
      ${r.match ? matchLine(r.match) : ""}
      ${(r.candidates || []).length ? `<div class="ck-cands">Candidates: ${r.candidates.map(matchLine).join("")}</div>` : ""}
      ${pins.filter((p) => p.ok).map((p) => `<details class="ck-para"><summary>§ ${p.no} exists — show it</summary><p>${esc(p.text)}</p></details>`).join("")}
      ${(r.notes || []).map((n) => `<p class="ck-note">${esc(n)}</p>`).join("")}
      ${quotes.map((q) => `<div class="ck-quote"><p class="ck-note">${esc(q.message || "")}</p><blockquote>${quoteHtml(q)}</blockquote></div>`).join("")}
    </article>`;
  }

  function report(text, cites, quotes) {
    const lines = [`HUDOC Researcher — citation check (${new Date().toISOString().slice(0, 10)})`, ""];
    for (const c of cites) {
      const r = c.result, m = r.match;
      lines.push(`${String(c.n).padStart(2, "0")}. [${(STATUS[r.status] || STATUS.not_found).label.toUpperCase()}] ${c.raw}`);
      if (m) lines.push(`    -> ${m.title}, ${m.date || ""}, no. ${(m.appnos || []).join(", ")} (${m.case_id})`);
      for (const n of r.notes || []) lines.push(`    ${n}`);
      for (const q of (c.checks && c.checks.quotes) || []) lines.push(`    "${q.text.slice(0, 80)}${q.text.length > 80 ? "…" : ""}": ${q.message}`);
    }
    return lines.join("\n");
  }

  function summary(cites, quotes) {
    const count = (s) => cites.filter((c) => c.result.status === s).length;
    const parts = Object.keys(STATUS).filter((s) => count(s)).map((s) => `${count(s)} ${STATUS[s].label}`);
    const qs = cites.flatMap((c) => (c.checks && c.checks.quotes) || []);
    const verb = qs.filter((q) => /verbatim in|found in/.test(q.message || "") && !q.show).length;
    return `Checked ${cites.length} citation${cites.length === 1 ? "" : "s"}${qs.length ? ` and ${qs.length} quotation${qs.length === 1 ? "" : "s"}` : ""}: ` +
      `${parts.join(" · ") || "none"}${qs.length ? ` — quotations: ${verb} verbatim, ${qs.length - verb} to check` : ""}.`;
  }

  let lastReport = "";
  async function run() {
    const text = $("ckInput").value;
    const out = $("ckOutput");
    if (!text.trim()) { out.hidden = true; return; }
    $("ckRun").disabled = true;
    $("ckStatus").textContent = "Checking…";
    try {
      const { cites, quotes } = await checkText(text, $("ckQuotes").checked);
      if (!cites.length) {
        $("ckSummary").textContent = "No ECtHR citation found. The check recognises “X v. State”, application numbers (no. 12345/67) and “X, cited above”.";
        $("ckText").innerHTML = ""; $("ckCards").innerHTML = ""; out.hidden = false; lastReport = ""; return;
      }
      $("ckSummary").textContent = summary(cites, quotes);
      $("ckText").innerHTML = annotated(text, cites, quotes);
      $("ckCards").innerHTML = cites.map(card).join("");
      lastReport = report(text, cites, quotes);
      out.hidden = false;
    } catch (e) {
      $("ckSummary").textContent = `The check could not run: ${e.message}. The search server may be unreachable.`;
      $("ckText").innerHTML = ""; $("ckCards").innerHTML = ""; out.hidden = false;
    } finally {
      $("ckRun").disabled = false;
      $("ckStatus").textContent = "";
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    $("ckRun").addEventListener("click", run);
    $("ckSample").addEventListener("click", () => { $("ckInput").value = SAMPLE; run(); });
    $("ckClear").addEventListener("click", () => { $("ckInput").value = ""; $("ckOutput").hidden = true; $("ckInput").focus(); });
    $("ckCopy").addEventListener("click", () => {
      if (!lastReport) return;
      navigator.clipboard?.writeText(lastReport).then(() => {
        $("ckCopy").textContent = "Copied"; setTimeout(() => { $("ckCopy").textContent = "⎘ Copy report"; }, 1400);
      });
    });
    $("ckInput").addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) run(); });
  });
})();
