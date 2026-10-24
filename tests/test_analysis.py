"""Unit tests for Order Flow and Option Chain analyzers."""

from src.analysis.option_chain_analyzer import OptionChainAnalyzer, calculate_max_pain
from src.analysis.order_flow_analyzer import OrderFlowAnalyzer
from src.models.schemas import (
    CandleDelta,
    OptionChainSnapshot,
    OptionData,
    OrderFlowSnapshot,
    PriceLevel,
    StrikeRow,
)


def test_order_flow_cvd_trend():
    analyzer = OrderFlowAnalyzer()
    snapshot = OrderFlowSnapshot(
        current_price=24850.0,
        cumulative_delta=1500,
        candle_deltas=[
            CandleDelta(delta=200, total_volume=5000),
            CandleDelta(delta=400, total_volume=6000),
            CandleDelta(delta=600, total_volume=8000),
        ],
    )
    res = analyzer.analyze(snapshot)
    assert res.cvd_trend == "BULLISH"
    assert res.cvd_score > 0.4


def test_order_flow_bullish_absorption():
    analyzer = OrderFlowAnalyzer()
    snapshot = OrderFlowSnapshot(
        current_price=24850.0,
        candle_deltas=[
            CandleDelta(close=24850.0, delta=100, total_volume=5000),
            CandleDelta(close=24840.0, delta=350, total_volume=8000),  # price drops, but aggressive buying
        ],
    )
    res = analyzer.analyze(snapshot)
    assert res.divergence == "BULLISH_ABSORPTION"


def test_order_flow_bearish_absorption():
    analyzer = OrderFlowAnalyzer()
    snapshot = OrderFlowSnapshot(
        current_price=24850.0,
        candle_deltas=[
            CandleDelta(close=24850.0, delta=-50, total_volume=5000),
            CandleDelta(close=24860.0, delta=-400, total_volume=8000),  # price rises, but aggressive selling
        ],
    )
    res = analyzer.analyze(snapshot)
    assert res.divergence == "BEARISH_ABSORPTION"


def test_order_flow_poc_calculation():
    analyzer = OrderFlowAnalyzer()
    snapshot = OrderFlowSnapshot(
        current_price=24850.0,
        price_levels=[
            PriceLevel(price=24800.0, total_volume=1000),
            PriceLevel(price=24850.0, total_volume=5000),  # Highest volume
            PriceLevel(price=24900.0, total_volume=2000),
        ],
    )
    res = analyzer.analyze(snapshot)
    assert res.poc_price == 24850.0


def test_option_chain_max_pain():
    strikes = [
        StrikeRow(strike=24800.0, call=OptionData(oi=10000), put=OptionData(oi=1000)),
        StrikeRow(strike=24850.0, call=OptionData(oi=8000), put=OptionData(oi=8000)),
        StrikeRow(strike=24900.0, call=OptionData(oi=2000), put=OptionData(oi=12000)),
    ]
    mp = calculate_max_pain(strikes)
    assert mp == 24850.0


def test_option_chain_pcr_and_buildup():
    analyzer = OptionChainAnalyzer()
    strikes = [
        StrikeRow(
            strike=24800.0,
            call=OptionData(oi=20000, oi_change=1000, ltp=150.0),
            put=OptionData(oi=40000, oi_change=8000, ltp=40.0),
        ),
        StrikeRow(
            strike=24850.0,
            call=OptionData(oi=30000, oi_change=2000, ltp=100.0),
            put=OptionData(oi=50000, oi_change=12000, ltp=80.0),
        ),
    ]
    snapshot = OptionChainSnapshot(underlying_price=24825.0, strikes=strikes)
    res = analyzer.analyze(snapshot)
    # Put OI additions (20,000) > Call OI additions (3,000) -> Bullish buildup
    assert res.buildup_score > 0.4
    # Total Put OI (90k) > Total Call OI (50k) -> PCR > 1.0
    assert res.pcr > 1.0
