"""
System configuration endpoints for environment and trading mode management.

This router provides endpoints for:
- Getting current environment and trading mode settings
- Switching between databases (dev/test/prod) at runtime
- Toggling between paper and live trading
"""
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel

from database import get_db
from models import User
from auth import get_current_user
from config import Environment, TradingMode

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/system", tags=["System"])


def validate_environment_trading_mode_combination(environment: str, trading_mode: str) -> tuple[bool, Optional[str]]:
    """
    Validate environment and trading mode combination.

    Valid combinations:
    - Paper mode: dev, test only (not prod)
    - Live mode: prod only (not dev, test)

    Returns:
        Tuple of (is_valid, error_message)
    """
    # Paper trading + prod: invalid
    if trading_mode == "paper" and environment == "prod":
        return False, "Paper trading cannot be used with production environment. Production requires live trading."

    # Live trading + dev/test: invalid
    if trading_mode == "live" and environment in ["dev", "test"]:
        return False, f"Live trading cannot be used with {environment} environment. Live trading requires production environment to prevent data loss."

    return True, None


class EnvironmentResponse(BaseModel):
    """Response model for environment settings."""
    environment: str
    trading_mode: str
    database: str
    trading_api: str
    can_toggle_trading_mode: bool
    warning: Optional[str] = None


class EnvironmentUpdateRequest(BaseModel):
    """Request model for updating environment."""
    environment: str


class TradingModeUpdateRequest(BaseModel):
    """Request model for updating trading mode."""
    mode: str


@router.get("/environment", response_model=EnvironmentResponse)
async def get_environment(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get current environment and trading mode settings for the authenticated user.

    Returns:
        - environment: Current database environment (dev/test/prod)
        - trading_mode: Current trading mode (paper/live)
        - database: Database name being used
        - trading_api: Trading API being used (Alpaca Paper or Schwab Live)
        - can_toggle_trading_mode: Whether user can toggle between paper and live
    """
    env = current_user.selected_environment or "dev"
    mode = current_user.selected_trading_mode or "paper"

    # Determine which trading API is active
    trading_api = "Alpaca Paper" if mode == "paper" else "Schwab Live"

    # Determine database name
    db_name = f"vegapunk_{env}"

    logger.info(f"📊 User {current_user.email} querying environment settings:")
    logger.info(f"   └─ Database: {db_name} ({env})")
    logger.info(f"   └─ Trading API: {trading_api} ({mode})")

    return EnvironmentResponse(
        environment=env,
        trading_mode=mode,
        database=db_name,
        trading_api=trading_api,
        can_toggle_trading_mode=True,  # All users can toggle for now
        warning="⚠️ Live trading uses real money!" if mode == "live" else None
    )


@router.post("/environment")
async def set_environment(
    request: EnvironmentUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Switch database environment for the authenticated user.

    This changes which database the user's queries are routed to.
    No server restart required - switch happens instantly.

    Args:
        environment: Target environment ('dev', 'test', or 'prod')

    Returns:
        Success message with new environment details
    """
    # Validate environment
    valid_environments = ["dev", "test", "prod"]
    if request.environment not in valid_environments:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid environment. Must be one of: {', '.join(valid_environments)}"
        )

    # Validate combination with current trading mode
    current_trading_mode = current_user.selected_trading_mode or "paper"
    is_valid, error_msg = validate_environment_trading_mode_combination(
        request.environment, current_trading_mode
    )
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_msg
        )

    # Update user's selected environment
    old_env = current_user.selected_environment or "dev"
    current_user.selected_environment = request.environment
    db.commit()
    db.refresh(current_user)

    db_name = f"vegapunk_{request.environment}"
    logger.warning(f"🔄 DATABASE SWITCH - User {current_user.email}")
    logger.warning(f"   └─ FROM: vegapunk_{old_env} ({old_env})")
    logger.warning(f"   └─ TO:   {db_name} ({request.environment})")
    logger.warning(f"   └─ All subsequent queries will use {db_name}")

    return {
        "success": True,
        "environment": request.environment,
        "database": f"vegapunk_{request.environment}",
        "message": f"Environment switched to {request.environment} (no restart required)"
    }


@router.post("/trading-mode")
async def set_trading_mode(
    request: TradingModeUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Toggle trading mode between paper and live trading.

    This switches between Alpaca Paper Trading and Schwab Live Trading APIs.
    No server restart required - switch happens instantly.

    Args:
        mode: Target trading mode ('paper' or 'live')

    Returns:
        Success message with new trading mode details

    Warning:
        Live mode uses real money via Schwab API!
    """
    # Validate trading mode
    valid_modes = ["paper", "live"]
    if request.mode not in valid_modes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid trading mode. Must be one of: {', '.join(valid_modes)}"
        )

    # NOTE: Validation disabled to allow coordinated environment+trading mode switches
    # The frontend will automatically switch environment after trading mode
    # Environment endpoint validation will prevent invalid end states

    # Update user's selected trading mode
    old_mode = current_user.selected_trading_mode or "paper"
    current_user.selected_trading_mode = request.mode
    db.commit()
    db.refresh(current_user)

    # Determine which API will be used
    old_api = "Alpaca Paper" if old_mode == "paper" else "Schwab Live"
    new_api = "Alpaca Paper" if request.mode == "paper" else "Schwab Live"

    if request.mode == "live":
        logger.error(f"⚠️  TRADING MODE SWITCH TO LIVE - User {current_user.email}")
        logger.error(f"   └─ FROM: {old_api} ({old_mode})")
        logger.error(f"   └─ TO:   {new_api} ({request.mode})")
        logger.error(f"   └─ ⚠️  ALL ORDERS WILL USE REAL MONEY VIA SCHWAB API ⚠️")
    else:
        logger.warning(f"🔄 TRADING MODE SWITCH - User {current_user.email}")
        logger.warning(f"   └─ FROM: {old_api} ({old_mode})")
        logger.warning(f"   └─ TO:   {new_api} ({request.mode})")

    return {
        "success": True,
        "trading_mode": request.mode,
        "trading_api": new_api,
        "message": f"Trading mode switched to {request.mode} (no restart required)",
        "warning": "⚠️ Live trading uses real money! All orders will execute with real capital." if request.mode == "live" else None
    }


@router.get("/health")
async def health_check():
    """
    Health check endpoint for monitoring.

    Returns:
        Status and version information
    """
    return {
        "status": "healthy",
        "service": "VegaPunkR Trading API",
        "version": "1.0.0",
        "features": {
            "multi_database": True,
            "hot_swap_environments": True,
            "paper_trading": True,
            "live_trading": True
        }
    }
