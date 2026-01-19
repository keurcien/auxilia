from datetime import datetime, timedelta, timezone
from uuid import UUID
from jose import JWTError, jwt
from pwdlib import PasswordHash

from app.auth.settings import auth_settings


password_hash = PasswordHash.recommended()

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plain password against the stored hash.
    """
    return password_hash.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    """
    Hash a password using the recommended algorithm (Argon2id).
    """
    return password_hash.hash(password)


def create_access_token(user_id: UUID, expires_delta: timedelta | None = None) -> str:
    """Create a JWT access token for a user."""
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=auth_settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES
        )

    to_encode = {
        "sub": str(user_id),
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }

    encoded_jwt = jwt.encode(
        to_encode,
        auth_settings.JWT_SECRET_KEY,
        algorithm=auth_settings.JWT_ALGORITHM,
    )
    return encoded_jwt


def decode_access_token(token: str) -> UUID | None:
    """Decode and validate a JWT access token. Returns user_id or None."""
    try:
        payload = jwt.decode(
            token,
            auth_settings.JWT_SECRET_KEY,
            algorithms=[auth_settings.JWT_ALGORITHM],
        )
        user_id_str: str | None = payload.get("sub")
        if user_id_str is None:
            return None
        return UUID(user_id_str)
    except JWTError:
        return None
