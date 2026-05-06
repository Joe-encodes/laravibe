"""
api/routers/auth.py — Authentication endpoints.
Handles login (exchanging master key for JWT) and verification.
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from api.services.auth_service import get_current_user, verify_master_key, create_session_token
from api.limiter import limiter

router = APIRouter(prefix="/api/auth", tags=["auth"])
logger = logging.getLogger(__name__)


class LoginRequest(BaseModel):
    token: str


@router.post("/login")
@limiter.limit("10/minute")
async def login(request: Request, body: LoginRequest):
    """
    Exchange the master repair token for a short-lived JWT session token.
    This is the ONLY endpoint that accepts the raw master key.
    Rate-limited to 10 attempts per minute to prevent brute force.
    """
    if not verify_master_key(body.token):
        logger.warning(f"[Auth] Failed login attempt from {request.client.host}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid master token.",
        )

    session_token = create_session_token(role="admin")
    logger.info(f"[Auth] Session token issued to {request.client.host}")
    return {
        "access_token": session_token,
        "token_type": "bearer",
        "expires_in": 8 * 3600,  # 8 hours in seconds
        "message": "Session established. Store the access_token — not this master key."
    }


@router.get("/verify")
async def verify_auth(user: dict = Depends(get_current_user)):
    """Verify a JWT session token is valid and not expired."""
    return {"status": "authorized", "user": user.get("user"), "role": user.get("role")}
