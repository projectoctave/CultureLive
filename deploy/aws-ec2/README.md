# Déploiement CultureLive sur AWS EC2 (Python)

Cible: une instance **Amazon Linux 2023** ou **Ubuntu 22.04**, type **t3.small** minimum (API + dashboard + worker léger).

## Prérequis AWS

- VPC avec sous-réseau public ou privé + NAT (accès Google APIs)
- Groupe de sécurité: `22` (SSH restreint), `80`/`443` (nginx), `8501` optionnel si dashboard exposé via nginx uniquement
- RDS PostgreSQL recommandé en prod (remplacer `DATABASE_URL` locale)
- Secrets Manager ou SSM Parameter Store pour `GOOGLE_*`, `TOKEN_ENCRYPTION_KEY`, `DASHBOARD_API_KEY`

## Bootstrap instance

```bash
sudo bash deploy/aws-ec2/bootstrap.sh
```

Copier `.env` sur l'instance (`/opt/culturelive/.env`), puis:

```bash
sudo systemctl enable --now culturelive-api culturelive-dashboard nginx
```

## DNS / TLS

- Pointer un enregistrement A vers l'elastic IP
- Mettre à jour `PUBLIC_BASE_URL` et `GOOGLE_REDIRECT_URI` (`https://votre-domaine/auth/google/callback`)
- Certbot: `sudo certbot --nginx -d votre-domaine`

## Observabilité

- Logs: `journalctl -u culturelive-api -f`
- Health: `GET /health`
