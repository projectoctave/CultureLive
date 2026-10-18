#!/usr/bin/env bash
# Chargé par les autres scripts : positionne le répertoire de travail et exporte le .env racine.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFRA_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$INFRA_DIR" || exit 1

ENV_FILE="${ENV_FILE:-$INFRA_DIR/../.env}"
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi
export ENV_FILE

: "${DOMAIN_NAME:?DOMAIN_NAME requis dans le .env}"
: "${JWT_SECRET:?JWT_SECRET requis dans le .env}"
: "${DASHBOARD_API_KEY:?DASHBOARD_API_KEY requis dans le .env}"

# shellcheck disable=SC2034  # utilisé par les scripts qui chargent ce fichier
DC="docker compose"

render_nginx() {
  local template="$1"
  mkdir -p nginx/conf.d
  sed "s|\${DOMAIN_NAME}|${DOMAIN_NAME}|g" "$template" > nginx/conf.d/default.conf
}
