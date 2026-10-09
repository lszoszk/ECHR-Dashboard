const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../docs/assets/pages-dashboard.js"), "utf8");
const context = {};
vm.runInNewContext(source.slice(source.indexOf("function truncateLabel("), source.indexOf("function makeKpi(")), context);
const label = context.citationDisplayLabel;
const fixtures = [
  ["Frydlender v. France [GC], no. 30979/96, \u00a7 43, ECHR 2000-VII", "Frydlender v. France"],
  ["Belinger v. Slovenia (dec.), no. 42320/98, 2 October 2001", "Belinger v. Slovenia (dec.)"],
  ["Iatridis v. Greece (just satisfaction) [GC], no. 31107/96, \u00a7 54", "Iatridis v. Greece (just satisfaction)"],
  ["Lukenda v. Slovenia, no. 23032/02, 6 October 2005", "Lukenda v. Slovenia"],
  ["Lithgow and Others v. the United Kingdom judgment of 8 July 1986, Series A no. 102", "Lithgow and Others v. the United Kingdom"],
  ["Findlay v. the United Kingdom, judgment of 25 February 1997, Reports 1997-I", "Findlay v. the United Kingdom"],
  ["Case v. State, nos. 1/99 and 2/99, ECHR 2000", "Case v. State"],
  ["Case v. State, 6 October 2005", "Case v. State"],
  ["Case v. State", "Case v. State"],
];
for (const [raw, expected] of fixtures) {
  assert.equal(label(raw), expected);
}
const long = label("Centre for Legal Resources on behalf of Valentin Campeanu v. Romania [GC], no. 47848/08");
assert(long.length <= 48);
assert(long.endsWith(" v. Romania"));
assert.notEqual(label(fixtures[2][0]), label("Iatridis v. Greece [GC], no. 31107/96"));
const full = fixtures[0][0];
const wrapped = context.citationTooltipTitle([{ label: full, chart: { width: 332 } }]);
assert.equal(wrapped.join(" "), full);
assert(wrapped.every((line) => line.length <= 38));
console.log("Citation labels: 9 fixtures, long-name country retention, stage distinction and lossless tooltip wrapping passed.");
