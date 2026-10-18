"""Batterie 3 — Google Calendar live (création + lecture + sync classify)."""

import os
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from tests.fixtures.sales_agenda import SALES_AGENDA

pytestmark = pytest.mark.google_live

BASE = os.getenv("PUBLIC_BASE_URL", "http://127.0.0.1:8000")
USER_ID = os.getenv("CULTURELIVE_TEST_USER_ID")


def _google_configured() -> bool:
    return bool(os.getenv("GOOGLE_CLIENT_ID") and os.getenv("GOOGLE_CLIENT_SECRET"))


@pytest.fixture(scope="module")
def require_google():
    if not _google_configured():
        pytest.skip("Google OAuth non configuré")
    if not USER_ID:
        pytest.skip("CULTURELIVE_TEST_USER_ID requis après callback OAuth")


@pytest.mark.order(1)
def test_create_sales_meetings_in_google(require_google):
    """Crée les meetings de l'agenda sales dans Google Calendar."""
    now = datetime.now(timezone.utc)
    created_ids: list[str] = []
    with httpx.Client(base_url=BASE, timeout=60) as client:
        for i, fixture in enumerate(SALES_AGENDA[:5]):
            start = now + timedelta(days=1, hours=i)
            end = start + timedelta(minutes=45)
            r = client.post(
                "/meetings",
                params={"user_id": USER_ID},
                json={
                    "summary": fixture.title,
                    "description": fixture.description,
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                },
            )
            r.raise_for_status()
            created_ids.append(r.json()["id"])
    assert len(created_ids) == 5


@pytest.mark.order(2)
def test_list_meetings_from_google(require_google):
    now = datetime.now(timezone.utc)
    time_min = (now + timedelta(hours=1)).isoformat()
    time_max = (now + timedelta(days=3)).isoformat()
    with httpx.Client(base_url=BASE, timeout=60) as client:
        r = client.get(
            "/meetings",
            params={"user_id": USER_ID, "time_min": time_min, "time_max": time_max},
        )
        r.raise_for_status()
        data = r.json()
    assert data["count"] >= 1


@pytest.mark.order(3)
def test_classify_sync_to_database(require_google):
    now = datetime.now(timezone.utc)
    with httpx.Client(base_url=BASE, timeout=120) as client:
        r = client.post(
            "/classify/sync",
            json={
                "time_min": (now + timedelta(hours=1)).isoformat(),
                "time_max": (now + timedelta(days=3)).isoformat(),
                "user_id": USER_ID,
            },
        )
        r.raise_for_status()
        assert r.json()["classified"] >= 1

        api_key = os.getenv("DASHBOARD_API_KEY")
        if api_key:
            stats = client.get("/stats/overview", headers={"X-API-Key": api_key})
            stats.raise_for_status()
            assert stats.json()["by_category"]
