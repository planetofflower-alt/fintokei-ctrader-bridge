"""Environment-backed configuration.

Credentials come from environment variables (or a local .env file for manual
runs). Never hard-code credentials in this repository.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return default


@dataclass(frozen=True)
class Config:
    client_id: str
    client_secret: str
    access_token: str
    account_id: int
    host: str          # "demo" or "live"
    allow_live: bool   # live host requires explicit opt-in
    max_lots: float    # server-side hard cap on order volume
    require_confirm: bool

    @property
    def credentials_present(self) -> bool:
        return bool(
            self.client_id
            and self.client_secret
            and self.access_token
            and self.account_id
        )


def load_config() -> Config:
    host = _env("CTRADER_HOST", "HOST", default="demo").lower()
    if host not in ("demo", "live"):
        raise ValueError(f"CTRADER_HOST must be 'demo' or 'live', got {host!r}")

    try:
        account_id = int(_env("CTRADER_ACCOUNT_ID", "ACCOUNT_ID", default="0"))
    except ValueError as exc:
        raise ValueError("CTRADER_ACCOUNT_ID must be an integer") from exc

    try:
        max_lots = float(_env("CTRADER_MAX_LOTS", default="0.1"))
    except ValueError as exc:
        raise ValueError("CTRADER_MAX_LOTS must be a number") from exc
    if max_lots <= 0:
        raise ValueError("CTRADER_MAX_LOTS must be positive")

    allow_live = _env("CTRADER_ALLOW_LIVE", default="false").lower() == "true"
    if host == "live" and not allow_live:
        raise ValueError(
            "CTRADER_HOST=live requires CTRADER_ALLOW_LIVE=true. "
            "Test on demo first."
        )

    require_confirm = _env("CTRADER_REQUIRE_CONFIRM", default="true").lower() != "false"

    return Config(
        client_id=_env("CTRADER_CLIENT_ID", "CLIENT_ID"),
        client_secret=_env("CTRADER_CLIENT_SECRET", "CLIENT_SECRET"),
        access_token=_env("CTRADER_ACCESS_TOKEN", "ACCESS_TOKEN"),
        account_id=account_id,
        host=host,
        allow_live=allow_live,
        max_lots=max_lots,
        require_confirm=require_confirm,
    )
