#!/usr/bin/env bash
# Met a jour l'enregistrement A ClouDNS pour DOMAIN_NAME -> TARGET_IP
# Secrets Cursor / .env : CLOUDNS_AUTH_ID, CLOUDNS_AUTH_PASSWORD
set -euo pipefail
# shellcheck source=_common.sh
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

TARGET_IP="${1:-${CULTURELIVE_PUBLIC_IP:-}}"
: "${TARGET_IP:?IP cible requise (argument ou CULTURELIVE_PUBLIC_IP)}"
: "${CLOUDNS_AUTH_ID:?CLOUDNS_AUTH_ID requis}"
: "${CLOUDNS_AUTH_PASSWORD:?CLOUDNS_AUTH_PASSWORD requis}"

FQDN="${DOMAIN_NAME:?DOMAIN_NAME requis}"
# culturelive.formation-dstest-octa-2026.cloud-ip.cc -> zone + host
if [[ "$FQDN" == *.*.*.* ]]; then
  ZONE="${FQDN#*.}"
  HOST="${FQDN%%.$ZONE}"
else
  echo "DOMAIN_NAME invalide: $FQDN" >&2
  exit 1
fi

records_json="$(curl -fsS \
  "https://api.cloudns.net/dns/records.json?auth-id=${CLOUDNS_AUTH_ID}&auth-password=${CLOUDNS_AUTH_PASSWORD}&domain-name=${ZONE}&host=${HOST}&type=A")"

record_id="$(python3 - <<'PY' "$records_json"
import json, sys
data = json.loads(sys.argv[1])
if not data:
    sys.exit("Aucun enregistrement A trouve")
# premier record A
for rid, rec in data.items():
    if rec.get("type") == "A":
        print(rid)
        break
else:
    sys.exit("Pas de record A")
PY
)"

curl -fsS \
  "https://api.cloudns.net/dns/update-record.json?auth-id=${CLOUDNS_AUTH_ID}&auth-password=${CLOUDNS_AUTH_PASSWORD}&domain-name=${ZONE}&record-id=${record_id}&host=${HOST}&record=${TARGET_IP}&ttl=60"

echo "DNS A ${HOST}.${ZONE} -> ${TARGET_IP} (record ${record_id})"
