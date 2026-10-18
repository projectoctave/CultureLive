"""Analytique de pilotage commercial : activité de prospection, entonnoir, pipeline, classement."""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend import domain as d
from backend.db.models import (
    Account,
    Activity,
    AppUser,
    Challenge,
    MeetingClassification,
    Opportunity,
    OpportunityStageEvent,
    SalesTarget,
)

TYPE_KEY = {"call": "calls", "email": "emails", "linkedin": "linkedin"}
SELLING_CATEGORIES = ("cold_call", "discovery_call", "demo", "negotiation")
FARMING_CATEGORIES = ("follow_up", "customer_success")
HISTORY_WEEKS = 12
RATIO_WEEKS = 4

Metrics = dict[tuple[uuid.UUID, date], dict[str, float]]


def _wk(column):
    return func.date_trunc("week", func.timezone("UTC", column))


def _day_start(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=timezone.utc)


def _f(value: Any) -> float:
    return float(value or 0)


def _round(value: float | None, digits: int = 1) -> float | None:
    return None if value is None else round(value, digits)


def _iso(value: datetime | date | None) -> str | None:
    return value.isoformat() if value else None


def _days_between(later: datetime, earlier: datetime | None) -> int | None:
    return None if earlier is None else max(0, (later - earlier).days)


def week_list(as_of: datetime, count: int = HISTORY_WEEKS) -> list[date]:
    current = d.week_start(as_of)
    return [current - timedelta(weeks=i) for i in range(count - 1, -1, -1)]


class Targets:
    def __init__(self, rows: list[SalesTarget]):
        self._values: dict[tuple[uuid.UUID | None, str, str], float] = {}
        for row in sorted(rows, key=lambda r: r.valid_from):
            self._values[(row.user_id, row.metric, row.period)] = float(row.target_value)

    def get(self, user_id: uuid.UUID | None, metric: str, period: str = "week") -> float:
        for owner in (user_id, None):
            if (owner, metric, period) in self._values:
                return self._values[(owner, metric, period)]
        if period == "week":
            return float(d.DEFAULT_WEEKLY_TARGETS.get(metric, 0))
        if metric == "revenue_won":
            return float(d.DEFAULT_QUARTER_QUOTA)
        return 0.0

    def weekly(self, user_id: uuid.UUID | None) -> dict[str, float]:
        keys = [*d.HUNTING_METRICS, "pipeline_created"]
        return {key: self.get(user_id, key) for key in keys}


async def load_users(session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID | None = None) -> list[AppUser]:
    q = select(AppUser).where(AppUser.organization_id == org_id).order_by(AppUser.alias, AppUser.public_ref)
    if user_id:
        q = q.where(AppUser.id == user_id)
    return list((await session.execute(q)).scalars().all())


async def load_targets(session: AsyncSession, org_id: uuid.UUID, as_of: datetime) -> Targets:
    rows = (
        (
            await session.execute(
                select(SalesTarget).where(SalesTarget.organization_id == org_id, SalesTarget.valid_from <= as_of.date())
            )
        )
        .scalars()
        .all()
    )
    return Targets(list(rows))


async def weekly_metrics(
    session: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID | None,
    first_week: date,
    as_of: datetime,
) -> Metrics:
    since = _day_start(first_week)
    out: Metrics = defaultdict(lambda: defaultdict(float))

    def scoped(query, column):
        query = query.where(column.organization_id == org_id)
        return query.where(column.user_id == user_id) if user_id else query

    wk = _wk(Activity.occurred_at)
    q = scoped(
        select(Activity.user_id, wk, Activity.type, Activity.outcome, Activity.is_hunting, func.count())
        .where(Activity.occurred_at >= since, Activity.occurred_at <= as_of)
        .group_by(Activity.user_id, wk, Activity.type, Activity.outcome, Activity.is_hunting),
        Activity,
    )
    for uid, week, kind, outcome, hunting, n in (await session.execute(q)).all():
        bucket = out[(uid, week.date())]
        if not hunting:
            bucket["farming_activities"] += n
            continue
        key = TYPE_KEY[kind]
        bucket[key] += n
        if outcome in d.CONVERSATION_OUTCOMES:
            bucket["conversations"] += n
            bucket[f"conv_{key}"] += n
        if outcome == "meeting_booked":
            bucket["meetings_booked"] += n

    q = scoped(
        select(Activity.user_id, wk, func.count(func.distinct(Activity.account_id)))
        .where(Activity.occurred_at >= since, Activity.occurred_at <= as_of, Activity.is_hunting.is_(True))
        .group_by(Activity.user_id, wk),
        Activity,
    )
    for uid, week, n in (await session.execute(q)).all():
        out[(uid, week.date())]["accounts_touched"] = n

    wk = _wk(Opportunity.created_at)
    q = scoped(
        select(Opportunity.user_id, wk, func.count(), func.coalesce(func.sum(Opportunity.amount), 0))
        .where(
            Opportunity.created_at >= since,
            Opportunity.created_at <= as_of,
            Opportunity.source == "outbound",
            Opportunity.is_new_logo.is_(True),
        )
        .group_by(Opportunity.user_id, wk),
        Opportunity,
    )
    for uid, week, n, amount in (await session.execute(q)).all():
        out[(uid, week.date())]["opportunities_created"] = n
        out[(uid, week.date())]["pipeline_created"] = _f(amount)

    wk = _wk(Opportunity.closed_at)
    q = scoped(
        select(
            Opportunity.user_id,
            wk,
            Opportunity.stage,
            func.count(),
            func.coalesce(func.sum(Opportunity.amount), 0),
        )
        .where(
            Opportunity.closed_at >= since,
            Opportunity.closed_at <= as_of,
            Opportunity.stage.in_([d.STAGE_WON, d.STAGE_LOST]),
        )
        .group_by(Opportunity.user_id, wk, Opportunity.stage),
        Opportunity,
    )
    for uid, week, stage, n, amount in (await session.execute(q)).all():
        bucket = out[(uid, week.date())]
        if stage == d.STAGE_WON:
            bucket["won_deals"] = n
            bucket["revenue_won"] = _f(amount)
        else:
            bucket["lost_deals"] = n

    wk = _wk(MeetingClassification.start_at)
    hours = func.coalesce(
        func.sum(func.extract("epoch", MeetingClassification.end_at - MeetingClassification.start_at)) / 3600.0, 0
    )
    q = scoped(
        select(MeetingClassification.user_id, wk, MeetingClassification.category_id, func.count(), hours)
        .where(MeetingClassification.start_at >= since, MeetingClassification.start_at <= as_of)
        .group_by(MeetingClassification.user_id, wk, MeetingClassification.category_id),
        MeetingClassification,
    )
    for uid, week, category, n, h in (await session.execute(q)).all():
        bucket = out[(uid, week.date())]
        if category in SELLING_CATEGORIES:
            bucket["hours_selling"] += _f(h)
        elif category in FARMING_CATEGORIES:
            bucket["hours_farming"] += _f(h)
        else:
            bucket["hours_internal"] += _f(h)
        if category == "discovery_call":
            bucket["meetings_discovery"] += n
    return out


async def upcoming_meetings(
    session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID | None, as_of: datetime, days: int = 7
) -> dict[uuid.UUID, int]:
    q = (
        select(MeetingClassification.user_id, func.count())
        .where(
            MeetingClassification.organization_id == org_id,
            MeetingClassification.start_at > as_of,
            MeetingClassification.start_at <= as_of + timedelta(days=days),
            MeetingClassification.category_id.in_(d.HUNTING_MEETING_CATEGORIES),
        )
        .group_by(MeetingClassification.user_id)
    )
    if user_id:
        q = q.where(MeetingClassification.user_id == user_id)
    return {uid: n for uid, n in (await session.execute(q)).all()}


def hunting_index(metrics: dict[str, float], targets: dict[str, float]) -> float:
    total = 0.0
    for key, spec in d.HUNTING_METRICS.items():
        target = targets.get(key, 0)
        ratio = 1.0 if target <= 0 else min(metrics.get(key, 0) / target, d.ATTAINMENT_CAP)
        total += spec["weight"] * ratio
    return round(total * 100, 1)


def pace_status(pace_index: float, progress: float) -> str:
    if progress < 0.4:
        return "early"
    if pace_index >= 90:
        return "on_track"
    if pace_index >= 60:
        return "watch"
    return "at_risk"


def _sum_weeks(metrics: Metrics, uid: uuid.UUID, weeks: list[date]) -> dict[str, float]:
    total: dict[str, float] = defaultdict(float)
    for week in weeks:
        for key, value in metrics.get((uid, week), {}).items():
            total[key] += value
    return total


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


async def tier_a_coverage(
    session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID | None, as_of: datetime
) -> dict[uuid.UUID, dict[str, int]]:
    """Part des comptes cibles prioritaires (tier A) réellement travaillés sur 30 jours."""
    recent = as_of - timedelta(days=30)
    touched = func.count().filter(Account.last_activity_at >= recent)
    q = (
        select(Account.owner_user_id, func.count(), touched)
        .where(
            Account.organization_id == org_id,
            Account.kind == "prospect",
            Account.status == "active",
            Account.tier == "A",
            Account.owner_user_id.is_not(None),
        )
        .group_by(Account.owner_user_id)
    )
    if user_id:
        q = q.where(Account.owner_user_id == user_id)
    return {uid: {"total": total, "touched": n} for uid, total, n in (await session.execute(q)).all()}


async def funnel(
    session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID | None, as_of: datetime, weeks: int = HISTORY_WEEKS
) -> dict[str, Any]:
    since = _day_start(week_list(as_of, weeks)[0])
    per_user: dict[uuid.UUID, Counter] = defaultdict(Counter)

    q = select(Account.owner_user_id, func.count()).where(
        Account.organization_id == org_id,
        Account.kind == "prospect",
        Account.status == "active",
        Account.owner_user_id.is_not(None),
    )
    if user_id:
        q = q.where(Account.owner_user_id == user_id)
    for uid, n in (await session.execute(q.group_by(Account.owner_user_id))).all():
        per_user[uid]["portfolio"] = n

    base = [
        Activity.organization_id == org_id,
        Activity.is_hunting.is_(True),
        Activity.occurred_at >= since,
        Activity.occurred_at <= as_of,
    ]
    if user_id:
        base.append(Activity.user_id == user_id)
    steps = {
        "contacted": [],
        "conversation": [Activity.outcome.in_(d.CONVERSATION_OUTCOMES)],
        "meeting": [Activity.outcome == "meeting_booked"],
    }
    for name, extra in steps.items():
        q = select(Activity.user_id, func.count(func.distinct(Activity.account_id))).where(*base, *extra)
        for uid, n in (await session.execute(q.group_by(Activity.user_id))).all():
            per_user[uid][name] = n

    opp_base = [
        Opportunity.organization_id == org_id,
        Opportunity.is_new_logo.is_(True),
        Opportunity.source == "outbound",
        Opportunity.created_at >= since,
        Opportunity.created_at <= as_of,
    ]
    if user_id:
        opp_base.append(Opportunity.user_id == user_id)
    q = select(Opportunity.user_id, func.count(func.distinct(Opportunity.account_id))).where(*opp_base)
    for uid, n in (await session.execute(q.group_by(Opportunity.user_id))).all():
        per_user[uid]["opportunity"] = n
    q = select(Opportunity.user_id, func.count(func.distinct(Opportunity.account_id))).where(
        *opp_base, Opportunity.stage == d.STAGE_WON
    )
    for uid, n in (await session.execute(q.group_by(Opportunity.user_id))).all():
        per_user[uid]["won"] = n

    labels = [
        ("portfolio", "Comptes cibles"),
        ("contacted", "Contactés"),
        ("conversation", "En conversation"),
        ("meeting", "RDV obtenus"),
        ("opportunity", "Opportunités"),
        ("won", "Gagnés"),
    ]

    def steps_for(counter: Counter) -> list[dict]:
        out, previous = [], None
        for key, label in labels:
            value = counter.get(key, 0)
            out.append(
                {
                    "key": key,
                    "label": label,
                    "count": value,
                    "rate_from_previous": _round(value / previous * 100) if previous else None,
                }
            )
            previous = value or previous
        return out

    team = Counter()
    for counter in per_user.values():
        team.update(counter)
    return {
        "window_weeks": weeks,
        "team": steps_for(team),
        "by_user": {str(uid): steps_for(counter) for uid, counter in per_user.items()},
    }


def _deal_flags(opp: Opportunity, account_name: str, alias: str | None, user_ref: str, as_of: datetime) -> dict:
    today = as_of.date()
    amount = _f(opp.amount)
    days_in_stage = _days_between(as_of, opp.last_stage_change_at) or 0
    since_activity = _days_between(as_of, opp.last_activity_at or opp.created_at) or 0
    flags: list[str] = []
    if since_activity > d.STALE_ACTIVITY_DAYS:
        flags.append("no_recent_activity")
    if days_in_stage > d.STAGE_STALE_DAYS.get(opp.stage, 21):
        flags.append("stuck_in_stage")
    if opp.expected_close_date and opp.expected_close_date < today:
        flags.append("close_date_passed")
    if not opp.next_step:
        flags.append("no_next_step")
    elif opp.next_step_due and opp.next_step_due < today:
        flags.append("next_step_overdue")
    stale = "no_recent_activity" in flags or "stuck_in_stage" in flags
    health = "stale" if stale else ("at_risk" if flags else "ok")
    return {
        "ref": opp.public_ref,
        "name": opp.name,
        "account": account_name,
        "user_ref": user_ref,
        "alias": alias,
        "stage": opp.stage,
        "stage_label": d.STAGE_LABELS[opp.stage],
        "amount": amount,
        "weighted": round(amount * d.STAGE_PROBABILITY[opp.stage], 2),
        "source": opp.source,
        "age_days": _days_between(as_of, opp.created_at),
        "days_in_stage": days_in_stage,
        "days_since_activity": since_activity,
        "expected_close_date": _iso(opp.expected_close_date),
        "next_step": opp.next_step,
        "next_step_due": _iso(opp.next_step_due),
        "flags": flags,
        "health": health,
    }


async def pipeline(
    session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID | None, as_of: datetime, targets: Targets | None = None
) -> dict[str, Any]:
    targets = targets or await load_targets(session, org_id, as_of)
    users = await load_users(session, org_id, user_id)
    by_id = {u.id: u for u in users}
    quarter_start, quarter_end = d.quarter_bounds(as_of.date())

    q = (
        select(Opportunity, Account.name)
        .join(Account, Account.id == Opportunity.account_id)
        .where(Opportunity.organization_id == org_id, Opportunity.stage.in_(d.OPEN_STAGES))
    )
    if user_id:
        q = q.where(Opportunity.user_id == user_id)
    deals = []
    for opp, account_name in (await session.execute(q)).all():
        owner = by_id.get(opp.user_id)
        if owner:
            deals.append(_deal_flags(opp, account_name, owner.alias, owner.public_ref, as_of))
    deals.sort(key=lambda x: -x["amount"])

    won_q = select(Opportunity.user_id, func.coalesce(func.sum(Opportunity.amount), 0)).where(
        Opportunity.organization_id == org_id,
        Opportunity.stage == d.STAGE_WON,
        Opportunity.closed_at >= _day_start(quarter_start),
        Opportunity.closed_at <= as_of,
    )
    if user_id:
        won_q = won_q.where(Opportunity.user_id == user_id)
    won_qtd = {uid: _f(v) for uid, v in (await session.execute(won_q.group_by(Opportunity.user_id))).all()}

    stage_rows = []
    for stage in d.OPEN_STAGES:
        stage_deals = [x for x in deals if x["stage"] == stage]
        stage_rows.append(
            {
                "stage": stage,
                "label": d.STAGE_LABELS[stage],
                "probability": d.STAGE_PROBABILITY[stage],
                "count": len(stage_deals),
                "amount": sum(x["amount"] for x in stage_deals),
                "weighted": sum(x["weighted"] for x in stage_deals),
                "stale": sum(1 for x in stage_deals if x["health"] == "stale"),
            }
        )

    rep_rows = []
    team_quota = team_won = team_open_q = 0.0
    for user in users:
        mine = [x for x in deals if x["user_ref"] == user.public_ref]
        in_quarter = [
            x
            for x in mine
            if not x["expected_close_date"] or date.fromisoformat(x["expected_close_date"]) <= quarter_end
        ]
        quota = targets.get(user.id, "revenue_won", "quarter")
        won = won_qtd.get(user.id, 0.0)
        gap = max(quota - won, 0.0)
        open_q = sum(x["amount"] for x in in_quarter)
        stale = [x for x in mine if x["health"] == "stale"]
        rep_rows.append(
            {
                "user_ref": user.public_ref,
                "alias": user.alias,
                "open_count": len(mine),
                "open_amount": sum(x["amount"] for x in mine),
                "weighted": sum(x["weighted"] for x in mine),
                "quarter_quota": quota,
                "won_qtd": won,
                "gap": gap,
                "open_in_quarter": open_q,
                "coverage": _round(open_q / gap, 2) if gap > 0 else None,
                "stale_count": len(stale),
                "stale_amount": sum(x["amount"] for x in stale),
                "next_step_issues": sum(1 for x in mine if {"no_next_step", "next_step_overdue"} & set(x["flags"])),
            }
        )
        team_quota += quota
        team_won += won
        team_open_q += open_q

    team_gap = max(team_quota - team_won, 0.0)
    coverage = _round(team_open_q / team_gap, 2) if team_gap > 0 else None
    needed = max(team_gap * d.PIPELINE_COVERAGE_TARGET - team_open_q, 0.0) if team_gap > 0 else 0.0

    window = 180
    since = as_of - timedelta(days=window)
    q = select(Opportunity).where(
        Opportunity.organization_id == org_id,
        Opportunity.stage.in_([d.STAGE_WON, d.STAGE_LOST]),
        Opportunity.closed_at >= since,
    )
    if user_id:
        q = q.where(Opportunity.user_id == user_id)
    closed = list((await session.execute(q)).scalars().all())
    won_list = [o for o in closed if o.stage == d.STAGE_WON]
    lost_list = [o for o in closed if o.stage == d.STAGE_LOST]
    reasons = Counter(o.lost_reason or "unknown" for o in lost_list)
    cycles = [(o.closed_at - o.created_at).days for o in won_list if o.closed_at]
    win_loss = {
        "window_days": window,
        "won": len(won_list),
        "lost": len(lost_list),
        "win_rate": _round(len(won_list) / len(closed) * 100) if closed else None,
        "avg_deal": _round(_mean([_f(o.amount) for o in won_list]), 0),
        "avg_cycle_days": _round(_mean([float(c) for c in cycles]), 0),
        "lost_reasons": [
            {"reason": key, "label": d.LOST_REASONS.get(key, "Non renseigné"), "count": n}
            for key, n in reasons.most_common()
        ],
    }

    reached: Counter = Counter()
    ev = (
        select(OpportunityStageEvent.to_stage, func.count(func.distinct(OpportunityStageEvent.opportunity_id)))
        .join(Opportunity, Opportunity.id == OpportunityStageEvent.opportunity_id)
        .where(Opportunity.organization_id == org_id, Opportunity.created_at >= as_of - timedelta(days=270))
    )
    if user_id:
        ev = ev.where(Opportunity.user_id == user_id)
    for stage, n in (await session.execute(ev.group_by(OpportunityStageEvent.to_stage))).all():
        reached[stage] = n
    chain = [*d.OPEN_STAGES, d.STAGE_WON]
    conversion = [
        {
            "from": a,
            "to": b,
            "from_label": d.STAGE_LABELS[a],
            "to_label": d.STAGE_LABELS[b],
            "reached_from": reached[a],
            "reached_to": reached[b],
            "rate": _round(reached[b] / reached[a] * 100) if reached[a] else None,
        }
        for a, b in zip(chain, chain[1:], strict=False)
    ]

    horizon = as_of.date() + timedelta(days=30)
    closing = [x for x in deals if x["expected_close_date"] and date.fromisoformat(x["expected_close_date"]) <= horizon]
    closing.sort(key=lambda x: x["expected_close_date"])
    return {
        "as_of": as_of.isoformat(),
        "quarter": {
            "start": quarter_start.isoformat(),
            "end": quarter_end.isoformat(),
            "days_left": (quarter_end - as_of.date()).days,
        },
        "open": {
            "count": len(deals),
            "amount": sum(x["amount"] for x in deals),
            "weighted": sum(x["weighted"] for x in deals),
            "stale_count": sum(1 for x in deals if x["health"] == "stale"),
            "stale_amount": sum(x["amount"] for x in deals if x["health"] == "stale"),
        },
        "team": {
            "quarter_quota": team_quota,
            "won_qtd": team_won,
            "gap": team_gap,
            "open_in_quarter": team_open_q,
            "coverage": coverage,
            "coverage_target": d.PIPELINE_COVERAGE_TARGET,
            "pipeline_needed": needed,
        },
        "by_stage": stage_rows,
        "by_rep": rep_rows,
        "deals": deals,
        "closing_30d": closing,
        "win_loss": win_loss,
        "stage_conversion": conversion,
    }


async def whitespace_accounts(
    session: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID | None,
    as_of: datetime,
    stale_days: int = 14,
    limit: int = 40,
) -> list[dict]:
    """Comptes cibles à travailler en priorité : jamais touchés ou délaissés, tier A d'abord."""
    cutoff = as_of - timedelta(days=stale_days)
    open_opp = select(Opportunity.account_id).where(Opportunity.stage.in_(d.OPEN_STAGES)).scalar_subquery()
    q = (
        select(Account, AppUser.public_ref, AppUser.alias)
        .join(AppUser, AppUser.id == Account.owner_user_id)
        .where(
            Account.organization_id == org_id,
            Account.kind == "prospect",
            Account.status == "active",
            (Account.last_activity_at.is_(None)) | (Account.last_activity_at < cutoff),
            Account.id.not_in(open_opp),
        )
        .order_by(Account.tier, Account.last_activity_at.asc().nulls_first(), Account.name)
        .limit(limit)
    )
    if user_id:
        q = q.where(Account.owner_user_id == user_id)
    out = []
    for account, user_ref, alias in (await session.execute(q)).all():
        out.append(
            {
                "ref": account.public_ref,
                "name": account.name,
                "industry": account.industry,
                "segment": account.segment,
                "tier": account.tier,
                "source": account.source,
                "user_ref": user_ref,
                "alias": alias,
                "days_since_touch": _days_between(as_of, account.last_activity_at),
                "never_touched": account.last_activity_at is None,
            }
        )
    return out


def _points(metrics: dict[str, float]) -> int:
    return int(sum(metrics.get(key, 0) * weight for key, weight in d.POINTS.items()))


def _streak(index_by_week: dict[date, float], completed: list[date]) -> int:
    streak = 0
    for week in reversed(completed):
        if index_by_week.get(week, 0) >= 90:
            streak += 1
        else:
            break
    return streak


async def team_summary(
    session: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID | None,
    as_of: datetime | None = None,
) -> dict[str, Any]:
    as_of = as_of or d.utcnow()
    weeks = week_list(as_of)
    current = weeks[-1]
    progress = d.week_progress(as_of)
    completed = weeks[:-1] if progress < 1.0 else weeks

    users = await load_users(session, org_id, user_id)
    targets = await load_targets(session, org_id, as_of)
    metrics = await weekly_metrics(session, org_id, user_id, weeks[0], as_of)
    upcoming = await upcoming_meetings(session, org_id, user_id, as_of)
    tier_a = await tier_a_coverage(session, org_id, user_id, as_of)
    flow = await funnel(session, org_id, user_id, as_of)
    flow["by_user"] = {u.public_ref: flow["by_user"].get(str(u.id), []) for u in users}
    pipe = await pipeline(session, org_id, user_id, as_of, targets)
    pipe_by_rep = {row["user_ref"]: row for row in pipe["by_rep"]}

    reps, weekly_rows = [], []
    team_actual: dict[str, float] = defaultdict(float)
    team_target: dict[str, float] = defaultdict(float)
    for user in users:
        tg = targets.weekly(user.id)
        actual = metrics.get((user.id, current), {})
        index_by_week = {w: hunting_index(metrics.get((user.id, w), {}), tg) for w in weeks}
        index = index_by_week[current]
        pace_index = round(index / progress, 1)
        recent = _sum_weeks(metrics, user.id, weeks[-RATIO_WEEKS:])
        long = _sum_weeks(metrics, user.id, weeks[-8:])
        touches = recent.get("calls", 0) + recent.get("emails", 0) + recent.get("linkedin", 0)
        hours_total = recent.get("hours_selling", 0) + recent.get("hours_farming", 0) + recent.get("hours_internal", 0)
        last2 = _mean([index_by_week[w] for w in completed[-2:]])
        prev4 = _mean([index_by_week[w] for w in completed[-6:-2]])
        tier = tier_a.get(user.id)
        pipe_row = pipe_by_rep.get(user.public_ref, {})
        reps.append(
            {
                "user_ref": user.public_ref,
                "alias": user.alias or user.public_ref,
                "targets": tg,
                "actuals": {k: _round(actual.get(k, 0), 0) for k in tg},
                "attainment": {k: _round(actual.get(k, 0) / tg[k] * 100, 0) if tg[k] else None for k in tg},
                "hunting_index": index,
                "pace_index": pace_index,
                "status": pace_status(pace_index, progress),
                "streak_weeks": _streak(index_by_week, completed),
                "trend": {"last_2_weeks": _round(last2), "previous_4_weeks": _round(prev4)},
                "ratios": {
                    "call_connect_rate": _round(recent["conv_calls"] / recent["calls"] * 100)
                    if recent.get("calls", 0) >= 10
                    else None,
                    "touches_4w": int(touches),
                    "meetings_booked_4w": int(recent.get("meetings_booked", 0)),
                    "touches_per_meeting": _round(touches / recent["meetings_booked"])
                    if recent.get("meetings_booked", 0) > 0
                    else None,
                    "meeting_to_opportunity": _round(long["opportunities_created"] / long["meetings_discovery"] * 100)
                    if long.get("meetings_discovery", 0) >= 3
                    else None,
                },
                "time_allocation": {
                    "selling": _round(recent.get("hours_selling", 0)),
                    "farming": _round(recent.get("hours_farming", 0)),
                    "internal": _round(recent.get("hours_internal", 0)),
                    "farming_share": _round(recent.get("hours_farming", 0) / hours_total * 100)
                    if hours_total
                    else None,
                },
                "tier_a_coverage_30d": _round(tier["touched"] / tier["total"] * 100, 0)
                if tier and tier["total"]
                else None,
                "tier_a_total": tier["total"] if tier else 0,
                "meetings_next_7d": upcoming.get(user.id, 0),
                "pipeline": {
                    k: pipe_row.get(k)
                    for k in (
                        "open_amount",
                        "weighted",
                        "coverage",
                        "gap",
                        "quarter_quota",
                        "won_qtd",
                        "stale_count",
                        "stale_amount",
                        "next_step_issues",
                    )
                },
            }
        )
        for key in tg:
            team_actual[key] += actual.get(key, 0)
            team_target[key] += tg[key]
        for week in weeks:
            row = metrics.get((user.id, week), {})
            weekly_rows.append(
                {
                    "week_start": week.isoformat(),
                    "user_ref": user.public_ref,
                    "alias": user.alias or user.public_ref,
                    "hunting_index": index_by_week[week],
                    **{k: _round(row.get(k, 0), 1) for k in (*tg, "conversations", "won_deals", "revenue_won")},
                }
            )

    on_track = sum(1 for r in reps if r["status"] in ("on_track", "early"))
    team_index = round(sum(r["hunting_index"] for r in reps) / len(reps), 1) if reps else 0.0
    team = {
        "hunting_index": team_index,
        "pace_index": round(team_index / progress, 1),
        "actuals": {k: _round(v, 0) for k, v in team_actual.items()},
        "targets": dict(team_target),
        "attainment": {
            k: _round(team_actual[k] / team_target[k] * 100, 0) if team_target[k] else None for k in team_target
        },
        "reps_total": len(reps),
        "reps_on_track": on_track,
        "reps_at_risk": sum(1 for r in reps if r["status"] == "at_risk"),
        "meetings_next_7d": sum(r["meetings_next_7d"] for r in reps),
    }
    return {
        "as_of": as_of.isoformat(),
        "week": {
            "start": current.isoformat(),
            "end": (current + timedelta(days=6)).isoformat(),
            "progress": round(progress, 2),
        },
        "metrics": {key: spec["label"] for key, spec in d.HUNTING_METRICS.items()}
        | {"pipeline_created": d.OTHER_TARGET_METRICS["pipeline_created"]["label"]},
        "team": team,
        "reps": reps,
        "weekly": weekly_rows,
        "funnel": flow,
        "pipeline": {
            "open": pipe["open"],
            "team": pipe["team"],
            "win_loss": pipe["win_loss"],
        },
    }


async def challenge_values(
    session: AsyncSession, org_id: uuid.UUID, challenge: Challenge, as_of: datetime
) -> dict[uuid.UUID, float]:
    start = _day_start(challenge.starts_on)
    end = min(_day_start(challenge.ends_on + timedelta(days=1)), as_of)
    metric = challenge.metric
    act = [
        Activity.organization_id == org_id,
        Activity.is_hunting.is_(True),
        Activity.occurred_at >= start,
        Activity.occurred_at < end,
    ]
    if metric == "calls":
        q = select(Activity.user_id, func.count()).where(*act, Activity.type == "call").group_by(Activity.user_id)
    elif metric == "conversations":
        q = (
            select(Activity.user_id, func.count())
            .where(*act, Activity.outcome.in_(d.CONVERSATION_OUTCOMES))
            .group_by(Activity.user_id)
        )
    elif metric == "meetings_booked":
        q = (
            select(Activity.user_id, func.count())
            .where(*act, Activity.outcome == "meeting_booked")
            .group_by(Activity.user_id)
        )
    elif metric == "accounts_touched":
        q = (
            select(Activity.user_id, func.count(func.distinct(Activity.account_id)))
            .where(*act)
            .group_by(Activity.user_id)
        )
    else:
        opp = [Opportunity.organization_id == org_id]
        if metric in ("opportunities_created", "pipeline_created"):
            opp += [
                Opportunity.created_at >= start,
                Opportunity.created_at < end,
                Opportunity.source == "outbound",
                Opportunity.is_new_logo.is_(True),
            ]
            value = (
                func.count() if metric == "opportunities_created" else func.coalesce(func.sum(Opportunity.amount), 0)
            )
        else:
            opp += [Opportunity.stage == d.STAGE_WON, Opportunity.closed_at >= start, Opportunity.closed_at < end]
            value = func.count()
        q = select(Opportunity.user_id, value).where(*opp).group_by(Opportunity.user_id)
    return {uid: _f(v) for uid, v in (await session.execute(q)).all()}


async def engagement(
    session: AsyncSession, org_id: uuid.UUID, viewer_user_id: uuid.UUID | None, as_of: datetime | None = None
) -> dict[str, Any]:
    """Classement, séries, badges et challenges. Visible par tous les rôles (alias et points uniquement)."""
    as_of = as_of or d.utcnow()
    weeks = week_list(as_of, 8)
    current = weeks[-1]
    progress = d.week_progress(as_of)
    completed = weeks[:-1] if progress < 1.0 else weeks

    users = await load_users(session, org_id)
    targets = await load_targets(session, org_id, as_of)
    metrics = await weekly_metrics(session, org_id, None, weeks[0], as_of)

    rows = []
    for user in users:
        tg = targets.weekly(user.id)
        index_by_week = {w: hunting_index(metrics.get((user.id, w), {}), tg) for w in weeks}
        week_metrics = metrics.get((user.id, current), {})
        month = _sum_weeks(metrics, user.id, weeks[-4:])
        rows.append(
            {
                "user_ref": user.public_ref,
                "alias": user.alias or user.public_ref,
                "is_me": viewer_user_id == user.id,
                "points_week": _points(week_metrics),
                "points_30d": _points(month),
                "streak_weeks": _streak(index_by_week, completed),
                "hunting_index": index_by_week[current],
                "_week": week_metrics,
            }
        )
    rows.sort(key=lambda r: (-r["points_week"], -r["points_30d"]))

    def leader(metric: str) -> str | None:
        best = max(rows, key=lambda r: r["_week"].get(metric, 0), default=None)
        return best["user_ref"] if best and best["_week"].get(metric, 0) > 0 else None

    awards = {
        "accounts_touched": ("Chasseur de la semaine", leader("accounts_touched")),
        "meetings_booked": ("Machine à RDV", leader("meetings_booked")),
        "pipeline_created": ("Rainmaker", leader("pipeline_created")),
        "calls": ("Bulldozer du téléphone", leader("calls")),
    }
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
        badges = [label for label, ref in awards.values() if ref == row["user_ref"]]
        if row["hunting_index"] >= 100:
            badges.append("Objectifs atteints")
        if row["streak_weeks"] >= 3:
            badges.append(f"Série de {row['streak_weeks']} semaines")
        row["badges"] = badges
        del row["_week"]

    challenges = (
        (
            await session.execute(
                select(Challenge)
                .where(Challenge.organization_id == org_id, Challenge.ends_on >= as_of.date() - timedelta(days=21))
                .order_by(Challenge.ends_on)
            )
        )
        .scalars()
        .all()
    )
    alias_by_id = {u.id: (u.public_ref, u.alias or u.public_ref) for u in users}
    out_challenges = []
    for ch in challenges:
        values = await challenge_values(session, org_id, ch, as_of)
        target = float(ch.target_value)
        today = as_of.date()
        status = "upcoming" if ch.starts_on > today else ("ended" if ch.ends_on < today else "active")
        progress_rows = sorted(
            (
                {
                    "user_ref": ref,
                    "alias": alias,
                    "is_me": viewer_user_id == uid,
                    "value": values.get(uid, 0.0),
                    "pct": _round(values.get(uid, 0.0) / target * 100, 0) if target else None,
                }
                for uid, (ref, alias) in alias_by_id.items()
            ),
            key=lambda r: -r["value"],
        )
        team_value = sum(values.get(uid, 0.0) for uid in alias_by_id)
        out_challenges.append(
            {
                "id": str(ch.id),
                "name": ch.name,
                "description": ch.description,
                "metric": ch.metric,
                "metric_label": d.CHALLENGE_METRICS.get(ch.metric, ch.metric),
                "scope": ch.scope,
                "target": target,
                "starts_on": ch.starts_on.isoformat(),
                "ends_on": ch.ends_on.isoformat(),
                "days_left": max((ch.ends_on - today).days, 0),
                "status": status,
                "reward_points": ch.reward_points,
                "progress": progress_rows,
                "team_value": team_value,
                "team_pct": _round(team_value / target * 100, 0) if target and ch.scope == "team" else None,
            }
        )
    return {
        "as_of": as_of.isoformat(),
        "leaderboard": rows,
        "challenges": out_challenges,
        "points_rules": d.POINTS,
    }
