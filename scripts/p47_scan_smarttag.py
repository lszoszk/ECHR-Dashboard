"""Identify cases whose DOCX contains Microsoft Office smartTag wrappers.

Old Office 2003/2007 saved location/date/etc. metadata wrapped in
<w:smartTag> elements.  python-docx's default Paragraph.text walks
only direct <w:r>/<w:t> children and silently drops anything inside
<w:smartTag>, leading to lost words like "England" and "Wales" in the
DB text.  Our fixed ``para_text_full`` does walk smartTag descendants,
but cases parsed BEFORE the fix still carry truncated text.

This scanner emits case_ids that need re-parsing.
"""
import sys
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
import zipfile

CACHE = Path.home() / "Desktop" / "HUDOC-Docx"


def has_smarttag(cid):
    path = CACHE / f"{cid}.docx"
    if not path.exists():
        return None
    try:
        with zipfile.ZipFile(path) as z:
            with z.open("word/document.xml") as f:
                # Read up to ~5MB; smartTag presence is binary signal,
                # no need to parse XML.
                data = f.read(5_000_000)
                if b"<w:smartTag" in data:
                    return cid
    except Exception:
        pass
    return None


def main():
    cids = sorted(p.stem for p in CACHE.glob("*.docx"))
    print(f"# scanning {len(cids)} cases", file=sys.stderr, flush=True)
    out = []
    with ProcessPoolExecutor(max_workers=8) as ex:
        futures = [ex.submit(has_smarttag, c) for c in cids]
        for i, fut in enumerate(as_completed(futures), 1):
            r = fut.result()
            if r:
                out.append(r)
            if i % 2000 == 0:
                print(f"  {i}/{len(cids)}  found={len(out)}",
                      file=sys.stderr, flush=True)
    print(f"\n# total cases with smartTag: {len(out)}", file=sys.stderr)
    for c in out:
        print(c)


if __name__ == "__main__":
    main()
