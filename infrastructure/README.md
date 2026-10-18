# Infrastructure CultureLive

Stack **dockerisée** pour une instance **AWS EC2** : **PostgreSQL**, **API**, **worker de synchronisation**, **dashboard Streamlit**, **nginx**, **Let's Encrypt (certbot)**.

## Arborescence

| Chemin | Rôle |
|--------|------|
| `docker-compose.yml` | Orchestration des services |
| `docker/` | Dockerfiles API/worker, dashboard, seed |
| `nginx/` | Templates nginx : HTTP (bootstrap ACME) et HTTPS (redirection 80 -> 443) |
| `scripts/deploy-stack.sh` | Déploiement one-go |
| `scripts/init-letsencrypt.sh` | Obtention du certificat + bascule HTTPS |
| `scripts/seed_demo_data.py` | Données fake : 3 entreprises x 3 sales |
| `terraform/` | EC2 (Ubuntu 24.04) + IP élastique + security group |

## Services

| Service | Rôle |
|---------|------|
| `postgres` | PostgreSQL 16, volume `pgdata` |
| `api` | FastAPI ; applique les migrations Alembic au démarrage ; healthcheck `/health` (teste aussi la base) |
| `worker` | Synchronise toutes les `SYNC_INTERVAL_MINUTES` les agendas Google connectés (incrémental) ; healthcheck par heartbeat |
| `dashboard` | Streamlit (login entreprise / sales) |
| `nginx` | Reverse proxy `/` -> dashboard, `/api/` -> API ; recharge les certificats toutes les 6 h |
| `certbot` | Renouvellement automatique du certificat |

## Fichier `.env` (racine du projet)

Copier `.env.example` vers `.env` et renseigner au minimum :

```env
DOMAIN_NAME=culturelive.example.com
LETSENCRYPT_EMAIL=admin@example.com
POSTGRES_PASSWORD=<secret>
JWT_SECRET=<32+ caractères>          # openssl rand -hex 32
DASHBOARD_API_KEY=<12+ caractères>   # openssl rand -hex 24
TOKEN_ENCRYPTION_KEY=<16+ caractères>
```

`JWT_SECRET` et `DASHBOARD_API_KEY` sont **obligatoires** : le compose et l'API refusent de démarrer sans eux.

## Déploiement

```bash
cd infrastructure
bash scripts/deploy-stack.sh
```

Étapes : rendu nginx HTTP, build, démarrage de la stack (`up --wait`), certificat Let's Encrypt, bascule nginx en HTTPS.

Options (variables d'environnement) :

| Variable | Effet |
|----------|-------|
| `RUN_SEED=true` | Charge aussi les données de démonstration. **Désactivé par défaut** : les comptes de démo ont des mots de passe publics. |
| `SKIP_TLS=true` | Reste en HTTP (essai local sans DNS) |
| `LETSENCRYPT_STAGING=true` | Certificat de test (sans limites de débit) |
| `ENV_FILE=/chemin/.env` | Utilise un autre fichier d'environnement |

Prérequis pour le certificat : l'enregistrement DNS A de `DOMAIN_NAME` pointe vers le serveur, les ports 80 et 443 sont ouverts.

> Utiliser les scripts plutôt que `docker compose up` directement : ils chargent le `.env` et génèrent la config nginx
> (`nginx/conf.d/default.conf`, non versionnée). En direct : `docker compose --env-file ../.env ...`.

## Données de démonstration

```bash
cd infrastructure
docker compose --env-file ../.env --profile seed run --rm seed
```

Le script affiche les comptes (login / mot de passe) : par exemple `nova_admin` voit toute l'équipe Nova, `nova.alice` ne voit que sa propre activité.

## Terraform (EC2)

```bash
cd infrastructure/terraform
cp terraform.tfvars.example terraform.tfvars   # key_name, domain_name, letsencrypt_email, repo_clone_url
terraform init
terraform apply
```

1. Créer l'enregistrement DNS A vers `public_ip`.
2. Se connecter en SSH (`ssh_hint` en sortie) : le dépôt est cloné dans `/opt/culturelive/CultureLive`.
3. Créer le `.env`, puis lancer `scripts/deploy-stack.sh`.

## Ce qui est vérifié, et ce qui ne l'est pas

Vérifié (exécuté, avec Docker, dans l'environnement de développement) :

- build des images, migrations au démarrage, `up --wait`, healthchecks (API, worker, postgres) ;
- parcours complet via nginx : `/api/health`, 401 sans clé, login org admin / sales, stats scopées, dashboard et websocket Streamlit ;
- nginx en HTTPS avec un certificat auto-signé : 443, redirection 301 depuis le 80, challenge ACME servi sur le 80, HSTS ;
- `terraform fmt`, `validate`, rendu du `user-data` ; `shellcheck` ; `docker compose config`.

Non vérifié :

- **l'émission réelle d'un certificat Let's Encrypt** (exige un vrai domaine) : la commande certbot est exécutée jusqu'au serveur de staging, qui n'a refusé que l'email factice utilisé pour le test ;
- `terraform apply` sur un vrai compte AWS ;
- le flux Google avec un vrai compte (voir `application/tests/test_google_flow_mocked.py` pour la couverture avec Google simulé).

## URLs

| Service | URL |
|---------|-----|
| Dashboard | `https://<DOMAIN>/` |
| API | `https://<DOMAIN>/api/` (ex. `/api/health`) |
