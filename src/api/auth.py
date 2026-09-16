"""Simple Session-based Auth API for Alpha Testing."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

try:
    from config.alpha_users import ALPHA_USERS
except ImportError:
    ALPHA_USERS = {
        "mihir": "alpha_pass_1",
        "rahul": "alpha_pass_2",
        "priya": "alpha_pass_3",
        "admin": "alpha_admin_2026",
        "tester": "alpha_test_pass",
    }

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

COOKIE_NAME = "alpha_session"


class LoginForm(BaseModel):
    username: str
    password: str


@router.post("/login")
async def login(form: LoginForm, response: Response) -> dict[str, Any]:
    """Authenticate an alpha tester and set session cookie."""
    username = form.username.strip()
    expected_pass = ALPHA_USERS.get(username)
    if not expected_pass or expected_pass != form.password:
        logger.warning("Failed login attempt for user '%s'", form.username)
        raise HTTPException(status_code=401, detail="Invalid Alpha credentials")

    response.set_cookie(
        key=COOKIE_NAME,
        value=username,
        httponly=True,
        max_age=86400 * 7,  # 7 days
        samesite="lax",
        secure=False,
    )
    logger.info("Alpha user '%s' logged in successfully", username)
    return {"status": "logged_in", "user": username, "user_id": username}


@router.post("/logout")
async def logout(response: Response) -> dict[str, str]:
    """Clear session cookie."""
    response.delete_cookie(key=COOKIE_NAME)
    return {"status": "logged_out"}


def get_current_user(request: Request) -> str:
    """Dependency that extracts user from alpha_session cookie or X-User-Id header.

    Supports:
    1. Browser session cookie: `alpha_session`
    2. Header fallback: `X-User-Id` (for curl, Postman, automated tests)
    """
    user = request.cookies.get(COOKIE_NAME) or request.headers.get("X-User-Id")
    if user and user.strip() in ALPHA_USERS:
        return user.strip()

    raise HTTPException(status_code=401, detail="Alpha access required. Please login.")


def get_current_user_optional(request: Request) -> str:
    """Optional user dependency — returns username if authenticated, else 'anonymous'."""
    user = request.cookies.get(COOKIE_NAME) or request.headers.get("X-User-Id")
    if user and user.strip() in ALPHA_USERS:
        return user.strip()
    return "anonymous"


@router.get("/me")
async def get_me(user: str = Depends(get_current_user_optional)) -> dict[str, Any]:
    """Get currently logged-in user."""
    authenticated = user != "anonymous"
    return {"user": user, "user_id": user, "authenticated": authenticated}
