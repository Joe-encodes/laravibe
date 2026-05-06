"""
api/services/auth_service.py — JWT + Master Token authentication.

Security Model:
  - The raw MASTER_REPAIR_TOKEN is ONLY used at the /api/auth/login endpoint.
  - On successful login, a short-lived JWT session token is issued.
  - All other endpoints validate the JWT — the master key never lives in the browser.
  - SSE endpoints also support a query_token parameter (the JWT, not the master key).
  - Failed login attempts are logged for audit purposes.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

from api.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

SESSION_DURATION_HOURS = 8


def create_session_token(role: str = "admin") -> str:
    """
    Create a short-lived JWT session token.
    Called after the master key is verified — this is what the FE stores and uses.
    """
    expire = datetime.now(timezone.utc) + timedelta(hours=SESSION_DURATION_HOURS)
    payload = {
        "sub": "laravibe-session",
        "role": role,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def verify_master_key(provided_key: str) -> bool:
    """Constant-time comparison to prevent timing attacks on master key verification."""
    import hmac
    return hmac.compare_digest(
        provided_key.encode("utf-8"),
        settings.master_repair_token.encode("utf-8"),
    )


async def get_current_user(
    request: Request,
    token: Optional[str] = Depends(oauth2_scheme),
) -> dict:
    """
    Dependency that validates the Bearer token.
    Accepts ONLY JWTs issued by /api/auth/login.
    Also reads 'token' query parameter for SSE EventSource connections.
    The raw master key is NOT accepted here — only session JWTs.
    """
    # SSE fallback: read from query param
    query_token = request.query_params.get("token")
    final_token = token or query_token

    if not final_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Please log in via /api/auth/login.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Decode and validate the JWT session token
    try:
        payload = jwt.decode(
            final_token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        sub: str = payload.get("sub")
        role: str = payload.get("role", "user")
        if sub != "laravibe-session":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid session token.",
            )
        return {"user": sub, "role": role}
    except JWTError as e:
        logger.warning(f"[Auth] JWT validation failed from {request.client.host}: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired or invalid. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
