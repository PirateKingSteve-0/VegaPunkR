from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime, JSON, Float, func
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    role = Column(String, default='user')  # 'user' or 'admin'
    is_active = Column(Boolean, default=True)
    hashed_password = Column(String, nullable=False)

    # Trading preferences
    risk_tolerance = Column(String, default='medium')  # 'low', 'medium', 'high'
    account_size_usd = Column(Float, default=0.0)  # Fetched/updated from broker API
    max_trade_percentage = Column(Float, default=0.02)  # e.g., 0.02 = 2% of portfolio

    # Environment and trading mode selection (for multi-database and API switching)
    selected_environment = Column(String, default='dev')  # 'dev', 'test', or 'prod'
    selected_trading_mode = Column(String, default='paper')  # 'paper' or 'live'

    # Additional fields
    timezone = Column(String, default='UTC')
    notification_preferences = Column(JSON, default=dict)  # Email, SMS, push settings
    last_login = Column(DateTime)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    strategies = relationship("Strategy", back_populates="user")
    trades = relationship("Trade", back_populates="user")
    positions = relationship("Position", back_populates="user")


class Strategy(Base):
    __tablename__ = 'strategies'
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    name = Column(String, nullable=False)
    strategy_type = Column(String)  # 'mean_reversion', 'momentum', 'ml_based', etc.
    params_json = Column(JSON, nullable=False)  # e.g., {"ma_short": 50, "ma_long": 200}
    instruments = Column(JSON, default=list)  # e.g., ["AAPL", "TSLA"] or ["stocks", "options"]

    # Strategy settings
    timeframe = Column(String, default='1d')  # '1m', '5m', '1h', '1d', etc.
    max_positions = Column(Integer, default=5)
    stop_loss_percentage = Column(Float)  # e.g., 0.02 = 2%
    take_profit_percentage = Column(Float)  # e.g., 0.05 = 5%

    # Performance tracking
    backtest_results = Column(JSON)  # Store backtest metrics

    # Status
    is_active = Column(Boolean, default=True)
    is_paper_trading = Column(Boolean, default=True)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="strategies")
    positions = relationship("Position", back_populates="strategy")
    performance_metrics = relationship("PerformanceMetrics", back_populates="strategy")


class Position(Base):
    __tablename__ = 'positions'
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    symbol = Column(String, nullable=False, index=True)
    qty = Column(Integer, nullable=False)

    # Entry details
    avg_entry_price = Column(Float, nullable=False)
    opened_at = Column(DateTime, server_default=func.now())

    # Current status
    current_price = Column(Float)
    unrealized_pnl = Column(Float)

    # Strategy link
    strategy_id = Column(Integer, ForeignKey('strategies.id'))

    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="positions")
    strategy = relationship("Strategy", back_populates="positions")
    trades = relationship("Trade", back_populates="position")


class Trade(Base):
    __tablename__ = 'trades'  # Make hypertable: SELECT create_hypertable('trades', 'timestamp');
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    symbol = Column(String, nullable=False, index=True)

    # Order details
    side = Column(String, nullable=False)  # 'buy' or 'sell'
    order_type = Column(String, default='market')  # 'market', 'limit', 'stop', 'stop_limit'
    qty = Column(Integer, nullable=False)
    filled_qty = Column(Integer)  # Actual filled amount (for partial fills)
    price = Column(Float, nullable=False)

    # Exit details (for closing trades)
    exit_price = Column(Float)
    exit_timestamp = Column(DateTime)

    # Financial details
    commission = Column(Float, default=0.0)
    pnl = Column(Float)  # Profit/loss for closed positions

    # Timestamps
    timestamp = Column(DateTime, nullable=False, index=True)  # Partition key for TimescaleDB

    # Links
    strategy_id = Column(Integer, ForeignKey('strategies.id'))
    position_id = Column(Integer, ForeignKey('positions.id'))

    # Status and metadata
    status = Column(String, default='executed')  # 'pending', 'executed', 'failed', 'cancelled'
    notes = Column(JSON)  # Entry reason, exit reason, metadata

    created_at = Column(DateTime, server_default=func.now())

    user = relationship("User", back_populates="trades")
    position = relationship("Position", back_populates="trades")


class PerformanceMetrics(Base):
    __tablename__ = 'performance_metrics'
    id = Column(Integer, primary_key=True, index=True)
    strategy_id = Column(Integer, ForeignKey('strategies.id'), nullable=False)

    # Time period
    period = Column(String, nullable=False)  # 'daily', 'weekly', 'monthly', 'all_time'
    date = Column(DateTime, nullable=False, index=True)

    # Trade statistics
    total_trades = Column(Integer, default=0)
    winning_trades = Column(Integer, default=0)
    losing_trades = Column(Integer, default=0)

    # Financial metrics
    total_pnl = Column(Float, default=0.0)
    gross_profit = Column(Float, default=0.0)
    gross_loss = Column(Float, default=0.0)
    total_commission = Column(Float, default=0.0)

    # Performance ratios
    win_rate = Column(Float)  # winning_trades / total_trades
    profit_factor = Column(Float)  # gross_profit / abs(gross_loss)
    sharpe_ratio = Column(Float)
    max_drawdown = Column(Float)
    avg_win = Column(Float)
    avg_loss = Column(Float)

    # Risk metrics
    largest_win = Column(Float)
    largest_loss = Column(Float)
    consecutive_wins = Column(Integer)
    consecutive_losses = Column(Integer)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    strategy = relationship("Strategy", back_populates="performance_metrics")


class RiskEvent(Base):
    __tablename__ = 'risk_events'
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)

    # Event details
    event_type = Column(String, nullable=False)  # 'max_drawdown', 'position_limit', 'daily_loss_limit', etc.
    severity = Column(String, nullable=False)  # 'info', 'warning', 'critical'
    action_taken = Column(String)  # 'trade_rejected', 'positions_closed', 'strategy_paused', 'notification_sent'

    # Context
    strategy_id = Column(Integer, ForeignKey('strategies.id'))
    details = Column(JSON)  # Additional context (limits breached, values, etc.)

    timestamp = Column(DateTime, nullable=False, index=True, server_default=func.now())
