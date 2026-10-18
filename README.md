# CultureLive

Microservice **Python** (Projet Octave) : connexion **Google Calendar**, création / lecture de meetings, **classification sales** (référentiel custom + IA optionnelle), persistance **PostgreSQL**, **dashboard** anonymisé par entreprise / utilisateur.

## Structure

| Dossier | Rôle |
|---------|------|
| `backend/` | API FastAPI, classifier, modèles DB |
| `integration/` | OAuth & client Google Calendar |
| `dashboard/` | Streamlit (stats via clé API) |
| `tests/` | Tests fonctionnels classification, pipeline DB, intégration Google |
| `deploy/` | Bootstrap **AWS EC2** (systemd + nginx) |
| `referential/` | Typologie sales par défaut |

## Démarrage local

```bash
cd CultureLive
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
# éditer .env (Google, TOKEN_ENCRYPTION_KEY, DASHBOARD_API_KEY)

export PYTHONPATH=$PWD
uvicorn backend.main:app --reload --port 8000
# autre terminal
streamlit run dashboard/app.py
```

OAuth : `GET http://localhost:8000/auth/google` → ouvrir `authorization_url` → noter `user_id` interne après callback (voir réponse + table `app_users`).

## Tests

```bash
export PYTHONPATH=$PWD
export DATABASE_URL=postgresql+asyncpg://cultur_live:cultur_live@localhost:5432/cultur_live
pytest tests/test_classification_functional.py -v
pytest tests/test_db_pipeline.py -v
# Google live (après OAuth + CULTURELIVE_TEST_USER_ID=<uuid app_users.id>)
pytest tests/test_google_integration.py -v -m google_live
```

## AWS

Voir `deploy/aws-ec2/README.md`.
