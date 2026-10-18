#!/bin/bash
set -euxo pipefail

export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y docker.io docker-compose-v2 git envsubst curl

systemctl enable docker
systemctl start docker
usermod -aG docker ubuntu

mkdir -p /opt/culturelive
chown ubuntu:ubuntu /opt/culturelive

cat >/opt/culturelive/bootstrap.env <<EOF
DOMAIN_NAME=${domain_name}
LETSENCRYPT_EMAIL=${letsencrypt_email}
EOF

# Le dépôt doit être copié ou cloné sur l'instance, puis :
#   cd /opt/culturelive/CultureLive/infrastructure && bash scripts/deploy-stack.sh
%{ if repo_clone_url != "" ~}
sudo -u ubuntu git clone ${repo_clone_url} /opt/culturelive/CultureLive || true
%{ endif ~}

cat >/etc/motd <<'MOTD'

CultureLive EC2 ready.
1) DNS A record -> this server IP
2) Copy .env to /opt/culturelive/CultureLive/.env (JWT_SECRET, POSTGRES_PASSWORD, ...)
3) cd /opt/culturelive/CultureLive/infrastructure && sudo -u ubuntu bash scripts/deploy-stack.sh

MOTD
