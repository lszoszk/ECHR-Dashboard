#!/usr/bin/env bash
#
# check_tls_expiry.sh — fail when the API's TLS certificate is close to expiry.
#
#   ./deploy/check_tls_expiry.sh                      # production host, 72 h threshold
#   ./deploy/check_tls_expiry.sh 150.254.115.204 96   # host, threshold in hours
#
# The production certificate is a short-lived (~6.6 day) Let's Encrypt IP
# certificate. If a renewal fails, every visitor falls back to the offline
# sample dataset within days, so this is meant to run from cron or any
# scheduler that can alert on a non-zero exit.
#
# Exit codes: 0 = comfortably valid, 1 = expires within the threshold or
# already expired, 2 = could not read the certificate.
set -u

HOST="${1:-150.254.115.204}"
THRESHOLD_HOURS="${2:-72}"

end_date="$(echo | openssl s_client -connect "${HOST}:443" -servername "${HOST}" 2>/dev/null \
  | openssl x509 -noout -enddate 2>/dev/null | sed 's/^notAfter=//')"

if [ -z "${end_date}" ]; then
  echo "ERROR: could not read the TLS certificate from ${HOST}:443" >&2
  exit 2
fi

# macOS (BSD) date first, then GNU date.
end_epoch="$(date -j -u -f '%b %e %T %Y %Z' "${end_date}" +%s 2>/dev/null \
  || date -u -d "${end_date}" +%s 2>/dev/null)"

if [ -z "${end_epoch}" ]; then
  echo "ERROR: could not parse certificate end date: ${end_date}" >&2
  exit 2
fi

hours_left=$(( (end_epoch - $(date -u +%s)) / 3600 ))

if [ "${hours_left}" -lt "${THRESHOLD_HOURS}" ]; then
  echo "ALERT: ${HOST} certificate expires in ${hours_left} h (threshold ${THRESHOLD_HOURS} h) — notAfter ${end_date}" >&2
  exit 1
fi

echo "OK: ${HOST} certificate valid for ${hours_left} h more (notAfter ${end_date})"
