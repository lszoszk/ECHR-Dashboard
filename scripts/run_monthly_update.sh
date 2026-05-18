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
