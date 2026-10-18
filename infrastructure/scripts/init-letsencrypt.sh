#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFRA_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$INFRA_DIR"

if [[ -f ../.env ]]; then
  set -a
  # shellcheck disable=SC1091
  source ../.env
  set +a
fi

: "${DOMAIN_NAME:?DOMAIN_NAME requis}"
: "${LETSENCRYPT_EMAIL:?LETSENCRYPT_EMAIL requis}"

export DOMAIN_NAME

echo "Demande certificat Let's Encrypt pour ${DOMAIN_NAME}..."
docker compose run --rm certbot certbot certonly \
  --webroot -w /var/www/certbot \
  --email "$LETSENCRYPT_EMAIL" \
  --agree-tos --no-eff-email \
  -d "$DOMAIN_NAME"

docker compose run --rm certbot sh -c '
  if [ ! -f /etc/letsencrypt/options-ssl-nginx.conf ]; then
    curl -sSL -o /etc/letsencrypt/options-ssl-nginx.conf \
      https://raw.githubusercontent.com/certbot/certbot/master/certbot-nginx/certbot_nginx/_internal/tls_configs/options-ssl-nginx.conf
  fi
  if [ ! -f /etc/letsencrypt/ssl-dhparams.pem ]; then
    openssl dhparam -out /etc/letsencrypt/ssl-dhparams.pem 2048
  fi
'

envsubst '${DOMAIN_NAME}' < nginx/default.conf.template > nginx/default.conf
docker compose restart nginx

echo "HTTPS actif — https://${DOMAIN_NAME}/ (dashboard) · https://${DOMAIN_NAME}/api/ (API)"
