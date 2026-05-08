#!/usr/bin/env python3
"""Compare our dashboard segmentation with HUDOC source DOCX for a sample
of cases.  Reports per-case completeness, gaps, and structural alignment."""
import json
import re
import ssl
import sys
import urllib.request
import io
from collections import Counter

try:
    from docx import Document
except ImportError:
    print("Need python-docx. Install with: pip3 install --user --break-system-packages python-docx")
    sys.exit(1)

API_BASE = "https://150.254.115.204/echr-api/api"
DOCX_URL = "https://hudoc.echr.coe.int/app/conversion/docx/?library=ECHR&id={cid}&filename={cid}.docx"
PARA_NUM_RE = re.compile(r"^\s*(\d+)\.\s+")

ctx = ssl._create_unverified_context()

def fetch_api(cid):
    url = f"{API_BASE}/cases/{cid}"
    return json.loads(urllib.request.urlopen(url, context=ctx, timeout=15).read())

def fetch_docx_paras(cid):
    url = DOCX_URL.format(cid=cid)
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
        "Accept": "*/*",
    })
    blob = urllib.request.urlopen(req, context=ctx, timeout=20).read()
    doc = Document(io.BytesIO(blob))
    out = []
    current_section = None
    for p in doc.paragraphs:
        text = (p.text or "").strip()
        if not text:
            continue
        # Skip headings (we just track them for context)
        m = PARA_NUM_RE.match(text)
        if m:
            n = int(m.group(1))
            out.append({"n": n, "text": text, "section": current_section})
        elif text.isupper() and len(text) < 100:
            current_section = text
    return out

def compare_case(cid):
    api = fetch_api(cid)
    api_paras = api.get("paragraphs", [])
    title = api.get("title", "")[:50]
    doc_type = api.get("document_type", "")

    # Our DB: numbered main-body paragraphs (excluding op_dispositif)
    our_numbered = set()
    for p in api_paras:
        if p.get("hudoc_para_no") and p.get("numbering_block") != "operative_dispositif":
            our_numbered.add(p["hudoc_para_no"])

    # HUDOC source paragraphs
    try:
        hudoc_paras = fetch_docx_paras(cid)
    except Exception as e:
        return {"cid": cid, "title": title, "error": str(e)[:100]}
    hudoc_numbers = {p["n"] for p in hudoc_paras}

    missing_in_ours = sorted(hudoc_numbers - our_numbered)
    extra_in_ours = sorted(our_numbered - hudoc_numbers)

    # Section breakdown of our DB
    sections = Counter(p.get("section") for p in api_paras)

    # Total comparison
    return {
        "cid": cid,
        "title": title,
        "doc_type": doc_type,
        "our_total_rows": len(api_paras),
        "our_numbered": len(our_numbered),
        "hudoc_paras": len(hudoc_paras),
        "missing_in_ours": missing_in_ours[:10] if len(missing_in_ours) < 100 else f"[{len(missing_in_ours)} missing — too many to list]",
        "missing_count": len(missing_in_ours),
        "extra_in_ours": extra_in_ours[:5] if extra_in_ours else [],
        "sections": dict(sections),
        "completeness_pct": round(100 * len(hudoc_numbers & our_numbered) / max(1, len(hudoc_numbers)), 1) if hudoc_numbers else 0,
        "cites": api.get("cites_count", 0),
        "cited_by": api.get("cited_by_count", 0),
    }

cases = [
    # Cases we just fixed (4)
    ("001-249494", "L.P. v. Hungary (committee, post-cleanup)"),
    ("001-249496", "BLASKO v. Slovakia (P26-retry recovered)"),
    ("001-249517", "SOCIETATEA MUZEULUI ARDELEAN (P26-retry recovered)"),
    ("001-249495", "BAYRAMALIYEV v. Türkiye (P31 dispositif demotion)"),
    # Other recent committee judgments (6)
    ("001-249521", "KHALOYAN v. Armenia (committee 2026)"),
    ("001-249522", "RYCHKA v. Ukraine (committee 2026)"),
    ("001-249515", "ISMAYILOVA v. Azerbaijan (committee 2026)"),
    ("001-249516", "SMARANDA AND OTHERS v. Romania (committee 2026)"),
    ("001-249520", "OMAROV v. Georgia (committee 2026)"),
    ("001-249530", "SIMONCINI v. San Marino (committee 2026)"),
    # Older committee judgments (3)
    ("001-194309", "KOSTYUCHENKO v. Russia (committee)"),
    ("001-160404", "KOSINSKI v. Poland (committee 2016)"),
    ("001-171503", "VOLCHKOVA AND ZHELEZNOVA v. Ukraine (committee 2017)"),
    # Decisions of various ages (5)
    ("001-188135", "BERLUSCONI v. Italy (decision, 2018)"),
    ("001-22231", "SLIVENKO v. Latvia (decision, 2002)"),
    ("001-220616", "McCALLUM v. Italy (decision, 2022)"),
    ("001-243130", "MANSOURI v. Italy (decision, 2025)"),
    ("001-175502", "HARKINS v. UK (decision, 2017)"),
    # Classic Pop A judgments (2)
    ("001-57619", "SOERING v. UK (1989, classic GC)"),
    ("001-189641", "MIFSUD v. Malta (2019, Chamber)"),
]
print(f"{'='*90}")
print("Dashboard vs HUDOC source — segmentation completeness")
print(f"{'='*90}\n")
for cid, label in cases:
    print(f"-- {cid}  [{label}]")
    r = compare_case(cid)
    if "error" in r:
        print(f"   ERROR: {r['error']}")
        continue
    completeness = r['completeness_pct']
    flag = "✅" if completeness >= 95 else ("⚠️ " if completeness >= 70 else "❌")
    print(f"   {flag} Completeness: {completeness}% — {r['our_numbered']}/{r['hudoc_paras']} HUDOC paragraphs covered")
    print(f"   our DB: {r['our_total_rows']} rows  | sections: {r['sections']}")
    if r['missing_count']:
        if isinstance(r['missing_in_ours'], str):
            print(f"   missing from our DB: {r['missing_in_ours']}")
        elif r['missing_count'] <= 10:
            print(f"   missing from our DB: ¶{','.join(map(str,r['missing_in_ours']))}")
        else:
            sample = r['missing_in_ours'][:5]
            print(f"   missing from our DB: ¶{','.join(map(str,sample))}, ... ({r['missing_count']} total)")
    if r['extra_in_ours']:
        print(f"   extra in our DB (no HUDOC ¶): ¶{','.join(map(str,r['extra_in_ours']))}")
    print(f"   cites: {r['cites']}, cited_by: {r['cited_by']}")
    print()
