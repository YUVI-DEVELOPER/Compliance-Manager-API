from __future__ import annotations

import asyncio
import logging

import asyncpg

from app.core.config import get_settings


logger = logging.getLogger(__name__)


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


async def ensure_database_exists() -> bool:
    settings = get_settings()
    if settings.APP_ENV.lower() == "production":
        raise RuntimeError("The dev database helper is not available when APP_ENV=production")

    connection = await asyncpg.connect(settings.asyncpg_admin_database_url)
    try:
        exists = await connection.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1",
            settings.database_name,
        )
        if exists:
            logger.info("Database %s already exists", settings.database_name)
            return False

        await connection.execute(f"CREATE DATABASE {_quote_identifier(settings.database_name)}")
        logger.info("Created database %s", settings.database_name)
        return True
    finally:
        await connection.close()


def main() -> None:
    created = asyncio.run(ensure_database_exists())
    if created:
        print("Created development database.")
    else:
        print("Development database already exists.")


if __name__ == "__main__":
    main()
