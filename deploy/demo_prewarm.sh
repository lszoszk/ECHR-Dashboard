#!/usr/bin/env bash
#
# demo_prewarm.sh — warm the production API and check the steps of a live demo.
#
#   ./deploy/demo_prewarm.sh                    # production API
#   ./deploy/demo_prewarm.sh https://host/echr-api
#   SLOW_S=3 ./deploy/demo_prewarm.sh           # stricter "too slow" threshold (default 5 s)
#
# Run it 10-15 minutes before presenting, and again right before if the API was
# restarted in between. The first pass touches every endpoint once so that the
# case-level caches, the SQLite page cache and the semantic index are loaded;
# the second pass is what gets timed and judged. The queries are the ones that
# were measured fast on the live server (quoted phrases and rare terms). Broad
# bare-word queries with an article filter (for example "effective remedy" with
# article 13) can take 10-30 s and are deliberately not in this list.
#
# Exit codes: 0 = every step answered under the threshold, 1 = at least one step
# was slow or failed, 2 = the API did not answer at all.
set -u

API="${1:-https://150.254.115.204/echr-api}"
SLOW_S="${SLOW_S:-5}"
MAX_S="${MAX_S:-300}"   # cold /api/stats after a container restart can take minutes

bad=0
pass="warm"

# timed LABEL PATH [curl args...] — GET API+PATH; print the timing on the second pass.
timed() {
  local label="$1" path="$2"; shift 2
  local out code secs mark=ok
  out="$(curl -sS -G -o /dev/null --max-time "${MAX_S}" -w '%{http_code} %{time_total}' "${API}${path}" "$@" 2>/dev/null)" \
    || out="000 ${MAX_S}"
  code="${out%% *}"; secs="${out##* }"
  [ "${pass}" = "warm" ] && return 0
  if [ "${code}" != "200" ]; then
    mark="FAILED"; bad=1
  elif awk -v s="${secs}" -v t="${SLOW_S}" 'BEGIN { exit !(s > t) }'; then
    mark="SLOW"; bad=1
  fi
  printf '  %-44s %7.2fs  HTTP %s  %s\n' "${label}" "${secs}" "${code}" "${mark}"
}

run_steps() {
  timed "health"                                  /health
  timed "stats (header counters)"                 /api/stats
  timed "facets (filter lists)"                   /api/facets
  timed "semantic index load (rag/health)"        /rag/health
  timed "name: Kudla v. Poland"                   /api/suggest   --data-urlencode "q=Kudla v. Poland" --data-urlencode "limit=3"
  timed "name: application number 30210/96"       /api/suggest   --data-urlencode "q=30210/96" --data-urlencode "limit=3"
  timed "phrase: \"pressing social need\""        /api/search    --data-urlencode 'q="pressing social need"' --data-urlencode "page_size=20"
  timed "phrase: \"living instrument\""           /api/search    --data-urlencode 'q="living instrument"' --data-urlencode "page_size=20"
  timed "phrase: \"chilling effect\""             /api/search    --data-urlencode 'q="chilling effect"' --data-urlencode "page_size=20"
  timed "phrase: \"journalistic sources\""        /api/search    --data-urlencode 'q="journalistic sources"' --data-urlencode "page_size=20"
  timed "phrase: \"pilot judgment\""              /api/search    --data-urlencode 'q="pilot judgment"' --data-urlencode "page_size=20"
  timed "refoulement, Article 3"                  /api/search    --data-urlencode "q=refoulement" --data-urlencode "articles=3" --data-urlencode "page_size=20"
  timed "positive obligations, 2010-2020"         /api/search    --data-urlencode "q=positive obligations" --data-urlencode "date_from=2010-01-01" --data-urlencode "date_to=2020-12-31" --data-urlencode "page_size=20"
  timed "semantic: journalist's confidential sources" /rag/similar --data-urlencode "q=protection of a journalist's confidential sources" --data-urlencode "k=10"
  timed "semantic: climate change"                /rag/similar   --data-urlencode "q=state obligations to prevent harm from climate change" --data-urlencode "k=10"
  timed "case page: Kudla v. Poland"              /api/cases/001-58920
  timed "case: cited by"                          /api/cases/001-58920/cited_by
  timed "case: cites"                             /api/cases/001-58920/cites
}

echo "Pre-warming ${API} (pass 1 of 2; /api/stats can take minutes right after a restart) ..."
if ! curl -sS -o /dev/null --max-time 20 "${API}/health" 2>/dev/null; then
  echo "ERROR: ${API}/health did not answer. Check the API and its TLS certificate first:" >&2
  echo "       ./deploy/check_tls_expiry.sh" >&2
  exit 2
fi
run_steps

pass="measure"
echo "Timing (pass 2 of 2; \"slow\" means over ${SLOW_S} s):"
run_steps

echo
if [ "${bad}" -eq 0 ]; then
  echo "READY — every demo step answered in under ${SLOW_S} s."
else
  echo "NOT READY — at least one step was slow or failed. Run it again in a minute;" >&2
  echo "if it stays slow, do not restart the API shortly before the demo (a cold start takes minutes)." >&2
fi
exit "${bad}"
