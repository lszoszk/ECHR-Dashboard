#!/usr/bin/env bash
#
# run_monthly_update.sh — monthly incremental update of the ECHR corpus.
#
# Discovers ECHR judgments published since the corpus's newest case,
# ingests them into the production database, and rebuilds the citation
# graph.  Safe to re-run: cases already present are skipped.
#
#   ./scripts/run_monthly_update.sh            # DRY RUN — discover + build only
#   ./scripts/run_monthly_update.sh --apply    # also write to the VM database
#
# Phases
#   1. dump the existing case list from the VM database
#   2. discover + fetch + build new cases locally  (scripts/p60_monthly_update.py)
#   3. [--apply] apply the update SQL to the VM database
#   4. [--apply] rebuild the citation graph        (scripts/p29_extract_citations.py)
#   4b.[--apply] checkpoint the WAL + warm the facets cache (mandatory)
#   5. [--apply] verify via the live API
#
# Recovery: p60 also emits <out>.rollback — apply it to the VM database
# to remove exactly the cases this run added.
#
# Requires locally: python3 with python-docx (for p60's DOCX parser),
# ssh access to the VM.  Run from the repository root or anywhere.
set -euo pipefail

VM="${ECHR_VM:-amuvmuser@150.254.115.204}"
CONTAINER="${ECHR_CONTAINER:-echr-api}"
DB="${ECHR_DB:-/data/echr_search.db}"
API="${ECHR_API:-https://150.254.115.204/echr-api}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK="${ECHR_WORK:-/tmp/echr_monthly_update}"
mkdir -p "$WORK"

APPLY=0
[ "${1:-}" = "--apply" ] && APPLY=1

echo "================================================================"
echo " ECHR corpus monthly update    $([ $APPLY -eq 1 ] && echo '[APPLY]' || echo '[DRY RUN]')"
echo "================================================================"

# ── Phase 1 — dump the existing case list from the VM ────────────────
echo
echo "[1/5] dumping existing case list from the VM database ..."
cat > "$WORK/_dump_existing.py" <<'PY'
import sqlite3
con = sqlite3.connect("/data/echr_search.db")
for cid, jd in con.execute(
        "SELECT case_id, COALESCE(judgment_date, '') FROM cases"):
    print(f"{cid}\t{jd}")
PY
ssh "$VM" "docker exec -i $CONTAINER python3 -" \
    < "$WORK/_dump_existing.py" > "$WORK/existing.tsv"
echo "      $(wc -l < "$WORK/existing.tsv" | tr -d ' ') cases in corpus"

# ── Phase 2 — discover + fetch + build (local) ───────────────────────
echo
echo "[2/5] discovering and building new cases (local) ..."
python3 "$SCRIPT_DIR/p60_monthly_update.py" \
    --existing "$WORK/existing.tsv" \
    --out      "$WORK/p60_update.sql"

if [ ! -s "$WORK/p60_update.sql" ]; then
    echo "no update SQL produced — nothing to do."
    exit 0
fi

if [ "$APPLY" -ne 1 ]; then
    echo
    echo "DRY RUN complete."
    echo "  forward SQL : $WORK/p60_update.sql"
    echo "  rollback    : $WORK/p60_update.sql.rollback"
    echo "Re-run with --apply to write these cases to the VM database."
    exit 0
fi

# ── Phase 3 — apply the update SQL on the VM ─────────────────────────
echo
echo "[3/5] applying update SQL to the VM database ..."
scp -q "$WORK/p60_update.sql"               "$VM:/tmp/p60_update.sql"
scp -q "$WORK/p60_update.sql.rollback"      "$VM:/tmp/p60_update.sql.rollback"
scp -q "$SCRIPT_DIR/p29_extract_citations.py" "$VM:/tmp/p29_extract_citations.py"
ssh "$VM" "docker cp /tmp/p60_update.sql          $CONTAINER:/tmp/p60_update.sql
           docker cp /tmp/p60_update.sql.rollback $CONTAINER:/tmp/p60_update.sql.rollback
           docker cp /tmp/p29_extract_citations.py $CONTAINER:/tmp/p29_extract_citations.py"
ssh "$VM" "docker exec -i $CONTAINER python3 -" <<PY
import sqlite3
con = sqlite3.connect("$DB")
before = con.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
con.executescript(open("/tmp/p60_update.sql").read())
con.commit()
after = con.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
print(f"      cases {before:,} -> {after:,}  (+{after - before})")
PY

# ── Phase 4 — rebuild the citation graph (P29) ───────────────────────
echo
echo "[4/5] rebuilding the citation graph (P29) ..."
ssh "$VM" "docker exec $CONTAINER python3 /tmp/p29_extract_citations.py \
           --db $DB --apply" | tail -3

# ── Phase 4b — checkpoint the WAL and warm the facets cache ──────────
# Both are mandatory after any write to this database and neither is
# optional politeness. A ~20 MB insert leaves WAL frames that readers must
# traverse, and the live API holds a connection open so SQLite never
# checkpoints on its own — P63/P64 left a 1.16 GB WAL that pushed
# /api/search from ~0.3 s to 8.8 s. Separately, api/main.py keys its facets
# cache on the DB file's (mtime, size), so ANY write — the checkpoint
# included — invalidates it, and the next visitor pays a >45 s whole-corpus
# aggregation that simply times out for them.
echo
echo "[4b] checkpointing the WAL and warming the facets cache ..."
ssh "$VM" "docker exec -i $CONTAINER python3 -" <<PY
import sqlite3, time, urllib.request
con = sqlite3.connect("$DB", timeout=180)
con.execute("PRAGMA busy_timeout = 180000")
for mode in ("PASSIVE", "TRUNCATE"):
    busy, pages, done = con.execute("PRAGMA wal_checkpoint(%s)" % mode).fetchone()
    print(f"      checkpoint {mode:8s} busy={busy} pages={pages:,} written={done:,}")
    if mode == "TRUNCATE" and busy:
        print("      WARNING: readers active, WAL not fully truncated")
con.close()
# BOTH endpoints, not just facets. /api/stats is called by the Search page
# itself (search-app.js:7038), and cold it takes ~76 s — so leaving it unwarmed
# hangs the site's own front door for whoever arrives first.
for path in ("/api/facets", "/api/stats"):
    t0 = time.time()
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000" + path, timeout=900) as r:
            n = len(r.read())
        print(f"      warmed {path:14s} {n:,} bytes in {time.time() - t0:.1f}s")
    except Exception as e:
        print(f"      WARNING: could not warm {path} ({e}) — first visitor will hang")
PY

# ── Phase 5 — verify via the live API ────────────────────────────────
echo
echo "[5/5] verifying via the live API ..."
curl -sk "$API/api/stats" \
    | python3 -c 'import sys,json; d=json.load(sys.stdin); print("      total cases:", d.get("total_cases") or d.get("cases"))' \
    || echo "      (stats endpoint unavailable — check the API manually)"

echo
echo "Update complete."
echo "  rollback if needed:  docker exec -i $CONTAINER python3 -c \\"
echo "    \"import sqlite3;c=sqlite3.connect('$DB');c.executescript(open('/tmp/p60_update.sql.rollback').read());c.commit()\""
echo "  then re-run P29."
