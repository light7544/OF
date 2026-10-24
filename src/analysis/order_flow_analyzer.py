"""Order Flow Analyzer: Cumulative Delta, Divergence, and Imbalances."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from src.models.schemas import OrderFlowSnapshot

logger = logging.getLogger("order_flow_analyzer")


class OrderFlowAnalysisResult:
    def __init__(
        self,
        cvd_score: float,
        cvd_trend: str,
        divergence: Optional[str] = None,
        imbalance_ratio: float = 0.0,
        poc_price: Optional[float] = None,
        vah_price: Optional[float] = None,
        val_price: Optional[float] = None,
        reasons: Optional[List[str]] = None,
    ):
        self.cvd_score = cvd_score  # -1.0 to +1.0
        self.cvd_trend = cvd_trend  # BULLISH, BEARISH, NEUTRAL
        self.divergence = divergence  # BULLISH_ABSORPTION, BEARISH_ABSORPTION, None
        self.imbalance_ratio = imbalance_ratio
        self.poc_price = poc_price
        self.vah_price = vah_price
        self.val_price = val_price
        self.reasons = reasons or []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cvd_score": self.cvd_score,
            "cvd_trend": self.cvd_trend,
            "divergence": self.divergence,
            "imbalance_ratio": self.imbalance_ratio,
            "poc_price": self.poc_price,
            "vah_price": self.vah_price,
            "val_price": self.val_price,
            "reasons": self.reasons,
        }


class OrderFlowAnalyzer:
    def __init__(self, imbalance_threshold: float = 3.0):
        self.imbalance_threshold = imbalance_threshold

    def analyze(self, snapshot: OrderFlowSnapshot) -> OrderFlowAnalysisResult:
        reasons: List[str] = []

        # 1. Cumulative Delta calculation & trend
        candle_deltas = snapshot.candle_deltas
        cumulative_delta = snapshot.cumulative_delta if snapshot.cumulative_delta is not None else 0
        if cumulative_delta == 0 and candle_deltas:
            cumulative_delta = sum(cd.delta for cd in candle_deltas)

        cvd_trend = "NEUTRAL"
        cvd_score = 0.0

        if candle_deltas and len(candle_deltas) >= 2:
            last_delta = candle_deltas[-1].delta if candle_deltas[-1].delta is not None else 0
            prev_delta = candle_deltas[-2].delta if candle_deltas[-2].delta is not None else 0
            delta_slope = last_delta - prev_delta

            if cumulative_delta > 500 and last_delta > 0:
                cvd_score = min(1.0, 0.4 + (cumulative_delta / 5000.0) * 0.6)
                cvd_trend = "BULLISH"
                reasons.append(f"Strong positive cumulative delta ({cumulative_delta:+d})")
            elif cumulative_delta < -500 and last_delta < 0:
                cvd_score = max(-1.0, -0.4 + (cumulative_delta / 5000.0) * 0.6)
                cvd_trend = "BEARISH"
                reasons.append(f"Strong negative cumulative delta ({cumulative_delta:+d})")
            else:
                cvd_score = max(-1.0, min(1.0, cumulative_delta / 2500.0))
                cvd_trend = "BULLISH" if cvd_score > 0.2 else ("BEARISH" if cvd_score < -0.2 else "NEUTRAL")
        else:
            # Single or snapshot level CVD
            if cumulative_delta > 0:
                cvd_score = min(1.0, cumulative_delta / 2500.0)
                cvd_trend = "BULLISH" if cvd_score > 0.2 else "NEUTRAL"
            elif cumulative_delta < 0:
                cvd_score = max(-1.0, cumulative_delta / 2500.0)
                cvd_trend = "BEARISH" if cvd_score < -0.2 else "NEUTRAL"

        # 2. Absorption / Divergence detection
        divergence = None
        if candle_deltas and len(candle_deltas) >= 2:
            last_candle = candle_deltas[-1]
            prev_candle = candle_deltas[-2]
            last_close = last_candle.close
            prev_close = prev_candle.close
            last_delta = last_candle.delta if last_candle.delta is not None else 0

            if last_close is not None and prev_close is not None and last_close > 0 and prev_close > 0:
                price_change = last_close - prev_close

                # Bullish absorption: Price falling or flat, but aggressive market buying (positive delta absorption)
                if price_change <= 0 and last_delta > 200:
                    divergence = "BULLISH_ABSORPTION"
                    reasons.append("Bullish absorption: Aggressive buyers accumulating into down move")
                    cvd_score = max(cvd_score, 0.5)

                # Bearish absorption: Price rising or flat, but aggressive market selling (negative delta absorption)
                elif price_change >= 0 and last_delta < -200:
                    divergence = "BEARISH_ABSORPTION"
                    reasons.append("Bearish absorption: Aggressive sellers distributing into up move")
                    cvd_score = min(cvd_score, -0.5)

        # 3. Bid/Ask imbalance from price levels
        total_bid = sum((p.bid_volume or 0) for p in snapshot.price_levels)
        total_ask = sum((p.ask_volume or 0) for p in snapshot.price_levels)
        imbalance_ratio = 1.0
        if total_bid > 0 and total_ask > 0:
            imbalance_ratio = total_bid / total_ask

        # 4. POC / Value Area
        poc_price = snapshot.poc_price
        vah_price = snapshot.vah_price
        val_price = snapshot.val_price

        if not poc_price and snapshot.price_levels:
            # Derive POC as price with maximum total volume
            highest_vol_level = max(snapshot.price_levels, key=lambda pl: pl.total_volume)
            poc_price = highest_vol_level.price

        return OrderFlowAnalysisResult(
            cvd_score=cvd_score,
            cvd_trend=cvd_trend,
            divergence=divergence,
            imbalance_ratio=imbalance_ratio,
            poc_price=poc_price,
            vah_price=vah_price,
            val_price=val_price,
            reasons=reasons,
        )
