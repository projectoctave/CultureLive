"""Batterie 1 — classification sur agenda sales fictif (sans Google)."""

import pytest

from backend.config import Settings
from backend.services.classifier import MeetingInput, classify_meeting
from backend.services.referential import SalesCategory, load_default_referential
from tests.fixtures.sales_agenda import SALES_AGENDA


@pytest.fixture
def settings_no_llm() -> Settings:
    return Settings(openai_api_key=None)


@pytest.mark.asyncio
@pytest.mark.parametrize("fixture", SALES_AGENDA, ids=lambda f: f.expected_category)
async def test_sales_typology_classification(settings_no_llm: Settings, fixture):
    referential = load_default_referential()
    result = await classify_meeting(
        settings_no_llm,
        MeetingInput(
            event_id="fixture",
            title=fixture.title,
            description=fixture.description,
        ),
        referential,
    )
    assert result.category_id == fixture.expected_category, (
        f"Attendu {fixture.expected_category}, obtenu {result.category_id} — {result.rationale}"
    )
    assert 0.0 <= result.confidence <= 1.0


@pytest.mark.asyncio
async def test_custom_referential_extra_category(settings_no_llm: Settings):
    referential = load_default_referential()
    referential.categories.append(
        SalesCategory(
            id="partner_call",
            label="Partenaire",
            description="Appel channel / alliance partenaire.",
        )
    )
    result = await classify_meeting(
        settings_no_llm,
        MeetingInput(
            event_id="x",
            title="Partner sync — revendeur VAR",
            description="Alliance go-to-market avec intégrateur.",
        ),
        referential,
    )
    assert result.category_id in {"partner_call", "other", "follow_up"}
