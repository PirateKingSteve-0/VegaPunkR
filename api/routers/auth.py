"""
Authentication endpoints.
"""
from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from database import get_db
from models import User
from schemas import Token, UserCreate, UserResponse, UserUpdate, DiscordTestRequest
from auth import (
    authenticate_user,
    create_access_token,
    get_password_hash,
    get_current_user,
    verify_password,
)
from config import settings
from notifications.discord import send_test_message
from notifications import reports as email_reports

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
