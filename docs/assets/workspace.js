/* Personal workspace: saved paragraphs (each with a note) and saved searches (query + filters),
   kept in this browser's localStorage only. Loaded by every page: window.ECHRWorkspace, and the
   count on the "Workspace" link ([data-ws-count]). Nothing is sent anywhere. */
(function () {
  "use strict";
  const KEY = "echr-workspace-v1";
  const WARNED = "echr-workspace-warned";
  const SITE = "https://lszoszk.github.io/ECHR-Dashboard/";
  const listeners = new Set();

  function read() {
    try {
      const d = JSON.parse(localStorage.getItem(KEY) || "{}");
      return { paragraphs: Array.isArray(d.paragraphs) ? d.paragraphs : [], searches: Array.isArray(d.searches) ? d.searches : [] };
    } catch (_) {
      return { paragraphs: [], searches: [] };
    }
  }

  function write(d) {
    try {
      localStorage.setItem(KEY, JSON.stringify(d));
    } catch (_) {
      toast("The workspace could not be saved: this browser's storage is full or switched off.");
      return false;
    }
    changed();
    return true;
  }

  function changed() {
    paintBadges();
    listeners.forEach((f) => { try { f(); } catch (_) { /* a listener's own problem */ } });
  }

  function firstSave() {
    let warned = null;
    try { warned = localStorage.getItem(WARNED); } catch (_) { /* private mode */ }
    if (warned) return;
    try { localStorage.setItem(WARNED, "1"); } catch (_) { /* private mode */ }
    toast("Saved in this browser only. Clearing browser data deletes your workspace — Workspace → Export keeps a copy.", 6000);
  }

  function toast(message, ms = 3200) {
    let t = document.getElementById("wsToast");
    if (!t) {
      t = document.createElement("div");
      t.id = "wsToast";
      t.setAttribute("role", "status");
      t.style.cssText = "position:fixed;left:50%;bottom:calc(var(--bar-h,30px) + 14px);transform:translateX(-50%);z-index:300;" +
        "max-width:min(560px,calc(100vw - 32px));padding:9px 14px;background:var(--ink,#242328);color:var(--paper,#faf8f3);" +
        "font:0.86rem/1.4 var(--font-serif,'Source Serif 4',Georgia,serif);box-shadow:0 2px 0 rgba(0,0,0,.2);";
      document.body.appendChild(t);
    }
    t.textContent = message;
    t.hidden = false;
    clearTimeout(t._h);
    t._h = setTimeout(() => { t.hidden = true; }, ms);
  }

  function paintBadges() {
    const n = api.count();
    document.querySelectorAll("[data-ws-count]").forEach((b) => { b.textContent = n ? String(n) : ""; b.hidden = !n; });
  }

  const md = (s) => String(s || "").replace(/\r?\n+/g, " ").trim();

  const api = {
    data: read,
    count() { const d = read(); return d.paragraphs.length + d.searches.length; },
    has(key) { return read().paragraphs.some((p) => p.key === key); },

    /** Save or unsave a paragraph; returns whether it is saved afterwards. */
    toggleParagraph(item) {
      const d = read();
      const i = d.paragraphs.findIndex((p) => p.key === item.key);
      if (i >= 0) {
        d.paragraphs.splice(i, 1);
        write(d);
        return false;
      }
      d.paragraphs.push({ ...item, note: item.note || "", addedAt: new Date().toISOString() });
      if (write(d)) firstSave();
      return true;
    },
    removeParagraph(key) { const d = read(); d.paragraphs = d.paragraphs.filter((p) => p.key !== key); write(d); },
    setNote(key, note) {
      const d = read();
      const p = d.paragraphs.find((x) => x.key === key);
      if (!p || p.note === note) return;
      p.note = note;
      try { localStorage.setItem(KEY, JSON.stringify(d)); } catch (_) { toast("The note could not be saved."); }
    },

    saveSearch(search) {
      const d = read();
      d.searches.push({ ...search, id: Date.now().toString(36) + Math.random().toString(36).slice(2, 6), savedAt: new Date().toISOString() });
      if (write(d)) { firstSave(); toast(`Saved to your Workspace: “${search.name}”.`); }
    },
    removeSearch(id) { const d = read(); d.searches = d.searches.filter((s) => s.id !== id); write(d); },
    search(id) { return read().searches.find((s) => s.id === id) || null; },

    onChange(fn) { listeners.add(fn); },
    toast,

    exportJSON() {
      return JSON.stringify({ app: "HUDOC Researcher workspace", version: 1, exported: new Date().toISOString(), ...read() }, null, 2);
    },
    exportMarkdown() {
      const d = read();
      const lines = [`# HUDOC Researcher — workspace (${new Date().toISOString().slice(0, 10)})`, "",
        "Paragraphs and searches saved in the browser. HUDOC (https://hudoc.echr.coe.int) is the authoritative source.", ""];
      lines.push(`## Saved paragraphs (${d.paragraphs.length})`, "");
      for (const p of d.paragraphs) {
        lines.push(`### ${md(p.title)}${p.paraNo != null ? `, § ${p.paraNo}` : ""}`, "");
        if (p.citation) lines.push(md(p.citation.split("\n")[0]), "");
        if (p.text) lines.push(`> ${md(p.text)}`, "");
        if (p.machineTranslation) lines.push("_Unofficial machine translation of a judgment HUDOC publishes only in French._", "");
        if (p.note) lines.push(`**Note.** ${md(p.note)}`, "");
        if (p.url) lines.push(p.url, "");
      }
      lines.push(`## Saved searches (${d.searches.length})`, "");
      for (const s of d.searches) {
        lines.push(`- **${md(s.name)}** — \`${md(s.q) || "(no query)"}\`${s.summary ? ` · ${md(s.summary)}` : ""} — ${SITE}?q=${encodeURIComponent(s.q || "")}`);
      }
      return lines.join("\n") + "\n";
    },
    /** Merge a JSON export into this workspace; returns {paragraphs, searches} added. */
    importJSON(text) {
      const incoming = JSON.parse(text);
      if (!incoming || !Array.isArray(incoming.paragraphs) || !Array.isArray(incoming.searches)) {
        throw new Error("This is not a HUDOC Researcher workspace file.");
      }
      const d = read();
      let addedP = 0, addedS = 0;
      for (const p of incoming.paragraphs) {
        if (!p || !p.key) continue;
        const mine = d.paragraphs.find((x) => x.key === p.key);
        if (!mine) { d.paragraphs.push(p); addedP++; }
        else if (!mine.note && p.note) mine.note = p.note;
      }
      for (const s of incoming.searches) {
        if (s && s.id && !d.searches.some((x) => x.id === s.id)) { d.searches.push(s); addedS++; }
      }
      write(d);
      return { paragraphs: addedP, searches: addedS };
    },
  };

  window.addEventListener("storage", (e) => { if (e.key === KEY) changed(); });
  document.addEventListener("DOMContentLoaded", paintBadges);
  window.ECHRWorkspace = api;
})();
