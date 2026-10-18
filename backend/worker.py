"""Worker : synchronise périodiquement les agendas Google de tous les utilisateurs connectés.

`python -m backend.worker`               boucle de synchronisation
`python -m backend.worker --healthcheck` code retour 0 si le worker a tourné récemment
"""

import asyncio
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.config import Settings, get_settings
from backend.db.session import dispose_engine, get_session_factory
from backend.services.sync import SyncResult, sync_users

logger = logging.getLogger("culturelive.worker")

HEARTBEAT_FILE = Path(os.getenv("WORKER_HEARTBEAT_FILE", "/tmp/culturelive-worker.heartbeat"))


def _heartbeat() -> None:
    HEARTBEAT_FILE.touch()


def healthcheck(settings: Settings) -> bool:
    max_age = 2 * settings.sync_interval_minutes * 60 + 120
    try:
        return time.time() - HEARTBEAT_FILE.stat().st_mtime < max_age
    except FileNotFoundError:
        return False


async def run_once(settings: Settings) -> SyncResult:
    now = datetime.now(timezone.utc)
    time_min = (now - timedelta(days=settings.sync_lookback_days)).isoformat()
    time_max = (now + timedelta(days=settings.sync_lookahead_days)).isoformat()
    async with get_session_factory()() as session:
        return await sync_users(session, settings, time_min, time_max)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = get_settings()
    interval = max(1, settings.sync_interval_minutes) * 60
    logger.info("Worker démarré (intervalle %s min)", settings.sync_interval_minutes)

    try:
        while True:
            _heartbeat()
            if not settings.google_configured():
                logger.warning("Google OAuth non configuré — rien à synchroniser")
            else:
                try:
                    result = await run_once(settings)
                    logger.info("Sync terminée: %s", result.as_dict())
                except Exception:
                    logger.exception("Cycle de sync en échec")
            await asyncio.sleep(interval)
    finally:
        await dispose_engine()


if __name__ == "__main__":
    if "--healthcheck" in sys.argv:
        sys.exit(0 if healthcheck(get_settings()) else 1)
    asyncio.run(main())
