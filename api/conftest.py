"""
Pytest configuration and fixtures for testing.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from models import Base
from tests.test_database import TEST_DATABASE_URL, test_engine


@pytest.fixture(scope="session")
def engine():
    """Create a test database engine for the entire test session."""
    return test_engine


@pytest.fixture(scope="session", autouse=True)
def setup_test_database(engine):
    """
    Set up test database schema before all tests.
    Tears down after all tests complete.
    """
    # Create all tables
    Base.metadata.create_all(bind=engine)
    yield
    # Drop all tables after tests
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def db_session(engine):
    """
    Create a new database session for each test function.
    Automatically rolls back after each test to keep tests isolated.
    """
    connection = engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection)()

    yield session

    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def sample_user(db_session):
    """Create a sample user for testing."""
    from models import User
    import bcrypt

    password = "testpass123"
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

    user = User(
        email="test@example.com",
        name="Test User",
        hashed_password=hashed,
        role="user",
        risk_tolerance="medium",
        account_size_usd=10000.0,
        max_trade_percentage=0.02
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def sample_strategy(db_session, sample_user):
    """Create a sample strategy for testing."""
    from models import Strategy

    strategy = Strategy(
        user_id=sample_user.id,
        name="Test Strategy",
        strategy_type="momentum",
        params_json={"ma_short": 50, "ma_long": 200},
        instruments=["AAPL", "TSLA"],
        timeframe="1d",
        is_active=True,
        is_paper_trading=True
    )
    db_session.add(strategy)
    db_session.commit()
    db_session.refresh(strategy)
    return strategy


@pytest.fixture
def sample_position(db_session, sample_user, sample_strategy):
    """Create a sample position for testing."""
    from models import Position

    position = Position(
        user_id=sample_user.id,
        symbol="AAPL",
        qty=10,
        avg_entry_price=150.0,
        current_price=155.0,
        unrealized_pnl=50.0,
        strategy_id=sample_strategy.id
    )
    db_session.add(position)
    db_session.commit()
    db_session.refresh(position)
    return position
