"""Single-password admin authentication.

POST /api/admin/login exchanges ADMIN_PASSWORD for a short-lived token:
    base64url(json payload) + "." + base64url(HMAC-SHA256(secret, payload))
Standard library only -- one admin doesn't justify a JWT dependency.
"""
import base64
import hashlib
import hmac
import json
import time
from collections import defaultdict, deque
from typing import Optional

from fastapi import Header, HTTPException, Request

from .config import config

LOGIN_ATTEMPTS = 5
LOGIN_WINDOW_SECONDS = 60


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(payload: str) -> str:
    digest = hmac.new(config.admin_secret.encode(), payload.encode(), hashlib.sha256).digest()
    return _b64encode(digest)


def create_token(now: Optional[float] = None) -> tuple[str, int]:
    """Returns (token, expires_at_epoch_ms)."""
    now = time.time() if now is None else now
    expires = int(now + config.admin_token_hours * 3600)
    payload = _b64encode(json.dumps({"exp": expires}).encode())
    return f"{payload}.{_sign(payload)}", expires * 1000


def verify_token(token: str, now: Optional[float] = None) -> bool:
    now = time.time() if now is None else now
    try:
        payload, signature = token.split(".", 1)
        if not hmac.compare_digest(signature, _sign(payload)):
            return False
        return json.loads(_b64decode(payload))["exp"] > now
    except (ValueError, KeyError, TypeError):
        return False


def password_matches(password: str) -> bool:
    return hmac.compare_digest(password.encode(), config.admin_password.encode())


class LoginRateLimiter:
    """Failed-login counter per client IP, kept in memory.

    Behind nginx, run uvicorn with --proxy-headers so request.client.host
    is the real visitor rather than nginx itself.
    """

    def __init__(self) -> None:
        self.failures: dict[str, deque[float]] = defaultdict(deque)

    def _recent(self, ip: str, now: float) -> deque[float]:
        attempts = self.failures[ip]
        while attempts and attempts[0] <= now - LOGIN_WINDOW_SECONDS:
            attempts.popleft()
        return attempts

    def is_blocked(self, ip: str, now: Optional[float] = None) -> bool:
        now = time.time() if now is None else now
        return len(self._recent(ip, now)) >= LOGIN_ATTEMPTS

    def record_failure(self, ip: str, now: Optional[float] = None) -> None:
        now = time.time() if now is None else now
        self._recent(ip, now).append(now)

    def reset(self, ip: str) -> None:
        self.failures.pop(ip, None)


login_limiter = LoginRateLimiter()


# -- FastAPI dependencies ---------------------------------------------------

def require_admin_enabled() -> None:
    # Without a configured password there is no admin surface at all.
    if not config.admin_password:
        raise HTTPException(status_code=404)


def require_admin(authorization: Optional[str] = Header(default=None)) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not logged in")
    if not verify_token(authorization.removeprefix("Bearer ")):
        raise HTTPException(status_code=401, detail="Session expired")


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"
