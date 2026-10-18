#!/usr/bin/env bash
# Obtient le certificat Let's Encrypt puis bascule nginx en HTTPS.
# Prérequis : DNS A de DOMAIN_NAME -> cette machine, ports 80/443 ouverts, stack HTTP démarrée.
set -euo pipefail
# shellcheck source=_common.sh
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

: "${LETSENCRYPT_EMAIL:?LETSENCRYPT_EMAIL requis dans le .env}"
STAGING_FLAG=()
if [[ "${LETSENCRYPT_STAGING:-false}" == "true" ]]; then
  STAGING_FLAG=(--staging)
fi

echo "Demande du certificat Let's Encrypt pour ${DOMAIN_NAME}..."
$DC run --rm --no-deps --entrypoint certbot certbot certonly \
  --webroot -w /var/www/certbot \
  --email "$LETSENCRYPT_EMAIL" \
  --agree-tos --no-eff-email --non-interactive \
  ${STAGING_FLAG[@]+"${STAGING_FLAG[@]}"} \
  -d "$DOMAIN_NAME"

render_nginx nginx/default.conf.template
$DC exec nginx nginx -t
$DC exec nginx nginx -s reload

echo "HTTPS actif : https://${DOMAIN_NAME}/ (dashboard) et https://${DOMAIN_NAME}/api/ (API)"
