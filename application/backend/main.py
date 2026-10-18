import json
import logging
import secrets
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from backend.config import Settings, get_settings
from backend.crypto import decrypt_text, encrypt_text
from backend.db.models import (
    AppUser,
    DashboardAccount,
    MeetingClassification,
    OAuthConnection,
    Organization,
    SalesReferential,
)
from backend.db.session import dispose_engine, get_db
from backend.deps import resolve_stats_scope
from backend.routers.coach import router as coach_router
from backend.services.auth import (
    DashboardRole,
    StatsScope,
    create_access_token,
    verify_password,
)
from backend.services.referential import SalesReferentialPayload, ensure_active_referential
from backend.services.sync import sync_users
from backend.services.tenancy import get_oauth_connection, get_or_create_user_for_google
from integration.google_calendar import create_event, list_events
from integration.google_oauth import authorization_url, exchange_code

logger = logging.getLogger("culturelive.api")

OAUTH_STATE_TTL_SECONDS = 600
_oauth_states: dict[str, float] = {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    problems = get_settings().startup_problems()
    if problems:
        raise RuntimeError("Configuration invalide : " + " ; ".join(problems))
    if not get_settings().google_configured():
        logger.warning("Google OAuth non configuré : routes Calendar indisponibles")
    yield
    await dispose_engine()


app = FastAPI(title="CultureLive API", version="0.3.0", lifespan=lifespan)
app.include_router(coach_router)


def require_admin_key(
    settings: Settings = Depends(get_settings),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> None:
    expected = settings.dashboard_api_key
    if not expected or not x_api_key or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(401, "Clé API admin requise (en-tête X-API-Key)")


def require_google(settings: Settings = Depends(get_settings)) -> None:
    if not settings.google_configured():
        raise HTTPException(503, "Google OAuth non configuré")


class LoginBody(BaseModel):
    login: str
    password: str


class CreateMeetingBody(BaseModel):
    summary: str
    description: str | None = None
    start: str = Field(description="ISO 8601")
    end: str
    time_zone: str = "Europe/Paris"


class ClassifyRangeBody(BaseModel):
    time_min: str
    time_max: str
    user_id: uuid.UUID | None = None
    force: bool = Field(default=False, description="Reclassifier même les événements inchangés")


@app.get("/health")
async def health(session: AsyncSession = Depends(get_db)) -> dict:
    await session.execute(select(1))
    return {"status": "ok", "service": "culturelive", "database": "ok"}


@app.post("/auth/dashboard/login")
async def dashboard_login(
    body: LoginBody,
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    result = await session.execute(select(DashboardAccount).where(DashboardAccount.login == body.login))
    account = result.scalars().first()
    if not account or not verify_password(body.password, account.password_hash):
        raise HTTPException(401, "Identifiants invalides")

    org = await session.get(Organization, account.organization_id)
    if not org:
        raise HTTPException(500, "Organisation introuvable")

    user_ref: str | None = None
    user_id: str | None = None
    if account.user_id:
        user = await session.get(AppUser, account.user_id)
        if user:
            user_ref = user.public_ref
            user_id = str(user.id)

    role = DashboardRole(account.role)
    token = create_access_token(
        settings,
        {
            "sub": account.login,
            "role": role.value,
            "organization_ref": org.public_ref,
            "organization_id": str(org.id),
            "user_ref": user_ref,
            "user_id": user_id,
        },
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "role": role.value,
        "organization_ref": org.public_ref,
        "user_ref": user_ref,
        "display_name": org.display_name,
    }


@app.get("/auth/google", dependencies=[Depends(require_google)])
async def auth_google(settings: Settings = Depends(get_settings)):
    now = time.time()
    for key in [k for k, ts in _oauth_states.items() if now - ts > OAUTH_STATE_TTL_SECONDS]:
        del _oauth_states[key]
    state = secrets.token_urlsafe(16)
    _oauth_states[state] = now
    return {"authorization_url": authorization_url(settings, state)}


@app.get("/auth/google/callback", dependencies=[Depends(require_google)])
async def auth_google_callback(
    code: str,
    state: str,
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    issued_at = _oauth_states.pop(state, None)
    if issued_at is None or time.time() - issued_at > OAUTH_STATE_TTL_SECONDS:
        raise HTTPException(400, "State OAuth invalide ou expiré")

    refresh_token, email = await run_in_threadpool(exchange_code, settings, code)
    user, org = await get_or_create_user_for_google(session, email)

    encrypted = encrypt_text(refresh_token, settings.token_encryption_key or "")
    existing = await get_oauth_connection(session, user.id)
    if existing:
        existing.encrypted_refresh_token = encrypted
    else:
        session.add(OAuthConnection(user_id=user.id, encrypted_refresh_token=encrypted))
    await session.commit()

    return {
        "connected": True,
        "user_id": str(user.id),
        "user_ref": user.public_ref,
        "organization_ref": org.public_ref,
    }


async def _refresh_token_for_user(session: AsyncSession, user_id: uuid.UUID, settings: Settings) -> str:
    conn = await get_oauth_connection(session, user_id)
    if not conn:
        raise HTTPException(404, "Aucune connexion Google pour cet utilisateur")
    return decrypt_text(conn.encrypted_refresh_token, settings.token_encryption_key or "")


@app.post("/meetings", dependencies=[Depends(require_admin_key), Depends(require_google)])
async def post_meeting(
    body: CreateMeetingBody,
    user_id: uuid.UUID = Query(..., description="UUID interne utilisateur"),
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    token = await _refresh_token_for_user(session, user_id, settings)
    event = await run_in_threadpool(
        create_event,
        settings,
        token,
        body.summary,
        body.start,
        body.end,
        body.description,
        body.time_zone,
    )
    return {
        "id": event.id,
        "summary": event.title,
        "start": event.start.isoformat(),
        "end": event.end.isoformat(),
        "html_link": event.html_link,
    }


@app.get("/meetings", dependencies=[Depends(require_admin_key), Depends(require_google)])
async def get_meetings(
    time_min: str,
    time_max: str,
    user_id: uuid.UUID = Query(...),
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    token = await _refresh_token_for_user(session, user_id, settings)
    events = await run_in_threadpool(list_events, settings, token, time_min, time_max)
    return {
        "count": len(events),
        "items": [
            {
                "id": e.id,
                "summary": e.title,
                "description": e.description,
                "start": e.start.isoformat(),
                "end": e.end.isoformat(),
                "html_link": e.html_link,
            }
            for e in events
        ],
    }


@app.get("/referential", dependencies=[Depends(require_admin_key)])
async def get_referential(session: AsyncSession = Depends(get_db)):
    _, payload = await ensure_active_referential(session)
    return payload.model_dump()


@app.put("/referential", dependencies=[Depends(require_admin_key)])
async def put_referential(payload: SalesReferentialPayload, session: AsyncSession = Depends(get_db)):
    await session.execute(update(SalesReferential).where(SalesReferential.is_active.is_(True)).values(is_active=False))
    row = SalesReferential(
        name=payload.name,
        version=payload.version,
        payload=json.loads(payload.model_dump_json()),
        is_active=True,
    )
    session.add(row)
    await session.commit()
    return {"updated": True, "referential_id": str(row.id)}


@app.post("/classify/sync", dependencies=[Depends(require_admin_key), Depends(require_google)])
async def classify_sync(
    body: ClassifyRangeBody,
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    user_ids = [body.user_id] if body.user_id else None
    if body.user_id and not await get_oauth_connection(session, body.user_id):
        raise HTTPException(404, "Aucune connexion Google pour cet utilisateur")
    if user_ids is None:
        connected = await session.execute(select(func.count()).select_from(OAuthConnection))
        if connected.scalar_one() == 0:
            raise HTTPException(404, "Aucun utilisateur connecté à Google")

    result = await sync_users(session, settings, body.time_min, body.time_max, user_ids, body.force)
    return result.as_dict()


def _scope_filters(scope: StatsScope) -> list:
    filters = []
    if scope.is_superadmin:
        return filters
    if scope.organization_id:
        filters.append(MeetingClassification.organization_id == uuid.UUID(scope.organization_id))
    if scope.role == DashboardRole.SALES_USER and scope.user_id:
        filters.append(MeetingClassification.user_id == uuid.UUID(scope.user_id))
    return filters


@app.get("/stats/overview")
async def stats_overview(
    scope: StatsScope = Depends(resolve_stats_scope),
    session: AsyncSession = Depends(get_db),
):
    filters = _scope_filters(scope)

    org_q = (
        select(Organization.public_ref, func.count(MeetingClassification.id))
        .join(MeetingClassification, MeetingClassification.organization_id == Organization.id)
        .group_by(Organization.public_ref)
    )
    user_q = (
        select(AppUser.public_ref, func.count(MeetingClassification.id))
        .join(MeetingClassification, MeetingClassification.user_id == AppUser.id)
        .group_by(AppUser.public_ref)
    )
    cat_q = select(
        MeetingClassification.category_id,
        MeetingClassification.category_label,
        func.count(),
    ).group_by(MeetingClassification.category_id, MeetingClassification.category_label)

    for f in filters:
        org_q = org_q.where(f)
        user_q = user_q.where(f)
        cat_q = cat_q.where(f)

    by_org = await session.execute(org_q)
    by_user = await session.execute(user_q)
    by_category = await session.execute(cat_q)
    return {
        "scope": {
            "role": scope.role.value if scope.role else "superadmin",
            "organization_ref": scope.organization_ref,
            "user_ref": scope.user_ref,
        },
        "by_organization": [{"organization_ref": r[0], "meetings": r[1]} for r in by_org.all()],
        "by_user": [{"user_ref": r[0], "meetings": r[1]} for r in by_user.all()],
        "by_category": [{"category_id": r[0], "label": r[1], "count": r[2]} for r in by_category.all()],
    }


@app.get("/stats/meetings")
async def stats_meetings(
    organization_ref: str | None = None,
    user_ref: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
    scope: StatsScope = Depends(resolve_stats_scope),
    session: AsyncSession = Depends(get_db),
):
    q = (
        select(
            MeetingClassification.title,
            MeetingClassification.category_label,
            MeetingClassification.confidence,
            MeetingClassification.start_at,
            AppUser.public_ref,
            Organization.public_ref,
        )
        .join(AppUser, AppUser.id == MeetingClassification.user_id)
        .join(Organization, Organization.id == MeetingClassification.organization_id)
        .order_by(MeetingClassification.start_at.desc())
        .limit(limit)
    )
    for f in _scope_filters(scope):
        q = q.where(f)

    if organization_ref:
        if scope.organization_ref and organization_ref != scope.organization_ref and not scope.is_superadmin:
            raise HTTPException(403, "Accès organisation refusé")
        q = q.where(Organization.public_ref == organization_ref)
    if user_ref:
        if scope.user_ref and user_ref != scope.user_ref and scope.role == DashboardRole.SALES_USER:
            raise HTTPException(403, "Accès utilisateur refusé")
        q = q.where(AppUser.public_ref == user_ref)

    rows = await session.execute(q)
    return [
        {
            "title": r[0],
            "category": r[1],
            "confidence": r[2],
            "start_at": r[3].isoformat(),
            "user_ref": r[4],
            "organization_ref": r[5],
        }
        for r in rows.all()
    ]
