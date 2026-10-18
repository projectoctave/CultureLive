#!/usr/bin/env bash
# Déploiement one-go : build, démarrage HTTP, certificat Let's Encrypt, bascule HTTPS.
# RUN_SEED=true  -> charge aussi les données de démonstration (comptes aux mots de passe connus).
# SKIP_TLS=true  -> reste en HTTP (test local sans DNS).
set -euo pipefail
# shellcheck source=_common.sh
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

RUN_SEED="${RUN_SEED:-false}"
SKIP_TLS="${SKIP_TLS:-false}"

bash "$SCRIPT_DIR/render-nginx-http-only.sh"
$DC build
$DC up -d --wait postgres api worker dashboard nginx certbot

if [[ "$SKIP_TLS" != "true" ]]; then
  bash "$SCRIPT_DIR/init-letsencrypt.sh"
fi

if [[ "$RUN_SEED" == "true" ]]; then
  $DC --profile seed run --rm seed
fi

echo "Déploiement terminé."
