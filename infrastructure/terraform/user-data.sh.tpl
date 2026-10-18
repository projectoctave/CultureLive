#!/bin/bash
set -euxo pipefail

export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y docker.io docker-compose-v2 git curl

systemctl enable --now docker
usermod -aG docker ubuntu

mkdir -p /opt/culturelive
chown ubuntu:ubuntu /opt/culturelive

%{ if repo_clone_url != "" ~}
sudo -u ubuntu git clone ${repo_clone_url} /opt/culturelive/CultureLive || true
%{ endif ~}

cat >/etc/motd <<'MOTD'

CultureLive EC2 prête.
1) Créer l'enregistrement DNS A de ${domain_name} vers l'IP de ce serveur
2) Créer /opt/culturelive/CultureLive/.env (voir .env.example : JWT_SECRET, DASHBOARD_API_KEY,
   POSTGRES_PASSWORD, TOKEN_ENCRYPTION_KEY, DOMAIN_NAME=${domain_name}, LETSENCRYPT_EMAIL=${letsencrypt_email})
3) cd /opt/culturelive/CultureLive/infrastructure && bash scripts/deploy-stack.sh
   (RUN_SEED=true pour charger les données de démonstration)

MOTD
