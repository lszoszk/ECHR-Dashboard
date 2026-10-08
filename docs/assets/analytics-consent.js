/* HUDOC Researcher — analytics consent (Google Consent Mode v2)
 * ---------------------------------------------------------------------------
 * Replaces the seven inlined gtag lines that used to sit in the <head> of
 * index.html, about.html, analytics.html and methodology.html and fired
 * unconditionally, with no consent gate at all.
 *
 * WHY THIS FILE LOADS gtag.js ITSELF
 * Consent Mode only works if the `consent default` command sits EARLIER IN THE
 * dataLayer QUEUE than `config` — gtag.js replays the queue in order when it
 * boots. Declaring <script src=gtag.js> in the HTML makes that ordering a
 * property of tag placement plus async/defer timing, which is fragile across
 * four hand-maintained pages with no build step. Injecting the library from
 * here makes it a property of statement order inside one file instead, which
 * nothing can perturb.
 *
 * WHY page_referrer IS SCRUBBED TOO
 * docs/assets/search-app.js:5486 writes the user's query into the address bar
 * (`?q=…`) on every search. Without scrubbing, that query reaches GA in
 * page_location on the search page AND in page_referrer on every page the user
 * visits next. Both are cleaned here.
 *
 * NOTE — there is a matching NON-CODE step. In GA4 Admin → Data Streams →
 * Enhanced measurement, "Page changes based on browser history events" must be
 * OFF. It is on by default and sends its own page_view with the raw URL on
 * every history.replaceState, which send_page_view:false does not suppress.
 *
 * Deliberately NOT added to semantic.html or the *_hudoc.html pages: they carry
 * no analytics today, and adding this script there would be introducing
 * tracking under cover of a privacy change.
 */
(function () {
  "use strict";

  var MEASUREMENT_ID = "G-F3XBX45HQC";
  var STORE_KEY = "echr-analytics-consent";
  var POLICY_VERSION = 1;

  var listeners = [];
  var gtagLoaded = false;

  // ---------------------------------------------------------------- storage

  function readChoice() {
    try {
      var raw = window.localStorage.getItem(STORE_KEY);
      if (!raw) return null;
      var parsed = JSON.parse(raw);
      // A stored record from an older policy is treated as absent, so bumping
      // POLICY_VERSION re-prompts without needing a new key.
      if (!parsed || parsed.v !== POLICY_VERSION) return null;
      if (parsed.choice !== "granted" && parsed.choice !== "denied") return null;
      return parsed;
    } catch (e) {
      return null;
    }
  }

  function writeChoice(choice) {
    try {
      window.localStorage.setItem(STORE_KEY, JSON.stringify({
        choice: choice,
        ts: new Date().toISOString(),
        v: POLICY_VERSION,
      }));
    } catch (e) { /* private mode — the session still works, just not sticky */ }
  }

  function clearChoice() {
    try { window.localStorage.removeItem(STORE_KEY); } catch (e) { /* ignore */ }
  }

  /** Do Not Track / Global Privacy Control. Honoured as a hard opt-out. */
  function signalsOptOut() {
    try {
      if (window.navigator && window.navigator.globalPrivacyControl === true) return true;
      var dnt = window.navigator.doNotTrack || window.doNotTrack ||
                (window.navigator.msDoNotTrack);
      return dnt === "1" || dnt === "yes";
    } catch (e) {
      return false;
    }
  }

  // ------------------------------------------------------------------ gtag

  function gtag() {
    window.dataLayer.push(arguments);
  }

  /** Always runs, first, even under DNT and even when the answer is "denied",
   *  so the queue is well-formed whatever happens afterwards. */
  function pushDefaults() {
    window.dataLayer = window.dataLayer || [];
    window.gtag = gtag;
    gtag("consent", "default", {
      ad_storage: "denied",
      ad_user_data: "denied",
      ad_personalization: "denied",
      analytics_storage: "denied",
      personalization_storage: "denied",
      functionality_storage: "granted",
      security_storage: "granted",
      wait_for_update: 500,
    });
  }

  function loadGtag() {
    if (gtagLoaded) return;
    gtagLoaded = true;
    var s = document.createElement("script");
    s.async = true;
    s.src = "https://www.googletagmanager.com/gtag/js?id=" + MEASUREMENT_ID;
    document.head.appendChild(s);
  }

  /** origin + pathname only — drops ?q=… and any #hash. */
  function cleanUrl(href) {
    if (!href) return "";
    try {
      var u = new URL(href, window.location.href);
      return u.origin + u.pathname;
    } catch (e) {
      return "";
    }
  }

  function viewName() {
    var p = (window.location.pathname || "").toLowerCase();
    if (p.indexOf("analytics") !== -1) return "Statistics";
    if (p.indexOf("methodology") !== -1) return "Methodology";
    if (p.indexOf("about") !== -1) return "About";
    if (p.indexOf("semantic") !== -1) return "Semantic Search";
    return "Search";
  }

  function configure() {
    gtag("js", new Date());
    gtag("config", MEASUREMENT_ID, {
      // We emit our own page_view below with a scrubbed URL. The automatic one
      // would carry the raw location, including ?q=.
      send_page_view: false,
      allow_google_signals: false,
      allow_ad_personalization_signals: false,
    });
    trackView();
  }

  /** The ONLY event this site emits. View names only — never queries,
   *  selections, filter state, or which judgments were opened. */
  function trackView(name) {
    var choice = readChoice();
    if (!choice || choice.choice !== "granted") return;
    try {
      gtag("event", "page_view", {
        page_title: name || viewName(),
        page_location: cleanUrl(window.location.href),
        page_referrer: cleanUrl(document.referrer),
      });
    } catch (e) { /* analytics must never break the page */ }
  }

  // ----------------------------------------------------------------- status

  function getStatus() {
    if (signalsOptOut()) {
      return {
        choice: "denied",
        reason: "dnt",
        label: "Analytics declined — your browser sends a Do Not Track signal.",
      };
    }
    var stored = readChoice();
    if (!stored) {
      return { choice: null, reason: "unset", label: "No choice made yet — analytics are off until you choose." };
    }
    return {
      choice: stored.choice,
      reason: "stored",
      label: stored.choice === "granted"
        ? "Analytics allowed."
        : "Analytics declined.",
    };
  }

  function notify() {
    for (var i = 0; i < listeners.length; i++) {
      try { listeners[i](getStatus()); } catch (e) { /* ignore */ }
    }
  }

  // ----------------------------------------------------------------- styles

  function injectStyles() {
    if (document.getElementById("echr-consent-styles")) return;
    var css =
      '.echr-consent{position:fixed;left:0;right:0;bottom:0;z-index:9999;' +
      'background:var(--paper,#faf8f4);color:var(--ink,#1a1a1a);' +
      'border-top:1px solid var(--rule,#d8d2c6);padding:.9rem 1.1rem;' +
      'display:flex;flex-wrap:wrap;gap:.75rem 1.25rem;align-items:center;' +
      'font-size:.86rem;line-height:1.5;box-shadow:0 -2px 12px rgba(0,0,0,.08)}' +
      '.echr-consent-text{flex:1 1 320px;margin:0}' +
      '.echr-consent-actions{display:flex;gap:.5rem;flex:0 0 auto}' +
      '.echr-consent button{font:inherit;padding:.45rem 1.1rem;cursor:pointer;' +
      'border:1px solid var(--ink,#1a1a1a);background:transparent;' +
      'color:var(--ink,#1a1a1a);border-radius:2px}' +
      '.echr-consent button:hover{background:var(--ink,#1a1a1a);color:var(--paper,#faf8f4)}' +
      '.echr-consent a{color:var(--garnet,#7c2128);text-decoration:underline}' +
      '.echr-consent-ui{margin:1rem 0;padding:.85rem 1rem;' +
      'border:1px solid var(--rule,#d8d2c6);border-radius:3px;font-size:.9rem}' +
      '.echr-consent-ui button{font:inherit;margin-top:.6rem;padding:.4rem 1rem;' +
      'cursor:pointer;border:1px solid var(--ink,#1a1a1a);background:transparent;' +
      'color:var(--ink,#1a1a1a);border-radius:2px}' +
      '@media print{.echr-consent{display:none}}';
    var style = document.createElement("style");
    style.id = "echr-consent-styles";
    style.textContent = css;
    document.head.appendChild(style);
  }

  // ----------------------------------------------------------------- banner

  function dismissBanner() {
    var el = document.getElementById("echr-consent-banner");
    if (el && el.parentNode) el.parentNode.removeChild(el);
  }

  function mountBanner() {
    if (document.getElementById("echr-consent-banner")) return;
    injectStyles();

    var bar = document.createElement("div");
    bar.id = "echr-consent-banner";
    bar.className = "echr-consent";
    bar.setAttribute("role", "dialog");
    // Not modal: it must never trap focus or block reading the page.
    bar.setAttribute("aria-modal", "false");
    bar.setAttribute("aria-labelledby", "echr-consent-text");

    var p = document.createElement("p");
    p.className = "echr-consent-text";
    p.id = "echr-consent-text";
    p.innerHTML =
      "We’d like to count which views of this site get used (Search, " +
      "Statistics, Methodology…). Nothing is sent unless you allow it, and " +
      "we never send your searches, your filters, or the judgments you open. " +
      '<a href="' + methodologyHref() + '">What this means</a>.';

    var actions = document.createElement("div");
    actions.className = "echr-consent-actions";

    // Equal visual weight, no preselection, no dismiss-X that silently means
    // "reject" — those are what make a banner non-compliant.
    var reject = document.createElement("button");
    reject.type = "button";
    reject.textContent = "Reject";
    reject.addEventListener("click", function () { deny(); });

    var allow = document.createElement("button");
    allow.type = "button";
    allow.textContent = "Allow";
    allow.addEventListener("click", function () { grant(); });

    actions.appendChild(reject);
    actions.appendChild(allow);
    bar.appendChild(p);
    bar.appendChild(actions);
    document.body.appendChild(bar);
  }

  /** methodology.html is one level up from assets/ but a sibling of the pages
   *  that load this file, so a bare relative link is correct everywhere. */
  function methodologyHref() {
    return "methodology.html#privacy-analytics";
  }

  // ------------------------------------------------------------ public API

  function grant() {
    writeChoice("granted");
    dismissBanner();
    try {
      gtag("consent", "update", { analytics_storage: "granted" });
      loadGtag();
      configure();
    } catch (e) { /* never break the page for analytics */ }
    notify();
  }

  function deny() {
    writeChoice("denied");
    dismissBanner();
    // No consent update, no library load, no network request to Google at all.
    notify();
  }

  function reset() {
    clearChoice();
    notify();
    if (!signalsOptOut()) mountBanner();
  }

  // ------------------------------------------------------- privacy control

  function mountPrivacyUi(root) {
    injectStyles();
    root.classList.add("echr-consent-ui");

    var status = document.createElement("p");
    status.style.margin = "0";

    var btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = "Reset analytics choice";
    btn.addEventListener("click", function () { reset(); });

    function render(s) {
      status.textContent = "Current choice: " + s.label;
      // Under DNT there is nothing to reset — the browser setting decides.
      btn.hidden = s.reason === "dnt";
    }

    render(getStatus());
    subscribe(render);

    root.appendChild(status);
    root.appendChild(btn);
  }

  function subscribe(fn) {
    if (typeof fn === "function") listeners.push(fn);
  }

  // ------------------------------------------------------------------ boot

  pushDefaults();

  window.EchrAnalytics = {
    getStatus: getStatus,
    grant: grant,
    deny: deny,
    reset: reset,
    subscribe: subscribe,
    trackView: trackView,
  };

  function boot() {
    var ui = document.querySelector("[data-echr-consent-ui]");
    if (ui) mountPrivacyUi(ui);

    // DNT/GPC: stop entirely. Nothing persisted, so clearing the browser
    // setting later re-surfaces the prompt rather than silently resuming.
    if (signalsOptOut()) return;

    var stored = readChoice();
    if (!stored) {
      mountBanner();
      return;
    }
    if (stored.choice === "granted") {
      try {
        gtag("consent", "update", { analytics_storage: "granted" });
        loadGtag();
        configure();
      } catch (e) { /* ignore */ }
    }
    // "denied" → nothing further happens.
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
