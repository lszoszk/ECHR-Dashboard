// OSCOLA citations built by docs/assets/search-app.js (buildOscolaCitation).   node scripts/test_oscola.js
const assert = require("assert");
const fs = require("fs");
const path = require("path");

const src = fs.readFileSync(path.join(__dirname, "..", "docs", "assets", "search-app.js"), "utf8");
const grab = (name) => src.slice(src.indexOf(name), src.indexOf("\n}\n", src.indexOf(name)) + 2);
const code = src.slice(src.indexOf("const OSCOLA_SMALL"), src.indexOf("function oscolaTitle")) +
  grab("function oscolaTitle") + grab("function oscolaDate") + grab("function buildOscolaCitation") +
  "\nmodule.exports = { buildOscolaCitation, oscolaTitle };";
const m = { exports: {} };
new Function("module", code)(m);
const { buildOscolaCitation, oscolaTitle } = m.exports;

const cite = (title, appno, date, body, type = "Judgment (Merits)", para = { hudocParaNo: 152, numberingBlock: "main_judgment" }) =>
  buildOscolaCitation({ title, case_no: appno, judgment_date: date, __originatingBody: body, document_type: type }, para);

assert.strictEqual(cite("CASE OF KUDLA v. POLAND", "30210/96", "26/10/2000", "Court (Grand Chamber)"),
  "Kudla v Poland [GC] App no 30210/96 (ECtHR, 26 October 2000), para 152");
assert.strictEqual(oscolaTitle("CASE OF HATTON AND OTHERS v. THE UNITED KINGDOM"), "Hatton and Others v the United Kingdom");
assert.strictEqual(oscolaTitle("CASE OF M.S.S. v. BELGIUM AND GREECE"), "M.S.S. v Belgium and Greece");
assert.strictEqual(oscolaTitle("CASE OF MCCANN AND OTHERS v. THE UNITED KINGDOM"), "McCann and Others v the United Kingdom");
assert.strictEqual(oscolaTitle("CASE OF O'DONOGHUE AND OTHERS v. THE UNITED KINGDOM"), "O'Donoghue and Others v the United Kingdom");
assert.strictEqual(oscolaTitle("CASE OF THE SUNDAY TIMES v. THE UNITED KINGDOM (No. 1)"), "The Sunday Times v the United Kingdom (No 1)");
assert.strictEqual(oscolaTitle("CASE OF OOO NEFTYANAYA KOMPANIYA YUKOS v. RUSSIA"), "OOO Neftyanaya Kompaniya Yukos v Russia");
assert.strictEqual(oscolaTitle("CASE OF SMITH v. CROATIA (JUST SATISFACTION)"), "Smith v Croatia");
assert.strictEqual(oscolaTitle("CASE OF X AND Y v. THE NETHERLANDS"), "X and Y v the Netherlands");
assert.strictEqual(cite("BANKOVIC AND OTHERS v. BELGIUM AND OTHERS", "52207/99", "12/12/2001", "Court (Grand Chamber)", "Decision", null),
  "Bankovic and Others v Belgium and Others (dec) [GC] App no 52207/99 (ECtHR, 12 December 2001)");
assert.strictEqual(cite("CASE OF X v. Y", "1/10;2/10", "2010-03-01", "Court (First Section)", "Judgment", { hudocParaNo: 3, numberingBlock: "operative_dispositif" }),
  "X v Y App nos 1/10 and 2/10 (ECtHR, 1 March 2010), operative provisions, point 3");
assert.strictEqual(cite("CASE OF X v. Y", "1/10;2/10;3/10;4/10", "01/03/2010", "25", "Judgment (Committee)", null),
  "X v Y App no 1/10 and 3 others (ECtHR, 1 March 2010)");
console.log("oscola: all tests passed");
