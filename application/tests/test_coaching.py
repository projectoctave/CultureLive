"""Pilotage commercial : données de démonstration, indicateurs, alertes, droits d'accès."""

import uuid
from datetime import date, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend import domain as d
from backend.db.session import get_session_factory
from backend.demo_data import PERSONAS, clear_demo, seed_demo
from backend.main import app

pytestmark = [pytest.mark.db_live, pytest.mark.usefixtures("migrated_db")]


def _org(suffix: str, tag: str, personas: list[str]) -> dict:
    users = [
        (f"usr_{tag}_{suffix}_{i}", f"Rep{i}", f"{tag}.{suffix}.{i}", f"Pass{tag}{i}!2026", persona)
        for i, persona in enumerate(personas)
    ]
    return {
        "public_ref": f"org_{tag}_{suffix}",
        "display_name": f"Test {tag}",
        "admin_login": f"{tag}_admin_{suffix}",
        "admin_password": "AdminPass!2026",
        "users": users,
    }


@pytest_asyncio.fixture(scope="module")
async def world():
    suffix = uuid.uuid4().hex[:6]
    org_a = _org(suffix, "alpha", ["hunter_star", "fading", "farmer", "spray"])
    org_b = _org(suffix, "beta", ["steady"])
    factory = get_session_factory()
    async with factory() as session:
        await seed_demo(session, [org_a, org_b])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield {"client": client, "a": org_a, "b": org_b}
    async with factory() as session:
        await clear_demo(session, [org_a["public_ref"], org_b["public_ref"]])
        await session.commit()


async def _headers(world, login: str, password: str) -> dict[str, str]:
    r = await world["client"].post("/auth/dashboard/login", json={"login": login, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _manager(world, key: str = "a") -> dict[str, str]:
    org = world[key]
    return await _headers(world, org["admin_login"], org["admin_password"])


async def _sales(world, index: int, key: str = "a") -> dict[str, str]:
    _, _, login, password, _ = world[key]["users"][index]
    return await _headers(world, login, password)


def _rep(summary: dict, user_ref: str) -> dict:
    return next(r for r in summary["reps"] if r["user_ref"] == user_ref)


def test_week_progress_and_quarters():
    from datetime import datetime, timezone

    monday_noon = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)
    assert d.week_progress(monday_noon) == 0.2
    wednesday_noon = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)
    assert d.week_progress(wednesday_noon) == pytest.approx(0.5)
    sunday_night = datetime(2026, 10, 18, 23, 0, tzinfo=timezone.utc)
    assert d.week_progress(sunday_night) > 0.95
    assert d.quarter_bounds(date(2026, 10, 18)) == (date(2026, 10, 1), date(2026, 12, 31))
    assert d.week_start(date(2026, 10, 18)) == date(2026, 10, 12)
    assert sum(m["weight"] for m in d.HUNTING_METRICS.values()) == pytest.approx(1.0)


async def test_personas_tell_their_story(world):
    headers = await _manager(world)
    r = await world["client"].get("/coach/summary", headers=headers)
    assert r.status_code == 200
    summary = r.json()
    refs = [u[0] for u in world["a"]["users"]]
    star, fading, farmer, spray = (_rep(summary, ref) for ref in refs)

    assert star["hunting_index"] > 85
    assert star["streak_weeks"] >= 1
    assert fading["hunting_index"] < star["hunting_index"] - 20
    assert fading["trend"]["last_2_weeks"] < fading["trend"]["previous_4_weeks"] * 0.8
    assert farmer["time_allocation"]["farming_share"] > 50
    assert spray["ratios"]["touches_per_meeting"] > star["ratios"]["touches_per_meeting"] * 1.5

    codes = {(a["code"], a["user_ref"]) for a in summary["alerts"]}
    assert ("declining", refs[1]) in codes or ("low_activity", refs[1]) in codes
    assert ("farming_drift", refs[2]) in codes
    assert ("low_meeting_yield", refs[3]) in codes
    assert ("recognition", refs[0]) in codes
    for alert in summary["alerts"]:
        assert alert["suggested_action"]


async def test_manager_sees_only_own_organization(world):
    headers = await _manager(world, "b")
    summary = (await world["client"].get("/coach/summary", headers=headers)).json()
    assert [r["user_ref"] for r in summary["reps"]] == [world["b"]["users"][0][0]]
    pipe = (await world["client"].get("/coach/pipeline", headers=headers)).json()
    assert {deal["user_ref"] for deal in pipe["deals"]} <= {world["b"]["users"][0][0]}

    foreign = await world["client"].post(
        "/coach/actions",
        headers=headers,
        json={"user_ref": world["a"]["users"][0][0], "kind": "nudge", "title": "Intrusion"},
    )
    assert foreign.status_code == 404


async def test_sales_user_scope_and_rights(world):
    mine = world["a"]["users"][1][0]
    headers = await _sales(world, 1)
    summary = (await world["client"].get("/coach/summary", headers=headers)).json()
    assert summary["viewer"]["is_manager"] is False
    assert [r["user_ref"] for r in summary["reps"]] == [mine]
    assert all(a["user_ref"] in (None, mine) for a in summary["alerts"])

    pipe = (await world["client"].get("/coach/pipeline", headers=headers)).json()
    assert {deal["user_ref"] for deal in pipe["deals"]} <= {mine}
    accounts = (await world["client"].get("/coach/accounts", headers=headers)).json()["items"]
    assert {item["user_ref"] for item in accounts} <= {mine}

    denied = await world["client"].post(
        "/coach/actions", headers=headers, json={"user_ref": mine, "kind": "nudge", "title": "Auto-assignation"}
    )
    assert denied.status_code == 403
    denied = await world["client"].put(
        "/coach/targets", headers=headers, json={"metric": "calls", "period": "week", "target_value": 1}
    )
    assert denied.status_code == 403
    denied = await world["client"].post(
        "/coach/challenges",
        headers=headers,
        json={
            "name": "Mon défi",
            "metric": "calls",
            "target_value": 1,
            "starts_on": date.today().isoformat(),
            "ends_on": date.today().isoformat(),
        },
    )
    assert denied.status_code == 403


async def test_engagement_exposes_only_aliases_and_points(world):
    headers = await _sales(world, 0)
    data = (await world["client"].get("/coach/engagement", headers=headers)).json()
    assert len(data["leaderboard"]) == 4
    assert sum(1 for row in data["leaderboard"] if row["is_me"]) == 1
    assert {"rank", "alias", "points_week", "badges"} <= set(data["leaderboard"][0])
    assert not any("login" in row or "email" in row for row in data["leaderboard"])
    assert data["challenges"]


async def test_coaching_action_lifecycle(world):
    manager = await _manager(world)
    target = world["a"]["users"][1][0]
    created = await world["client"].post(
        "/coach/actions",
        headers=manager,
        json={
            "user_ref": target,
            "kind": "one_to_one",
            "title": "Point 1:1 de test",
            "due_on": (date.today() + timedelta(days=2)).isoformat(),
        },
    )
    assert created.status_code == 201
    action_id = created.json()["id"]

    other = await _sales(world, 2)
    assert (
        await world["client"].patch(f"/coach/actions/{action_id}", headers=other, json={"status": "done"})
    ).status_code == 403

    owner = await _sales(world, 1)
    mine = (await world["client"].get("/coach/actions", headers=owner)).json()
    assert action_id in {a["id"] for a in mine}
    done = await world["client"].patch(f"/coach/actions/{action_id}", headers=owner, json={"status": "done"})
    assert done.status_code == 200 and done.json()["status"] == "done"
    open_ids = {a["id"] for a in (await world["client"].get("/coach/actions", headers=manager)).json()}
    assert action_id not in open_ids


async def test_target_override_changes_attainment(world):
    manager = await _manager(world)
    ref = world["a"]["users"][0][0]
    before = _rep((await world["client"].get("/coach/summary", headers=manager)).json(), ref)
    r = await world["client"].put(
        "/coach/targets",
        headers=manager,
        json={"user_ref": ref, "metric": "calls", "period": "week", "target_value": 400},
    )
    assert r.status_code == 200
    after = _rep((await world["client"].get("/coach/summary", headers=manager)).json(), ref)
    assert after["targets"]["calls"] == 400
    assert after["attainment"]["calls"] < before["attainment"]["calls"]

    bad = await world["client"].put(
        "/coach/targets", headers=manager, json={"metric": "unknown", "period": "week", "target_value": 1}
    )
    assert bad.status_code == 422


async def test_sales_logs_own_activity_only(world):
    owner = await _sales(world, 0)
    before = _rep((await world["client"].get("/coach/summary", headers=owner)).json(), world["a"]["users"][0][0])
    accounts = (await world["client"].get("/coach/accounts", headers=owner, params={"stale_days": 1})).json()["items"]
    assert accounts
    ok = await world["client"].post(
        "/coach/activities",
        headers=owner,
        json={"type": "call", "outcome": "conversation", "account_ref": accounts[0]["ref"]},
    )
    assert ok.status_code == 201 and ok.json()["is_hunting"] is True
    after = _rep((await world["client"].get("/coach/summary", headers=owner)).json(), world["a"]["users"][0][0])
    assert after["actuals"]["calls"] == before["actuals"]["calls"] + 1

    colleague = await _sales(world, 2)
    foreign = await world["client"].post(
        "/coach/activities", headers=colleague, json={"type": "call", "account_ref": accounts[0]["ref"]}
    )
    assert foreign.status_code == 403
    impersonation = await world["client"].post(
        "/coach/activities", headers=colleague, json={"type": "call", "user_ref": world["a"]["users"][0][0]}
    )
    assert impersonation.status_code == 403


async def test_pipeline_flags_and_coverage(world):
    manager = await _manager(world)
    pipe = (await world["client"].get("/coach/pipeline", headers=manager)).json()
    assert pipe["open"]["count"] == len(pipe["deals"]) > 0
    assert pipe["team"]["quarter_quota"] == sum(rep["quarter_quota"] for rep in pipe["by_rep"])
    for deal in pipe["deals"]:
        assert deal["stage"] in d.OPEN_STAGES
        assert deal["health"] in {"ok", "at_risk", "stale"}
        if "no_recent_activity" in deal["flags"]:
            assert deal["health"] == "stale"
    stale = [deal for deal in pipe["deals"] if deal["health"] == "stale"]
    assert pipe["open"]["stale_count"] == len(stale)
    assert [s["stage"] for s in pipe["by_stage"]] == list(d.OPEN_STAGES)


async def test_demo_seed_is_deterministic():
    suffix = uuid.uuid4().hex[:6]
    org = _org(suffix, "gamma", ["steady"])
    factory = get_session_factory()
    from sqlalchemy import func, select

    from backend.db.models import Activity, Opportunity

    counts = []
    try:
        for _ in range(2):
            async with factory() as session:
                await seed_demo(session, [org], seed=7)
                activities = (await session.execute(select(func.count()).select_from(Activity))).scalar_one()
                opps = (await session.execute(select(func.count()).select_from(Opportunity))).scalar_one()
                counts.append((activities, opps))
    finally:
        async with factory() as session:
            await clear_demo(session, [org["public_ref"]])
            await session.commit()
    assert counts[0][0] > 0
    assert PERSONAS["steady"].calls > 0
    assert counts[0] == counts[1]
