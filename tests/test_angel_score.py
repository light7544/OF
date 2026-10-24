"""Unit tests for Angel One Option Chain factor scoring, normalization, and fallback modes."""

from datetime import datetime, timedelta, timezone
import pytest

from angel_chain import compute_angel_chain_score
from src.analysis.option_chain_analyzer import OptionChainAnalysisResult
from src.analysis.order_flow_analyzer import OrderFlowAnalysisResult
from src.config import SignalsConfig, SignalWeights
from src.models.schemas import OptionChainSnapshot, OrderFlowSnapshot, SignalType
from src.signals.signal_engine import SignalEngine


@pytest.fixture
def base_snapshots():
    of_snap = OrderFlowSnapshot(current_price=24850.0, cumulative_delta=100)
    oc_snap = OptionChainSnapshot(underlying_price=24850.0)
    return of_snap, oc_snap


@pytest.fixture
def bullish_of_oc_results():
    of_res = OrderFlowAnalysisResult(cvd_score=0.8, cvd_trend="BULLISH", reasons=["Positive Delta"])
    oc_res = OptionChainAnalysisResult(
        buildup_score=0.8,
        pcr=1.2,
        pcr_score=0.8,
        max_pain=24800.0,
        max_pain_drift_score=0.8,
        atm_strike=24850.0,
        reasons=["Call buildup support"],
    )
    return of_res, oc_res


@pytest.fixture
def bearish_of_oc_results():
    of_res = OrderFlowAnalysisResult(cvd_score=-0.8, cvd_trend="BEARISH", reasons=["Negative Delta"])
    oc_res = OptionChainAnalysisResult(
        buildup_score=-0.8,
        pcr=0.7,
        pcr_score=-0.8,
        max_pain=24900.0,
        max_pain_drift_score=-0.8,
        atm_strike=24850.0,
        reasons=["Call writing resistance"],
    )
    return of_res, oc_res


# ==============================================================================
# 1. compute_angel_chain_score Unit Tests
# ==============================================================================

def test_angel_score_bullish():
    summary = {
        "pcr_oi": 1.4,
        "pe_oi_chg_total": 80000,
        "ce_oi_chg_total": 20000,
        "spot": 24820.0,
        "support": 24800.0,
        "resistance": 25200.0,
        "bias": "BULLISH",
    }
    score = compute_angel_chain_score(summary)
    assert 0.0 < score <= 1.0
    assert score > 0.5


def test_angel_score_bearish():
    summary = {
        "pcr_oi": 0.6,
        "pe_oi_chg_total": 15000,
        "ce_oi_chg_total": 75000,
        "spot": 25180.0,
        "support": 24800.0,
        "resistance": 25200.0,
        "bias": "BEARISH",
    }
    score = compute_angel_chain_score(summary)
    assert -1.0 <= score < 0.0
    assert score < -0.5


def test_angel_score_zero_oi_change():
    """Verify that zero OI change falls back cleanly to bias without ZeroDivisionError."""
    summary_neutral = {
        "pcr_oi": 1.0,
        "pe_oi_chg_total": 0,
        "ce_oi_chg_total": 0,
        "spot": 25000.0,
        "support": 24800.0,
        "resistance": 25200.0,
        "bias": "NEUTRAL",
    }
    score_neutral = compute_angel_chain_score(summary_neutral)
    assert score_neutral == 0.0

    summary_bullish_bias = {
        "pcr_oi": 1.0,
        "pe_oi_chg_total": 0,
        "ce_oi_chg_total": 0,
        "spot": 25000.0,
        "support": 24800.0,
        "resistance": 25200.0,
        "bias": "BULLISH",
    }
    score_bias = compute_angel_chain_score(summary_bullish_bias)
    assert score_bias > 0.0


def test_angel_score_empty_or_none():
    assert compute_angel_chain_score(None) == 0.0
    assert compute_angel_chain_score({}) == 0.0
    assert compute_angel_chain_score({"status": "EMPTY_CHAIN"}) == 0.0


# ==============================================================================
# 2. Shadow Mode Tests (Default weight = 0.0)
# ==============================================================================

def test_shadow_mode_computes_score_without_affecting_composite(base_snapshots, bullish_of_oc_results):
    of_snap, oc_snap = base_snapshots
    of_res, oc_res = bullish_of_oc_results

    # Config with shadow mode: angel_chain weight = 0.0
    cfg = SignalsConfig(
        min_confidence=0.65,
        weights=SignalWeights(
            order_flow_cumulative_delta=0.35,
            option_chain_buildup=0.35,
            pcr_trend=0.15,
            max_pain_drift=0.15,
            angel_chain=0.0,
        ),
    )
    engine = SignalEngine(cfg)

    angel_summary = {
        "pcr_oi": 1.3,
        "pe_oi_chg_total": 50000,
        "ce_oi_chg_total": 10000,
        "spot": 24850.0,
        "support": 24800.0,
        "resistance": 25100.0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Evaluate with Angel summary
    decision_with_angel = engine.evaluate(of_res, oc_res, of_snap, oc_snap, angel_summary=angel_summary)

    # Evaluate without Angel summary (fallback)
    decision_fallback = engine.evaluate(of_res, oc_res, of_snap, oc_snap, angel_summary=None)

    # In shadow mode, composite scores MUST be identical
    assert decision_with_angel.factors["weights_mode"] == "SHADOW_MODE"
    assert decision_with_angel.factors["angel_chain_score"] is not None
    assert decision_with_angel.factors["angel_chain_score"] > 0.0
    assert decision_with_angel.factors["angel_chain_weighted"] == 0.0
    assert decision_with_angel.factors["composite_score"] == decision_fallback.factors["composite_score"]


# ==============================================================================
# 3. Active Mode Tests (Weight > 0.0, Normalized)
# ==============================================================================

def test_active_mode_normalizes_composite(base_snapshots, bullish_of_oc_results):
    of_snap, oc_snap = base_snapshots
    of_res, oc_res = bullish_of_oc_results

    # Config with active angel_chain weight = 0.15
    cfg = SignalsConfig(
        min_confidence=0.65,
        weights=SignalWeights(
            order_flow_cumulative_delta=0.35,
            option_chain_buildup=0.35,
            pcr_trend=0.15,
            max_pain_drift=0.15,
            angel_chain=0.15,
        ),
    )
    engine = SignalEngine(cfg)

    # All factors bullish (+0.80) including Angel (+0.80)
    angel_bullish = {
        "pcr_oi": 1.32,
        "pe_oi_chg_total": 80000,
        "ce_oi_chg_total": 10000,
        "spot": 24820.0,
        "support": 24800.0,
        "resistance": 25200.0,
        "bias": "BULLISH",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    decision = engine.evaluate(of_res, oc_res, of_snap, oc_snap, angel_summary=angel_bullish)
    assert decision.factors["weights_mode"] == "ANGEL_ACTIVE"
    assert decision.factors["angel_chain_weighted"] > 0.0
    # Composite remains strictly <= 1.0 due to normalization by total active weight
    assert -1.0 <= decision.factors["composite_score"] <= 1.0


# ==============================================================================
# 4. Fallback Mode Tests (Missing and Stale Data)
# ==============================================================================

def test_fallback_on_missing_angel_data(base_snapshots, bullish_of_oc_results):
    of_snap, oc_snap = base_snapshots
    of_res, oc_res = bullish_of_oc_results

    cfg = SignalsConfig(weights=SignalWeights(angel_chain=0.15))
    engine = SignalEngine(cfg)

    decision = engine.evaluate(of_res, oc_res, of_snap, oc_snap, angel_summary=None)
    assert decision.factors["weights_mode"] == "FALLBACK_BASE"
    assert decision.factors["angel_chain_score"] is None
    assert decision.factors["angel_chain_status"] == "MISSING"


def test_fallback_on_stale_angel_data(base_snapshots, bullish_of_oc_results):
    of_snap, oc_snap = base_snapshots
    of_res, oc_res = bullish_of_oc_results

    cfg = SignalsConfig(weights=SignalWeights(angel_chain=0.15))
    engine = SignalEngine(cfg)

    # 15 minutes old timestamp
    stale_ts = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()
    stale_summary = {
        "pcr_oi": 1.3,
        "pe_oi_chg_total": 50000,
        "ce_oi_chg_total": 10000,
        "spot": 24850.0,
        "support": 24800.0,
        "resistance": 25100.0,
        "timestamp": stale_ts,
    }

    decision = engine.evaluate(of_res, oc_res, of_snap, oc_snap, angel_summary=stale_summary)
    assert decision.factors["weights_mode"] == "FALLBACK_BASE"
    assert decision.factors["angel_chain_score"] is None
    assert decision.factors["angel_chain_status"] == "STALE"


# ==============================================================================
# 5. Sign Verification Tests
# ==============================================================================

def test_negative_angel_score_strengthens_bearish_put_signal(base_snapshots, bearish_of_oc_results):
    """Confirm a negative angel_chain_score makes a bearish (PUT) composite stronger (more negative)."""
    of_snap, oc_snap = base_snapshots
    of_res, oc_res = bearish_of_oc_results

    cfg = SignalsConfig(weights=SignalWeights(angel_chain=0.15))
    engine = SignalEngine(cfg)

    bearish_angel = {
        "pcr_oi": 0.6,
        "pe_oi_chg_total": 10000,
        "ce_oi_chg_total": 60000,
        "spot": 25150.0,
        "support": 24800.0,
        "resistance": 25200.0,
        "bias": "BEARISH",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    decision_bearish = engine.evaluate(of_res, oc_res, of_snap, oc_snap, angel_summary=bearish_angel)
    assert decision_bearish.factors["angel_chain_score"] < -0.5
    assert decision_bearish.signal == SignalType.PUT_BUY
    assert decision_bearish.factors["composite_score"] < 0.0


def test_negative_angel_score_weakens_bullish_call_signal(base_snapshots, bullish_of_oc_results):
    """Confirm a negative angel_chain_score pulls a bullish (CALL) composite weaker."""
    of_snap, oc_snap = base_snapshots
    of_res, oc_res = bullish_of_oc_results

    # Active angel weight
    cfg_active = SignalsConfig(
        min_confidence=0.65,
        weights=SignalWeights(
            order_flow_cumulative_delta=0.35,
            option_chain_buildup=0.35,
            pcr_trend=0.15,
            max_pain_drift=0.15,
            angel_chain=0.25,
        ),
    )
    engine = SignalEngine(cfg_active)

    # Opposing (bearish) Angel data
    bearish_angel = {
        "pcr_oi": 0.5,
        "pe_oi_chg_total": 5000,
        "ce_oi_chg_total": 80000,
        "spot": 25180.0,
        "support": 24800.0,
        "resistance": 25200.0,
        "bias": "BEARISH",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    decision_opposed = engine.evaluate(of_res, oc_res, of_snap, oc_snap, angel_summary=bearish_angel)
    decision_fallback = engine.evaluate(of_res, oc_res, of_snap, oc_snap, angel_summary=None)

    # Bearish Angel significantly lowers the bullish composite score
    assert decision_opposed.factors["composite_score"] < decision_fallback.factors["composite_score"]
