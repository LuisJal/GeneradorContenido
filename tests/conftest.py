"""Shared test fixtures: provides a clean in-memory DB for dashboard tests."""
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import Base
from app.database import get_db
from app.main import app


_test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


def _override_get_db():
    """Yield a session from the in-memory test database."""
    with Session(_test_engine) as session:
        yield session


@pytest.fixture(autouse=True)
def clean_test_db(monkeypatch):
    """Create fresh tables before each test, drop after."""
    key = Fernet.generate_key().decode()
    monkeypatch.setattr("app.services.bot_manager.settings.encryption_key", key)

    Base.metadata.create_all(_test_engine)
    app.dependency_overrides[get_db] = _override_get_db
    yield
    app.dependency_overrides.clear()
    Base.metadata.drop_all(_test_engine)
