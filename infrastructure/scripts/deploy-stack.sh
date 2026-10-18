#!/usr/bin/env bash
# Déploiement one-go : nginx HTTP → certificat → nginx HTTPS → seed demo optionnel.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFRA_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$INFRA_DIR"

RUN_SEED="${RUN_SEED:-true}"

if [[ -f ../.env ]]; then
  set -a
  # shellcheck disable=SC1091
  source ../.env
  set +a
fi

: "${DOMAIN_NAME:?DOMAIN_NAME requis dans .env}"
: "${LETSENCRYPT_EMAIL:?LETSENCRYPT_EMAIL requis}"

bash scripts/render-nginx-http-only.sh
docker compose build
docker compose up -d postgres api dashboard nginx certbot

echo "Attente des services..."
sleep 8
bash scripts/init-letsencrypt.sh

if [[ "$RUN_SEED" == "true" ]]; then
  docker compose --profile seed run --rm seed
fi

echo "Déploiement terminé."
