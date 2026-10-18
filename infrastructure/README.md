# Infrastructure CultureLive

Stack **dockerisée** pour une instance **AWS EC2** : **PostgreSQL**, **API**, **dashboard Streamlit**, **nginx**, **Let's Encrypt**.

## Arborescence

| Chemin | Rôle |
|--------|------|
| `docker-compose.yml` | Orchestration des services |
| `docker/` | Dockerfiles API, dashboard, seed |
| `nginx/` | Config nginx (template HTTPS + script HTTP bootstrap) |
| `scripts/seed_demo_data.py` | Données fake 3×3 entreprises / sales |
| `scripts/deploy-stack.sh` | Déploiement one-go |
| `scripts/init-letsencrypt.sh` | Certificat + activation HTTPS |
| `terraform/` | EC2 + EIP + security group |

## Variables `.env` (racine projet)

En plus des variables existantes :

```env
DOMAIN_NAME=culturelive.example.com
LETSENCRYPT_EMAIL=admin@example.com
POSTGRES_USER=cultur_live
POSTGRES_PASSWORD=<secret>
JWT_SECRET=<secret-long>
TOKEN_ENCRYPTION_KEY=<secret>
```

## Déploiement local / EC2 (Docker)

```bash
cd infrastructure
cp ../.env.example ../.env   # compléter DOMAIN_NAME, JWT_SECRET, etc.
export DOMAIN_NAME=... LETSENCRYPT_EMAIL=...
bash scripts/deploy-stack.sh
```

Étapes exécutées :

1. Build images API + dashboard + seed  
2. PostgreSQL + services  
3. nginx HTTP (challenge ACME)  
4. Certificat Let's Encrypt  
5. nginx HTTPS (template `nginx/default.conf.template`)  
6. Seed demo (`RUN_SEED=false` pour désactiver)

## Seed manuel

```bash
cd infrastructure
docker compose --profile seed run --rm seed
```

Comptes créés (exemple) — voir sortie console du script :

- **Org admin** : `nova_admin` / `NovaAdmin!2026` (vue toute l'équipe Nova)  
- **Sales** : `nova.alice` / `NovaAlice!2026` (vue individuelle)

## Terraform (EC2)

```bash
cd infrastructure/terraform
cp terraform.tfvars.example terraform.tfvars
terraform init
terraform apply
```

Configurer le **DNS A** vers `public_ip`, copier le repo et le `.env` sur l'instance, puis lancer `deploy-stack.sh`.

## URLs

| Service | URL |
|---------|-----|
| Dashboard | `https://<DOMAIN>/` |
| API | `https://<DOMAIN>/api/` (ex. `/api/health`) |
