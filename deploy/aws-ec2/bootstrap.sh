#!/usr/bin/env bash
set -euo pipefail

APP_DIR=/opt/culturelive
PY=python3.11

sudo mkdir -p "$APP_DIR"
sudo chown "$USER":"$USER" "$APP_DIR"

if ! command -v "$PY" >/dev/null 2>&1; then
  sudo apt-get update -qq
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y python3.11 python3.11-venv nginx
fi

"$PY" -m venv "$APP_DIR/.venv"
source "$APP_DIR/.venv/bin/activate"
pip install -U pip
pip install -e "$APP_DIR/[dev]"

sudo cp "$APP_DIR/deploy/aws-ec2/systemd/culturelive-api.service" /etc/systemd/system/
sudo cp "$APP_DIR/deploy/aws-ec2/systemd/culturelive-dashboard.service" /etc/systemd/system/
sudo cp "$APP_DIR/deploy/aws-ec2/nginx/culturelive.conf" /etc/nginx/sites-available/culturelive
sudo ln -sf /etc/nginx/sites-available/culturelive /etc/nginx/sites-enabled/culturelive
sudo systemctl daemon-reload

echo "Bootstrap OK — déposer le code dans $APP_DIR et configurer .env"
