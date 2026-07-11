"""
Database connection and session management with multi-database support.

This module manages connection pools to three separate databases:
- Development (dev): For feature development and experimentation
- Test (test): For testing and validation (in-memory)
- Production (prod): For live trading

Users can switch between databases at runtime without server restart.
"""
import os
from typing import Generator, Optional
from fastapi import Request
from jose import jwt
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from config import settings, Environment

_ENV_BY_NAME = {"dev": Environment.DEV, "test": Environment.TEST, "prod": Environment.PROD}


def _env_from_request(request: Optional[Request]) -> Optional[Environment]:
    """Best-effort: read the `env` claim from the request's bearer token to pick
    the database. The claim is set at login and re-minted by the environment
    toggle (`/system/environment`), so it's signed and tamper-proof. Never
    raises — any problem (no token, bad token, no claim) returns None and the
    caller falls back to the process default."""
    if request is None:
        return None
    try:
        auth = request.headers.get("authorization") or request.headers.get("Authorization")
        if not auth or not auth.lower().startswith("bearer "):
            return None
        token = auth.split(" ", 1)[1].strip()
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return _ENV_BY_NAME.get(str(payload.get("env") or "").lower())
    except Exception:
        return None


def default_environment() -> Environment:
    """The database environment this PROCESS runs against, from the ``APP_ENV``
    env var (default ``dev``).

    IMPORTANT: database selection is **process-level**, not per-request. The
    UI's per-user environment / trading-mode switch changes the *broker client*
    (`trading_client_manager.get_client`) but does NOT reroute the database —
    every API request and the background engine worker use this one environment.
    Running "live" while the process is on ``dev`` would place real broker orders
    against the dev DB (split-brain). For a live run, launch a DEDICATED process
    with ``APP_ENV=prod`` so the whole app (API + engine) uses the prod DB
    consistently with the live broker. See docs/live-test-plan-2026-07-13.md.
    """
    return _ENV_BY_NAME.get(os.getenv("APP_ENV", "dev").strip().lower(), Environment.DEV)

# Create connection pools for all three databases
# Each pool maintains its own connection pool for efficient query handling
engines = {
    Environment.DEV: create_engine(
        settings.DATABASE_DEV_URL,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,  # Verify connections before using
        echo=False  # Set to True for SQL query logging
    ),
    Environment.TEST: create_engine(
        settings.DATABASE_TEST_URL,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
        echo=False
    ),
    Environment.PROD: create_engine(
        settings.DATABASE_PROD_URL,
        pool_size=15,
        max_overflow=30,
        pool_pre_ping=True,
        echo=False
    ),
}

# Create session makers for each environment
SessionLocals = {
    Environment.DEV: sessionmaker(autocommit=False, autoflush=False, bind=engines[Environment.DEV]),
    Environment.TEST: sessionmaker(autocommit=False, autoflush=False, bind=engines[Environment.TEST]),
    Environment.PROD: sessionmaker(autocommit=False, autoflush=False, bind=engines[Environment.PROD]),
}


def get_db_session(environment: Environment) -> Generator[Session, None, None]:
    """
    Get database session for specified environment.

    Args:
        environment: The environment to connect to (dev/test/prod)

    Yields:
        Database session for the specified environment

    Usage:
        db = next(get_db_session(Environment.DEV))
        users = db.query(User).all()
        db.close()
    """
    if environment not in SessionLocals:
        raise ValueError(f"Invalid environment: {environment}")

    db = SessionLocals[environment]()
    try:
        yield db
    finally:
        db.close()


def get_db(request: Request = None) -> Generator[Session, None, None]:
    """
    Dependency function for FastAPI to get a database session.

    Routes to the environment named in the caller's JWT ``env`` claim, so the UI
    environment toggle actually reroutes the database per-request. Falls back to
    this process's default (``default_environment()`` / ``APP_ENV``) when there's
    no valid token (login, public endpoints, or direct non-request callers such
    as scripts/tests).

    NOTE: this routes API reads/writes by the request token. Background services
    (the trading engine worker, the email scheduler) have no request/token and
    stay pinned to ``default_environment()`` — trading must not be per-request.

    Usage in FastAPI:
        @app.get("/users")
        def get_users(db: Session = Depends(get_db)):
            return db.query(User).all()
    """
    env = _env_from_request(request) or default_environment()
    yield from get_db_session(env)


def get_engine(environment: Environment):
    """
    Get SQLAlchemy engine for specified environment.

    Useful for running migrations or raw SQL queries.

    Args:
        environment: The environment to get engine for

    Returns:
        SQLAlchemy Engine instance
    """
    if environment not in engines:
        raise ValueError(f"Invalid environment: {environment}")
    return engines[environment]
