"""Synchronisation Google Calendar -> classification -> PostgreSQL (incrémentale)."""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from backend.config import Settings
from backend.crypto import decrypt_text
from backend.db.models import AppUser, MeetingClassification, OAuthConnection
from backend.services.classifier import MeetingInput, classify_meeting
from backend.services.referential import SalesReferentialPayload, ensure_active_referential
from backend.services.tenancy import get_oauth_connection
from integration.google_calendar import list_events

logger = logging.getLogger("culturelive.sync")

LLM_CONCURRENCY = 5


@dataclass
class SyncResult:
    users: int = 0
    fetched: int = 0
    classified: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)

    def merge(self, other: "SyncResult") -> None:
        self.users += other.users
        self.fetched += other.fetched
        self.classified += other.classified
        self.skipped += other.skipped
        self.errors.extend(other.errors)

    def as_dict(self) -> dict:
        return {
            "users": self.users,
            "fetched": self.fetched,
            "classified": self.classified,
            "skipped": self.skipped,
            "errors": self.errors,
        }


async def sync_user(
    session: AsyncSession,
    settings: Settings,
    user: AppUser,
    referential_id: uuid.UUID,
    referential: SalesReferentialPayload,
    time_min: str,
    time_max: str,
    force: bool = False,
) -> SyncResult:
    result = SyncResult(users=1)

    connection = await get_oauth_connection(session, user.id)
    if connection is None:
        raise LookupError("Aucune connexion Google pour cet utilisateur")
    refresh_token = decrypt_text(connection.encrypted_refresh_token, settings.token_encryption_key or "")

    events = await run_in_threadpool(list_events, settings, refresh_token, time_min, time_max)
    result.fetched = len(events)
    if not events:
        return result

    existing_rows = await session.execute(
        select(
            MeetingClassification.google_event_id,
            MeetingClassification.title,
            MeetingClassification.description,
            MeetingClassification.referential_id,
        ).where(
            MeetingClassification.user_id == user.id,
            MeetingClassification.google_event_id.in_([e.id for e in events]),
        )
    )
    existing = {row[0]: row for row in existing_rows.all()}

    def unchanged(event) -> bool:
        prev = existing.get(event.id)
        return bool(
            prev
            and prev[1] == event.title
            and (prev[2] or None) == (event.description or None)
            and prev[3] == referential_id
        )

    to_classify = [e for e in events if force or not unchanged(e)]
    result.skipped = len(events) - len(to_classify)

    semaphore = asyncio.Semaphore(LLM_CONCURRENCY)

    async def classify(event):
        async with semaphore:
            return await classify_meeting(
                settings,
                MeetingInput(
                    event_id=event.id,
                    title=event.title,
                    description=event.description,
                    start_iso=event.start.isoformat(),
                    end_iso=event.end.isoformat(),
                ),
                referential,
            )

    classifications = await asyncio.gather(*(classify(e) for e in to_classify))

    for event, clf in zip(to_classify, classifications, strict=True):
        stmt = insert(MeetingClassification).values(
            google_event_id=event.id,
            calendar_id="primary",
            user_id=user.id,
            organization_id=user.organization_id,
            referential_id=referential_id,
            title=event.title,
            description=event.description,
            start_at=event.start,
            end_at=event.end,
            category_id=clf.category_id,
            category_label=clf.category_label,
            confidence=clf.confidence,
            rationale=clf.rationale,
            raw_event=event.raw,
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_event_user",
            set_={
                "referential_id": referential_id,
                "title": event.title,
                "description": event.description,
                "start_at": event.start,
                "end_at": event.end,
                "category_id": clf.category_id,
                "category_label": clf.category_label,
                "confidence": clf.confidence,
                "rationale": clf.rationale,
                "raw_event": event.raw,
                "classified_at": func.now(),
            },
        )
        await session.execute(stmt)

    await session.commit()
    result.classified = len(to_classify)
    return result


async def sync_users(
    session: AsyncSession,
    settings: Settings,
    time_min: str,
    time_max: str,
    user_ids: list[uuid.UUID] | None = None,
    force: bool = False,
) -> SyncResult:
    """Synchronise les utilisateurs donnés (ou tous ceux connectés à Google).

    Un utilisateur en échec (token révoqué, quota…) n'empêche pas les autres.
    """
    referential_row, referential = await ensure_active_referential(session)
    referential_id = referential_row.id

    if user_ids is None:
        rows = await session.execute(select(OAuthConnection.user_id).distinct())
        user_ids = [r[0] for r in rows.all()]

    total = SyncResult()
    for uid in user_ids:
        user = await session.get(AppUser, uid)
        if user is None:
            continue
        user_ref = user.public_ref
        try:
            total.merge(
                await sync_user(session, settings, user, referential_id, referential, time_min, time_max, force)
            )
        except Exception as exc:
            await session.rollback()
            logger.exception("Sync en échec pour %s", user_ref)
            total.users += 1
            total.errors.append(f"{user_ref}: {type(exc).__name__}: {exc}")
    return total
