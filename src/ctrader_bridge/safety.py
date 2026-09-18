"""Order validation. Pure functions, unit-tested offline.

Design rules enforced here (this is the safety gate for every write tool):

* Limit orders only — no market orders exist in this codebase at all.
* stop_loss and take_profit are REQUIRED on every order and must be on the
  correct side of the limit price.
* volume is capped server-side by CTRADER_MAX_LOTS.
* confirm=true must be passed explicitly; the human approval step in the chat
  is meaningless if the tool can fire without it.
"""

from __future__ import annotations

from dataclasses import dataclass

SIDES = ("BUY", "SELL")


class OrderRejected(Exception):
    """Raised when an order fails safety validation. Never raised for reads."""


@dataclass(frozen=True)
class OrderParams:
    symbol: str
    side: str           # "BUY" | "SELL"
    volume_lots: float
    limit_price: float
    stop_loss: float
    take_profit: float


def validate_limit_order(
    *,
    symbol: str,
    side: str,
    volume_lots: float,
    limit_price: float,
    stop_loss: float,
    take_profit: float,
    confirm: bool,
    max_lots: float,
    require_confirm: bool,
) -> OrderParams:
    if not symbol or not symbol.strip():
        raise OrderRejected("symbol is required")
    symbol = symbol.strip().upper()

    side = (side or "").strip().upper()
    if side not in SIDES:
        raise OrderRejected("side must be BUY or SELL")

    for name, value in (
        ("volume_lots", volume_lots),
        ("limit_price", limit_price),
        ("stop_loss", stop_loss),
        ("take_profit", take_profit),
    ):
        if value is None:
            raise OrderRejected(f"{name} is required")
        try:
            float(value)
        except (TypeError, ValueError):
            raise OrderRejected(f"{name} must be a number")

    volume_lots = float(volume_lots)
    limit_price = float(limit_price)
    stop_loss = float(stop_loss)
    take_profit = float(take_profit)

    if volume_lots <= 0:
        raise OrderRejected("volume_lots must be positive")
    if volume_lots > max_lots:
        raise OrderRejected(
            f"volume_lots {volume_lots} exceeds server cap CTRADER_MAX_LOTS={max_lots}"
        )
    if limit_price <= 0 or stop_loss <= 0 or take_profit <= 0:
        raise OrderRejected("prices must be positive")

    if side == "BUY":
        if not (stop_loss < limit_price < take_profit):
            raise OrderRejected(
                "BUY limit order requires stop_loss < limit_price < take_profit"
            )
    else:
        if not (take_profit < limit_price < stop_loss):
            raise OrderRejected(
                "SELL limit order requires take_profit < limit_price < stop_loss"
            )

    if require_confirm and confirm is not True:
        raise OrderRejected(
            "confirm must be true. Ask the human to approve the order first."
        )

    return OrderParams(
        symbol=symbol,
        side=side,
        volume_lots=volume_lots,
        limit_price=limit_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
    )
