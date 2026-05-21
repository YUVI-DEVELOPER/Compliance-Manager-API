from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from alembic import command
from alembic.config import Config

from app.core.config import get_settings


logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def get_alembic_config() -> Config:
    settings = get_settings()
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)
    return config


def upgrade_to_head() -> None:
    logger.info("Applying database migrations")
    command.upgrade(get_alembic_config(), "head")
    logger.info("Database migrations are current")


async def upgrade_to_head_async() -> None:
    await asyncio.to_thread(upgrade_to_head)


def main() -> None:
    upgrade_to_head()


if __name__ == "__main__":
    main()
