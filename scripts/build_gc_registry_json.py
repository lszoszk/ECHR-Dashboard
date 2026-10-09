#!/usr/bin/env python3
"""
Turn the Registry's "Table of all Grand Chamber judgments and decisions" (an .xlsx file published by
the Court) into docs/data/gc_registry.json, keyed by HUDOC item id, for the dashboard to show the
Court's own one-line subject and article-by-article conclusions on Grand Chamber cases.

The file is read with the standard library only (an .xlsx is a zip of XML), as untrusted input: nothing
in it is executed. Each row's HUDOC item id comes from the hyperlink on the application-number cell.

Usage
-----
    python3 scripts/build_gc_registry_json.py "GC judgments and decisions.xlsx" docs/data/gc_registry.json

The table says of itself "Prepared by the Registry. It does not bind the Court."; the dashboard shows it
with that attribution.
"""
from __future__ import annotations

import datetime
import json
import re
import sys
import xml.etree.ElementTree as ET
import zipfile

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
SOURCE = ("Registry of the European Court of Human Rights, Table of all Grand Chamber judgments and "
          "decisions (prepared by the Registry; it does not bind the Court)")


def col_index(ref: str) -> int:
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group(0):
        n = n * 26 + ord(ch) - 64
    return n - 1


def clean(text: str) -> str:
    return re.sub(r"[ \t ]+", " ", (text or "").replace("\r", "")).strip()


def read_sheet(path: str):
    z = zipfile.ZipFile(path)
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS):
            shared.append("".join(t.text or "" for t in si.iter("{%s}t" % NS["m"])))
    book = ET.fromstring(z.read("xl/workbook.xml"))
    rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
    first = book.find("m:sheets", NS)[0]
    target = rels[first.get("{%s}id" % NS["r"])].lstrip("/")
    part = target if target.startswith("xl/") else "xl/" + target
    rows: dict[int, dict[int, str]] = {}
    for _, el in ET.iterparse(z.open(part), events=("end",)):
        if el.tag.endswith("}row"):
            cells = {}
            for c in el.findall("m:c", NS):
                v = c.find("m:v", NS)
                kind = c.get("t")
                if kind == "inlineStr":
                    val = "".join(t.text or "" for t in c.iter("{%s}t" % NS["m"]))
                elif v is None:
                    continue
                elif kind == "s":
                    val = shared[int(v.text)]
                else:
                    val = v.text
                cells[col_index(c.get("r"))] = val
            if cells:
                rows[int(el.get("r"))] = cells
            el.clear()
    xml = z.read(part).decode("utf8", "ignore")
    sheet_rels = part.replace("worksheets/", "worksheets/_rels/") + ".rels"
    targets = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read(sheet_rels))} \
        if sheet_rels in z.namelist() else {}
    links: dict[int, str] = {}
    for ref, rid in re.findall(r'<hyperlink [^>]*?ref="([A-Z]+\d+)"[^>]*?r:id="([^"]+)"', xml):
        m = re.search(r"i=(001-\d+)", targets.get(rid, ""))
        if m:
            links[int(re.search(r"\d+", ref).group(0))] = m.group(1)
    return rows, links


def excel_date(value: str) -> str:
    try:
        d = datetime.date(1899, 12, 30) + datetime.timedelta(days=int(float(value)))
    except (TypeError, ValueError):
        return ""
    return d.strftime("%d/%m/%Y")


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    rows, links = read_sheet(sys.argv[1])
    cases: dict[str, dict] = {}
    duplicates = 0
    for rn in sorted(rows):
        r = rows[rn]
        item = links.get(rn)
        if not item or rn <= 4:
            continue
        entry = {
            "name": clean(r.get(2, "")),
            "appno": clean(r.get(3, "")),
            "date": excel_date(r.get(4, "")),
            "kind": clean(r.get(5, "")),
            "subject": clean(r.get(6, "")),
            "conclusions": [clean(x) for x in re.split(r"\n+", r.get(7, "") or "") if clean(x)],
        }
        if item in cases:                       # the same HUDOC document listed twice: keep the first
            duplicates += 1
            continue
        cases[item] = entry
    out = {"source": SOURCE, "cases": cases}
    with open(sys.argv[2], "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"{len(cases)} documents written to {sys.argv[2]} ({duplicates} duplicate item ids skipped)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
