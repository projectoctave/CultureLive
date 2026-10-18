"""API de pilotage commercial : prospection, pipeline, classement, coaching."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend import domain as d
from backend.db.models import Account, Activity, AppUser, Challenge, CoachingAction, SalesTarget
from backend.db.session import get_db
from backend.deps import CoachContext, coach_context, require_manager, user_by_ref
from backend.services import analytics
from backend.services.coaching import build_alerts

router = APIRouter(prefix="/coach", tags=["coach"])

ActivityType = Literal["call", "email", "linkedin"]
Outcome = Literal["no_response", "conversation", "meeting_booked", "not_interested"]
CoachingKind = Literal["nudge", "one_to_one", "call_shadowing", "training", "recognition"]


class ActivityBody(BaseModel):
    type: ActivityType
    outcome: Outcome = "no_response"
    account_ref: str | None = None
    user_ref: str | None = Field(default=None, description="Manager uniquement : commercial concerné")
    occurred_at: datetime | None = None
    duration_seconds: int | None = Field(default=None, ge=0)


class CoachingActionBody(BaseModel):
    user_ref: str
    kind: CoachingKind
    title: str = Field(min_length=3, max_length=256)
    note: str | None = Field(default=None, max_length=2000)
    related_metric: str | None = Field(default=None, max_length=64)
    due_on: date | None = None


class CoachingActionPatch(BaseModel):
    status: Literal["open", "done", "dismissed"]


class TargetBody(BaseModel):
    user_ref: str | None = Field(default=None, description="Vide = objectif par défaut de l'équipe")
    metric: str = Field(max_length=64)
    period: Literal["week", "quarter"] = "week"
    target_value: float = Field(ge=0)


class ChallengeBody(BaseModel):
    name: str = Field(min_length=3, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    metric: str = Field(max_length=64)
    scope: Literal["individual", "team"] = "individual"
    target_value: float = Field(gt=0)
    starts_on: date
    ends_on: date
    reward_points: int = Field(default=0, ge=0)


def _action_dict(action: CoachingAction, user: AppUser) -> dict:
    return {
        "id": str(action.id),
        "user_ref": user.public_ref,
        "alias": user.alias or user.public_ref,
        "created_by": action.created_by,
        "kind": action.kind,
        "kind_label": d.COACHING_KINDS.get(action.kind, action.kind),
        "title": action.title,
        "note": action.note,
        "related_metric": action.related_metric,
        "due_on": action.due_on.isoformat() if action.due_on else None,
        "status": action.status,
        "created_at": action.created_at.isoformat() if action.created_at else None,
        "completed_at": action.completed_at.isoformat() if action.completed_at else None,
    }


@router.get("/summary")
async def summary(ctx: CoachContext = Depends(coach_context), session: AsyncSession = Depends(get_db)):
    data = await analytics.team_summary(session, ctx.org_id, ctx.user_id)
    data["alerts"] = build_alerts(data)
    data["viewer"] = {"role": ctx.role.value if ctx.role else "superadmin", "is_manager": ctx.is_manager}
    return data


@router.get("/pipeline")
async def pipeline(ctx: CoachContext = Depends(coach_context), session: AsyncSession = Depends(get_db)):
    return await analytics.pipeline(session, ctx.org_id, ctx.user_id, d.utcnow())


@router.get("/accounts")
async def accounts_to_work(
    stale_days: int = Query(14, ge=1, le=180),
    limit: int = Query(40, ge=1, le=200),
    ctx: CoachContext = Depends(coach_context),
    session: AsyncSession = Depends(get_db),
):
    items = await analytics.whitespace_accounts(session, ctx.org_id, ctx.user_id, d.utcnow(), stale_days, limit)
    return {"stale_days": stale_days, "items": items}


@router.get("/engagement")
async def engagement(ctx: CoachContext = Depends(coach_context), session: AsyncSession = Depends(get_db)):
    return await analytics.engagement(session, ctx.org_id, ctx.user_id)


@router.get("/actions")
async def list_actions(
    status: Literal["open", "done", "dismissed", "all"] = "open",
    user_ref: str | None = None,
    ctx: CoachContext = Depends(coach_context),
    session: AsyncSession = Depends(get_db),
):
    q = (
        select(CoachingAction, AppUser)
        .join(AppUser, AppUser.id == CoachingAction.user_id)
        .where(CoachingAction.organization_id == ctx.org_id)
        .order_by(CoachingAction.due_on.asc().nulls_last(), CoachingAction.created_at.desc())
    )
    if ctx.user_id:
        q = q.where(CoachingAction.user_id == ctx.user_id)
    elif user_ref:
        q = q.where(AppUser.public_ref == user_ref)
    if status != "all":
        q = q.where(CoachingAction.status == status)
    rows = (await session.execute(q.limit(200))).all()
    return [_action_dict(action, user) for action, user in rows]


@router.post("/actions", status_code=201)
async def create_action(
    body: CoachingActionBody, ctx: CoachContext = Depends(require_manager), session: AsyncSession = Depends(get_db)
):
    user = await user_by_ref(session, ctx.org_id, body.user_ref)
    action = CoachingAction(
        organization_id=ctx.org_id,
        user_id=user.id,
        created_by=ctx.login,
        kind=body.kind,
        title=body.title,
        note=body.note,
        related_metric=body.related_metric,
        due_on=body.due_on,
    )
    session.add(action)
    await session.commit()
    await session.refresh(action)
    return _action_dict(action, user)


@router.patch("/actions/{action_id}")
async def update_action(
    action_id: uuid.UUID,
    body: CoachingActionPatch,
    ctx: CoachContext = Depends(coach_context),
    session: AsyncSession = Depends(get_db),
):
    action = await session.get(CoachingAction, action_id)
    if not action or action.organization_id != ctx.org_id:
        raise HTTPException(404, "Action introuvable")
    if ctx.user_id and action.user_id != ctx.user_id:
        raise HTTPException(403, "Action assignée à un autre commercial")
    action.status = body.status
    action.completed_at = d.utcnow() if body.status != "open" else None
    await session.commit()
    user = await session.get(AppUser, action.user_id)
    return _action_dict(action, user)


@router.put("/targets", status_code=200)
async def set_target(
    body: TargetBody, ctx: CoachContext = Depends(require_manager), session: AsyncSession = Depends(get_db)
):
    valid_metrics = {*d.HUNTING_METRICS, *d.OTHER_TARGET_METRICS}
    if body.metric not in valid_metrics:
        raise HTTPException(422, f"Indicateur inconnu. Valeurs possibles : {sorted(valid_metrics)}")
    user_id = (await user_by_ref(session, ctx.org_id, body.user_ref)).id if body.user_ref else None
    today = d.utcnow().date()
    existing = (
        (
            await session.execute(
                select(SalesTarget).where(
                    SalesTarget.organization_id == ctx.org_id,
                    SalesTarget.user_id.is_(user_id) if user_id is None else SalesTarget.user_id == user_id,
                    SalesTarget.metric == body.metric,
                    SalesTarget.period == body.period,
                    SalesTarget.valid_from == today,
                )
            )
        )
        .scalars()
        .first()
    )
    value = Decimal(str(body.target_value))
    if existing:
        existing.target_value = value
    else:
        session.add(
            SalesTarget(
                organization_id=ctx.org_id,
                user_id=user_id,
                metric=body.metric,
                period=body.period,
                target_value=value,
                valid_from=today,
            )
        )
    await session.commit()
    return {"updated": True, "metric": body.metric, "user_ref": body.user_ref, "target_value": body.target_value}


@router.post("/challenges", status_code=201)
async def create_challenge(
    body: ChallengeBody, ctx: CoachContext = Depends(require_manager), session: AsyncSession = Depends(get_db)
):
    if body.metric not in d.CHALLENGE_METRICS:
        raise HTTPException(422, f"Indicateur inconnu. Valeurs possibles : {sorted(d.CHALLENGE_METRICS)}")
    if body.ends_on < body.starts_on:
        raise HTTPException(422, "ends_on doit être postérieure à starts_on")
    challenge = Challenge(
        organization_id=ctx.org_id,
        name=body.name,
        description=body.description,
        metric=body.metric,
        scope=body.scope,
        target_value=Decimal(str(body.target_value)),
        starts_on=body.starts_on,
        ends_on=body.ends_on,
        reward_points=body.reward_points,
    )
    session.add(challenge)
    await session.commit()
    return {"id": str(challenge.id)}


@router.post("/activities", status_code=201)
async def log_activity(
    body: ActivityBody, ctx: CoachContext = Depends(coach_context), session: AsyncSession = Depends(get_db)
):
    """Saisie d'une action de prospection (ou import CRM). Un commercial ne saisit que pour lui-même."""
    if ctx.user_id:
        me = await session.get(AppUser, ctx.user_id)
        if body.user_ref and (me is None or body.user_ref != me.public_ref):
            raise HTTPException(403, "Un commercial ne peut saisir que ses propres activités")
        user_id = ctx.user_id
    else:
        if not body.user_ref:
            raise HTTPException(422, "user_ref requis pour un manager")
        user_id = (await user_by_ref(session, ctx.org_id, body.user_ref)).id

    account = None
    if body.account_ref:
        account = (
            (
                await session.execute(
                    select(Account).where(Account.organization_id == ctx.org_id, Account.public_ref == body.account_ref)
                )
            )
            .scalars()
            .first()
        )
        if not account:
            raise HTTPException(404, "Compte inconnu")
        if ctx.user_id and account.owner_user_id != ctx.user_id:
            raise HTTPException(403, "Compte attribué à un autre commercial")

    when = body.occurred_at or d.utcnow()
    activity = Activity(
        organization_id=ctx.org_id,
        user_id=user_id,
        account_id=account.id if account else None,
        type=body.type,
        outcome=body.outcome,
        is_hunting=account.kind == "prospect" if account else True,
        occurred_at=when,
        duration_seconds=body.duration_seconds,
        source="manual",
    )
    session.add(activity)
    if account:
        account.first_touch_at = account.first_touch_at or when
        if not account.last_activity_at or when > account.last_activity_at:
            account.last_activity_at = when
    await session.commit()
    return {"id": str(activity.id), "is_hunting": activity.is_hunting}
