# CultureLive — Note de cadrage & spécification (v0.2)

**Projet** : CultureLive  
**Écosystème** : Projet Octave (GitHub)  
**Statut document** : Spécification de référence — première brique livrée  
**Version applicative** : 0.2.0  
**Stack** : Python 3.12+, FastAPI, PostgreSQL, Alembic, Google Calendar API, Streamlit, Docker, Terraform  
**Hébergement cible** : AWS (une instance EC2 exécutant la stack Docker ; PostgreSQL managé possible en production)

---

## 1. Contexte et objectifs

CultureLive est un **microservice** qui connecte l’agenda **Google Calendar** d’un utilisateur commercial, permet de **créer** et **lire** des réunions sur une période donnée, puis d’**analyser** ces réunions pour les **classifier** selon une **typologie sales** (référentiel paramétrable, enrichissement IA optionnel). Les résultats sont **persistés** dans **PostgreSQL** et **visualisés** via un **dashboard** dont les statistiques sont **segmentées par entreprise et par utilisateur**, sans exposer de données personnelles identifiables (PII).

### 1.1 Objectifs métier

- Donner une vision structurée du temps commercial passé en réunion (cold call, discovery, démo, etc.).
- Permettre un référentiel de typologie **custom** (évolution métier, verticals, langues).
- Préparer des agrégats anonymisés pour pilotage et tableaux de bord.

### 1.2 Périmètre (inclus)

| Brique | Description |
|--------|-------------|
| **B1 — Calendar** | OAuth Google, création et lecture d’événements sur une fenêtre temporelle |
| **B2 — Classification** | Classification des meetings récupérés + stockage PostgreSQL |
| **B3 — Dashboard** | Login par entreprise / par sales ; l’admin d’une entreprise voit toute son équipe, un sales ne voit que lui |
| **B4 — Qualité** | Tests fonctionnels (classification, DB, flux Google simulé, migrations, auth) + CI GitHub Actions ; tests Google live prêts mais non exécutés |
| **B5 — Déploiement** | `infrastructure/` : Docker (PostgreSQL, API, worker, dashboard, nginx, certbot), Terraform EC2, Let’s Encrypt |

### 1.3 Hors périmètre (explicite)

- Synchronisation temps réel (webhooks Google) — la synchronisation est périodique (worker).
- Multi-calendriers avancés, salles, ressources.
- SSO entreprise (SAML/OIDC) — OAuth Google utilisateur uniquement.
- Interface d’administration complète (CRUD utilisateurs UI).
- Haute disponibilité multi-AZ, autoscaling — cible infra v2.

---

## 2. Architecture logique

```
┌─────────────────┐     OAuth2      ┌──────────────────┐
│  Utilisateur    │◄──────────────►│ Google Calendar  │
│  (navigateur)   │                 │      API         │
└────────┬────────┘                 └────────▲─────────┘
         │                                   │
         │ HTTPS                             │ refresh token
         ▼                                   │
┌────────────────────────────────────────────────────────┐
│                    EC2 (CultureLive)                    │
│  ┌──────────────┐  ┌─────────────┐  ┌───────────────┐ │
│  │  backend/    │  │ integration/│  │  dashboard/   │ │
│  │  FastAPI     │──│ Google OAuth│  │  Streamlit    │ │
│  │  + worker    │  │ + Calendar  │  │  (stats API)  │ │
│  └──────┬───────┘  └─────────────┘  └───────▲───────┘ │
│         │                                    │         │
│         └──────────────┬─────────────────────┘         │
│                        ▼                               │
│                 PostgreSQL (RDS)                       │
└────────────────────────────────────────────────────────┘
         │ optionnel
         ▼
   OpenAI API (classification IA si clé configurée)
```

### 2.1 Découpage code (dépôt)

Le dépôt est séparé en deux blocs : le code applicatif (`application/`) et l’infrastructure (`infrastructure/`).

| Dossier | Rôle |
|---------|------|
| `application/` | Tout le code applicatif Python (`pyproject.toml`, `alembic.ini`, `docker-compose.dev.yml` pour la base locale) |
| `application/backend/` | API REST, règles métier, classifier, modèle de données, endpoints stats, worker |
| `application/backend/migrations/` | Migrations Alembic (schéma de la base) |
| `application/integration/` | Couche d’intégration Google (OAuth, client Calendar) |
| `application/dashboard/` | Application Streamlit consommant l’API stats (login entreprise / sales) |
| `application/referential/` | Référentiel typologie sales par défaut (JSON) |
| `application/tests/` | Tests fonctionnels (classification, DB, auth, flux Google simulé, migrations) et tests Google live |
| `infrastructure/` | Docker Compose, Dockerfiles, nginx, Let’s Encrypt, seed de démo, Terraform (**AWS EC2**) |

---

## 3. Exigences fonctionnelles

### 3.1 Authentification Google (B1)

| ID | Exigence | Critère d’acceptation |
|----|----------|------------------------|
| AUTH-01 | Démarrer le flux OAuth | `GET /auth/google` retourne une `authorization_url` valide |
| AUTH-02 | Callback OAuth | `GET /auth/google/callback` échange le code, stocke le refresh token chiffré |
| AUTH-03 | Tenancy | Création ou rattachement `organization` + `app_user` avec identifiants publics anonymisés |
| AUTH-04 | Réponse connexion | JSON incluant `user_id`, `user_ref`, `organization_ref` (pas d’email exposé côté dashboard) |

**Scopes Google** : `calendar.events`, `userinfo.email` (email utilisé uniquement en backend pour le mapping tenancy).

### 3.2 Gestion des réunions (B1)

| ID | Exigence | Critère d’acceptation |
|----|----------|------------------------|
| MTG-01 | Créer une réunion | `POST /meetings?user_id=` (clé admin) crée un événement dans le calendrier `primary` |
| MTG-02 | Lister sur période | `GET /meetings?user_id=&time_min=&time_max=` (clé admin) retourne les événements ordonnés, toutes pages Google parcourues |
| MTG-03 | Champs minimum | `summary`, `description`, `start`, `end`, identifiant Google `id` |

Corps création (`POST /meetings`) :

- `summary` (obligatoire), `description` (optionnel)
- `start`, `end` : ISO 8601
- `time_zone` : défaut `Europe/Paris`

### 3.3 Référentiel typologie sales (B2)

| ID | Exigence | Critère d’acceptation |
|----|----------|------------------------|
| REF-01 | Référentiel par défaut | Fichier `application/referential/sales-typology.json` chargé si aucun actif en base |
| REF-02 | Lecture | `GET /referential` (clé admin) retourne le référentiel actif |
| REF-03 | Mise à jour | `PUT /referential` (clé admin) remplace le référentiel actif ; les réunions déjà classées sont reclassées à la prochaine synchronisation |

**Catégories par défaut** : `cold_call`, `discovery_call`, `demo`, `negotiation`, `follow_up`, `customer_success`, `internal`, `other`.

Chaque catégorie comporte : `id`, `label`, `description` (utilisée par le classifier IA).

### 3.4 Classification et persistance (B2)

| ID | Exigence | Critère d’acceptation |
|----|----------|------------------------|
| CLS-01 | Sync classify | `POST /classify/sync` (clé admin) lit Calendar sur `[time_min, time_max]` et classifie |
| CLS-02 | Moteur | Heuristiques mots-clés ; si `OPENAI_API_KEY` présent, LLM avec repli heuristique |
| CLS-03 | Idempotence | Upsert par couple (`google_event_id`, `user_id`) |
| CLS-05 | Synchronisation incrémentale | Un événement inchangé (titre, description, référentiel) n’est pas reclassifié ; `force=true` reclassifie tout |
| CLS-06 | Isolation des erreurs | L’échec d’un utilisateur (token révoqué…) n’empêche pas la synchronisation des autres ; il est remonté dans `errors` |
| CLS-07 | Synchronisation périodique | Le worker synchronise tous les utilisateurs connectés toutes les `SYNC_INTERVAL_MINUTES` |
| CLS-04 | Traçabilité | Stocker `category_id`, `category_label`, `confidence`, `rationale`, horodatage |

### 3.5 Dashboard et statistiques (B3)

| ID | Exigence | Critère d’acceptation |
|----|----------|------------------------|
| DSH-01 | Authentification | `POST /auth/dashboard/login` (login / mot de passe, bcrypt) renvoie un JWT ; les endpoints stats acceptent ce jeton, ou la clé admin `X-API-Key` (accès global) |
| DSH-05 | Rôles | `org_admin` : voit tous les sales de son entreprise ; `sales_user` : voit uniquement sa propre activité (403 sur les données d’autrui) |
| DSH-02 | Agrégats | `GET /stats/overview` : volumes par `organization_ref`, `user_ref`, catégorie |
| DSH-03 | Liste filtrée | `GET /stats/meetings?organization_ref=&user_ref=` sans email ni nom réel |
| DSH-04 | UI | Streamlit : écran de connexion, graphiques barres / camembert, tableau filtrable selon le rôle |

**Règle d’anonymisation** :

- `organization_ref` : dérivé stable du domaine email (`org_<hash10>`).
- `user_ref` : dérivé stable org + email (`usr_<hash10>`).
- Le dashboard et l’API stats n’exposent **pas** l’email Google.

---

## 4. Modèle de données (PostgreSQL)

| Table | Description |
|-------|-------------|
| `organizations` | Tenant ; `public_ref` anonymisé |
| `app_users` | Utilisateur applicatif rattaché à une org ; `public_ref` anonymisé |
| `oauth_connections` | Refresh token Google **chiffré** (`TOKEN_ENCRYPTION_KEY`) |
| `dashboard_accounts` | Comptes de connexion au dashboard (rôle `org_admin` ou `sales_user`, mot de passe haché) |
| `sales_referentials` | Référentiels JSON versionnés ; un actif à la fois |
| `meeting_classifications` | Résultat de classification par événement et utilisateur |

Contrainte d’unicité : `(google_event_id, user_id)` sur `meeting_classifications`.

Le schéma est géré par **Alembic** (`application/backend/migrations/`) ; les migrations sont appliquées au démarrage du conteneur API (`python -m backend.db.migrate`). Un test vérifie que les modèles et les migrations restent alignés et que les migrations sont réversibles.

---

## 5. Spécification API (résumé)

| Méthode | Route | Auth | Description |
|---------|-------|------|-------------|
| GET | `/health` | — | Sonde de disponibilité (teste aussi la base) |
| GET | `/auth/google` | — | URL OAuth |
| GET | `/auth/google/callback` | — | Finalisation OAuth (`state` à usage unique, expire en 10 min) |
| POST | `/auth/dashboard/login` | — | Login dashboard, renvoie un JWT |
| POST | `/meetings` | clé admin | Création événement |
| GET | `/meetings` | clé admin | Liste sur période |
| GET | `/referential` | clé admin | Référentiel actif |
| PUT | `/referential` | clé admin | Nouveau référentiel actif |
| POST | `/classify/sync` | clé admin | Lecture Calendar + classification + DB (incrémental) |
| GET | `/stats/overview` | JWT ou clé admin | Agrégats anonymisés, limités au périmètre du rôle |
| GET | `/stats/meetings` | JWT ou clé admin | Liste des meetings classifiés, limitée au périmètre du rôle |

La **clé admin** est l’en-tête `X-API-Key` (valeur `DASHBOARD_API_KEY`).

Variables d’environnement : voir `.env.example`.

---

## 6. Exigences non fonctionnelles

### 6.1 Sécurité

- Secrets uniquement via variables d’environnement (jamais commités).
- Refresh tokens chiffrés en base (AES-GCM).
- Routes d’administration protégées par la clé admin ; dashboard protégé par login (JWT, mots de passe hachés bcrypt).
- Démarrage refusé si `JWT_SECRET` (32 caractères min.) ou `DASHBOARD_API_KEY` (12 caractères min.) sont absents.
- Les comptes du seed de démonstration ont des mots de passe publics : ne pas les charger en production (`RUN_SEED=false`, valeur par défaut).
- HTTPS obligatoire en production (nginx + certificat).

### 6.2 Infrastructure AWS (cible)

- **Compute** : une instance EC2 (type minimal recommandé `t3.small`, Ubuntu 24.04) exécutant la stack Docker, créée par Terraform (`infrastructure/terraform/`).
- **Services** : PostgreSQL, API, worker de synchronisation, dashboard, nginx, certbot — voir `infrastructure/docker-compose.yml`.
- **HTTPS** : Let’s Encrypt via certbot, renouvellement automatique, redirection 80 vers 443.
- **Base** : PostgreSQL en conteneur avec volume persistant ; un PostgreSQL managé (RDS) reste possible en changeant `DATABASE_URL`.
- **Réseau** : security group ouvrant 22 (à restreindre), 80 et 443.
- **Secrets** : fichier `.env` sur l’instance (jamais commité) ; AWS Secrets Manager ou SSM à envisager.

Détails opérationnels et état de vérification : `infrastructure/README.md`.

### 6.3 Observabilité

- Healthchecks Docker : API (`/health`, vérifie la base), worker (heartbeat), PostgreSQL.
- Logs : `docker compose logs -f api worker`.

---

## 7. Stratégie de tests

| Suite | Fichier | Objectif |
|-------|---------|----------|
| Classification | `application/tests/test_classification_functional.py` | Agenda sales fictif (`application/tests/fixtures/sales_agenda.py`) — 8 typologies |
| Pipeline DB | `application/tests/test_db_pipeline.py` | Classifier → insert PostgreSQL → cohérence agrégats |
| Auth dashboard | `application/tests/test_auth_dashboard.py` | Login, périmètre `org_admin` / `sales_user`, refus 403 / 401 |
| Flux Google simulé | `application/tests/test_google_flow_mocked.py` | OAuth, création, lecture paginée, classification, sync incrémentale, isolation des erreurs, worker, clé admin, stats — avec un faux Google Calendar |
| Migrations | `application/tests/test_migrations.py` | Schéma créé par Alembic, aligné avec les modèles, réversible |
| Google live | `application/tests/test_google_integration.py` | Création de meetings réels, lecture, `classify/sync`, stats (marqueur `google_live`) — **non exécuté à ce jour** : aucun compte Google de test n’a pu être créé |

**Prérequis Google live** : OAuth configuré, API démarrée, `DASHBOARD_API_KEY` et `CULTURELIVE_TEST_USER_ID` (UUID interne renvoyé par le callback).

La CI (`.github/workflows/ci.yml`) exécute le lint, les tests avec PostgreSQL, shellcheck, `terraform validate` et le build des images Docker.

```bash
cd application
export PYTHONPATH=$PWD
export DATABASE_URL=postgresql+asyncpg://cultur_live:cultur_live@localhost:5432/cultur_live
pytest -m "not google_live" -v          # suite complète hors Google réel
pytest tests/test_google_integration.py -v -m google_live
```

---

## 8. Flux métier de référence

1. **Onboarding** : l’utilisateur ouvre `authorization_url` → callback → récupération `user_id`.
2. **Alimentation** : création manuelle ou réunions existantes dans Google Calendar.
3. **Analyse** : le worker synchronise périodiquement (ou appel manuel de `POST /classify/sync`) ; seuls les événements nouveaux ou modifiés sont classifiés.
4. **Pilotage** : connexion au dashboard ; l’admin d’une entreprise voit son équipe, un sales voit sa propre activité.

```mermaid
sequenceDiagram
    participant U as Utilisateur
    participant API as CultureLive API
    participant G as Google Calendar
    participant DB as PostgreSQL
    participant D as Dashboard

    U->>API: GET /auth/google
    API-->>U: authorization_url
    U->>G: Consentement OAuth
    G->>API: callback + code
    API->>DB: user + token chiffré
    U->>API: POST /classify/sync
    API->>G: events.list
    API->>API: classify (heuristique / IA)
    API->>DB: meeting_classifications
    D->>API: POST /auth/dashboard/login puis GET /stats/* (JWT)
    API->>DB: agrégats anonymisés
    API-->>D: JSON stats
```

---

## 9. Roadmap indicative

| Version | Thème |
|---------|--------|
| v0.3 | Webhooks Google (temps réel) |
| v0.4 | Référentiels multiples par organisation |
| v0.5 | Export BI (CSV, API), correction manuelle de la catégorie, métriques OTel |
| v1.0 | Durcissement prod (sauvegardes automatiques, RDS Multi-AZ, rotation des secrets, audit) |

---

## 10. Annexes — exploitation

### 10.1 Développement local

```bash
cd CultureLive
cp .env.example .env          # renseigner DASHBOARD_API_KEY, JWT_SECRET, TOKEN_ENCRYPTION_KEY, GOOGLE_*
cd application
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
docker compose -f docker-compose.dev.yml up -d postgres   # PostgreSQL local (ou une instance existante)
export PYTHONPATH=$PWD
python -m backend.db.migrate  # applique les migrations
uvicorn backend.main:app --reload --port 8000
streamlit run dashboard/app.py    # terminal séparé
python -m backend.worker          # optionnel : synchronisation périodique
python ../infrastructure/scripts/seed_demo_data.py   # optionnel : données de démonstration
```

### 10.2 Déploiement (Docker, EC2, HTTPS)

Voir `infrastructure/README.md` : `bash infrastructure/scripts/deploy-stack.sh` après avoir renseigné le `.env`.

### 10.3 Dépôt GitHub

Repository public cible : **CultureLive**, associé au programme **Projet Octave** (`Lancs0022/Projet-Octave`).

---

## 11. Glossaire

| Terme | Définition |
|-------|------------|
| **ND** | Note de cadrage — présent document |
| **Meeting** | Événement Google Calendar |
| **Référentiel** | Liste des catégories sales et leurs définitions |
| **Ref anonymisée** | `organization_ref` / `user_ref` — identifiants opaques pour stats |

---

*Document maintenu à la racine du dépôt. Toute évolution fonctionnelle majeure doit mettre à jour ce README et incrémenter la version indiquée en en-tête.*
