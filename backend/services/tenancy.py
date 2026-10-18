import hashlib
import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import AppUser, Organization, OAuthConnection


def _public_ref(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(4)}"


def organization_ref_from_email(email: str) -> str:
    """Identifiant entreprise stable mais non réversible (domaine hashé)."""
    domain = email.split("@")[-1].lower()
    digest = hashlib.sha256(domain.encode()).hexdigest()[:10]
    return f"org_{digest}"


async def get_or_create_user_for_google(session: AsyncSession, email: str) -> tuple[AppUser, Organization]:
    domain = email.split("@")[-1].lower()
    org_ref = organization_ref_from_email(email)

    org_result = await session.execute(select(Organization).where(Organization.public_ref == org_ref))
    org = org_result.scalars().first()
    if not org:
        org = Organization(public_ref=org_ref)
        session.add(org)
        await session.flush()

    user_ref_seed = hashlib.sha256(f"{org_ref}:{email.lower()}".encode()).hexdigest()[:10]
    user_ref = f"usr_{user_ref_seed}"

    user_result = await session.execute(select(AppUser).where(AppUser.public_ref == user_ref))
    user = user_result.scalars().first()
    if not user:
        user = AppUser(organization_id=org.id, public_ref=user_ref)
        session.add(user)
        await session.flush()

    _ = domain  # réservé pour évolutions multi-tenant
    return user, org


async def get_oauth_connection(session: AsyncSession, user_id) -> OAuthConnection | None:
    result = await session.execute(select(OAuthConnection).where(OAuthConnection.user_id == user_id))
    return result.scalars().first()
