"""Flux Google complet avec Google simulé : OAuth -> créer -> lire -> classifier -> stocker -> stats.

Le vrai réseau Google n'est pas touché : `googleapiclient.discovery.build` et l'échange de code OAuth
sont remplacés. Tout le reste (API, chiffrement des tokens, classifier, PostgreSQL, stats) est réel.
"""

import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from backend.config import get_settings
from backend.crypto import decrypt_text
from backend.db.models import AppUser, MeetingClassification, OAuthConnection, Organization
from backend.db.session import get_session_factory
from backend.main import app
from backend.services.sync import sync_users
from backend.worker import run_once
from tests.fakes.google import FakeCalendarStore, fake_build
from tests.fixtures.sales_agenda import SALES_AGENDA

pytestmark = [pytest.mark.db_live, pytest.mark.usefixtures("migrated_db")]


@pytest.fixture
def google_env(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "fake-client-id.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "fake-client-secret")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    get_settings.cache_clear()
    yield get_settings()
    get_settings.cache_clear()


@pytest.fixture
def calendar(monkeypatch):
    store = FakeCalendarStore(page_size=3)
    monkeypatch.setattr("integration.google_calendar.build", fake_build(store))
    return store


@pytest.fixture
def connect_as(monkeypatch):
    """Simule le retour Google du callback OAuth pour l'email donné."""

    def _connect(email: str):
        monkeypatch.setattr("backend.main.exchange_code", lambda settings, code: ("refresh-token-xyz", email))

    return _connect


@pytest.fixture
async def client(google_env):
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers={"X-API-Key": google_env.dashboard_api_key}
    ) as c:
        yield c


@pytest.fixture
async def cleanup_orgs():
    created: list[str] = []
    yield created
    async with get_session_factory()() as session:
        await session.execute(delete(Organization).where(Organization.public_ref.in_(created)))
        await session.commit()


async def _connect_via_oauth(client, cleanup_orgs) -> dict:
    start = await client.get("/auth/google")
    assert start.status_code == 200
    url = start.json()["authorization_url"]
    query = parse_qs(urlparse(url).query)
    assert urlparse(url).netloc == "accounts.google.com"
    assert query["client_id"] == ["fake-client-id.apps.googleusercontent.com"]
    assert query["access_type"] == ["offline"]

    callback = await client.get("/auth/google/callback", params={"code": "auth-code", "state": query["state"][0]})
    assert callback.status_code == 200, callback.text
    data = callback.json()
    cleanup_orgs.append(data["organization_ref"])
    return {**data, "state": query["state"][0]}


async def test_full_google_flow(client, calendar, connect_as, cleanup_orgs, google_env):
    suffix = uuid.uuid4().hex[:8]
    email = f"alice.{suffix}@acme-{suffix}.test"
    connect_as(email)

    # 1. OAuth : le callback crée tenant + utilisateur anonymisés et stocke le token chiffré
    connected = await _connect_via_oauth(client, cleanup_orgs)
    assert connected["user_ref"].startswith("usr_") and connected["organization_ref"].startswith("org_")
    assert email not in str(connected)
    user_id = connected["user_id"]

    async with get_session_factory()() as session:
        conn = (
            await session.execute(select(OAuthConnection).where(OAuthConnection.user_id == uuid.UUID(user_id)))
        ).scalar_one()
        assert "refresh-token-xyz" not in conn.encrypted_refresh_token
        assert decrypt_text(conn.encrypted_refresh_token, google_env.token_encryption_key) == "refresh-token-xyz"

    # le state OAuth est à usage unique
    replay = await client.get("/auth/google/callback", params={"code": "auth-code", "state": connected["state"]})
    assert replay.status_code == 400

    # 2. Création de l'agenda sales dans (faux) Google
    tomorrow = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) + timedelta(days=1)
    for i, fixture in enumerate(SALES_AGENDA):
        start = tomorrow + timedelta(hours=i)
        created = await client.post(
            "/meetings",
            params={"user_id": user_id},
            json={
                "summary": fixture.title,
                "description": fixture.description,
                "start": start.isoformat(),
                "end": (start + timedelta(minutes=45)).isoformat(),
            },
        )
        assert created.status_code == 200, created.text
        assert created.json()["id"].startswith("fake_evt_")
    assert len(calendar.events) == len(SALES_AGENDA)

    # 3. Lecture sur une période (traverse la pagination : 8 événements, pages de 3)
    window = {
        "time_min": (tomorrow - timedelta(hours=1)).isoformat(),
        "time_max": (tomorrow + timedelta(days=1)).isoformat(),
    }
    listed = await client.get("/meetings", params={"user_id": user_id, **window})
    assert listed.status_code == 200
    assert listed.json()["count"] == len(SALES_AGENDA)
    assert calendar.list_calls >= 3

    narrow = await client.get(
        "/meetings",
        params={
            "user_id": user_id,
            "time_min": (tomorrow - timedelta(hours=1)).isoformat(),
            "time_max": (tomorrow + timedelta(hours=1, minutes=30)).isoformat(),
        },
    )
    assert narrow.json()["count"] == 2

    # 4. Classification + stockage : chaque typologie attendue est retrouvée en base
    synced = await client.post("/classify/sync", json={**window, "user_id": user_id})
    assert synced.status_code == 200, synced.text
    assert synced.json() == {
        "users": 1,
        "fetched": len(SALES_AGENDA),
        "classified": len(SALES_AGENDA),
        "skipped": 0,
        "errors": [],
    }

    expected_by_title = {f.title: f.expected_category for f in SALES_AGENDA}
    async with get_session_factory()() as session:
        rows = (
            (
                await session.execute(
                    select(MeetingClassification).where(MeetingClassification.user_id == uuid.UUID(user_id))
                )
            )
            .scalars()
            .all()
        )
        assert {r.title: r.category_id for r in rows} == expected_by_title

    # 5. Sync incrémentale : rien n'est reclassifié si rien n'a changé
    again = await client.post("/classify/sync", json={**window, "user_id": user_id})
    assert (again.json()["classified"], again.json()["skipped"]) == (0, len(SALES_AGENDA))

    # 6. Un événement modifié dans Google est reclassifié, les autres sont ignorés
    calendar.find("Point café")["summary"] = "Cold call — liste outbound relancée"
    changed = await client.post("/classify/sync", json={**window, "user_id": user_id})
    assert (changed.json()["classified"], changed.json()["skipped"]) == (1, len(SALES_AGENDA) - 1)
    async with get_session_factory()() as session:
        row = (
            await session.execute(
                select(MeetingClassification).where(
                    MeetingClassification.title.like("Cold call — liste outbound relancée%"),
                    MeetingClassification.user_id == uuid.UUID(user_id),
                )
            )
        ).scalar_one()
        assert row.category_id == "cold_call"

    forced = await client.post("/classify/sync", json={**window, "user_id": user_id, "force": True})
    assert forced.json()["classified"] == len(SALES_AGENDA)

    # 7. Stats : anonymisées, cohérentes avec la base
    overview = await client.get("/stats/overview")
    assert overview.status_code == 200
    by_user = {u["user_ref"]: u["meetings"] for u in overview.json()["by_user"]}
    assert by_user[connected["user_ref"]] == len(SALES_AGENDA)
    assert email not in overview.text

    meetings = await client.get("/stats/meetings", params={"user_ref": connected["user_ref"]})
    assert len(meetings.json()) == len(SALES_AGENDA)


async def test_admin_routes_require_api_key(google_env):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as anonymous:
        user_id = str(uuid.uuid4())
        window = {"time_min": "2026-01-01T00:00:00+00:00", "time_max": "2026-12-31T00:00:00+00:00"}
        checks = [
            await anonymous.get("/meetings", params={"user_id": user_id, **window}),
            await anonymous.post(
                "/meetings", params={"user_id": user_id}, json={"summary": "x", "start": "a", "end": "b"}
            ),
            await anonymous.post("/classify/sync", json=window),
            await anonymous.get("/referential"),
            await anonymous.put(
                "/referential",
                json={"version": "1", "name": "x", "categories": [{"id": "a", "label": "a", "description": "a"}]},
            ),
            await anonymous.get("/stats/overview"),
        ]
        assert [r.status_code for r in checks] == [401] * len(checks)

        wrong = await anonymous.get("/referential", headers={"X-API-Key": "wrong-key-wrong-key"})
        assert wrong.status_code == 401
        assert (await anonymous.get("/health")).status_code == 200


async def test_sync_isolates_failing_user(calendar, google_env, cleanup_orgs):
    from backend.crypto import encrypt_text

    suffix = uuid.uuid4().hex[:8]
    factory = get_session_factory()
    async with factory() as session:
        org = Organization(public_ref=f"org_iso_{suffix}")
        session.add(org)
        await session.flush()
        good = AppUser(organization_id=org.id, public_ref=f"usr_good_{suffix}")
        bad = AppUser(organization_id=org.id, public_ref=f"usr_bad_{suffix}")
        session.add_all([good, bad])
        await session.flush()
        session.add(OAuthConnection(user_id=bad.id, encrypted_refresh_token="not-a-valid-ciphertext"))
        session.add(
            OAuthConnection(
                user_id=good.id, encrypted_refresh_token=encrypt_text("tok", google_env.token_encryption_key)
            )
        )
        await session.commit()
        cleanup_orgs.append(org.public_ref)
        good_id, bad_id = good.id, bad.id

    start = datetime.now(timezone.utc) + timedelta(days=1)
    calendar.add("Discovery call Isolation", start.isoformat(), (start + timedelta(minutes=30)).isoformat())

    async with factory() as session:
        result = await sync_users(
            session,
            google_env,
            (start - timedelta(hours=1)).isoformat(),
            (start + timedelta(hours=1)).isoformat(),
            user_ids=[bad_id, good_id],
        )
    assert result.classified == 1
    assert len(result.errors) == 1 and f"usr_bad_{suffix}" in result.errors[0]


async def test_worker_run_once_syncs_connected_users(calendar, google_env, cleanup_orgs, connect_as, client):
    suffix = uuid.uuid4().hex[:8]
    connect_as(f"bob.{suffix}@worker-{suffix}.test")
    connected = await _connect_via_oauth(client, cleanup_orgs)

    soon = datetime.now(timezone.utc) + timedelta(days=2)
    calendar.add("Démo CultureLive worker", soon.isoformat(), (soon + timedelta(minutes=45)).isoformat())

    result = await run_once(google_env)
    assert result.errors == []
    assert result.classified >= 1

    async with get_session_factory()() as session:
        row = (
            (
                await session.execute(
                    select(MeetingClassification).where(
                        MeetingClassification.user_id == uuid.UUID(connected["user_id"])
                    )
                )
            )
            .scalars()
            .all()
        )
        assert [r.category_id for r in row] == ["demo"]
