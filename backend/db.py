"""Database engine setup. `DATABASE_URL` decides everything -- point it at
`sqlite:///./backend/dev.db` for local development/testing (no server needed) or
`postgresql://...` in production (Fly Postgres sets this automatically once
attached). No other code in `backend/` branches on which one is in use.
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
    # check_same_thread=False: FastAPI can call from multiple threads; only
    # meaningful for the SQLite dev path, ignored by the Postgres driver.
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=connect_args)


def init_schema(engine: Engine) -> None:
    """Create every table if it doesn't already exist -- safe to call on every
    app startup, same idempotence guarantee as the existing SQLite stores'
    `CREATE TABLE IF NOT EXISTS`."""
    metadata.create_all(engine)
