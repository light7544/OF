"""Multi-factor Confluence Signal Engine."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional
from src.analysis.option_chain_analyzer import OptionChainAnalysisResult
from src.analysis.order_flow_analyzer import OrderFlowAnalysisResult
from src.config import SignalsConfig
from src.models.schemas import (
    OptionChainSnapshot,
    OrderFlowSnapshot,
    SignalDecision,
    SignalType,
)

logger = logging.getLogger("signal_engine")


def get_atm_strike(spot_price: float, step: float = 50.0) -> float:
    """Round spot price to the nearest Nifty strike (multiple of 50)."""
    return round(spot_price / step) * step


class SignalEngine:
    def __init__(self, config: SignalsConfig):
        self.config = config

    def evaluate(
        self,
        of_res: Optional[OrderFlowAnalysisResult],
        oc_res: Optional[OptionChainAnalysisResult],
        of_snapshot: Optional[OrderFlowSnapshot],
        oc_snapshot: Optional[OptionChainSnapshot],
        angel_summary: Optional[Dict[str, Any]] = None,
        is_mock: bool = False,
    ) -> SignalDecision:
        """Evaluate multi-factor confluence and generate a SignalDecision."""
        if not of_res or not oc_res or not of_snapshot or not oc_snapshot:
            return SignalDecision(
                signal=SignalType.DATA_UNAVAILABLE,
                confidence=0.0,
                underlying_price=0.0,
                symbol="NIFTY",
                reason="One or more data snapshots are missing or invalid.",
                is_mock=is_mock,
            )

        spot = oc_snapshot.underlying_price or of_snapshot.current_price or 0.0
        if spot <= 0:
            return SignalDecision(
                signal=SignalType.DATA_UNAVAILABLE,
                confidence=0.0,
                underlying_price=0.0,
                symbol="NIFTY",
                reason="Invalid underlying spot price.",
                is_mock=is_mock,
            )

        # Evaluate Angel One Option Chain factor
        is_angel_valid = False
        angel_score = 0.0
        angel_status = "MISSING"

        if angel_summary and isinstance(angel_summary, dict) and angel_summary.get("status") != "EMPTY_CHAIN":
            ts_str = angel_summary.get("timestamp")
            if ts_str:
                try:
                    ts = datetime.fromisoformat(str(ts_str))
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    age_sec = (datetime.now(timezone.utc) - ts).total_seconds()
                    if age_sec <= 600:  # Fresh within 10 minutes
                        is_angel_valid = True
                        angel_status = "FRESH"
                    else:
                        angel_status = "STALE"
                except Exception:
                    is_angel_valid = True
                    angel_status = "FRESH"
            else:
                is_angel_valid = True
                angel_status = "FRESH"

            if is_angel_valid:
                from angel_chain import compute_angel_chain_score
                angel_score = compute_angel_chain_score(angel_summary)

        w = self.config.weights
        angel_weight = getattr(w, "angel_chain", 0.0)

        if is_angel_valid and angel_weight > 0.0:
            # Active mode: normalize by total active weights so composite is on standard [-1, 1] scale
            total_active_weight = (
                w.order_flow_cumulative_delta
                + w.option_chain_buildup
                + w.pcr_trend
                + w.max_pain_drift
                + angel_weight
            )
            w_of = w.order_flow_cumulative_delta * of_res.cvd_score
            w_oc = w.option_chain_buildup * oc_res.buildup_score
            w_pcr = w.pcr_trend * oc_res.pcr_score
            w_mp = w.max_pain_drift * oc_res.max_pain_drift_score
            w_angel = angel_weight * angel_score

            raw_sum = w_of + w_oc + w_pcr + w_mp + w_angel
            composite_score = raw_sum / total_active_weight if total_active_weight > 0 else raw_sum
            weights_mode = "ANGEL_ACTIVE"
        elif is_angel_valid and angel_weight == 0.0:
            # Shadow mode: angel score is computed & recorded in factors, but has 0 weight and base weights are preserved
            base_total = (
                w.order_flow_cumulative_delta
                + w.option_chain_buildup
                + w.pcr_trend
                + w.max_pain_drift
            )
            w_of = w.order_flow_cumulative_delta * of_res.cvd_score
            w_oc = w.option_chain_buildup * oc_res.buildup_score
            w_pcr = w.pcr_trend * oc_res.pcr_score
            w_mp = w.max_pain_drift * oc_res.max_pain_drift_score
            w_angel = 0.0

            raw_sum = w_of + w_oc + w_pcr + w_mp
            composite_score = raw_sum / base_total if base_total > 0 else raw_sum
            weights_mode = "SHADOW_MODE"
        else:
            # Fallback mode: Angel is missing or stale. Uses base weights without Angel factor
            base_total = (
                w.order_flow_cumulative_delta
                + w.option_chain_buildup
                + w.pcr_trend
                + w.max_pain_drift
            )
            if base_total <= 0:
                base_total = 1.0
                w_of = 0.35 * of_res.cvd_score
                w_oc = 0.35 * oc_res.buildup_score
                w_pcr = 0.15 * oc_res.pcr_score
                w_mp = 0.15 * oc_res.max_pain_drift_score
            else:
                w_of = w.order_flow_cumulative_delta * of_res.cvd_score
                w_oc = w.option_chain_buildup * oc_res.buildup_score
                w_pcr = w.pcr_trend * oc_res.pcr_score
                w_mp = w.max_pain_drift * oc_res.max_pain_drift_score

            w_angel = 0.0
            raw_sum = w_of + w_oc + w_pcr + w_mp
            composite_score = raw_sum / base_total
            weights_mode = "FALLBACK_BASE"

        raw_confidence = abs(composite_score)

        # Check for sharp contradiction between Order Flow and Option Chain
        # e.g., OF is strongly bullish (+0.6) but Option Chain is strongly bearish (-0.6)
        is_contradictory = (of_res.cvd_score > 0.4 and oc_res.buildup_score < -0.4) or (
            of_res.cvd_score < -0.4 and oc_res.buildup_score > 0.4
        )

        factors = {
            "order_flow_score": of_res.cvd_score,
            "order_flow_weighted": round(w_of, 4),
            "option_chain_score": oc_res.buildup_score,
            "option_chain_weighted": round(w_oc, 4),
            "pcr_score": oc_res.pcr_score,
            "pcr_weighted": round(w_pcr, 4),
            "max_pain_drift_score": oc_res.max_pain_drift_score,
            "max_pain_weighted": round(w_mp, 4),
            "angel_chain_score": round(angel_score, 4) if is_angel_valid else None,
            "angel_chain_weighted": round(w_angel, 4) if is_angel_valid else 0.0,
            "angel_chain_status": angel_status,
            "composite_score": round(composite_score, 4),
            "is_contradictory": is_contradictory,
            "weights_mode": weights_mode,
        }

        evidence = of_res.reasons + oc_res.reasons

        if is_contradictory:
            return SignalDecision(
                signal=SignalType.NO_TRADE,
                confidence=round(raw_confidence * 0.5, 3),
                underlying_price=spot,
                symbol="NIFTY",
                reason="Contradiction between Order Flow delta and Option Chain buildup. Neutral stance taken.",
                evidence=evidence,
                factors=factors,
                is_mock=is_mock,
            )

        min_conf = self.config.min_confidence

        if raw_confidence < min_conf:
            return SignalDecision(
                signal=SignalType.NO_TRADE,
                confidence=round(raw_confidence, 3),
                underlying_price=spot,
                symbol="NIFTY",
                reason=f"Composite score ({composite_score:+.2f}) below threshold ({min_conf:.2f}).",
                evidence=evidence,
                factors=factors,
                is_mock=is_mock,
            )

        atm_strike = get_atm_strike(spot)
        expiry = oc_snapshot.expiry or "CURRENT_WEEKLY"

        # Find ATM option prices from option chain strikes
        entry_price = 100.0  # reasonable fallback
        matched_strike = next((s for s in oc_snapshot.strikes if abs(s.strike - atm_strike) < 25), None)

        if composite_score > 0:
            signal_type = SignalType.CALL_BUY
            opt_type = "CE"
            if matched_strike and matched_strike.call and matched_strike.call.ltp > 0:
                entry_price = matched_strike.call.ltp
            action_desc = f"Confluence CALL BUY signal at strike {atm_strike:.0f} CE"
        else:
            signal_type = SignalType.PUT_BUY
            opt_type = "PE"
            if matched_strike and matched_strike.put and matched_strike.put.ltp > 0:
                entry_price = matched_strike.put.ltp
            action_desc = f"Confluence PUT BUY signal at strike {atm_strike:.0f} PE"

        stop_loss = max(1.0, round(entry_price - 15.0, 2))
        target_1 = round(entry_price + 12.0, 2)
        target_2 = round(entry_price + 24.0, 2)
        risk = max(1.0, entry_price - stop_loss)
        reward = target_1 - entry_price
        risk_reward = round(reward / risk, 2)

        return SignalDecision(
            signal=signal_type,
            confidence=round(raw_confidence, 3),
            underlying_price=spot,
            symbol="NIFTY",
            strike=atm_strike,
            option_type=opt_type,
            expiry=expiry,
            entry_price=entry_price,
            stop_loss=stop_loss,
            target_1=target_1,
            target_2=target_2,
            risk_reward=risk_reward,
            reason=f"{action_desc} (Composite: {composite_score:+.2f}, Conf: {raw_confidence*100:.1f}%)",
            evidence=evidence,
            factors=factors,
            is_mock=is_mock,
        )
