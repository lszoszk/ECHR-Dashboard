// Citation finding and quotation matching of the Check page (docs/assets/check-app.js).
//   node scripts/test_check_app.js
const assert = require("assert");
const path = require("path");
const ck = require(path.join(__dirname, "..", "docs", "assets", "check-app.js"));

const text = `The Court has held that Article 13 “guarantees an effective remedy before a national authority” (Kudła v. Poland [GC], no. 30210/96, § 156, ECHR 2000-XI). In Handyside v. the United Kingdom (7 December 1976, §§ 48-49, Series A no. 24) the Court said so. See also Banković and Others v. Belgium and Others (dec.) [GC], no. 52207/99, ECHR 2001-XII. The Sunday Times v. the United Kingdom (no. 1), 26 April 1979, Series A no. 30. Ilaşcu and Others v. Moldova and Russia [GC], no. 48787/99, § 311, ECHR 2004-VII. M.S.S. v. Belgium and Greece [GC], no. 30696/09, ECHR 2011. As held in application no. 12345/06, § 4, the remedy matters (Kudła, cited above, § 157). Under Article 6 § 1 of the Convention nothing changes.`;

const cites = ck.findCitations(text);
const by = (re) => cites.find((c) => re.test(c.raw));

let c = by(/^Kudła v\. Poland/);
assert.deepStrictEqual([c.name, c.appnos, c.gc, c.pins], ["Kudła v. Poland", ["30210/96"], true, [156]]);

c = by(/^Handyside/);
assert.strictEqual(c.name, "Handyside v. the United Kingdom");
assert.strictEqual(c.date, "1976-12-07");
assert.deepStrictEqual(c.pins, [48, 49]);

c = by(/^Banković/);
assert.deepStrictEqual([c.name, c.dec, c.gc, c.appnos], ["Banković and Others v. Belgium and Others", true, true, ["52207/99"]]);

c = by(/Sunday Times/);
assert.strictEqual(c.name, "Sunday Times v. the United Kingdom (no. 1)");  // leading "The" dropped
assert.strictEqual(c.date, "1979-04-26");

c = by(/^Ilaşcu/);
assert.strictEqual(c.name, "Ilaşcu and Others v. Moldova and Russia");
c = by(/^M\.S\.S\./);
assert.strictEqual(c.name, "M.S.S. v. Belgium and Greece");

c = cites.find((x) => x.kind === "appno");
assert.deepStrictEqual([c.appnos, c.pins], [["12345/06"], [4]]);
c = cites.find((x) => x.kind === "short");
assert.deepStrictEqual([c.shortName, c.pins], ["Kudła", [157]]);

assert.ok(!cites.some((x) => /Article 6 § 1 of the Convention/.test(x.raw)), "an Article reference is no citation");
assert.deepStrictEqual(ck.pinsIn(", § 51, 17 December 2020").pins, [51], "a date after the pinpoint is not a paragraph");
assert.deepStrictEqual(ck.pinsIn(", §§ 45, 47 and 50-51").pins, [45, 47, 50, 51]);
assert.strictEqual(cites.length, 8);

const quotes = ck.findQuotes(text, cites);
assert.strictEqual(quotes.length, 1);
assert.strictEqual(quotes[0].cite, by(/^Kudła v\. Poland/).n);

// Quotations against paragraph text.
const segments = ck.segmentsOf([
  { hudoc_para_no: 48, text: "48. The Court points out that the machinery of protection is subsidiary.", numbering_block: "main_judgment" },
  { hudoc_para_no: 49, text: "49. Freedom of expression constitutes one of the essential foundations of such a society, one of the basic conditions for its progress.", numbering_block: "main_judgment" },
  { hudoc_para_no: null, text: "“A quoted passage that belongs to paragraph 49.”", row_role: "quote" },
  { hudoc_para_no: 1, text: "1. I dissent.", numbering_block: "separate_opinion" },
]);
assert.deepStrictEqual([...segments.keys()], [48, 49]);
const all = ck.tokenIndex(segments);
let r = ck.compareQuote("one of the essential foundations of such a society", all);
assert.deepStrictEqual([r.verdict, r.paras], ["verbatim", [49]]);
r = ck.compareQuote("Freedom of expression constitutes one of the essential foundations of a democratic society, one of the basic conditions for its progress", all);
assert.strictEqual(r.verdict, "near");
assert.ok(r.missing.includes("democratic"));
r = ck.compareQuote("the machinery of protection [...] is subsidiary", all);
assert.strictEqual(r.verdict, "verbatim");
r = ck.compareQuote("a quoted passage that belongs to paragraph", all);
assert.deepStrictEqual(r.paras, [49]);
r = ck.compareQuote("states enjoy an unlimited margin in matters of taxation policy", all);
assert.strictEqual(r.verdict, "none");

console.log("check-app: all tests passed");
