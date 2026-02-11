from typing import AsyncGenerator, Generator

from sqlalchemy import create_engine, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from app.config import settings

# Async engine (for future async routes)
async_engine = create_async_engine(
    settings.database_url,
    echo=settings.is_development,
)

# Sync engine (for dashboard routes and Alembic)
_sync_url = settings.database_url.replace("+aiosqlite", "")
sync_engine = create_engine(_sync_url)


@event.listens_for(sync_engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, _connection_record):
    """Enable WAL mode and foreign keys for SQLite."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


async_session = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)


async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session


def get_db() -> Generator[Session, None, None]:
    """Sync DB session dependency for FastAPI routes."""
    with Session(sync_engine) as session:
        yield session
