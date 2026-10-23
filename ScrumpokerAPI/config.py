import os
import secrets
from dataclasses import dataclass, field

from dotenv import load_dotenv

# Reads a .env file next to where uvicorn is started, if there is one.
# Real environment variables take precedence over the file.
load_dotenv()


def _origins() -> list[str]:
    raw = os.getenv("CORS_ORIGINS", "*")
    return [o.strip() for o in raw.split(",") if o.strip()]


@dataclass
class Config:
    # Admin endpoints are disabled (404) unless a password is set.
    admin_password: str = field(default_factory=lambda: os.getenv("ADMIN_PASSWORD", ""))
    # Signs admin tokens. If unset, a random secret is generated per
    # process -- admins simply have to log in again after a restart.
    admin_secret: str = field(default_factory=lambda: os.getenv("ADMIN_SECRET") or secrets.token_hex(32))
    admin_token_hours: float = field(default_factory=lambda: float(os.getenv("ADMIN_TOKEN_HOURS", "8")))
    # Comma-separated list, e.g. "https://comp-sci.co.uk". Admin auth uses
    # a Bearer header rather than cookies, so "*" is not a CSRF risk.
    cors_origins: list[str] = field(default_factory=_origins)


config = Config()
