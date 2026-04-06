"""
OAuth2 authentication setup (prepared for future use).
Currently placeholder for token-based authentication.
"""
from datetime import datetime, timedelta
from typing import Optional
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel
import os

# OAuth2 scheme
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


class TokenData(BaseModel):
    """Token data model."""

    username: Optional[str] = None
    exp: Optional[datetime] = None


def create_access_token(
    data: dict, expires_delta: Optional[timedelta] = None
) -> str:
    """
    Create JWT access token (placeholder).

    Args:
        data: Token data
        expires_delta: Token expiration time

    Returns:
        Token string
    """
    # TODO: Implement JWT token creation when OAuth is activated
    return "placeholder_token"


def verify_token(token: str) -> bool:
    """
    Verify access token (placeholder).

    Args:
        token: Token to verify

    Returns:
        True if token is valid, False otherwise
    """
    # TODO: Implement JWT token verification when OAuth is activated
    return True


# Note: OAuth authentication is prepared but not enforced in API endpoints.
# To activate OAuth:
# 1. Implement JWT creation and verification
# 2. Add dependency to API endpoint: async def get_current_user(token: str = Depends(oauth2_scheme))
# 3. Validate token before processing requests
