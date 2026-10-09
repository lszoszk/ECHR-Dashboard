"""
Resolve ECtHR citations for the Check page.

The page finds the citations in a pasted text itself and sends only what identifies each cited
document (application numbers, the "X v. State" name, a date, the [GC] and (dec.) markers); the
text never reaches the server. Each citation is resolved against the judgments of the corpus and,
failing that, against HUDOC's French-only judgments, with the rules of the citation graph: the
application number first, then the date, then [GC], then the principal judgment of the case.

    index = CitationIndex.from_db(con)
    resolve_items(index, [{"key": "c1", "appnos": ["30210/96"], "name": "Kudła v. Poland", "gc": True}])

Statuses: found, check (found, but something in the citation does not match), ambiguous (several
documents fit), not_found, outside (a document kind the corpus does not hold, e.g. a decision).
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata
from collections import defaultdict
from datetime import date

APPNO = re.compile(r"(?<![\d/])(\d{1,7})/(\d{4}|\d{2})(?![\d/])")
# A judgment given after (or before) the principal one: on just satisfaction alone, revision,
# interpretation or preliminary objections. "Merits and Just Satisfaction" is the principal judgment.
SECONDARY_TYPES = {"judgment (just satisfaction)", "judgment (revision)", "judgment (interpretation)",
                   "judgment (preliminary objection)"}
SECONDARY_TITLE = re.compile(r"\((?:just satisfaction|article 50|article 41|revision|interpretation|"
                             r"preliminary objections?)[^)]*\)", re.I)
# One spelling per State, so that "Türkiye" finds "TURKEY" and the reverse.
STATE_ALIASES = [
    (r"\bturkiye\b", "turkey"),
    (r"\bthe former yugoslav republic of macedonia\b", "north macedonia"),
    (r"\brepublic of moldova\b", "moldova"),
    (r"\brussian federation\b", "russia"),
]
MAX_ITEMS = 200
FRENCH_ONLY_NOTE = ("HUDOC publishes this judgment only in French, so it is not in this English corpus: "
                    "the citation exists, but its paragraphs and quotations cannot be checked here.")


def ascii_text(value) -> str:
    text = str(value or "").lower().replace("ł", "l").replace("ı", "i")
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def appnos_of(value) -> set[str]:
    return {f"{int(n)}/{int(y) % 100:02d}" for n, y in APPNO.findall(str(value or ""))}


def name_key(value) -> str:
    """'CASE OF KUDLA v. POLAND (No. 2)' and 'Kudła v. Poland (no. 2)' -> 'kudla v poland no 2'."""
    text = ascii_text(value)
    text = re.sub(r"^\s*(?:case of|affaire)\s+", "", text)
    text = re.sub(r"\[[^\]]*\]|\(dec\.?\)", " ", text)
    # keep "(no. 2)"; drop "(merits)", "(just satisfaction)", "(preliminary objections)" and the like
    text = re.sub(r"\((?!\s*no\.?\s*\d)[^)]*\)", " ", text)
    text = re.sub(r"\s+(?:v|c)\.?\s+", " v ", text)
    for pattern, repl in STATE_ALIASES:
        text = re.sub(pattern, repl, text)
    text = re.sub(r"\bthe\b", " ", text)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def applicant_words(key: str) -> list[str]:
    head = key.split(" v ", 1)[0]
    return [w for w in head.split() if w not in {"and", "others", "of", "no"} and not w.isdigit()]


def iso_date(ddmmyyyy) -> str | None:
    m = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", str(ddmmyyyy or ""))
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


def _columns(con: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in con.execute(f"PRAGMA table_info({table})")}


class CitationIndex:
    def __init__(self, docs: list[dict], french: list[dict]):
        self.docs = {d["case_id"]: d for d in docs}
        self.by_appno: dict[str, list[dict]] = defaultdict(list)
        self.by_name: dict[str, list[dict]] = defaultdict(list)
        for d in docs:
            for a in d["appnos"]:
                self.by_appno[a].append(d)
            self.by_name[d["name_key"]].append(d)
        self.fr_by_appno: dict[str, list[dict]] = defaultdict(list)
        self.fr_by_name: dict[str, list[dict]] = defaultdict(list)
        for f in french:
            for a in f["appnos"]:
                self.fr_by_appno[a].append(f)
            self.fr_by_name[f["name_key"]].append(f)

    @classmethod
    def from_db(cls, con: sqlite3.Connection) -> "CitationIndex":
        cols = _columns(con, "cases")
        origin = "text_origin" if "text_origin" in cols else "NULL"
        source = "source_case_id" if "source_case_id" in cols else "NULL"
        docs = []
        for r in con.execute(
                f"SELECT case_id, case_no, title, judgment_date, document_type, originating_body, importance, "
                f"hudoc_url, {origin}, {source} FROM cases"):
            case_id, case_no, title, jdate, dtype, body, importance, url, text_origin, source_id = r
            dtype, body = dtype or "", str(body or "")
            docs.append({
                "case_id": case_id, "title": re.sub(r"^CASE OF\s+", "", title or "", flags=re.I).strip(),
                "appnos": appnos_of(case_no), "date": iso_date(jdate), "document_type": dtype,
                "body": body, "importance": importance, "hudoc_url": url,
                "gc": "grand chamber" in body.lower(), "decision": dtype.lower().startswith("decision"),
                "secondary": dtype.lower() in SECONDARY_TYPES or bool(SECONDARY_TITLE.search(title or "")),
                "machine_translation": text_origin == "machine_translation", "source_case_id": source_id,
                "name_key": name_key(title),
            })
        french = []
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "french_only_cases" in tables:
            for case_id, title, case_no, jdate, url in con.execute(
                    "SELECT source_id, title, case_no, judgment_date, hudoc_url FROM french_only_cases"):
                french.append({"case_id": case_id, "title": re.sub(r"^CASE OF\s+", "", title or "", flags=re.I).strip(),
                               "appnos": appnos_of(case_no), "date": iso_date(jdate), "hudoc_url": url,
                               "name_key": name_key(title)})
        return cls(docs, french)


def _public(d: dict) -> dict:
    return {k: (sorted(v) if isinstance(v, set) else v) for k, v in d.items() if k != "name_key"}


def _same_applicant(cited_key: str, doc_key: str) -> bool:
    """Whether the cited name plausibly names the document's applicant (first significant word)."""
    cited = applicant_words(cited_key)
    if not cited:
        return True
    return cited[0] in set(applicant_words(doc_key)) or doc_key.startswith(cited_key)


def _pick(docs: list[dict], item: dict) -> list[dict]:
    """Narrow several documents of one case to the cited one: date, then [GC], then the principal judgment."""
    if len(docs) <= 1:
        return docs
    if item.get("date"):
        same_day = [d for d in docs if d["date"] == item["date"]]
        if same_day:
            docs = same_day
    if len(docs) > 1:
        wanted_gc = [d for d in docs if d["gc"] == bool(item.get("gc"))]
        if wanted_gc:
            docs = wanted_gc
    if len(docs) > 1:
        principal = [d for d in docs if not d["secondary"]]
        if principal:
            docs = principal
    return docs


def _notes_for(match: dict, item: dict, index: CitationIndex) -> tuple[str, list[str]]:
    """Status and notes for a matched judgment, comparing it with what the citation says."""
    notes, status = [], "found"
    cited_key = name_key(item.get("name") or "")
    if cited_key and " v " in cited_key and not _same_applicant(cited_key, match["name_key"]):
        status = "check"
        notes.append(f"Application no. {', '.join(sorted(match['appnos']))} is {match['title']}, "
                     f"not {item.get('name')}.")
    if item.get("date") and match["date"] and item["date"] != match["date"]:
        status = "check"
        notes.append(f"The judgment is dated {match['date']}, not {item['date']}.")
    if item.get("gc") and not match["gc"]:
        status = "check"
        notes.append(f"Cited as [GC], but this is a judgment of the {match['body'] or 'Court'}.")
    elif match["gc"] and not item.get("gc"):
        notes.append("This is a Grand Chamber judgment: the Court cites it with [GC].")
    if not match["gc"] and not match["secondary"]:
        later = [d for a in match["appnos"] for d in index.by_appno.get(a, [])
                 if d["gc"] and not d["secondary"] and (d["date"] or "") > (match["date"] or "")]
        if later:
            gc = sorted(later, key=lambda d: d["date"] or "")[-1]
            status = "check"
            notes.append(f"The case was referred to the Grand Chamber, which gave judgment on {gc['date']} "
                         f"({gc['case_id']}): cite that judgment unless the Chamber judgment is the point.")
    if match["machine_translation"]:
        notes.append("HUDOC publishes this judgment only in French; the English text here is an unofficial "
                     "machine translation.")
    return status, notes


def resolve_item(index: CitationIndex, item: dict) -> dict:
    out = {"key": item.get("key"), "status": "not_found", "match": None, "candidates": [], "notes": []}
    appnos = {a for raw in (item.get("appnos") or []) for a in appnos_of(raw)}
    cited_key = name_key(item.get("name") or "")

    if item.get("dec"):
        decisions = [d for a in appnos for d in index.by_appno.get(a, []) if d["decision"]]
        if not decisions and cited_key:
            decisions = [d for d in index.by_name.get(cited_key, []) if d["decision"]]
        decisions = _pick(decisions, item)
        if len(decisions) == 1:
            out.update(status="found", match=_public(decisions[0]))
            return out
        out["status"] = "outside"
        out["notes"].append("Admissibility decisions are not in this database (it holds judgments): "
                            "check the decision on HUDOC.")
        return out

    if appnos:
        docs = [d for a in sorted(appnos) for d in index.by_appno.get(a, []) if not d["decision"]]
        docs = list({d["case_id"]: d for d in docs}.values())
        if not docs:
            french = list({f["case_id"]: f for a in appnos for f in index.fr_by_appno.get(a, [])}.values())
            if french:
                f = sorted(french, key=lambda x: x["date"] or "")[0] if len(french) > 1 else french[0]
                out.update(status="outside", match={**_public(f), "french_only": True})
                out["notes"].append(FRENCH_ONLY_NOTE)
                if cited_key and not _same_applicant(cited_key, f["name_key"]):
                    out["status"] = "check"
                    out["notes"].insert(0, f"Application no. {', '.join(sorted(f['appnos']))} is {f['title']}, "
                                           f"not {item.get('name')}.")
                return out
            out["notes"].append(f"No judgment with application no. {', '.join(sorted(appnos))} in this database or "
                                "among HUDOC's French-only judgments. It may be a decision or a communicated case "
                                "(check HUDOC), or the number may be mistyped or invented.")
            return out
        picked = _pick(docs, item)
        if len(picked) > 1:
            out["status"] = "ambiguous"
            out["candidates"] = [_public(d) for d in sorted(picked, key=lambda d: d["date"] or "")]
            out["notes"].append("Several judgments carry this application number; add the date or [GC].")
            return out
        out["match"] = _public(picked[0])
        out["status"], out["notes"] = _notes_for(picked[0], item, index)
        return out

    if not cited_key or " v " not in cited_key:
        out["notes"].append("Nothing to identify the judgment by: give the application number or the full name.")
        return out
    docs = [d for d in index.by_name.get(cited_key, []) if not d["decision"]]
    if not docs:  # "X v. State" without its "(no. 2)", or with words the title spells differently
        docs = [d for k, ds in index.by_name.items() if k.startswith(cited_key + " no ") for d in ds if not d["decision"]]
    if not docs and item.get("date"):
        docs = [d for d in index.docs.values() if d["date"] == item["date"] and not d["decision"]
                and _same_applicant(cited_key, d["name_key"]) and cited_key.split(" v ", 1)[1] in d["name_key"]]
    if not docs:
        french = index.fr_by_name.get(cited_key, [])
        if french:
            out.update(status="outside", match={**_public(french[0]), "french_only": True})
            out["notes"].append(FRENCH_ONLY_NOTE)
            return out
        out["notes"].append(f"No judgment named {item.get('name')} in this database or among HUDOC's French-only "
                            "judgments. Check the spelling, or the case may be a decision or invented.")
        return out
    picked = _pick(docs, item)
    if len(picked) > 1:
        out["status"] = "ambiguous"
        out["candidates"] = [_public(d) for d in sorted(picked, key=lambda d: d["date"] or "")]
        out["notes"].append("Several judgments fit this name; add the application number or the date.")
        return out
    out["match"] = _public(picked[0])
    out["status"], out["notes"] = _notes_for(picked[0], item, index)
    if not item.get("date"):
        out["notes"].append("Identified by name only; the Court's citation gives the application number.")
    return out


def resolve_items(index: CitationIndex, items: list[dict]) -> list[dict]:
    return [resolve_item(index, it) for it in (items or [])[:MAX_ITEMS] if isinstance(it, dict)]


def _iso(value) -> str | None:
    """'2000-10-26' as given by the page; anything else is ignored."""
    try:
        return date.fromisoformat(str(value)).isoformat() if value else None
    except ValueError:
        return None


def clean_item(raw: dict) -> dict:
    """Keep only the fields the resolver reads, bounded in size."""
    return {
        "key": str(raw.get("key", ""))[:40],
        "appnos": [str(a)[:20] for a in (raw.get("appnos") or [])][:20],
        "name": str(raw.get("name") or "")[:200],
        "date": _iso(raw.get("date")),
        "gc": bool(raw.get("gc")),
        "dec": bool(raw.get("dec")),
    }
