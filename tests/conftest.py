import os
import tempfile
from pathlib import Path

# Point the app at a throwaway SQLite file BEFORE any app module creates the
# engine, so the suite never touches the developer's database.db.
_TEST_DB = Path(tempfile.gettempdir()) / "job_board_pytest.db"
os.environ["DATABASE_URI"] = f"sqlite:///{_TEST_DB.as_posix()}"
os.environ["SECRET_KEY"] = "test-secret-key-that-is-at-least-32-bytes"
os.environ.setdefault("ENV", "test")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import app.models
from app.models.user import User


@pytest.fixture
def test_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)


@pytest.fixture
def seeded():
    """Fresh seeded database for each test."""
    from app.seed import seed

    seed(reset=True)


@pytest.fixture
def client(seeded):
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def users(seeded):
    """Seed user ids keyed by username."""
    from app.database import engine

    with Session(engine) as session:
        return {u.username: u.id for u in session.exec(select(User)).all()}


@pytest.fixture
def db():
    """Session on the app's (test) database for direct assertions."""
    from app.database import engine

    with Session(engine) as session:
        yield session
