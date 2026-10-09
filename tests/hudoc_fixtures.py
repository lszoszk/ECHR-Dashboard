"""Shared offline HUDOC catalog fixtures."""
from collections import Counter
import hudoc_catalog as catalog

def document(cid="001-1", language="ENG", ecli="ECLI:one", **extra):
    return dict(itemid=cid, languageisocode=language, ecli=ecli,
                docname="CASE OF SAMPLE v. POLAND", appno="1/58",
                kpdate="1959-01-01T00:00:00", judgementdate="01/01/1959 00:00:00",
                doctypebranch="CHAMBER", doctype="HEJUD", documentcollectionid2="JUDGMENTS", **extra)


def fixture(rows, languages=("ENG",)):
    counts = Counter(r["languageisocode"] for r in rows)
    return {"documents": rows, "manifest": {
        "since": "1959-01-01", "to": "1959-12-31", "languages": list(languages),
        "generated_at": "2026-10-09T00:00:00+00:00", "count_checked": True,
        "resumed": False, "raw_count": len(rows),
        "sha256": catalog.fingerprint(r["itemid"] for r in rows),
        "partitions": [{"language": lang, "since": "1959-01-01", "to": "1959-12-31", "count": counts[lang]} for lang in languages]}}


