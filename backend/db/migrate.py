"""Application des migrations Alembic (`alembic upgrade head`) depuis Python ou la CLI."""

import sys
from pathlib import Path

from alembic import command
from alembic.config import Config

ROOT = Path(__file__).resolve().parents[2]


def alembic_config(database_url: str | None = None) -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "backend" / "migrations"))
    if database_url:
        cfg.attributes["database_url"] = database_url
    return cfg


def upgrade_head(database_url: str | None = None) -> None:
    command.upgrade(alembic_config(database_url), "head")


if __name__ == "__main__":
    upgrade_head()
    print("Migrations appliquées (head).", file=sys.stderr)
