#!/usr/bin/env bash
# Config nginx HTTP seule (nécessaire avant l'obtention du certificat).
set -euo pipefail
# shellcheck source=_common.sh
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

render_nginx nginx/default.http.conf.template
echo "nginx/conf.d/default.conf (HTTP) généré pour ${DOMAIN_NAME}"
