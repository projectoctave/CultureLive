"""Auth dashboard — scope org admin vs sales user."""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from backend.config import get_settings
from backend.db.models import AppUser, DashboardAccount, MeetingClassification, Organization
from backend.db.session import get_session_factory, init_db
from backend.main import app
from backend.services.auth import DashboardRole, hash_password

pytestmark = pytest.mark.db_live


@pytest.fixture
async def auth_fixture():
    await init_db()
    factory = get_session_factory()
    suffix = uuid.uuid4().hex[:6]
    async with factory() as session:
        org = Organization(public_ref=f"org_auth_{suffix}", display_name="Auth Test Co")
        session.add(org)
        await session.flush()
        u1 = AppUser(organization_id=org.id, public_ref=f"usr_a_{suffix}")
        u2 = AppUser(organization_id=org.id, public_ref=f"usr_b_{suffix}")
        session.add_all([u1, u2])
        await session.flush()
        session.add(
            DashboardAccount(
                login=f"admin_{suffix}",
                password_hash=hash_password("AdminPass!1"),
                role=DashboardRole.ORG_ADMIN.value,
                organization_id=org.id,
            )
        )
        session.add(
            DashboardAccount(
                login=f"sales_{suffix}",
                password_hash=hash_password("SalesPass!1"),
                role=DashboardRole.SALES_USER.value,
                organization_id=org.id,
                user_id=u1.id,
            )
        )
        now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        for user, title in [(u1, "Discovery Acme"), (u2, "Cold call list")]:
            session.add(
                MeetingClassification(
                    google_event_id=f"evt_{user.id}_{suffix}",
                    user_id=user.id,
                    organization_id=org.id,
                    title=title,
                    start_at=now,
                    end_at=now,
                    category_id="discovery_call",
                    category_label="Discovery call",
                    confidence=0.8,
                )
            )
        await session.commit()
        yield {
            "suffix": suffix,
            "org_ref": org.public_ref,
            "u1_ref": u1.public_ref,
            "u2_ref": u2.public_ref,
        }


@pytest.fixture
def jwt_settings(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-jwt-secret-for-pytest-only")
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_org_admin_sees_all_users(auth_fixture, jwt_settings):
    sfx = auth_fixture["suffix"]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login = await client.post("/auth/dashboard/login", json={"login": f"admin_{sfx}", "password": "AdminPass!1"})
        assert login.status_code == 200
        token = login.json()["access_token"]
        overview = await client.get("/stats/overview", headers={"Authorization": f"Bearer {token}"})
        assert overview.status_code == 200
        users = {u["user_ref"] for u in overview.json()["by_user"]}
        assert auth_fixture["u1_ref"] in users
        assert auth_fixture["u2_ref"] in users


@pytest.mark.asyncio
async def test_sales_user_sees_only_self(auth_fixture, jwt_settings):
    sfx = auth_fixture["suffix"]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login = await client.post("/auth/dashboard/login", json={"login": f"sales_{sfx}", "password": "SalesPass!1"})
        token = login.json()["access_token"]
        overview = await client.get("/stats/overview", headers={"Authorization": f"Bearer {token}"})
        users = overview.json()["by_user"]
        assert len(users) == 1
        assert users[0]["user_ref"] == auth_fixture["u1_ref"]
