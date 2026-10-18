#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

sudo DEBIAN_FRONTEND=noninteractive apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
  postgresql postgresql-client python3.12-venv openssl

cd application
python3 -m venv .venv
.venv/bin/pip install -q -e ".[dev]"
