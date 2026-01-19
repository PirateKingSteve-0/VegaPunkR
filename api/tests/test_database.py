"""
Test database configuration and utilities.
"""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Get test database URL from environment
TEST_DATABASE_URL = os.getenv('DATABASE_TEST_URL')

# Create test engine
test_engine = create_engine(TEST_DATABASE_URL, echo=False)  # Set echo=True for SQL debugging

# Create test session factory
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def get_test_db():
    """
    Dependency function for FastAPI tests to get test database session.
    """
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()
