"""Unit tests for domain sanity validators."""

from src.models.schemas import (
    BuildupType,
    CandleDelta,
    OptionChainSnapshot,
    OptionData,
    OptionGreek,
    OrderFlowSnapshot,
    PriceLevel,
    StrikeRow,
)
from src.models.validators import (
    cross_check_buildup,
    validate_option_chain_snapshot,
    validate_order_flow_snapshot,
)


def test_valid_order_flow_snapshot():
    snapshot = OrderFlowSnapshot(
        current_price=24850.0,
        price_levels=[
            PriceLevel(price=24850.0, bid_volume=100, ask_volume=120, total_volume=220)
        ],
        candle_deltas=[
            CandleDelta(open=24840.0, high=24860.0, low=24840.0, close=24850.0, total_volume=500, delta=20)
        ],
    )
    is_valid, errors = validate_order_flow_snapshot(snapshot)
    assert is_valid
    assert len(errors) == 0


def test_order_flow_negative_volume_fails():
    snapshot = OrderFlowSnapshot(
        current_price=24850.0,
        price_levels=[
            PriceLevel(price=24850.0, bid_volume=-10, ask_volume=120, total_volume=110)
        ],
    )
    is_valid, errors = validate_order_flow_snapshot(snapshot)
    assert not is_valid
    assert any("Negative volume" in e for e in errors)


def test_option_chain_non_ascending_strikes_fail():
    strikes = [
        StrikeRow(strike=25000.0, call=OptionData(ltp=100.0, oi=1000)),
        StrikeRow(strike=24900.0, call=OptionData(ltp=150.0, oi=1200)),
    ]
    snapshot = OptionChainSnapshot(underlying_price=24950.0, strikes=strikes)
    is_valid, errors = validate_option_chain_snapshot(snapshot)
    assert not is_valid
    assert any("not strictly ascending" in e for e in errors)


def test_option_chain_invalid_deltas_fail():
    # Call delta must be in [0, 1]
    strikes_bad_call = [
        StrikeRow(strike=25000.0, call=OptionData(ltp=100.0, oi=1000, greeks=OptionGreek(delta=1.5)))
    ]
    snapshot = OptionChainSnapshot(underlying_price=24950.0, strikes=strikes_bad_call)
    is_valid, errors = validate_option_chain_snapshot(snapshot)
    assert not is_valid
    assert any("Call delta out of range" in e for e in errors)

    # Put delta must be in [-1, 0]
    strikes_bad_put = [
        StrikeRow(strike=25000.0, put=OptionData(ltp=100.0, oi=1000, greeks=OptionGreek(delta=0.5)))
    ]
    snapshot2 = OptionChainSnapshot(underlying_price=24950.0, strikes=strikes_bad_put)
    is_valid2, errors2 = validate_option_chain_snapshot(snapshot2)
    assert not is_valid2
    assert any("Put delta out of range" in e for e in errors2)


def test_cross_check_buildup():
    # Price Up, OI Up -> Long Buildup
    consistent, expected = cross_check_buildup(10.0, 5000.0, BuildupType.LONG_BUILDUP)
    assert consistent
    assert expected == BuildupType.LONG_BUILDUP

    # Price Down, OI Up -> Short Buildup
    consistent, expected = cross_check_buildup(-5.0, 3000.0, BuildupType.SHORT_BUILDUP)
    assert consistent
    assert expected == BuildupType.SHORT_BUILDUP

    # Price Up, OI Down -> Short Covering
    consistent, expected = cross_check_buildup(8.0, -1500.0, BuildupType.SHORT_COVERING)
    assert consistent
    assert expected == BuildupType.SHORT_COVERING

    # Price Down, OI Down -> Long Unwinding
    consistent, expected = cross_check_buildup(-6.0, -2000.0, BuildupType.LONG_UNWINDING)
    assert consistent
    assert expected == BuildupType.LONG_UNWINDING
