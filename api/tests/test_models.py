"""
Tests for database models.
"""
import pytest
from datetime import datetime
from models import User, Strategy, Position, Trade, PerformanceMetrics, RiskEvent


def test_create_user(db_session):
    """Test creating a user."""
    user = User(
        email="newuser@example.com",
        name="New User",
        hashed_password="hashed_pw",
        role="user"
    )
    db_session.add(user)
    db_session.commit()

    assert user.id is not None
    assert user.email == "newuser@example.com"
    assert user.is_active is True  # Default value
    assert user.created_at is not None


def test_admin_user_exists(db_session):
    """Test that admin user (pirateking) exists in test database."""
    import bcrypt

    # Create admin user for testing
    hashed_pw = bcrypt.hashpw("Kaidasparrow5264!".encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    admin = User(
        email="kingofpirates92@gmail.com",
        name="pirateking",
        hashed_password=hashed_pw,
        role="admin",
        risk_tolerance="medium",
        account_size_usd=5000.0,
        max_trade_percentage=0.02,
        timezone="America/Los_Angeles"
    )
    db_session.add(admin)
    db_session.commit()

    # Verify admin user
    user = db_session.query(User).filter(User.email == "kingofpirates92@gmail.com").first()
    assert user is not None
    assert user.name == "pirateking"
    assert user.role == "admin"
    assert user.account_size_usd == 5000.0
    assert user.timezone == "America/Los_Angeles"


def test_user_strategies_relationship(db_session, sample_user, sample_strategy):
    """Test User-Strategy relationship."""
    user = db_session.query(User).filter(User.id == sample_user.id).first()
    assert len(user.strategies) == 1
    assert user.strategies[0].name == "Test Strategy"


def test_create_position(db_session, sample_user, sample_strategy):
    """Test creating a position."""
    position = Position(
        user_id=sample_user.id,
        symbol="TSLA",
        qty=5,
        avg_entry_price=200.0,
        strategy_id=sample_strategy.id
    )
    db_session.add(position)
    db_session.commit()

    assert position.id is not None
    assert position.symbol == "TSLA"
    assert position.qty == 5


def test_create_trade(db_session, sample_user, sample_strategy, sample_position):
    """Test creating a trade."""
    trade = Trade(
        user_id=sample_user.id,
        symbol="AAPL",
        side="buy",
        order_type="market",
        qty=10,
        filled_qty=10,
        price=150.0,
        commission=1.0,
        timestamp=datetime.now(),
        strategy_id=sample_strategy.id,
        position_id=sample_position.id,
        status="executed"
    )
    db_session.add(trade)
    db_session.commit()

    assert trade.id is not None
    assert trade.side == "buy"
    assert trade.price == 150.0


def test_performance_metrics(db_session, sample_strategy):
    """Test creating performance metrics."""
    metrics = PerformanceMetrics(
        strategy_id=sample_strategy.id,
        period="daily",
        date=datetime.now(),
        total_trades=10,
        winning_trades=6,
        losing_trades=4,
        total_pnl=500.0,
        win_rate=0.6
    )
    db_session.add(metrics)
    db_session.commit()

    assert metrics.id is not None
    assert metrics.win_rate == 0.6


def test_risk_event(db_session, sample_user, sample_strategy):
    """Test creating a risk event."""
    event = RiskEvent(
        user_id=sample_user.id,
        event_type="position_limit",
        severity="warning",
        action_taken="trade_rejected",
        strategy_id=sample_strategy.id,
        details={"limit": 5, "attempted": 6}
    )
    db_session.add(event)
    db_session.commit()

    assert event.id is not None
    assert event.severity == "warning"
    assert event.details["limit"] == 5


def test_query_user_positions(db_session, sample_user, sample_position):
    """Test querying user positions."""
    positions = db_session.query(Position).filter(
        Position.user_id == sample_user.id
    ).all()

    assert len(positions) == 1
    assert positions[0].symbol == "AAPL"


def test_strategy_cascade(db_session, sample_user):
    """Test that deleting a strategy doesn't delete the user."""
    strategy = Strategy(
        user_id=sample_user.id,
        name="Temporary Strategy",
        params_json={"test": "value"}
    )
    db_session.add(strategy)
    db_session.commit()
    strategy_id = strategy.id

    db_session.delete(strategy)
    db_session.commit()

    # User should still exist
    user = db_session.query(User).filter(User.id == sample_user.id).first()
    assert user is not None

    # Strategy should be gone
    deleted_strategy = db_session.query(Strategy).filter(Strategy.id == strategy_id).first()
    assert deleted_strategy is None
