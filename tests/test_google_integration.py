"""Batterie 3 — Google Calendar LIVE (création + lecture + sync classify).

Nécessite un vrai compte Google connecté via OAuth. Ignorée sinon.
Variables : GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, CULTURELIVE_TEST_USER_ID, DASHBOARD_API_KEY
et une API démarrée sur PUBLIC_BASE_URL.
"""

import os
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from tests.fixtures.sales_agenda import SALES_AGENDA

pytestmark = pytest.mark.google_live

BASE = os.getenv("PUBLIC_BASE_URL", "http://127.0.0.1:8000")
USER_ID = os.getenv("CULTURELIVE_TEST_USER_ID")
ADMIN_KEY = os.getenv("DASHBOARD_API_KEY", "")


@pytest.fixture(scope="module")
def require_google():
    if not (os.getenv("GOOGLE_CLIENT_ID") and os.getenv("GOOGLE_CLIENT_SECRET")):
        pytest.skip("Google OAuth non configuré")
    if not USER_ID:
        pytest.skip("CULTURELIVE_TEST_USER_ID requis après callback OAuth")
    if not ADMIN_KEY:
        pytest.skip("DASHBOARD_API_KEY requise")


@pytest.fixture
def client(require_google):
    with httpx.Client(base_url=BASE, timeout=120, headers={"X-API-Key": ADMIN_KEY}) as c:
        yield c


@pytest.mark.order(1)
def test_create_sales_meetings_in_google(client):
    now = datetime.now(timezone.utc)
    created_ids: list[str] = []
    for i, fixture in enumerate(SALES_AGENDA[:5]):
        start = now + timedelta(days=1, hours=i)
        r = client.post(
            "/meetings",
            params={"user_id": USER_ID},
            json={
                "summary": fixture.title,
                "description": fixture.description,
                "start": start.isoformat(),
                "end": (start + timedelta(minutes=45)).isoformat(),
            },
        )
        r.raise_for_status()
        created_ids.append(r.json()["id"])
    assert len(created_ids) == 5


@pytest.mark.order(2)
def test_list_meetings_from_google(client):
    now = datetime.now(timezone.utc)
    r = client.get(
        "/meetings",
        params={
            "user_id": USER_ID,
            "time_min": (now + timedelta(hours=1)).isoformat(),
            "time_max": (now + timedelta(days=3)).isoformat(),
        },
    )
    r.raise_for_status()
    assert r.json()["count"] >= 1


@pytest.mark.order(3)
def test_classify_sync_to_database(client):
    now = datetime.now(timezone.utc)
    body = {
        "time_min": (now + timedelta(hours=1)).isoformat(),
        "time_max": (now + timedelta(days=3)).isoformat(),
        "user_id": USER_ID,
    }
    r = client.post("/classify/sync", json=body)
    r.raise_for_status()
    data = r.json()
    assert data["errors"] == []
    assert data["classified"] + data["skipped"] >= 1

    again = client.post("/classify/sync", json=body)
    again.raise_for_status()
    assert again.json()["classified"] == 0

    stats = client.get("/stats/overview")
    stats.raise_for_status()
    assert stats.json()["by_category"]
