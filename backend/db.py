"""Database engine setup. DATABASE_URL decides sqlite vs postgresql; no other
code in backend/ branches on which one is in use. See CHG-20260928-11.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from sqlalchemy import Engine, create_engine

from .models import metadata

load_dotenv()

_DEFAULT_SQLITE_URL = "sqlite:///./backend/dev.db"


def get_database_url() -> str:
    return os.environ.get("DATABASE_URL", _DEFAULT_SQLITE_URL)


def make_engine(database_url: str | None = None) -> Engine:
    url = database_url or get_database_url()
    # check_same_thread=False lets FastAPI call from multiple threads; SQLite-only, ignored by Postgres.
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=connect_args)


def init_schema(engine: Engine) -> None:
    """Creates every table if missing; safe to call on every app startup."""
    metadata.create_all(engine)
