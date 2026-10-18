"""Dépendances FastAPI partagées : authentification et périmètre de données."""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import Settings, get_settings
from backend.db.models import AppUser, Organization
from backend.db.session import get_db
from backend.services.auth import DashboardRole, StatsScope, decode_access_token


async def resolve_stats_scope(
    settings: Settings = Depends(get_settings),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None),
) -> StatsScope:
    if x_api_key and settings.dashboard_api_key and secrets.compare_digest(x_api_key, settings.dashboard_api_key):
        return StatsScope(is_superadmin=True)

    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        try:
            payload = decode_access_token(settings, token)
        except Exception as exc:
            raise HTTPException(401, "Token invalide") from exc
        return StatsScope(
            role=payload.role,
            organization_ref=payload.organization_ref,
            user_ref=payload.user_ref,
            organization_id=payload.organization_id,
            user_id=payload.user_id,
        )

    raise HTTPException(401, "Authentification requise (login ou X-API-Key)")


@dataclass
class CoachContext:
    """Périmètre résolu d'une requête de pilotage : une organisation, éventuellement un seul commercial."""

    org_id: uuid.UUID
    org_ref: str
    role: DashboardRole | None
    user_id: uuid.UUID | None
    login: str

    @property
    def is_manager(self) -> bool:
        return self.role != DashboardRole.SALES_USER


async def coach_context(
    organization_ref: str | None = Query(default=None, description="Requis avec la clé admin"),
    scope: StatsScope = Depends(resolve_stats_scope),
    session: AsyncSession = Depends(get_db),
) -> CoachContext:
    if scope.is_superadmin:
        if not organization_ref:
            raise HTTPException(400, "organization_ref requis avec la clé admin")
        org = (
            (await session.execute(select(Organization).where(Organization.public_ref == organization_ref)))
            .scalars()
            .first()
        )
        if not org:
            raise HTTPException(404, "Organisation inconnue")
        return CoachContext(org.id, org.public_ref, None, None, "admin-key")

    if not scope.organization_id:
        raise HTTPException(403, "Organisation absente du jeton")
    user_id = uuid.UUID(scope.user_id) if scope.role == DashboardRole.SALES_USER and scope.user_id else None
    if scope.role == DashboardRole.SALES_USER and not user_id:
        raise HTTPException(403, "Compte commercial sans utilisateur rattaché")
    return CoachContext(
        uuid.UUID(scope.organization_id),
        scope.organization_ref or "",
        scope.role,
        user_id,
        scope.user_ref or scope.organization_ref or "user",
    )


async def require_manager(ctx: CoachContext = Depends(coach_context)) -> CoachContext:
    if not ctx.is_manager:
        raise HTTPException(403, "Réservé aux managers (org_admin)")
    return ctx


async def user_by_ref(session: AsyncSession, org_id: uuid.UUID, user_ref: str) -> AppUser:
    user = (
        (
            await session.execute(
                select(AppUser).where(AppUser.organization_id == org_id, AppUser.public_ref == user_ref)
            )
        )
        .scalars()
        .first()
    )
    if not user:
        raise HTTPException(404, "Commercial inconnu dans cette organisation")
    return user
