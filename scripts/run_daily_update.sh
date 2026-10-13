#!/usr/bin/env bash
#
# run_daily_update.sh — once-a-day incremental update of the ECHR corpus.
#
#   ./scripts/run_daily_update.sh                 # DRY RUN: discover + build locally, write nothing
#   ./scripts/run_daily_update.sh --apply         # also write to the VM databases
#   ./scripts/run_daily_update.sh --since 2026-10-01   # override the discovery window start
#
# Most days there is nothing new and the run ends after phase 2 without touching the VM.
# When HUDOC has new English judgments:
#   1. dump the case list of the VM database (read only)
#   2. fetch + build the new judgments locally          (scripts/p60_monthly_update.py)
#   3. [--apply] insert them on the VM, one transaction; the rollback SQL is kept next to it
#   4. [--apply] HUDOC "Case details" metadata for them  (p69 fetch + deploy/sync_metadata_on_vm.sh)
#   5. [--apply] rebuild the citation graph               (deploy/rebuild_citations.sh, then p76 for echr_fr.db)
#   6. [--apply] checkpoint the WAL, warm /api/facets and /api/stats, check the count via the API
#
# Judgments whose DOCX HUDOC has not rendered yet (HTTP 500) are skipped and tried again the next day.
# If a run stops after phase 3, the ids are kept in $WORK/pending_ids.txt and the next run finishes
# phases 4-6 for them first.
#
# Not covered: new decisions, new French-only judgments (echr_fr.db), the Semantic Search index and the
# static Statistics page.
#
# Requires locally: python3 with python-docx, ssh access to the VM. Scheduling: deploy/echr-daily-update.plist.
set -euo pipefail

VM="${ECHR_VM:-amuvmuser@150.254.115.204}"
CONTAINER="${ECHR_CONTAINER:-echr-api}"
DB="${ECHR_DB:-/data/echr_search.db}"
FR_DB="${ECHR_FR_DB:-/data/echr_fr.db}"
API="${ECHR_API:-https://150.254.115.204/echr-api}"
REMOTE_DIR="${ECHR_REMOTE_DIR:-/home/amuvmuser/echr/updates}"
MAX_NEW="${ECHR_MAX_NEW:-150}"          # more than this in one day = something is wrong; stop and look
WORK="${ECHR_WORK:-$HOME/.echr-daily-update}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAMP="$(date +%Y%m%d-%H%M)"
SSH=(ssh -o BatchMode=yes -o ConnectTimeout=20 "$VM")

APPLY=0
SINCE=()
while [ $# -gt 0 ]; do
  case "$1" in
    --apply) APPLY=1 ;;
    --since) SINCE=(--since "$2"); shift ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

mkdir -p "$WORK/logs"
LOG="$WORK/logs/$(date +%Y-%m-%d).log"
exec > >(tee -a "$LOG") 2>&1

# one run at a time
if ! mkdir "$WORK/lock" 2>/dev/null; then
  if kill -0 "$(cat "$WORK/lock/pid" 2>/dev/null)" 2>/dev/null; then
    echo "$(date '+%F %T') another run is in progress (pid $(cat "$WORK/lock/pid")); exiting"; exit 0
  fi
  rm -rf "$WORK/lock"; mkdir "$WORK/lock"
fi
echo $$ > "$WORK/lock/pid"
trap 'rm -rf "$WORK/lock"' EXIT

echo "================================================================"
echo " ECHR daily update  $(date '+%F %T')  $([ $APPLY -eq 1 ] && echo '[APPLY]' || echo '[DRY RUN]')"
echo "================================================================"

if [ "$(curl -sk -o /dev/null -w '%{http_code}' --max-time 30 "$API/health")" != "200" ]; then
  echo "API $API/health does not answer 200 — not updating today."; exit 3
fi

# ── phases 4-6, for a list of new case ids ──────────────────────────
post_steps() {
  local ids="$1"
  echo; echo "[4/6] HUDOC metadata for $(wc -l < "$ids" | tr -d ' ') new cases ..."
  rm -f "$WORK/ids.db" "$WORK/hudoc_meta.json"
  python3 -c "import sqlite3; sqlite3.connect('$WORK/ids.db').execute('CREATE TABLE cases (case_id TEXT)')"
  python3 "$ROOT/scripts/p69_sync_hudoc_metadata.py" fetch --db "$WORK/ids.db" --out "$WORK/hudoc_meta.json" --ids "$ids"
  "$ROOT/deploy/sync_metadata_on_vm.sh" "$WORK/hudoc_meta.json" --apply

  echo; echo "[5/6] rebuilding the citation graph ..."
  "$ROOT/deploy/rebuild_citations.sh" --apply
  scp -q -o BatchMode=yes "$ROOT/scripts/p76_french_citations.py" "$VM:/tmp/p76_french_citations.py"
  "${SSH[@]}" "docker cp /tmp/p76_french_citations.py $CONTAINER:/tmp/p76_french_citations.py && rm -f /tmp/p76_french_citations.py && \
    if docker exec $CONTAINER test -f $FR_DB; then docker exec $CONTAINER python3 /tmp/p76_french_citations.py --main $DB --fr $FR_DB --apply | tail -2; fi"

  echo; echo "[6/6] checkpointing the WAL and warming the caches ..."
  "${SSH[@]}" "docker exec -i $CONTAINER python3 -" <<PY
import sqlite3, time, urllib.request
for path in ("$DB", "$FR_DB"):
    try:
        con = sqlite3.connect(path, timeout=180)
    except sqlite3.Error:
        continue
    con.execute("PRAGMA busy_timeout = 180000")
    print("      checkpoint", path, con.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone())
    con.close()
for path in ("/api/facets", "/api/stats"):
    t0 = time.time()
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000" + path, timeout=900) as r:
            n = len(r.read())
        print(f"      warmed {path:12s} {n:,} bytes in {time.time() - t0:.1f}s")
    except Exception as e:
        print(f"      WARNING: could not warm {path} ({e})")
PY
  rm -f "$WORK/pending_ids.txt"
}

# a run that stopped after inserting cases: finish it first
if [ -s "$WORK/pending_ids.txt" ]; then
  echo "unfinished run found: $(wc -l < "$WORK/pending_ids.txt" | tr -d ' ') cases inserted without the later steps"
  if [ "$APPLY" -eq 1 ]; then post_steps "$WORK/pending_ids.txt"; else echo "(dry run: would finish them now)"; fi
fi

# ── phase 1 — the corpus's case list (read only) ───────────────────
echo; echo "[1/6] case list of the VM database ..."
"${SSH[@]}" "docker exec -i $CONTAINER python3 -" > "$WORK/existing.tsv" <<PY
import sqlite3
con = sqlite3.connect("file:$DB?mode=ro", uri=True)
for cid, jd in con.execute("SELECT case_id, COALESCE(judgment_date, '') FROM cases"):
    print(f"{cid}\t{jd}")
PY
BEFORE="$(wc -l < "$WORK/existing.tsv" | tr -d ' ')"
echo "      $BEFORE cases"

# ── phase 2 — discover + build locally ─────────────────────────────
echo; echo "[2/6] new English judgments on HUDOC ..."
SQL="$WORK/p60_update_$STAMP.sql"
rm -f "$WORK"/p60_update_*.sql "$WORK"/p60_update_*.sql.rollback
python3 "$ROOT/scripts/p60_monthly_update.py" --existing "$WORK/existing.tsv" --out "$SQL" ${SINCE[@]+"${SINCE[@]}"}
NEW=0
[ -s "$SQL" ] && NEW="$(grep -c '^INSERT OR IGNORE INTO cases ' "$SQL" || true)"
if [ "$NEW" -eq 0 ]; then
  echo; echo "nothing new to load."; exit 0
fi
if [ "$NEW" -gt "$MAX_NEW" ]; then
  echo; echo "STOP: $NEW new cases in one run (limit $MAX_NEW). Check $SQL, then run with ECHR_MAX_NEW=$NEW."; exit 4
fi
grep -o "^INSERT OR IGNORE INTO cases ([^)]*) VALUES ('[0-9-]*'" "$SQL" | sed "s/.*VALUES ('//; s/'$//" > "$WORK/new_ids.txt"
if [ "$APPLY" -ne 1 ]; then
  echo; echo "DRY RUN: $NEW cases would be loaded ($SQL). Re-run with --apply."; exit 0
fi

# ── phase 3 — insert on the VM ─────────────────────────────────────
echo; echo "[3/6] inserting $NEW cases on the VM ..."
NAME="$(basename "$SQL")"
"${SSH[@]}" "mkdir -p $REMOTE_DIR"
scp -q -o BatchMode=yes "$SQL" "$SQL.rollback" "$VM:$REMOTE_DIR/"
"${SSH[@]}" "docker cp $REMOTE_DIR/$NAME $CONTAINER:/tmp/$NAME"
cp "$WORK/new_ids.txt" "$WORK/pending_ids.txt"     # from here on, a stopped run is finished by the next one
"${SSH[@]}" "docker exec -i $CONTAINER python3 -" <<PY
import sqlite3, sys
con = sqlite3.connect("$DB", timeout=300)
con.execute("PRAGMA busy_timeout = 300000")
before = con.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
con.executescript(open("/tmp/$NAME").read())
con.commit()
after = con.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
print(f"      cases {before:,} -> {after:,} (+{after - before}; built $NEW)")
sys.exit(0 if after - before == $NEW else 1)
PY
"${SSH[@]}" "docker exec $CONTAINER rm -f /tmp/$NAME"
echo "      rollback: $REMOTE_DIR/$NAME.rollback (then re-run deploy/rebuild_citations.sh --apply)"

post_steps "$WORK/pending_ids.txt"

AFTER="$(curl -sk --max-time 300 "$API/api/stats" | python3 -c 'import sys,json; print(json.load(sys.stdin)["total_cases"])' 2>/dev/null || echo '?')"
echo; echo "Done: $BEFORE -> $AFTER cases. Log: $LOG"
