"""Unit tests for SignalEngine."""

from src.analysis.option_chain_analyzer import OptionChainAnalysisResult
from src.analysis.order_flow_analyzer import OrderFlowAnalysisResult
from src.config import SignalsConfig
from src.models.schemas import (
    OptionChainSnapshot,
    OptionData,
    OrderFlowSnapshot,
    SignalType,
    StrikeRow,
)
from src.signals.signal_engine import SignalEngine, get_atm_strike


def test_atm_strike_rounding():
    assert get_atm_strike(24823.0) == 24800.0
    assert get_atm_strike(24835.0) == 24850.0
    assert get_atm_strike(24876.0) == 24900.0


def test_confluence_call_buy():
    engine = SignalEngine(SignalsConfig(min_confidence=0.60))
    of_res = OrderFlowAnalysisResult(cvd_score=0.85, cvd_trend="BULLISH", reasons=["CVD surge"])
    oc_res = OptionChainAnalysisResult(
        buildup_score=0.80,
        pcr=1.35,
        pcr_score=0.75,
        max_pain=24900.0,
        max_pain_drift_score=0.50,
        atm_strike=24850.0,
        reasons=["Heavy Put writing"],
    )
    of_snap = OrderFlowSnapshot(current_price=24850.0)
    oc_snap = OptionChainSnapshot(
        underlying_price=24850.0,
        strikes=[StrikeRow(strike=24850.0, call=OptionData(ltp=110.0), put=OptionData(ltp=90.0))],
    )

    decision = engine.evaluate(of_res, oc_res, of_snap, oc_snap)
    assert decision.signal == SignalType.CALL_BUY
    assert decision.strike == 24850.0
    assert decision.option_type == "CE"
    assert decision.entry_price == 110.0
    assert decision.confidence >= 0.60


def test_confluence_put_buy():
    engine = SignalEngine(SignalsConfig(min_confidence=0.60))
    of_res = OrderFlowAnalysisResult(cvd_score=-0.85, cvd_trend="BEARISH", reasons=["CVD dump"])
    oc_res = OptionChainAnalysisResult(
        buildup_score=-0.80,
        pcr=0.70,
        pcr_score=-0.75,
        max_pain=24750.0,
        max_pain_drift_score=-0.60,
        atm_strike=24850.0,
        reasons=["Heavy Call writing"],
    )
    of_snap = OrderFlowSnapshot(current_price=24850.0)
    oc_snap = OptionChainSnapshot(
        underlying_price=24850.0,
        strikes=[StrikeRow(strike=24850.0, call=OptionData(ltp=110.0), put=OptionData(ltp=95.0))],
    )

    decision = engine.evaluate(of_res, oc_res, of_snap, oc_snap)
    assert decision.signal == SignalType.PUT_BUY
    assert decision.strike == 24850.0
    assert decision.option_type == "PE"
    assert decision.entry_price == 95.0
    assert decision.confidence >= 0.60


def test_contradictory_signals_produce_no_trade():
    engine = SignalEngine(SignalsConfig(min_confidence=0.60))
    # OF is bullish, but Option Chain is bearish
    of_res = OrderFlowAnalysisResult(cvd_score=0.80, cvd_trend="BULLISH")
    oc_res = OptionChainAnalysisResult(
        buildup_score=-0.80,
        pcr=0.70,
        pcr_score=-0.70,
        max_pain=24800.0,
        max_pain_drift_score=-0.50,
        atm_strike=24850.0,
    )
    of_snap = OrderFlowSnapshot(current_price=24850.0)
    oc_snap = OptionChainSnapshot(underlying_price=24850.0)

    decision = engine.evaluate(of_res, oc_res, of_snap, oc_snap)
    assert decision.signal == SignalType.NO_TRADE
    assert "Contradiction" in decision.reason


def test_low_confidence_produces_no_trade():
    engine = SignalEngine(SignalsConfig(min_confidence=0.75))
    of_res = OrderFlowAnalysisResult(cvd_score=0.20, cvd_trend="NEUTRAL")
    oc_res = OptionChainAnalysisResult(
        buildup_score=0.20,
        pcr=1.02,
        pcr_score=0.10,
        max_pain=24850.0,
        max_pain_drift_score=0.0,
        atm_strike=24850.0,
    )
    of_snap = OrderFlowSnapshot(current_price=24850.0)
    oc_snap = OptionChainSnapshot(underlying_price=24850.0)

    decision = engine.evaluate(of_res, oc_res, of_snap, oc_snap)
    assert decision.signal == SignalType.NO_TRADE
    assert "below threshold" in decision.reason


def test_missing_data_produces_data_unavailable():
    engine = SignalEngine(SignalsConfig())
    decision = engine.evaluate(None, None, None, None)
    assert decision.signal == SignalType.DATA_UNAVAILABLE
