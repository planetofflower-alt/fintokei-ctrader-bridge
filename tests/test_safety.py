import pytest

from ctrader_bridge.safety import OrderRejected, validate_limit_order

KW = dict(max_lots=0.1, require_confirm=True)
BUY_OK = dict(
    symbol="XAUUSD", side="BUY", volume_lots=0.05,
    limit_price=4350.0, stop_loss=4340.0, take_profit=4370.0, confirm=True,
)
SELL_OK = dict(
    symbol="XAUUSD", side="SELL", volume_lots=0.05,
    limit_price=4380.0, stop_loss=4390.0, take_profit=4360.0, confirm=True,
)


def test_valid_buy_limit_accepted():
    params = validate_limit_order(**BUY_OK, **KW)
    assert params.side == "BUY"
    assert params.volume_lots == 0.05


def test_valid_sell_limit_accepted():
    params = validate_limit_order(**SELL_OK, **KW)
    assert params.side == "SELL"


def test_rejects_bad_side():
    with pytest.raises(OrderRejected, match="BUY or SELL"):
        validate_limit_order(**{**BUY_OK, "side": "LONG"}, **KW)


def test_rejects_zero_and_negative_volume():
    with pytest.raises(OrderRejected, match="positive"):
        validate_limit_order(**{**BUY_OK, "volume_lots": 0}, **KW)
    with pytest.raises(OrderRejected, match="positive"):
        validate_limit_order(**{**BUY_OK, "volume_lots": -0.5}, **KW)


def test_rejects_volume_over_cap():
    with pytest.raises(OrderRejected, match="CTRADER_MAX_LOTS"):
        validate_limit_order(**{**BUY_OK, "volume_lots": 0.11}, **KW)


def test_rejects_missing_stop_loss():
    with pytest.raises(OrderRejected, match="stop_loss is required"):
        validate_limit_order(**{**BUY_OK, "stop_loss": None}, **KW)


def test_rejects_missing_take_profit():
    with pytest.raises(OrderRejected, match="take_profit is required"):
        validate_limit_order(**{**BUY_OK, "take_profit": None}, **KW)


def test_rejects_wrong_side_stops_buy():
    # SL above price is invalid for BUY
    with pytest.raises(OrderRejected, match="stop_loss < limit_price < take_profit"):
        validate_limit_order(**{**BUY_OK, "stop_loss": 4360.0, "take_profit": 4370.0}, **KW)


def test_rejects_wrong_side_stops_sell():
    with pytest.raises(OrderRejected, match="take_profit < limit_price < stop_loss"):
        validate_limit_order(**{**SELL_OK, "stop_loss": 4370.0, "take_profit": 4360.0}, **KW)


def test_rejects_without_confirm():
    with pytest.raises(OrderRejected, match="confirm"):
        validate_limit_order(**{**BUY_OK, "confirm": False}, **KW)
    with pytest.raises(OrderRejected, match="confirm"):
        validate_limit_order(**{**BUY_OK, "confirm": None}, **KW)


def test_confirm_bypass_when_require_confirm_off():
    params = validate_limit_order(
        **{**BUY_OK, "confirm": None},
        max_lots=0.1,
        require_confirm=False,
    )
    assert params.symbol == "XAUUSD"


def test_symbol_normalized():
    params = validate_limit_order(**{**BUY_OK, "symbol": " xauusd "}, **KW)
    assert params.symbol == "XAUUSD"
