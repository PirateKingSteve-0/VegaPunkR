"""
Database connection and session management with multi-database support.

This module manages connection pools to three separate databases:
- Development (dev): For feature development and experimentation
- Test (test): For testing and validation (in-memory)
- Production (prod): For live trading

Users can switch between databases at runtime without server restart.
"""
from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from config import settings, Environment

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


def get_db(environment: Environment = Environment.DEV) -> Generator[Session, None, None]:
    """
    Dependency function for FastAPI to get database session.

    This is the main function used in FastAPI route dependencies.
    It defaults to DEV environment if not specified.

    Args:
        environment: The environment to connect to (defaults to DEV)

    Yields:
        Database session

    Usage in FastAPI:
        @app.get("/users")
        def get_users(db: Session = Depends(get_db)):
            return db.query(User).all()

        # Or with specific environment:
        @app.get("/users")
        def get_users(db: Session = Depends(lambda: get_db(Environment.PROD))):
            return db.query(User).all()
    """
    yield from get_db_session(environment)


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
