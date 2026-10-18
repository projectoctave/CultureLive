import json
from pathlib import Path

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import SalesReferential

REF_PATH = Path(__file__).resolve().parents[2] / "referential" / "sales-typology.json"


class SalesCategory(BaseModel):
    id: str
    label: str
    description: str


class SalesReferentialPayload(BaseModel):
    version: str
    name: str
    description: str | None = None
    categories: list[SalesCategory] = Field(min_length=1)


def load_default_referential() -> SalesReferentialPayload:
    return SalesReferentialPayload.model_validate_json(REF_PATH.read_text())


async def ensure_active_referential(session: AsyncSession) -> tuple[SalesReferential, SalesReferentialPayload]:
    result = await session.execute(
        select(SalesReferential).where(SalesReferential.is_active.is_(True)).order_by(SalesReferential.created_at.desc())
    )
    row = result.scalars().first()
    if row:
        return row, SalesReferentialPayload.model_validate(row.payload)

    payload = load_default_referential()
    row = SalesReferential(name=payload.name, version=payload.version, payload=json.loads(payload.model_dump_json()))
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row, payload
