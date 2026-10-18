#!/usr/bin/env python3
"""Charge PostgreSQL avec des données fake (3 entreprises × 3 sales) + comptes dashboard."""

from __future__ import annotations

import asyncio
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import delete, select

from backend.db.migrate import upgrade_head
from backend.db.models import (
    AppUser,
    DashboardAccount,
    MeetingClassification,
    Organization,
)
from backend.db.session import dispose_engine, get_session_factory
from backend.services.auth import DashboardRole, hash_password
from backend.services.classifier import MeetingInput, classify_heuristic
from backend.services.referential import ensure_active_referential
from tests.fixtures.sales_agenda import SALES_AGENDA

DEMO_ORGS = [
    {
        "public_ref": "org_nova_sales",
        "display_name": "Nova Sales (demo)",
        "admin_login": "nova_admin",
        "admin_password": "NovaAdmin!2026",
        "users": [
            ("usr_nova_alice", "nova.alice", "NovaAlice!2026"),
            ("usr_nova_bob", "nova.bob", "NovaBob!2026"),
            ("usr_nova_chloe", "nova.chloe", "NovaChloe!2026"),
        ],
    },
    {
        "public_ref": "org_helios_corp",
        "display_name": "Helios Corp (demo)",
        "admin_login": "helios_admin",
        "admin_password": "HeliosAdmin!2026",
        "users": [
            ("usr_helios_dan", "helios.dan", "HeliosDan!2026"),
            ("usr_helios_eva", "helios.eva", "HeliosEva!2026"),
            ("usr_helios_fay", "helios.fay", "HeliosFay!2026"),
        ],
    },
    {
        "public_ref": "org_zephyr_b2b",
        "display_name": "Zephyr B2B (demo)",
        "admin_login": "zephyr_admin",
        "admin_password": "ZephyrAdmin!2026",
        "users": [
            ("usr_zephyr_gus", "zephyr.gus", "ZephyrGus!2026"),
            ("usr_zephyr_hana", "zephyr.hana", "ZephyrHana!2026"),
            ("usr_zephyr_ian", "zephyr.ian", "ZephyrIan!2026"),
        ],
    },
]


async def clear_demo(session) -> None:
    refs = [o["public_ref"] for o in DEMO_ORGS]
    orgs = (await session.execute(select(Organization).where(Organization.public_ref.in_(refs)))).scalars().all()
    org_ids = [o.id for o in orgs]
    if not org_ids:
        return
    await session.execute(delete(MeetingClassification).where(MeetingClassification.organization_id.in_(org_ids)))
    await session.execute(delete(DashboardAccount).where(DashboardAccount.organization_id.in_(org_ids)))
    users = (await session.execute(select(AppUser).where(AppUser.organization_id.in_(org_ids)))).scalars().all()
    user_ids = [u.id for u in users]
    if user_ids:
        await session.execute(delete(MeetingClassification).where(MeetingClassification.user_id.in_(user_ids)))
    await session.execute(delete(AppUser).where(AppUser.organization_id.in_(org_ids)))
    await session.execute(delete(Organization).where(Organization.id.in_(org_ids)))


async def seed() -> None:
    await asyncio.to_thread(upgrade_head)
    factory = get_session_factory()

    async with factory() as session:
        await clear_demo(session)
        await session.commit()

        ref_row, ref_payload = await ensure_active_referential(session)
        now = datetime.now(timezone.utc)
        credentials: list[tuple[str, str, str]] = []

        for org_def in DEMO_ORGS:
            org = Organization(public_ref=org_def["public_ref"], display_name=org_def["display_name"])
            session.add(org)
            await session.flush()

            session.add(
                DashboardAccount(
                    login=org_def["admin_login"],
                    password_hash=hash_password(org_def["admin_password"]),
                    role=DashboardRole.ORG_ADMIN.value,
                    organization_id=org.id,
                )
            )
            credentials.append(("org_admin", org_def["admin_login"], org_def["admin_password"]))

            for user_ref, login, password in org_def["users"]:
                user = AppUser(organization_id=org.id, public_ref=user_ref)
                session.add(user)
                await session.flush()

                session.add(
                    DashboardAccount(
                        login=login,
                        password_hash=hash_password(password),
                        role=DashboardRole.SALES_USER.value,
                        organization_id=org.id,
                        user_id=user.id,
                    )
                )
                credentials.append(("sales_user", login, password))

                sample = random.sample(SALES_AGENDA, k=min(5, len(SALES_AGENDA)))
                for j, fixture in enumerate(sample):
                    clf = classify_heuristic(
                        MeetingInput(
                            event_id=f"demo_{uuid.uuid4().hex[:8]}",
                            title=fixture.title,
                            description=fixture.description,
                        ),
                        ref_payload,
                    )
                    start = now - timedelta(days=random.randint(1, 21), hours=j)
                    session.add(
                        MeetingClassification(
                            google_event_id=f"fake_{org.public_ref}_{user.public_ref}_{j}_{uuid.uuid4().hex[:6]}",
                            user_id=user.id,
                            organization_id=org.id,
                            referential_id=ref_row.id,
                            title=fixture.title,
                            description=fixture.description,
                            start_at=start,
                            end_at=start + timedelta(minutes=45),
                            category_id=clf.category_id,
                            category_label=clf.category_label,
                            confidence=clf.confidence,
                            rationale=clf.rationale,
                        )
                    )

        await session.commit()

    print("\n=== CultureLive — données demo chargées ===\n")
    print("Comptes dashboard (login / mot de passe / rôle) :\n")
    for role, login, password in credentials:
        print(f"  [{role:10}] {login:16} / {password}")
    print("\nExemple connexion API : POST /auth/dashboard/login")
    print("Puis dashboard Streamlit avec ces identifiants.\n")


async def main() -> None:
    try:
        await seed()
    finally:
        await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
