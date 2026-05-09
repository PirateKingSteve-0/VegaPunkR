"""
Authentication utilities for JWT tokens and password hashing.
"""
from datetime import datetime, timedelta
from typing import Optional
import bcrypt
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models import User

# OAuth2 scheme for token authentication
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_PREFIX}/auth/login")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against a hash."""
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))


def get_password_hash(password: str) -> str:
    """Hash a password."""
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Create a JWT access token.

    Args:
        data: Dictionary of data to encode in the token
        expires_delta: Optional expiration time delta

    Returns:
        Encoded JWT token string
    """
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> Optional[dict]:
    """
    Decode and verify a JWT token.

    Returns:
        Decoded token data or None if invalid
    """
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except JWTError:
        return None


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> User:
    """
    Get the current authenticated user from the JWT token.

    This is a FastAPI dependency that can be used in route handlers.

    Example:
        @app.get("/me")
        def get_me(current_user: User = Depends(get_current_user)):
            return current_user
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    payload = decode_access_token(token)
    if payload is None:
        raise credentials_exception

    # JWT `sub` is the user id (string-typed for JWT compliance). Using id
    # instead of email so a user changing their email mid-session doesn't
    # invalidate the existing token.
    sub = payload.get("sub")
    if sub is None:
        raise credentials_exception
    try:
        user_id = int(sub)
    except (TypeError, ValueError):
        raise credentials_exception

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise credentials_exception

    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")

    return user


ROLE_USER = "user"
ROLE_ADMIN = "admin"
ROLE_VIEWER = "viewer"
ROLE_AUDITOR = "auditor"
ROLE_STRATEGY_AUTHOR = "strategy_author"

VALID_ROLES = {ROLE_USER, ROLE_ADMIN, ROLE_VIEWER, ROLE_AUDITOR, ROLE_STRATEGY_AUTHOR}

# Roles that may write to their OWN account: edit settings, create or
# modify strategies, manage watchlists, etc. `viewer` and `auditor` are
# strictly read-only on their own data.
_WRITE_OWN_ROLES = {ROLE_USER, ROLE_ADMIN, ROLE_STRATEGY_AUTHOR}

# Roles that may place or cancel orders. `strategy_author` can build
# strategies but never trades — order placement is gated separately so
# they can author without a trading liability surface.
_PLACE_ORDER_ROLES = {ROLE_USER, ROLE_ADMIN}

# Roles that may read across all users (no act-as).
_READ_CROSS_USER_ROLES = {ROLE_ADMIN, ROLE_AUDITOR}


async def get_current_active_admin(
    current_user: User = Depends(get_current_user)
) -> User:
    """Strictly admin — used for user-management endpoints (role changes,
    creating users, etc.). For *read* across users, prefer
    `get_current_active_admin_or_auditor` so auditors aren't locked out of
    oversight."""
    if current_user.role != ROLE_ADMIN:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return current_user


async def get_current_active_admin_or_auditor(
    current_user: User = Depends(get_current_user)
) -> User:
    """Read-only-across-users dependency. Used by `/admin/users/...`
    inspect endpoints — both admins (who manage users) and auditors (who
    only observe) are allowed through. Writes still need
    `get_current_active_admin`."""
    if current_user.role not in _READ_CROSS_USER_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Admin or auditor privileges required",
        )
    return current_user


async def require_can_write_own(
    current_user: User = Depends(get_current_user),
) -> User:
    """Block writes for read-only roles (`viewer`, `auditor`). Apply on
    POST/PATCH/DELETE handlers that mutate the *current user's* own
    resources. Place-order endpoints additionally need
    `require_can_place_orders`."""
    if current_user.role not in _WRITE_OWN_ROLES:
        raise HTTPException(
            status_code=403,
            detail=f"Your role ({current_user.role}) is read-only.",
        )
    return current_user


async def require_can_place_orders(
    current_user: User = Depends(get_current_user),
) -> User:
    """Block order placement for non-trading roles (`viewer`, `auditor`,
    `strategy_author`). Distinct from `require_can_write_own` because
    `strategy_author` can mutate strategies but must never trade."""
    if current_user.role not in _PLACE_ORDER_ROLES:
        raise HTTPException(
            status_code=403,
            detail=f"Your role ({current_user.role}) cannot place orders.",
        )
    return current_user


def authenticate_user(db: Session, email: str, password: str) -> Optional[User]:
    """
    Authenticate a user by email and password.

    Returns:
        User object if authentication successful, None otherwise
    """
    user = db.query(User).filter(User.email == email).first()
    if not user:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user
