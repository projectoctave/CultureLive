"""Auth dashboard — scope org admin vs sales user."""

import uuid
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from backend.db.models import AppUser, DashboardAccount, MeetingClassification, Organization
from backend.db.session import get_session_factory
from backend.main import app
from backend.services.auth import DashboardRole, hash_password

pytestmark = [pytest.mark.db_live, pytest.mark.usefixtures("migrated_db")]


async def test_dashboard_auth_scopes():
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
        session.add_all(
            [
                DashboardAccount(
                    login=f"admin_{suffix}",
                    password_hash=hash_password("AdminPass!1"),
                    role=DashboardRole.ORG_ADMIN.value,
                    organization_id=org.id,
                ),
                DashboardAccount(
                    login=f"sales_{suffix}",
                    password_hash=hash_password("SalesPass!1"),
                    role=DashboardRole.SALES_USER.value,
                    organization_id=org.id,
                    user_id=u1.id,
                ),
            ]
        )
        now = datetime.now(timezone.utc)
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
        org_id, u1_ref, u2_ref = org.id, u1.public_ref, u2.public_ref

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            admin_login = await client.post(
                "/auth/dashboard/login", json={"login": f"admin_{suffix}", "password": "AdminPass!1"}
            )
            assert admin_login.status_code == 200
            admin_token = admin_login.json()["access_token"]
            admin_overview = await client.get("/stats/overview", headers={"Authorization": f"Bearer {admin_token}"})
            users = {u["user_ref"] for u in admin_overview.json()["by_user"]}
            assert users == {u1_ref, u2_ref}

            sales_login = await client.post(
                "/auth/dashboard/login", json={"login": f"sales_{suffix}", "password": "SalesPass!1"}
            )
            sales_token = sales_login.json()["access_token"]
            sales_overview = await client.get("/stats/overview", headers={"Authorization": f"Bearer {sales_token}"})
            sales_users = sales_overview.json()["by_user"]
            assert [u["user_ref"] for u in sales_users] == [u1_ref]

            forbidden = await client.get(
                "/stats/meetings",
                params={"user_ref": u2_ref},
                headers={"Authorization": f"Bearer {sales_token}"},
            )
            assert forbidden.status_code == 403

            bad = await client.post("/auth/dashboard/login", json={"login": f"admin_{suffix}", "password": "nope"})
            assert bad.status_code == 401
    finally:
        async with factory() as session:
            await session.execute(delete(Organization).where(Organization.id == org_id))
            await session.commit()
