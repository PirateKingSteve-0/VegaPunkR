"""
Authentication endpoints.
"""
import logging
from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from database import get_db
from models import User
from schemas import (
    Token,
    UserCreate,
    UserResponse,
    UserUpdate,
    DiscordTestRequest,
    TradingHaltRequest,
    TradingHaltResponse,
)
from auth import (
    authenticate_user,
    require_can_write_own,
    create_access_token,
    get_password_hash,
    get_current_user,
    verify_password,
)
from config import settings
from utils.market_hours import (
    HALT_MODE_FLATTEN,
    current_market_date_et,
    trading_halt_state,
)
from notifications.discord import send_test_message
from notifications import reports as email_reports

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(user_data: UserCreate, db: Session = Depends(get_db)):
    """
    Register a new user.

    - **email**: User's email address (must be unique)
    - **password**: Password (min 8 characters)
    - **name**: User's full name
    - **role**: 'user' or 'admin' (default: user)
    """
    # Check if user already exists
    existing_user = db.query(User).filter(User.email == user_data.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )

    # Create new user
    hashed_password = get_password_hash(user_data.password)
    db_user = User(
        email=user_data.email,
        name=user_data.name,
        hashed_password=hashed_password,
        role=user_data.role,
        risk_tolerance=user_data.risk_tolerance,
        account_size_usd=user_data.account_size_usd,
        max_trade_percentage=user_data.max_trade_percentage,
        timezone=user_data.timezone,
        trading_window_enabled=user_data.trading_window_enabled,
        trading_window_start=user_data.trading_window_start,
        trading_window_end=user_data.trading_window_end,
        is_active=True
    )

    db.add(db_user)
    db.commit()
    db.refresh(db_user)

    return db_user


@router.post("/login", response_model=Token)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    """
    Login with email and password to get an access token.

    - **username**: User's email address
    - **password**: User's password

    Returns a JWT access token valid for 24 hours.
    """
    user = authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Create access token. Subject is the user id (as a string per JWT spec)
    # so a future email change won't invalidate the in-flight session.
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": str(user.id), "env": user.selected_environment or "dev"},
        expires_delta=access_token_expires
    )

    return {"access_token": access_token, "token_type": "bearer"}


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    """
    Get current user information.

    Requires authentication token in header:
    Authorization: Bearer <token>
    """
    return current_user


@router.patch("/me", response_model=UserResponse)
def update_me(
    update: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update the current user's profile and trading preferences.

    Editable identity fields: name, email. Password change requires
    `current_password` + `new_password`. Email updates propagate
    automatically to anyone with email reports enabled because the
    dispatcher reads `User.email` at send time.
    """
    if update.trading_window_enabled and (
        update.trading_window_start is not None
        and update.trading_window_end is not None
        and update.trading_window_start >= update.trading_window_end
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="trading_window_start must be earlier than trading_window_end"
        )

    payload = update.model_dump(exclude_unset=True)

    # daily_loss_limit_pct is bounded by Pydantic (0.5–20). No further
    # cross-field validation needed — defensive lower bound is already
    # enforced in `_check_user_daily_loss_limit` (treats <=0 as opt-out).

    # Password change is its own concern — handled before generic field
    # assignment so we don't ever assign `new_password` / `current_password`
    # onto the User model.
    new_password = payload.pop("new_password", None)
    current_password = payload.pop("current_password", None)
    if new_password or current_password:
        if not (new_password and current_password):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password change requires both current_password and new_password",
            )
        if not verify_password(current_password, current_user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Current password is incorrect",
            )
        current_user.hashed_password = get_password_hash(new_password)

    # Email change — uniqueness check before commit so we surface a clean
    # 400 instead of a DB unique-violation 500.
    if "email" in payload:
        new_email = payload["email"]
        if new_email != current_user.email:
            existing = db.query(User).filter(User.email == new_email).first()
            if existing and existing.id != current_user.id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="That email is already in use",
                )

    for field, value in payload.items():
        setattr(current_user, field, value)

    if (
        current_user.trading_window_enabled
        and current_user.trading_window_start
        and current_user.trading_window_end
        and current_user.trading_window_start >= current_user.trading_window_end
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="trading_window_start must be earlier than trading_window_end"
        )

    db.commit()
    db.refresh(current_user)
    return current_user


def _halt_response(user: User) -> TradingHaltResponse:
    """Render the user's halt state. Reads through `trading_halt_state` rather
    than the columns directly so the API can never report a halt the engine
    would ignore — e.g. a stale stamp from a previous session."""
    halted, mode = trading_halt_state(user)
    if not halted:
        message = "Trading is active. New entries are allowed."
    elif mode == HALT_MODE_FLATTEN:
        message = (
            "Done for the day. Open positions are being closed at market and "
            "no new entries will be taken until the next market day."
        )
    else:
        message = (
            "Done for the day. Open positions keep running their stop/target "
            "and no new entries will be taken until the next market day."
        )
    return TradingHaltResponse(
        trading_halted=halted,
        trading_halt_mode=mode,
        trading_halted_on=user.trading_halted_on if halted else None,
        message=message,
    )


@router.get("/me/trading-halt", response_model=TradingHaltResponse)
def get_trading_halt(current_user: User = Depends(get_current_user)):
    """Current "done for the day" state. Read-only, so every role can see it —
    a viewer should be able to tell whether the account is trading."""
    return _halt_response(current_user)


@router.post("/me/trading-halt", response_model=TradingHaltResponse)
def set_trading_halt(
    body: TradingHaltRequest,
    current_user: User = Depends(require_can_write_own),
    db: Session = Depends(get_db),
):
    """Stop trading for the rest of the market day.

    `mode='ride'` blocks new entries and leaves open positions to their
    stop-loss / take-profit / trailing / forced-EOD exits. `mode='flatten'`
    blocks new entries *and* brings the forced exit forward to now, so the
    engine closes everything at market on its next evaluation tick.

    Gated on `require_can_write_own`, not `require_can_place_orders`: this is a
    restriction on the account, and a role that may not open trades must still
    be able to stop them. Sells are never blocked by the halt, so an account
    stopped this way always retains a path out of its positions.

    Idempotent, and re-postable with a different mode — switching from 'ride'
    to 'flatten' mid-session is a normal thing to want.
    """
    current_user.trading_halted_on = current_market_date_et()
    current_user.trading_halt_mode = body.mode
    db.commit()
    db.refresh(current_user)

    logger.warning(
        "User %s halted trading for %s (mode=%s)",
        current_user.id, current_user.trading_halted_on, body.mode,
    )
    return _halt_response(current_user)


@router.delete("/me/trading-halt", response_model=TradingHaltResponse)
def clear_trading_halt(
    current_user: User = Depends(require_can_write_own),
    db: Session = Depends(get_db),
):
    """Resume trading for the rest of the day.

    Clears the stamp entirely rather than writing tomorrow's date — "not
    halted" is the absence of a halt, and NULL is the only state that means
    that. Note this only lifts the *manual* halt: the daily-loss cap and every
    other gate are unaffected and may still be blocking entries.
    """
    current_user.trading_halted_on = None
    current_user.trading_halt_mode = None
    db.commit()
    db.refresh(current_user)

    logger.info("User %s resumed trading", current_user.id)
    return _halt_response(current_user)


@router.post("/me/notifications/discord/test")
def test_discord_webhook(
    body: DiscordTestRequest,
    current_user: User = Depends(get_current_user),
):
    """Send a test embed to the supplied Discord webhook so the user can verify
    their setup before saving. Does not persist anything."""
    ok, message = send_test_message(body.webhook_url)
    if not ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)
    return {"ok": True, "message": message}


@router.post("/me/notifications/email-reports/test")
def test_email_report(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Send a real-shaped daily report against today's trades to the user's
    current email address. Lets the user verify formatting and that messages
    actually land in inbox vs. spam before relying on scheduled reports."""
    ok, message = email_reports.send_test_now(db, current_user)
    if not ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)
    return {"ok": True, "message": message}


@router.post("/logout")
def logout(current_user: User = Depends(get_current_user)):
    """
    Logout endpoint (client-side token removal).

    Note: JWT tokens are stateless, so logout is handled client-side
    by removing the token. This endpoint just validates the token.
    """
    return {"message": "Successfully logged out"}
