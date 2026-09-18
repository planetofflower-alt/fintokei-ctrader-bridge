"""MCP stdio server exposing safety-gated cTrader tools."""

from __future__ import annotations

import json
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

from .client import BridgeError, CTraderBridge, NotConnectedError
from .config import Config
from .safety import OrderRejected, validate_limit_order

# ProtoOATrendbarPeriod enum values
PERIODS = {
    "M1": 1, "M5": 5, "M15": 7, "M30": 8,
    "H1": 9, "H4": 10, "D1": 12, "W1": 13, "MN1": 14,
}


class CTraderMCPServer:
    def __init__(self, config: Config):
        self.config = config
        self.bridge = CTraderBridge(config)
        self.server: Server = Server("fintokei-ctrader-bridge")
        self._register()

    async def _ensure_connected(self) -> None:
        if self.bridge.client is None:
            await self.bridge.connect()

    def _register(self) -> None:
        cfg = self.config

        @self.server.list_tools()
        async def list_tools() -> list[types.Tool]:
            return [
                types.Tool(
                    name="get_account_status",
                    description="Get positions and pending orders for the cTrader account (read-only).",
                    inputSchema={"type": "object", "properties": {}},
                ),
                types.Tool(
                    name="list_symbols",
                    description="List tradable symbols, optionally filtered by text.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "filter": {"type": "string", "default": ""},
                        },
                    },
                ),
                types.Tool(
                    name="get_quote",
                    description="Get the latest bid/ask for a symbol (e.g. XAUUSD).",
                    inputSchema={
                        "type": "object",
                        "properties": {"symbol": {"type": "string"}},
                        "required": ["symbol"],
                    },
                ),
                types.Tool(
                    name="get_candles",
                    description="Get recent OHLC candles for a symbol. Periods: M1, M5, M15, M30, H1, H4, D1, W1, MN1.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "symbol": {"type": "string"},
                            "period": {"type": "string", "enum": list(PERIODS)},
                            "count": {"type": "integer", "default": 100, "maximum": 500},
                        },
                        "required": ["symbol", "period"],
                    },
                ),
                types.Tool(
                    name="preview_limit_order",
                    description=(
                        "Validate and preview a limit order WITHOUT placing it. "
                        "Returns the exact parameters that would be submitted."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "symbol": {"type": "string"},
                            "side": {"type": "string", "enum": ["BUY", "SELL"]},
                            "volume_lots": {"type": "number"},
                            "limit_price": {"type": "number"},
                            "stop_loss": {"type": "number"},
                            "take_profit": {"type": "number"},
                        },
                        "required": [
                            "symbol", "side", "volume_lots",
                            "limit_price", "stop_loss", "take_profit",
                        ],
                    },
                ),
                types.Tool(
                    name="place_limit_order",
                    description=(
                        f"Place a LIMIT order. stop_loss and take_profit are "
                        f"required and must be on the correct side of limit_price. "
                        f"volume_lots is capped at {cfg.max_lots}. "
                        f"Call ONLY after the human explicitly approves the "
                        f"previewed order, then pass confirm=true."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "symbol": {"type": "string"},
                            "side": {"type": "string", "enum": ["BUY", "SELL"]},
                            "volume_lots": {"type": "number"},
                            "limit_price": {"type": "number"},
                            "stop_loss": {"type": "number"},
                            "take_profit": {"type": "number"},
                            "confirm": {
                                "type": "boolean",
                                "description": "Must be true; set only after explicit human approval.",
                            },
                        },
                        "required": [
                            "symbol", "side", "volume_lots", "limit_price",
                            "stop_loss", "take_profit", "confirm",
                        ],
                    },
                ),
                types.Tool(
                    name="cancel_order",
                    description="Cancel a pending order by order ID.",
                    inputSchema={
                        "type": "object",
                        "properties": {"order_id": {"type": "integer"}},
                        "required": ["order_id"],
                    },
                ),
            ]

        @self.server.call_tool()
        async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
            try:
                result = await self._dispatch(name, arguments or {})
                text = json.dumps(result, ensure_ascii=False, default=str)
            except OrderRejected as exc:
                text = json.dumps({"error": "order_rejected", "reason": str(exc)})
            except NotConnectedError as exc:
                text = json.dumps({"error": "not_connected", "reason": str(exc)})
            except BridgeError as exc:
                text = json.dumps({"error": "bridge_error", "reason": str(exc)})
            except Exception as exc:  # keep the session informed, never crash
                text = json.dumps({"error": "internal_error", "reason": str(exc)})
            return [types.TextContent(type="text", text=text)]

    async def _dispatch(self, name: str, args: dict) -> Any:
        if name == "preview_limit_order":
            params = validate_limit_order(
                symbol=args.get("symbol", ""),
                side=args.get("side", ""),
                volume_lots=args.get("volume_lots"),
                limit_price=args.get("limit_price"),
                stop_loss=args.get("stop_loss"),
                take_profit=args.get("take_profit"),
                confirm=True,
                max_lots=self.config.max_lots,
                require_confirm=False,
            )
            return {
                "preview": params.__dict__,
                "max_lots_cap": self.config.max_lots,
                "note": "Valid. Show this to the human and ask for approval "
                        "before calling place_limit_order.",
            }

        if name == "place_limit_order":
            params = validate_limit_order(
                symbol=args.get("symbol", ""),
                side=args.get("side", ""),
                volume_lots=args.get("volume_lots"),
                limit_price=args.get("limit_price"),
                stop_loss=args.get("stop_loss"),
                take_profit=args.get("take_profit"),
                confirm=args.get("confirm"),
                max_lots=self.config.max_lots,
                require_confirm=self.config.require_confirm,
            )
            await self._ensure_connected()
            result = await self.bridge.place_limit_order(
                symbol=params.symbol,
                side=params.side,
                volume_lots=params.volume_lots,
                limit_price=params.limit_price,
                stop_loss=params.stop_loss,
                take_profit=params.take_profit,
            )
            result["host"] = self.config.host
            return result

        await self._ensure_connected()

        if name == "get_account_status":
            data = await self.bridge.get_account_and_orders()
            data["host"] = self.config.host
            data["account_id"] = self.bridge._account_id
            return data
        if name == "list_symbols":
            filt = (args.get("filter") or "").upper()
            names = sorted(self.bridge.symbols_by_name)
            if filt:
                names = [n for n in names if filt in n]
            return {"count": len(names), "symbols": names}
        if name == "get_quote":
            return await self.bridge.get_quote(args["symbol"])
        if name == "get_candles":
            period_key = str(args.get("period", "H1")).upper()
            count = min(int(args.get("count", 100)), 500)
            bars = await self.bridge.get_trendbars(
                args["symbol"], PERIODS[period_key], count
            )
            return {"symbol": args["symbol"].upper(), "period": period_key,
                    "count": len(bars), "candles": bars}
        if name == "cancel_order":
            return await self.bridge.cancel_order(int(args["order_id"]))

        raise BridgeError(f"unknown tool: {name}")

    async def run(self) -> None:
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                self.server.create_initialization_options(),
            )
