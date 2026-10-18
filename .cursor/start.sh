#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/application"

use_local_pg=1
if [[ -n "${DATABASE_URL:-}" ]] && [[ "$DATABASE_URL" != *"@localhost"* ]] && [[ "$DATABASE_URL" != *"@127.0.0.1"* ]]; then
  use_local_pg=0
fi

if [[ "$use_local_pg" == 1 ]]; then
  sudo pg_ctlcluster 16 main start 2>/dev/null || sudo service postgresql start
  until pg_isready -q; do sleep 1; done
  sudo -u postgres psql -v ON_ERROR_STOP=1 <<'SQL'
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'cultur_live') THEN
    CREATE ROLE cultur_live LOGIN PASSWORD 'cultur_live';
  END IF;
END $$;
SELECT 'CREATE DATABASE cultur_live OWNER cultur_live' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'cultur_live')\gexec
GRANT ALL PRIVILEGES ON DATABASE cultur_live TO cultur_live;
SQL
fi

if [[ ! -f "$ROOT/.env" ]]; then
  cat > "$ROOT/.env" <<EOF
DATABASE_URL=${DATABASE_URL:-postgresql+asyncpg://cultur_live:cultur_live@localhost:5432/cultur_live}
POSTGRES_USER=cultur_live
POSTGRES_PASSWORD=cultur_live
POSTGRES_DB=cultur_live
DASHBOARD_API_KEY=$(openssl rand -hex 24)
JWT_SECRET=$(openssl rand -hex 32)
TOKEN_ENCRYPTION_KEY=$(openssl rand -hex 24)
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=http://localhost:8000/auth/google/callback
PUBLIC_BASE_URL=http://localhost:8000
SYNC_INTERVAL_MINUTES=15
SYNC_LOOKBACK_DAYS=7
SYNC_LOOKAHEAD_DAYS=30
EOF
fi

set -a
# shellcheck source=/dev/null
source "$ROOT/.env"
set +a
export PYTHONPATH="$ROOT/application"

.venv/bin/python -m backend.db.migrate

TMUX="${TMUX:-tmux -f /exec-daemon/tmux.portal.conf}"
SESSION=culturelive_api
$TMUX has-session -t "=$SESSION" 2>/dev/null || $TMUX new-session -d -s "$SESSION" -c "$ROOT/application" -- bash -lc \
  "set -a && source '$ROOT/.env' && set +a && export PYTHONPATH='$ROOT/application' && exec .venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port 8000"
