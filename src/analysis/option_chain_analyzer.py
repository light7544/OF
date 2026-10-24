"""Option Chain Analyzer: Buildup pressure, PCR trend, and Max Pain."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from src.models.schemas import OptionChainSnapshot, StrikeRow
from src.models.validators import cross_check_buildup

logger = logging.getLogger("option_chain_analyzer")


class OptionChainAnalysisResult:
    def __init__(
        self,
        buildup_score: float,
        pcr: float,
        pcr_score: float,
        max_pain: float,
        max_pain_drift_score: float,
        atm_strike: float,
        reasons: Optional[List[str]] = None,
        warnings: Optional[List[str]] = None,
    ):
        self.buildup_score = buildup_score  # -1.0 to +1.0
        self.pcr = pcr
        self.pcr_score = pcr_score  # -1.0 to +1.0
        self.max_pain = max_pain
        self.max_pain_drift_score = max_pain_drift_score  # -1.0 to +1.0
        self.atm_strike = atm_strike
        self.reasons = reasons or []
        self.warnings = warnings or []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "buildup_score": self.buildup_score,
            "pcr": self.pcr,
            "pcr_score": self.pcr_score,
            "max_pain": self.max_pain,
            "max_pain_drift_score": self.max_pain_drift_score,
            "atm_strike": self.atm_strike,
            "reasons": self.reasons,
            "warnings": self.warnings,
        }


def calculate_max_pain(strikes: List[StrikeRow]) -> float:
    """Calculate the Max Pain strike price where option buyers lose the most money."""
    if not strikes:
        return 0.0

    strike_prices = [row.strike for row in strikes]
    min_loss = float("inf")
    max_pain_strike = strike_prices[len(strike_prices) // 2]

    for candidate in strike_prices:
        total_payout = 0.0
        for row in strikes:
            k = row.strike
            # Call payout = max(0, candidate - k) * Call OI
            if row.call and row.call.oi > 0:
                if candidate > k:
                    total_payout += (candidate - k) * row.call.oi

            # Put payout = max(0, k - candidate) * Put OI
            if row.put and row.put.oi > 0:
                if candidate < k:
                    total_payout += (k - candidate) * row.put.oi

        if total_payout < min_loss:
            min_loss = total_payout
            max_pain_strike = candidate

    return max_pain_strike


class OptionChainAnalyzer:
    def __init__(self, near_atm_range: int = 5):
        self.near_atm_range = near_atm_range

    def analyze(self, snapshot: OptionChainSnapshot) -> OptionChainAnalysisResult:
        reasons: List[str] = []
        warnings: List[str] = []
        spot = snapshot.underlying_price or 0.0
        strikes = snapshot.strikes

        if not strikes or spot <= 0:
            return OptionChainAnalysisResult(
                buildup_score=0.0,
                pcr=1.0,
                pcr_score=0.0,
                max_pain=spot,
                max_pain_drift_score=0.0,
                atm_strike=spot,
                reasons=["No strikes available for analysis"],
            )

        # 1. ATM Strike
        atm_row = min(strikes, key=lambda s: abs(s.strike - spot))
        atm_strike = atm_row.strike
        atm_index = strikes.index(atm_row)

        start_idx = max(0, atm_index - self.near_atm_range)
        end_idx = min(len(strikes), atm_index + self.near_atm_range + 1)
        near_atm_strikes = strikes[start_idx:end_idx]

        # 2. Buildup & Pressure Score
        total_call_oi_chg = 0
        total_put_oi_chg = 0
        total_call_oi = 0
        total_put_oi = 0

        for row in near_atm_strikes:
            if row.call:
                total_call_oi += row.call.oi
                total_call_oi_chg += row.call.oi_change
                # Cross-check buildup tag
                consistent, expected = cross_check_buildup(row.call.change, row.call.oi_change, row.call.buildup)
                if not consistent:
                    msg = f"UI tag '{row.call.buildup.value}' differs from matrix '{expected.value}' at CE {row.strike}"
                    warnings.append(msg)
                    logger.debug(msg)

            if row.put:
                total_put_oi += row.put.oi
                total_put_oi_chg += row.put.oi_change
                consistent, expected = cross_check_buildup(row.put.change, row.put.oi_change, row.put.buildup)
                if not consistent:
                    msg = f"UI tag '{row.put.buildup.value}' differs from matrix '{expected.value}' at PE {row.strike}"
                    warnings.append(msg)
                    logger.debug(msg)

        # Net writing pressure: Put OI addition is bullish (+), Call OI addition is bearish (-)
        net_oi_addition = total_put_oi_chg - total_call_oi_chg
        denom = abs(total_put_oi_chg) + abs(total_call_oi_chg) + 1
        buildup_score = max(-1.0, min(1.0, net_oi_addition / denom))

        if buildup_score > 0.3:
            reasons.append(f"Bullish option buildup: Put writers active near ATM (+{total_put_oi_chg:,} PE OI)")
        elif buildup_score < -0.3:
            reasons.append(f"Bearish option buildup: Call writers active near ATM (+{total_call_oi_chg:,} CE OI)")

        # 3. PCR (Put-Call Ratio)
        pcr = snapshot.pcr if snapshot.pcr is not None else 1.0
        if total_call_oi > 0 and (pcr <= 0 or pcr == 1.0):
            # Recalculate across entire visible chain if snapshot default
            all_put_oi = sum(r.put.oi for r in strikes if r.put)
            all_call_oi = sum(r.call.oi for r in strikes if r.call)
            if all_call_oi > 0:
                pcr = all_put_oi / all_call_oi

        # PCR Score: > 1.2 bullish, < 0.8 bearish
        pcr_score = max(-1.0, min(1.0, (pcr - 1.0) / 0.4))
        if pcr > 1.15:
            reasons.append(f"Elevated PCR ({pcr:.2f}) indicates bullish put support")
        elif pcr < 0.85:
            reasons.append(f"Depressed PCR ({pcr:.2f}) indicates bearish call overhang")

        # 4. Max Pain
        max_pain = snapshot.max_pain if snapshot.max_pain is not None else 0.0
        if max_pain <= 0:
            max_pain = calculate_max_pain(strikes)

        drift = max_pain - spot
        # Drift score: +1.0 if max pain 100+ points above spot, -1.0 if 100+ points below
        max_pain_drift_score = max(-1.0, min(1.0, drift / 100.0))
        if drift > 20:
            reasons.append(f"Max Pain ({max_pain:.0f}) is above spot ({spot:.1f}), upward pull")
        elif drift < -20:
            reasons.append(f"Max Pain ({max_pain:.0f}) is below spot ({spot:.1f}), downward pull")

        return OptionChainAnalysisResult(
            buildup_score=buildup_score,
            pcr=pcr,
            pcr_score=pcr_score,
            max_pain=max_pain,
            max_pain_drift_score=max_pain_drift_score,
            atm_strike=atm_strike,
            reasons=reasons,
            warnings=warnings,
        )
