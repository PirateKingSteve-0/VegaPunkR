#!/usr/bin/env python3
"""
Database setup and management script.

Usage:
    python setup_db.py init     # Create all tables
    python setup_db.py migrate  # Run Alembic migrations
    python setup_db.py reset    # Drop all tables and recreate
"""
import sys
import os
from sqlalchemy import text

# Add current directory to path
sys.path.insert(0, os.path.dirname(__file__))

from models import Base
from database import engine


def init_db():
    """Create all tables defined in models."""
    print("Creating all tables...")
    Base.metadata.create_all(bind=engine)
    print("✓ All tables created successfully!")

    # Create TimescaleDB hypertable for trades
    print("\nSetting up TimescaleDB hypertable for trades...")
    try:
        with engine.connect() as conn:
            # Check if TimescaleDB extension exists
            result = conn.execute(text(
                "SELECT 1 FROM pg_extension WHERE extname = 'timescaledb'"
            ))
            if not result.fetchone():
                print("Installing TimescaleDB extension...")
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE"))
                conn.commit()

            # Create hypertable
            print("Creating hypertable on trades.timestamp...")
            conn.execute(text(
                "SELECT create_hypertable('trades', 'timestamp', if_not_exists => TRUE)"
            ))
            conn.commit()
            print("✓ Hypertable created successfully!")
    except Exception as e:
        print(f"⚠ Warning: Could not create hypertable: {e}")
        print("This is OK if you're using regular PostgreSQL instead of TimescaleDB")


def reset_db():
    """Drop all tables and recreate them."""
    print("WARNING: This will delete all data!")
    response = input("Are you sure? (yes/no): ")
    if response.lower() != 'yes':
        print("Aborted.")
        return

    print("Dropping all tables...")
    Base.metadata.drop_all(bind=engine)
    print("✓ All tables dropped!")

    init_db()


def run_migrations():
    """Run Alembic migrations."""
    import subprocess
    print("Running Alembic migrations...")
    subprocess.run(["alembic", "upgrade", "head"], cwd=os.path.dirname(__file__))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1]

    if command == "init":
        init_db()
    elif command == "migrate":
        run_migrations()
    elif command == "reset":
        reset_db()
    else:
        print(f"Unknown command: {command}")
        print(__doc__)
        sys.exit(1)
