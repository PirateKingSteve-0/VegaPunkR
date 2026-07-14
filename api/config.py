"""
Application configuration settings.
"""
import os
from enum import Enum
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()


class Environment(str, Enum):
    """Environment types for database selection."""
    DEV = "dev"
    TEST = "test"
    PROD = "prod"


class TradingMode(str, Enum):
    """Trading mode selection."""
    PAPER = "paper"
    LIVE = "live"


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # API Settings
    APP_NAME: str = "VegaPunkR Trading API"
    APP_VERSION: str = "1.0.0"
    API_V1_PREFIX: str = "/api/v1"
    DEBUG: bool = True

    # Security - JWT token signing
    SECRET_KEY: str = os.getenv("SECRET_KEY", "")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours

    # Database URLs for all environments
    DATABASE_DEV_URL: str = os.getenv("DATABASE_DEV_URL", "postgresql://user:pass@localhost:5432/vegapunk_dev")
    DATABASE_TEST_URL: str = os.getenv("DATABASE_TEST_URL", "postgresql://user:pass@localhost:5433/vegapunk_test")
    DATABASE_PROD_URL: str = os.getenv("DATABASE_PROD_URL", "postgresql://user:pass@localhost:5434/vegapunk_prod")

    # Legacy (for backward compatibility)
    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/vegapunk_dev")

    def get_database_url(self, environment: Environment) -> str:
        """Get database URL for specified environment."""
        if environment == Environment.DEV:
            return self.DATABASE_DEV_URL
        elif environment == Environment.TEST:
            return self.DATABASE_TEST_URL
        elif environment == Environment.PROD:
            return self.DATABASE_PROD_URL
        else:
            return self.DATABASE_DEV_URL

    # Tradier API Keys — Tradier is the ONLY broker. Alpaca and Schwab were removed
    # 2026-07-13: Alpaca's free tier returns no greeks (it silently disabled the delta
    # and open-interest gates), and Schwab was never wired to a trading path.
    TRADIER_SANDBOX_API_KEY: str = os.getenv("TRADIER_SANDBOX_API_KEY", "")
    TRADIER_SANDBOX_ACCOUNT_NUMBER: str = os.getenv("TRADIER_SANDBOX_ACCOUNT_NUMBER", "")
    TRADIER_SANDBOX_BASE_URL: str = os.getenv("TRADIER_SANDBOX_BASE_URL", "https://sandbox.tradier.com")
    TRADIER_LIVE_API_KEY: str = os.getenv("TRADIER_LIVE_API_KEY", "")
    TRADIER_LIVE_BASE_URL: str = os.getenv("TRADIER_LIVE_BASE_URL", "https://api.tradier.com")
    TRADIER_ENV: str = os.getenv("TRADIER_ENV", "sandbox")

    # Discord Webhooks
    DISCORD_WEBHOOK_URL: str = os.getenv("DISCORD_WEBHOOK_URL", "")
    DISCORD_WEBHOOK_URL_DEV: str = os.getenv("DISCORD_WEBHOOK_URL_DEV", "")

    # Resend (email reports). Without RESEND_API_KEY the dispatcher logs the
    # rendered report and skips the network call — useful in dev.
    RESEND_API_KEY: str = os.getenv("RESEND_API_KEY", "")
    EMAIL_FROM_ADDRESS: str = os.getenv("EMAIL_FROM_ADDRESS", "reports@vegapunkr.local")
    EMAIL_FROM_NAME: str = os.getenv("EMAIL_FROM_NAME", "VegaPunkR Reports")

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"


settings = Settings()
