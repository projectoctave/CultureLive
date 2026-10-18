"""Batterie 2 — persistance PostgreSQL + classifier sur meetings injectés."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select

from backend.config import Settings
from backend.db.models import AppUser, MeetingClassification, Organization
from backend.db.session import get_session_factory
from backend.services.classifier import MeetingInput, classify_meeting
from backend.services.referential import ensure_active_referential
from tests.fixtures.sales_agenda import SALES_AGENDA

pytestmark = [pytest.mark.db_live, pytest.mark.usefixtures("migrated_db")]


@pytest.fixture
async def db_session():
    factory = get_session_factory()
    async with factory() as session:
        yield session


async def test_classify_and_persist_pipeline(db_session):
    settings = Settings(openai_api_key=None)
    suffix = uuid.uuid4().hex[:8]
    org = Organization(public_ref=f"org_test_{suffix}")
    db_session.add(org)
    await db_session.flush()
    org_id = org.id
    user = AppUser(organization_id=org_id, public_ref=f"usr_test_{suffix}")
    db_session.add(user)
    await db_session.flush()
    user_id = user.id

    ref_row, ref_payload = await ensure_active_referential(db_session)
    now = datetime.now(timezone.utc)

    try:
        for i, fixture in enumerate(SALES_AGENDA):
            classification = await classify_meeting(
                settings,
                MeetingInput(event_id=f"evt_{i}", title=fixture.title, description=fixture.description),
                ref_payload,
            )
            db_session.add(
                MeetingClassification(
                    google_event_id=f"google_evt_{i}_{uuid.uuid4().hex[:8]}",
                    user_id=user_id,
                    organization_id=org_id,
                    referential_id=ref_row.id,
                    title=fixture.title,
                    description=fixture.description,
                    start_at=now + timedelta(hours=i),
                    end_at=now + timedelta(hours=i, minutes=30),
                    category_id=classification.category_id,
                    category_label=classification.category_label,
                    confidence=classification.confidence,
                    rationale=classification.rationale,
                )
            )
        await db_session.commit()

        result = await db_session.execute(
            select(MeetingClassification.category_id).where(MeetingClassification.user_id == user_id)
        )
        categories = {row[0] for row in result.all()}
        assert "discovery_call" in categories
        assert "cold_call" in categories
        assert len(categories) >= 5
    finally:
        await db_session.rollback()
        await db_session.execute(delete(Organization).where(Organization.id == org_id))
        await db_session.commit()
