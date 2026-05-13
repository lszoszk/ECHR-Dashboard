"""Parallel wrapper for p39_extract_heading_data — process N cases concurrently.

Usage:
    python3 scripts/p39_extract_parallel.py \\
        --list /tmp/cids.txt --out /tmp/all_extract.tsv --workers 8
"""
import sys
import argparse
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed

# Make sibling p39_extract_heading_data importable
_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))
import p39_extract_heading_data as ec  # noqa: E402


def process_one(cid):
    try:
        return cid, ec.extract_case(cid), None
    except Exception as e:
        return cid, [], str(e)[:80]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    cids = [l.strip() for l in args.list.open() if l.strip()]
    print(f"processing {len(cids)} cases with {args.workers} workers", file=sys.stderr)

    n_ok = n_err = 0
    with args.out.open("w") as f:
        f.write("case_id\thash\tmatch_key\thpno\theading_level\theading_prefix\n")
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            futures = [ex.submit(process_one, c) for c in cids]
            for i, fut in enumerate(as_completed(futures), 1):
                cid, rows, err = fut.result()
                if err:
                    n_err += 1
                else:
                    n_ok += 1
                    for r in rows:
                        f.write(
                            f"{r['cid']}\t{r['hash']}\t{r['match_key']}\t"
                            f"{r['hpno'] if r['hpno'] is not None else ''}\t"
                            f"{r['heading_level']}\t{r['heading_prefix']}\n"
                        )
                if i % 200 == 0:
                    print(f"  {i}/{len(cids)}  ok={n_ok} err={n_err}",
                          file=sys.stderr, flush=True)
    print(f"\nwrote {args.out}  ok={n_ok} err={n_err}", file=sys.stderr)


if __name__ == "__main__":
    main()
