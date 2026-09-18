"""Async bridge between asyncio and the Twisted-based ctrader-open-api client."""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any

from twisted.internet import reactor

from ctrader_open_api import Client, EndPoints
from ctrader_open_api.client import Protobuf
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import *  # noqa: F401,F403
from ctrader_open_api.messages.OpenApiMessages_pb2 import *  # noqa: F401,F403
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import *  # noqa: F401,F403
from ctrader_open_api.tcpProtocol import TcpProtocol

PRICE_DIVISOR = 100_000
VOLUME_PER_LOT = 100  # API volume unit is 0.01 lot
CONNECT_TIMEOUT_S = 20
REQUEST_TIMEOUT_S = 15
SPOT_TIMEOUT_S = 10

# ProtoOATrendbarPeriod enum value -> duration in milliseconds
_PERIOD_MS = {
    1: 60_000,            # M1
    2: 2 * 60_000,        # M2
    3: 3 * 60_000,        # M3
    4: 4 * 60_000,        # M4
    5: 5 * 60_000,        # M5
    6: 10 * 60_000,       # M10
    7: 15 * 60_000,       # M15
    8: 30 * 60_000,       # M30
    9: 60 * 60_000,       # H1
    10: 4 * 60 * 60_000,  # H4
    11: 12 * 60 * 60_000, # H12
    12: 24 * 60 * 60_000, # D1
    13: 7 * 24 * 60 * 60_000,   # W1
    14: 30 * 24 * 60 * 60_000,  # MN1 (approx)
}

_ERROR_MESSAGES = {"ProtoOAErrorRes", "ProtoOAOrderErrorEvent"}

_reactor_started = False
_reactor_lock = threading.Lock()


def _ensure_reactor_thread() -> None:
    global _reactor_started
    with _reactor_lock:
        if _reactor_started:
            return
        thread = threading.Thread(
            target=reactor.run,
            kwargs={"installSignalHandlers": False},
            daemon=True,
            name="ctrader-reactor",
        )
        thread.start()
        _reactor_started = True


class BridgeError(Exception):
    pass


class NotConnectedError(BridgeError):
    pass


class CTraderBridge:
    """Thin async wrapper over the blocking-free Twisted cTrader client.

    Only reads plus LIMIT-order placement/cancellation are implemented.
    """

    def __init__(self, config):
        self.config = config
        self.client: Client | None = None
        self.symbols_by_name: dict[str, dict[str, Any]] = {}
        self._spot_waiters: dict[int, asyncio.Future] = {}
        self._connect_future: asyncio.Future | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._account_id: int = 0

    # ------------------------------------------------------------------
    # connection / auth
    # ------------------------------------------------------------------
    async def connect(self) -> None:
        if not self.config.credentials_present:
            raise NotConnectedError(
                "cTrader credentials are not configured (CTRADER_CLIENT_ID, "
                "CTRADER_CLIENT_SECRET, CTRADER_ACCESS_TOKEN, CTRADER_ACCOUNT_ID)"
            )

        self._loop = asyncio.get_running_loop()
        connected = self._loop.create_future()
        self._connect_future = connected

        host = (
            EndPoints.PROTOBUF_LIVE_HOST
            if self.config.host == "live"
            else EndPoints.PROTOBUF_DEMO_HOST
        )

        def _setup() -> None:
            self.client = Client(host, EndPoints.PROTOBUF_PORT, TcpProtocol)
            self.client.setConnectedCallback(
                lambda _client: self._set_future(connected, True)
            )
            self.client.setDisconnectedCallback(self._on_disconnected)
            self.client.setMessageReceivedCallback(self._on_message)
            self.client.startService()

        _ensure_reactor_thread()
        reactor.callFromThread(_setup)

        await asyncio.wait_for(connected, timeout=CONNECT_TIMEOUT_S)
        await self._app_auth()
        await self._resolve_account_id()
        await self._account_auth()
        await self._load_symbols()

    def _set_future(self, future: asyncio.Future | None, value: Any) -> None:
        if future is None or self._loop is None:
            return

        def _resolve() -> None:
            if not future.done():
                future.set_result(value)

        self._loop.call_soon_threadsafe(_resolve)

    def _fail_future(self, future: asyncio.Future, error: Exception) -> None:
        def _reject() -> None:
            if not future.done():
                future.set_exception(error)

        if self._loop is not None:
            self._loop.call_soon_threadsafe(_reject)

    def _on_disconnected(self, _client, reason) -> None:
        error = NotConnectedError(str(reason))
        if self._connect_future is not None:
            self._fail_future(self._connect_future, error)
        self._fail_spot_waiters(error)

    def _fail_spot_waiters(self, error: Exception) -> None:
        for fut in list(self._spot_waiters.values()):
            self._fail_future(fut, error)
        self._spot_waiters.clear()

    def _on_message(self, _client, message) -> None:
        try:
            inner = Protobuf.extract(message)
        except Exception:
            return
        name = inner.DESCRIPTOR.name
        if name == "ProtoOASpotEvent":
            self._set_future(
                self._spot_waiters.get(inner.symbolId), inner
            )
        elif name == "ProtoOAOrderErrorEvent":
            pass  # delivered to the pending _send() caller too

    async def _send(self, request):
        """Send a request and return the extracted response message."""
        if self.client is None or self._loop is None:
            raise NotConnectedError("not connected")
        future = self._loop.create_future()

        def _do_send() -> None:
            deferred = self.client.send(
                request, responseTimeoutInSeconds=REQUEST_TIMEOUT_S
            )
            deferred.addCallbacks(
                lambda result: self._set_future(future, result),
                lambda failure: self._fail_future(future, failure.value),
            )

        reactor.callFromThread(_do_send)
        wrapper = await future
        response = Protobuf.extract(wrapper)
        name = response.DESCRIPTOR.name
        if name in _ERROR_MESSAGES:
            code = getattr(response, "errorCode", "")
            desc = getattr(response, "description", "")
            raise BridgeError(f"cTrader API error {code}: {desc}")
        return response

    async def _app_auth(self) -> None:
        req = ProtoOAApplicationAuthReq(
            clientId=self.config.client_id,
            clientSecret=self.config.client_secret,
        )
        await self._send(req)

    async def _resolve_account_id(self) -> None:
        """Accept either the visible account number or the internal id."""
        res = await self._send(
            ProtoOAGetAccountListByAccessTokenReq(
                accessToken=self.config.access_token
            )
        )
        configured = int(self.config.account_id)
        logins: list[str] = []
        for account in res.ctidTraderAccount:
            logins.append(str(account.traderLogin))
            if configured in (account.ctidTraderAccountId, account.traderLogin):
                self._account_id = account.ctidTraderAccountId
                return
        raise BridgeError(
            f"account {self.config.account_id} not authorised for this token "
            f"(authorised account numbers: {', '.join(logins) or 'none'})"
        )

    async def _account_auth(self) -> None:
        req = ProtoOAAccountAuthReq(
            ctidTraderAccountId=self._account_id,
            accessToken=self.config.access_token,
        )
        await self._send(req)

    async def _load_symbols(self) -> None:
        res = await self._send(
            ProtoOASymbolsListReq(
                ctidTraderAccountId=self._account_id,
                includeArchivedSymbols=False,
            )
        )
        light = {s.symbolName.upper(): s.symbolId for s in res.symbol}
        ids = [s.symbolId for s in res.symbol if s.enabled]

        details: dict[int, Any] = {}
        chunk = 50
        for i in range(0, len(ids), chunk):
            detail_res = await self._send(
                ProtoOASymbolByIdReq(
                    ctidTraderAccountId=self._account_id,
                    symbolId=ids[i : i + chunk],
                )
            )
            for s in detail_res.symbol:
                details[s.symbolId] = s

        for name, sid in light.items():
            d = details.get(sid)
            self.symbols_by_name[name] = {
                "id": sid,
                "digits": d.digits if d else None,
                "min_volume_lots": (d.minVolume / VOLUME_PER_LOT) if d else None,
                "lot_size_units": (d.lotSize / VOLUME_PER_LOT) if d else None,
            }

    def _symbol_id(self, symbol: str) -> int:
        entry = self.symbols_by_name.get(symbol.upper())
        if entry is None:
            raise BridgeError(f"unknown symbol: {symbol}")
        return entry["id"]

    # ------------------------------------------------------------------
    # reads
    # ------------------------------------------------------------------
    async def get_account_and_orders(self) -> dict[str, Any]:
        res = await self._send(
            ProtoOAReconcileReq(ctidTraderAccountId=self._account_id)
        )
        positions = [
            {
                "position_id": p.positionId,
                "symbol_id": p.tradeData.symbolId,
                "side": ProtoOATradeSide.Name(p.tradeData.tradeSide),
                "volume_lots": p.tradeData.volume / VOLUME_PER_LOT,
                "entry_price": p.price,
                "stop_loss": p.stopLoss or None,
                "take_profit": p.takeProfit or None,
            }
            for p in res.position
        ]
        orders = [
            {
                "order_id": o.orderId,
                "symbol_id": o.tradeData.symbolId,
                "side": ProtoOATradeSide.Name(o.tradeData.tradeSide),
                "order_type": ProtoOAOrderType.Name(o.orderType),
                "volume_lots": o.tradeData.volume / VOLUME_PER_LOT,
                "limit_price": o.limitPrice or None,
                "stop_price": o.stopPrice or None,
                "stop_loss": o.stopLoss or None,
                "take_profit": o.takeProfit or None,
            }
            for o in res.order
        ]
        return {"positions": positions, "orders": orders}

    async def get_quote(self, symbol: str) -> dict[str, Any]:
        symbol_id = self._symbol_id(symbol)
        waiter = self._loop.create_future()
        self._spot_waiters[symbol_id] = waiter
        try:
            sub = ProtoOASubscribeSpotsReq(
                ctidTraderAccountId=self._account_id,
                symbolId=[symbol_id],
            )
            await self._send(sub)
            event = await asyncio.wait_for(waiter, timeout=SPOT_TIMEOUT_S)
            return {
                "symbol": symbol.upper(),
                "bid": event.bid / PRICE_DIVISOR if event.bid else None,
                "ask": event.ask / PRICE_DIVISOR if event.ask else None,
                "timestamp_ms": event.timestamp,
            }
        finally:
            self._spot_waiters.pop(symbol_id, None)
            try:
                await self._send(
                    ProtoOAUnsubscribeSpotsReq(
                        ctidTraderAccountId=self._account_id,
                        symbolId=[symbol_id],
                    )
                )
            except BridgeError:
                pass

    async def get_trendbars(
        self, symbol: str, period: int, count: int
    ) -> list[dict[str, Any]]:
        symbol_id = self._symbol_id(symbol)
        now_ms = int(time.time() * 1000)
        span = _PERIOD_MS.get(period, 60 * 60_000) * (count + 5)
        res = await self._send(
            ProtoOAGetTrendbarsReq(
                ctidTraderAccountId=self._account_id,
                symbolId=symbol_id,
                period=period,
                fromTimestamp=now_ms - span,
                toTimestamp=now_ms,
                count=count,
            )
        )
        return [
            {
                "open": (bar.low + bar.deltaOpen) / PRICE_DIVISOR,
                "high": (bar.low + bar.deltaHigh) / PRICE_DIVISOR,
                "low": bar.low / PRICE_DIVISOR,
                "close": (bar.low + bar.deltaClose) / PRICE_DIVISOR,
                "volume": bar.volume,
                "utc_minutes": bar.utcTimestampInMinutes,
            }
            for bar in res.trendbar
        ]

    # ------------------------------------------------------------------
    # writes (validation happens in safety.py before we are called)
    # ------------------------------------------------------------------
    async def place_limit_order(
        self,
        *,
        symbol: str,
        side: str,
        volume_lots: float,
        limit_price: float,
        stop_loss: float,
        take_profit: float,
    ) -> dict[str, Any]:
        symbol_id = self._symbol_id(symbol)
        req = ProtoOANewOrderReq(
            ctidTraderAccountId=self._account_id,
            symbolId=symbol_id,
            orderType=ProtoOAOrderType.LIMIT,
            tradeSide=(
                ProtoOATradeSide.BUY if side == "BUY" else ProtoOATradeSide.SELL
            ),
            volume=int(round(volume_lots * VOLUME_PER_LOT)),
            limitPrice=limit_price,
            stopLoss=stop_loss,
            takeProfit=take_profit,
            label="fintokei-ctrader-bridge",
        )
        event = await self._send(req)
        exec_type = ProtoOAExecutionType.Name(event.executionType)
        order_id = event.order.orderId if event.HasField("order") else None
        return {
            "status": exec_type,
            "order_id": order_id,
            "symbol": symbol.upper(),
            "side": side,
            "volume_lots": volume_lots,
            "limit_price": limit_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
        }

    async def cancel_order(self, order_id: int) -> dict[str, Any]:
        event = await self._send(
            ProtoOACancelOrderReq(
                ctidTraderAccountId=self._account_id,
                orderId=order_id,
            )
        )
        exec_type = ProtoOAExecutionType.Name(event.executionType)
        return {"status": exec_type, "order_id": order_id}
