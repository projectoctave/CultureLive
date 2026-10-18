#!/usr/bin/env python3
"""Charge PostgreSQL avec le jeu de données de démonstration (pilotage commercial, 12 semaines d'historique)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for candidate in (ROOT / "application", ROOT):
    if (candidate / "backend").is_dir() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from backend.db.migrate import upgrade_head  # noqa: E402
from backend.db.session import dispose_engine, get_session_factory  # noqa: E402
from backend.demo_data import seed_demo  # noqa: E402


async def seed() -> None:
    await asyncio.to_thread(upgrade_head)
    factory = get_session_factory()
    async with factory() as session:
        credentials = await seed_demo(session)

    print("\n=== CultureLive - données demo chargées ===\n")
    print("Comptes dashboard (rôle / login / mot de passe) :\n")
    for role, login, password in credentials:
        print(f"  [{role:10}] {login:16} / {password}")
    print("\nConnexion API : POST /auth/dashboard/login, puis dashboard Streamlit.\n")


async def main() -> None:
    try:
        await seed()
    finally:
        await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
