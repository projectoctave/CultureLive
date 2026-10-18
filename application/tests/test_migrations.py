"""Les migrations Alembic créent le schéma, restent alignées avec les modèles et sont réversibles."""

import uuid

import asyncpg
import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from backend.config import get_settings
from backend.db.migrate import alembic_config, upgrade_head
from backend.db.models import Base
from tests.conftest import run_in_thread

pytestmark = pytest.mark.db_live

EXPECTED_TABLES = {
    "organizations",
    "app_users",
    "oauth_connections",
    "dashboard_accounts",
    "sales_referentials",
    "meeting_classifications",
    "accounts",
    "activities",
    "opportunities",
    "opportunity_stage_events",
    "sales_targets",
    "challenges",
    "coaching_actions",
    "alembic_version",
}


@pytest.fixture
async def scratch_database_url():
    base = make_url(get_settings().database_url)
    name = f"culturelive_migr_{uuid.uuid4().hex[:8]}"
    admin_dsn = base.set(drivername="postgresql", database="postgres").render_as_string(hide_password=False)
    try:
        admin = await asyncpg.connect(admin_dsn)
    except Exception as exc:
        pytest.skip(f"Connexion admin PostgreSQL impossible: {exc}")
    try:
        await admin.execute(f'CREATE DATABASE "{name}"')
    except Exception as exc:
        await admin.close()
        pytest.skip(f"Droit CREATEDB requis: {exc}")
    try:
        yield base.set(database=name).render_as_string(hide_password=False)
    finally:
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await admin.close()


async def test_migrations_up_match_models_and_down(scratch_database_url):
    run_in_thread(upgrade_head, scratch_database_url)

    engine = create_async_engine(scratch_database_url)
    try:
        async with engine.connect() as conn:
            tables = await conn.run_sync(lambda c: set(inspect(c).get_table_names()))
            assert EXPECTED_TABLES <= tables

            diff = await conn.run_sync(
                lambda c: compare_metadata(MigrationContext.configure(c, opts={"compare_type": True}), Base.metadata)
            )
            assert diff == [], f"Les modèles divergent des migrations: {diff}"
    finally:
        await engine.dispose()

    run_in_thread(command.downgrade, alembic_config(scratch_database_url), "base")

    engine = create_async_engine(scratch_database_url)
    try:
        async with engine.connect() as conn:
            tables = await conn.run_sync(lambda c: set(inspect(c).get_table_names()))
            assert tables <= {"alembic_version"}
    finally:
        await engine.dispose()
