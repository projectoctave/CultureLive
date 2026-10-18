# CultureLive — Note de cadrage & spécification (v0.1)

**Projet** : CultureLive  
**Écosystème** : Projet Octave (GitHub)  
**Statut document** : Spécification de référence — première brique livrée  
**Version applicative** : 0.1.0  
**Stack** : Python 3.12+, FastAPI, PostgreSQL, Google Calendar API, Streamlit  
**Hébergement cible** : AWS (instance EC2 Python, PostgreSQL managé recommandé en production)

---

## 1. Contexte et objectifs

CultureLive est un **microservice** qui connecte l’agenda **Google Calendar** d’un utilisateur commercial, permet de **créer** et **lire** des réunions sur une période donnée, puis d’**analyser** ces réunions pour les **classifier** selon une **typologie sales** (référentiel paramétrable, enrichissement IA optionnel). Les résultats sont **persistés** dans **PostgreSQL** et **visualisés** via un **dashboard** dont les statistiques sont **segmentées par entreprise et par utilisateur**, sans exposer de données personnelles identifiables (PII).

### 1.1 Objectifs métier

- Donner une vision structurée du temps commercial passé en réunion (cold call, discovery, démo, etc.).
- Permettre un référentiel de typologie **custom** (évolution métier, verticals, langues).
- Préparer des agrégats anonymisés pour pilotage et tableaux de bord.

### 1.2 Périmètre v0.1 (inclus)

| Brique | Description |
|--------|-------------|
| **B1 — Calendar** | OAuth Google, création et lecture d’événements sur une fenêtre temporelle |
| **B2 — Classification** | Classification des meetings récupérés + stockage PostgreSQL |
| **B3 — Dashboard** | Visualisation des stats et listes filtrées (clé API) |
| **B4 — Qualité** | Tests fonctionnels classification, pipeline DB, intégration Google (live) |
| **B5 — Déploiement** | Artefacts bootstrap EC2 (systemd, nginx) |

### 1.3 Hors périmètre v0.1 (explicite)

- Synchronisation temps réel (webhooks Google) — prévu ultérieurement.
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
│  │  classifier  │  │ + Calendar  │  │  (stats API)  │ │
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

| Dossier | Rôle |
|---------|------|
| `backend/` | API REST, règles métier, classifier, modèle de données, endpoints stats |
| `integration/` | Couche d’intégration Google (OAuth, client Calendar) |
| `dashboard/` | Application Streamlit consommant l’API stats (authentification par clé) |
| `tests/` | Batteries fonctionnelles (classification, DB, Google live) |
| `referential/` | Référentiel typologie sales par défaut (JSON) |
| `deploy/` | Scripts et unités systemd / nginx pour **AWS EC2** |

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
| MTG-01 | Créer une réunion | `POST /meetings?user_id=` crée un événement dans le calendrier `primary` |
| MTG-02 | Lister sur période | `GET /meetings?user_id=&time_min=&time_max=` retourne les événements ordonnés |
| MTG-03 | Champs minimum | `summary`, `description`, `start`, `end`, identifiant Google `id` |

Corps création (`POST /meetings`) :

- `summary` (obligatoire), `description` (optionnel)
- `start`, `end` : ISO 8601
- `time_zone` : défaut `Europe/Paris`

### 3.3 Référentiel typologie sales (B2)

| ID | Exigence | Critère d’acceptation |
|----|----------|------------------------|
| REF-01 | Référentiel par défaut | Fichier `referential/sales-typology.json` chargé si aucun actif en base |
| REF-02 | Lecture | `GET /referential` retourne le référentiel actif |
| REF-03 | Mise à jour | `PUT /referential` remplace le référentiel actif (versionning simple en base) |

**Catégories par défaut** : `cold_call`, `discovery_call`, `demo`, `negotiation`, `follow_up`, `customer_success`, `internal`, `other`.

Chaque catégorie comporte : `id`, `label`, `description` (utilisée par le classifier IA).

### 3.4 Classification et persistance (B2)

| ID | Exigence | Critère d’acceptation |
|----|----------|------------------------|
| CLS-01 | Sync classify | `POST /classify/sync` lit Calendar sur `[time_min, time_max]` et classifie |
| CLS-02 | Moteur | Heuristiques mots-clés ; si `OPENAI_API_KEY` présent, LLM avec repli heuristique |
| CLS-03 | Idempotence | Upsert par couple (`google_event_id`, `user_id`) |
| CLS-04 | Traçabilité | Stocker `category_id`, `category_label`, `confidence`, `rationale`, horodatage |

### 3.5 Dashboard et statistiques (B3)

| ID | Exigence | Critère d’acceptation |
|----|----------|------------------------|
| DSH-01 | Authentification | Endpoints stats protégés par en-tête `X-API-Key` = `DASHBOARD_API_KEY` |
| DSH-02 | Agrégats | `GET /stats/overview` : volumes par `organization_ref`, `user_ref`, catégorie |
| DSH-03 | Liste filtrée | `GET /stats/meetings?organization_ref=&user_ref=` sans email ni nom réel |
| DSH-04 | UI | Streamlit : graphiques barres / camembert + tableau filtrable |

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
| `sales_referentials` | Référentiels JSON versionnés ; un actif à la fois |
| `meeting_classifications` | Résultat de classification par événement et utilisateur |

Contrainte d’unicité : `(google_event_id, user_id)` sur `meeting_classifications`.

---

## 5. Spécification API (résumé)

| Méthode | Route | Auth | Description |
|---------|-------|------|-------------|
| GET | `/health` | — | Sonde disponibilité |
| GET | `/auth/google` | — | URL OAuth |
| GET | `/auth/google/callback` | — | Finalisation OAuth |
| POST | `/meetings` | `user_id` query | Création événement |
| GET | `/meetings` | `user_id` query | Liste sur période |
| GET | `/referential` | — | Référentiel actif |
| PUT | `/referential` | — | Nouveau référentiel actif |
| POST | `/classify/sync` | — | Lecture Calendar + classify + DB |
| GET | `/stats/overview` | `X-API-Key` | Agrégats anonymisés |
| GET | `/stats/meetings` | `X-API-Key` | Liste meetings classifiés |

Variables d’environnement : voir `.env.example`.

---

## 6. Exigences non fonctionnelles

### 6.1 Sécurité

- Secrets uniquement via variables d’environnement (jamais commités).
- Refresh tokens chiffrés en base (AES-GCM).
- Dashboard et stats : clé API dédiée.
- HTTPS obligatoire en production (nginx + certificat).

### 6.2 Infrastructure AWS (cible)

- **Compute** : EC2 (type minimal recommandé `t3.small`), Amazon Linux 2023 ou Ubuntu 22.04.
- **Base** : PostgreSQL (RDS recommandé) ; `DATABASE_URL` async (`postgresql+asyncpg://…`).
- **Réseau** : SG restrictif ; egress vers Google APIs et OpenAI si IA activée.
- **Secrets** : AWS Secrets Manager ou SSM Parameter Store.
- **Process** : `systemd` pour API (port 8000) et dashboard (8501 derrière nginx).

Détails opérationnels : `deploy/aws-ec2/README.md`.

### 6.3 Observabilité

- Healthcheck : `/health`.
- Logs applicatifs : journal systemd (`culturelive-api`, `culturelive-dashboard`).

---

## 7. Stratégie de tests

| Suite | Fichier | Objectif |
|-------|---------|----------|
| Classification | `tests/test_classification_functional.py` | Agenda sales fictif (`tests/fixtures/sales_agenda.py`) — 8 typologies |
| Pipeline DB | `tests/test_db_pipeline.py` | Classifier → insert PostgreSQL → cohérence agrégats |
| Google live | `tests/test_google_integration.py` | Création meetings réels, lecture, `classify/sync`, stats (marqueur `google_live`) |

**Prérequis Google live** : OAuth configuré, `CULTURELIVE_TEST_USER_ID` = UUID interne après callback.

```bash
export PYTHONPATH=$PWD
export DATABASE_URL=postgresql+asyncpg://cultur_live:cultur_live@localhost:5432/cultur_live
pytest tests/test_classification_functional.py tests/test_db_pipeline.py -v
pytest tests/test_google_integration.py -v -m google_live
```

---

## 8. Flux métier de référence

1. **Onboarding** : l’utilisateur ouvre `authorization_url` → callback → récupération `user_id`.
2. **Alimentation** : création manuelle ou réunions existantes dans Google Calendar.
3. **Analyse** : appel `POST /classify/sync` sur la période d’intérêt.
4. **Pilotage** : consultation dashboard (volumes par org / user / typologie).

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
    D->>API: GET /stats/* (X-API-Key)
    API->>DB: agrégats anonymisés
    API-->>D: JSON stats
```

---

## 9. Roadmap indicative (post v0.1)

| Version | Thème |
|---------|--------|
| v0.2 | Webhooks Google, sync incrémentale |
| v0.3 | Référentiels multiples par organisation |
| v0.4 | Export BI (CSV, API), métriques OTel |
| v1.0 | Durcissement prod (RDS Multi-AZ, rotation secrets, audit) |

---

## 10. Annexes — exploitation locale

### 10.1 Installation

```bash
cd CultureLive
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
# Renseigner GOOGLE_*, TOKEN_ENCRYPTION_KEY, DASHBOARD_API_KEY
export PYTHONPATH=$PWD
uvicorn backend.main:app --reload --port 8000
# Terminal séparé
streamlit run dashboard/app.py
```

### 10.2 Docker Compose (PostgreSQL local)

```bash
docker compose up -d postgres
```

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
