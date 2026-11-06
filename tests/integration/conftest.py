import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Iterator

import asyncpg
import pytest
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.core.config import Settings
from backend.database.base import Base
from backend.database.models import Plan


def _async_url(url: URL) -> str:
    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+asyncpg")
    return url.render_as_string(hide_password=False)


async def _create_database(admin_url: URL, database: str) -> None:
    connection = await asyncpg.connect(
        host=admin_url.host,
        port=admin_url.port or 5432,
        user=admin_url.username,
        password=admin_url.password,
        database="postgres",
    )
    try:
        await connection.execute(f'CREATE DATABASE "{database}"')
    finally:
        await connection.close()


async def _drop_database(admin_url: URL, database: str) -> None:
    connection = await asyncpg.connect(
        host=admin_url.host,
        port=admin_url.port or 5432,
        user=admin_url.username,
        password=admin_url.password,
        database="postgres",
    )
    try:
        await connection.execute(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
    finally:
        await connection.close()


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    explicit_url = os.getenv("TEST_DATABASE_URL")
    if explicit_url:
        yield _async_url(make_url(explicit_url))
        return

    base_url = make_url(Settings().database_url)
    admin_url = base_url.set(database="postgres")
    database = f"svdb_test_{uuid.uuid4().hex[:12]}"
    try:
        asyncio.run(_create_database(admin_url, database))
    except (OSError, asyncpg.PostgresError) as exc:
        pytest.skip(f"PostgreSQL is not available for integration tests: {exc}")
    try:
        yield _async_url(base_url.set(database=database))
    finally:
        asyncio.run(_drop_database(admin_url, database))


@pytest.fixture
async def engine(postgres_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(postgres_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
        await engine.dispose()


@pytest.fixture
async def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
async def plans(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session:
        session.add(
            Plan(
                code="free",
                name="Free",
                max_resolution_p=480,
                daily_included_downloads=5,
                priority=0,
                is_active=True,
            )
        )
        session.add(
            Plan(
                code="premium",
                name="Premium",
                max_resolution_p=2160,
                daily_included_downloads=None,
                priority=10,
                is_active=True,
            )
        )
        await session.commit()
