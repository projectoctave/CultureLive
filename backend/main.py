import secrets
import uuid
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import Settings, get_settings
from backend.crypto import decrypt_text, encrypt_text
from backend.db.models import MeetingClassification, OAuthConnection
from backend.db.session import get_db, init_db
from backend.services.classifier import MeetingInput, classify_meeting
from backend.services.referential import SalesReferentialPayload, ensure_active_referential, load_default_referential
from backend.db.models import DashboardAccount
from backend.services.auth import (
    DashboardRole,
    StatsScope,
    create_access_token,
    decode_access_token,
    verify_password,
)
from backend.services.tenancy import get_oauth_connection, get_or_create_user_for_google
from integration.google_calendar import create_event, list_events
from integration.google_oauth import authorization_url, exchange_code

app = FastAPI(title="CultureLive API", version="0.1.0")

_oauth_states: dict[str, datetime] = {}


class LoginBody(BaseModel):
    login: str
    password: str


async def resolve_stats_scope(
    settings: Settings = Depends(get_settings),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None),
) -> StatsScope:
    if settings.dashboard_api_key and x_api_key == settings.dashboard_api_key:
        return StatsScope(is_superadmin=True)

    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        if not settings.jwt_secret:
            raise HTTPException(503, "JWT_SECRET non configuré")
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


@app.post("/auth/dashboard/login")
async def dashboard_login(
    body: LoginBody,
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    if not settings.jwt_secret:
        raise HTTPException(503, "JWT_SECRET non configuré")

    result = await session.execute(select(DashboardAccount).where(DashboardAccount.login == body.login))
    account = result.scalars().first()
    if not account or not verify_password(body.password, account.password_hash):
        raise HTTPException(401, "Identifiants invalides")

    from backend.db.models import AppUser, Organization

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


@app.on_event("startup")
async def startup() -> None:
    await init_db()


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "culturelive"}


@app.get("/auth/google")
async def auth_google(settings: Settings = Depends(get_settings)):
    if not settings.google_configured():
        raise HTTPException(503, "Google OAuth non configuré")
    state = secrets.token_urlsafe(16)
    _oauth_states[state] = datetime.now(timezone.utc)
    return {"authorization_url": authorization_url(settings, state)}


@app.get("/auth/google/callback")
async def auth_google_callback(
    code: str,
    state: str,
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    if state not in _oauth_states:
        raise HTTPException(400, "State OAuth invalide")
    del _oauth_states[state]

    refresh_token, email = exchange_code(settings, code)
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


@app.post("/meetings")
async def post_meeting(
    body: CreateMeetingBody,
    user_id: uuid.UUID = Query(..., description="UUID interne utilisateur"),
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    if not settings.google_configured():
        raise HTTPException(503, "Google OAuth non configuré")
    token = await _refresh_token_for_user(session, user_id, settings)
    event = create_event(
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


@app.get("/meetings")
async def get_meetings(
    time_min: str,
    time_max: str,
    user_id: uuid.UUID = Query(...),
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    if not settings.google_configured():
        raise HTTPException(503, "Google OAuth non configuré")
    token = await _refresh_token_for_user(session, user_id, settings)
    events = list_events(settings, token, time_min, time_max)
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


@app.get("/referential")
async def get_referential(session: AsyncSession = Depends(get_db)):
    _, payload = await ensure_active_referential(session)
    return payload.model_dump()


@app.put("/referential")
async def put_referential(payload: SalesReferentialPayload, session: AsyncSession = Depends(get_db)):
    from backend.db.models import SalesReferential
    import json

    await session.execute(
        SalesReferential.__table__.update().where(SalesReferential.is_active.is_(True)).values(is_active=False)
    )
    row = SalesReferential(
        name=payload.name,
        version=payload.version,
        payload=json.loads(payload.model_dump_json()),
        is_active=True,
    )
    session.add(row)
    await session.commit()
    return {"updated": True, "referential_id": str(row.id)}


@app.post("/classify/sync")
async def classify_sync(
    body: ClassifyRangeBody,
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    if not settings.google_configured():
        raise HTTPException(503, "Google OAuth non configuré")

    ref_row, ref_payload = await ensure_active_referential(session)

    if body.user_id:
        user_ids = [body.user_id]
    else:
        result = await session.execute(select(OAuthConnection.user_id))
        user_ids = list({row[0] for row in result.all()})

    if not user_ids:
        raise HTTPException(404, "Aucun utilisateur connecté à Google")

    stored = 0
    for uid in user_ids:
        from backend.db.models import AppUser

        user = await session.get(AppUser, uid)
        if not user:
            continue
        token = await _refresh_token_for_user(session, uid, settings)
        events = list_events(settings, token, body.time_min, body.time_max)
        for ev in events:
            classification = await classify_meeting(
                settings,
                MeetingInput(
                    event_id=ev.id,
                    title=ev.title,
                    description=ev.description,
                    start_iso=ev.start.isoformat(),
                    end_iso=ev.end.isoformat(),
                ),
                ref_payload,
            )
            stmt = insert(MeetingClassification).values(
                google_event_id=ev.id,
                calendar_id="primary",
                user_id=user.id,
                organization_id=user.organization_id,
                referential_id=ref_row.id,
                title=ev.title,
                description=ev.description,
                start_at=ev.start,
                end_at=ev.end,
                category_id=classification.category_id,
                category_label=classification.category_label,
                confidence=classification.confidence,
                rationale=classification.rationale,
                raw_event=ev.raw,
            )
            stmt = stmt.on_conflict_do_update(
                constraint="uq_event_user",
                set_={
                    "category_id": classification.category_id,
                    "category_label": classification.category_label,
                    "confidence": classification.confidence,
                    "rationale": classification.rationale,
                    "classified_at": func.now(),
                },
            )
            await session.execute(stmt)
            stored += 1

    await session.commit()
    return {"classified": stored}


def _apply_scope_to_meetings(scope: StatsScope):
    q_filters = []
    if scope.is_superadmin:
        return q_filters
    if scope.organization_id:
        q_filters.append(MeetingClassification.organization_id == uuid.UUID(scope.organization_id))
    if scope.role == DashboardRole.SALES_USER and scope.user_id:
        q_filters.append(MeetingClassification.user_id == uuid.UUID(scope.user_id))
    return q_filters


@app.get("/stats/overview")
async def stats_overview(
    scope: StatsScope = Depends(resolve_stats_scope),
    session: AsyncSession = Depends(get_db),
):
    from backend.db.models import AppUser, Organization

    scope_filters = _apply_scope_to_meetings(scope)

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

    for f in scope_filters:
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
    limit: int = 100,
    scope: StatsScope = Depends(resolve_stats_scope),
    session: AsyncSession = Depends(get_db),
):
    from backend.db.models import AppUser, Organization

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
    for f in _apply_scope_to_meetings(scope):
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


@app.get("/dev/default-referential")
async def dev_default_referential():
    return load_default_referential().model_dump()
