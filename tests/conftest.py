import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="sunday_test_")
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_TMP, 'test.db')}"
os.environ["LANGGRAPH_CHECKPOINT_PATH"] = os.path.join(_TMP, "checkpoints.sqlite3")
os.environ["OPENROUTER_API_KEY"] = ""
os.environ["OLLAMA_BASE_URL"] = "http://localhost:1"
os.environ["LOG_LEVEL"] = "WARNING"

import pytest

from app.core import models  # noqa: F401  (register models on Base.metadata)
from app.core.database import Base, SessionLocal, engine


@pytest.fixture(autouse=True)
def clean_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()