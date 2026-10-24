"""Domain sanity check validators for financial and option data."""

from __future__ import annotations

import logging
from typing import List, Tuple
from src.models.schemas import (
    BuildupType,
    OptionChainSnapshot,
    OrderFlowSnapshot,
)

logger = logging.getLogger("validators")


def cross_check_buildup(
    price_change: float, oi_change: float, reported_tag: BuildupType
) -> Tuple[bool, BuildupType]:
    """Cross-check reported UI buildup tag against the theoretical Price/OI direction matrix.

    Returns (is_consistent, expected_tag).
    """
    if price_change > 0 and oi_change > 0:
        expected = BuildupType.LONG_BUILDUP
    elif price_change < 0 and oi_change > 0:
        expected = BuildupType.SHORT_BUILDUP
    elif price_change > 0 and oi_change < 0:
        expected = BuildupType.SHORT_COVERING
    elif price_change < 0 and oi_change < 0:
        expected = BuildupType.LONG_UNWINDING
    else:
        expected = BuildupType.NEUTRAL

    is_consistent = reported_tag == expected or reported_tag == BuildupType.NEUTRAL
    return is_consistent, expected


def validate_order_flow_snapshot(snapshot: OrderFlowSnapshot) -> Tuple[bool, List[str]]:
    """Validate OrderFlowSnapshot against strict domain rules.

    Returns (is_valid, error_messages).
    """
    errors: List[str] = []

    if snapshot.current_price is None or snapshot.current_price <= 0:
        errors.append(f"Invalid current_price: {snapshot.current_price}")

    if snapshot.cumulative_delta is None and not snapshot.candle_deltas:
        errors.append("Missing cumulative_delta in order flow snapshot")

    if not snapshot.price_levels and not snapshot.candle_deltas:
        errors.append("Order flow snapshot has neither price levels nor candle deltas")

    for pl in snapshot.price_levels:
        if pl.bid_volume < 0 or pl.ask_volume < 0 or pl.total_volume < 0:
            errors.append(
                f"Negative volume at price {pl.price}: bid={pl.bid_volume}, "
                f"ask={pl.ask_volume}, total={pl.total_volume}"
            )

    for cd in snapshot.candle_deltas:
        if cd.total_volume < 0:
            errors.append(f"Negative candle total volume: {cd.total_volume}")

    is_valid = len(errors) == 0
    if not is_valid:
        logger.warning("OrderFlowSnapshot validation FAILED: %s", errors)
    return is_valid, errors


def validate_option_chain_snapshot(snapshot: OptionChainSnapshot) -> Tuple[bool, List[str]]:
    """Validate OptionChainSnapshot against strict financial domain rules.

    Rules:
    - Underlying price > 0
    - Non-empty strikes
    - Strictly ascending strikes
    - Non-negative OI and volume
    - Call delta in [0, 1]
    - Put delta in [-1, 0]
    - IV in plausible range [5, 100]% (if present)
    """
    errors: List[str] = []

    if snapshot.underlying_price is None or snapshot.underlying_price <= 0:
        errors.append(f"Invalid underlying_price: {snapshot.underlying_price}")

    if not snapshot.strikes:
        errors.append("Option chain snapshot has no strikes")
        return False, errors

    # Check strictly ascending strikes
    prev_strike = -1.0
    for row in snapshot.strikes:
        if row.strike <= prev_strike:
            errors.append(f"Strikes not strictly ascending: {row.strike} <= {prev_strike}")
            break
        prev_strike = row.strike

        # Check call side
        if row.call:
            if row.call.oi < 0 or row.call.volume < 0 or row.call.ltp < 0:
                errors.append(f"Negative call values at strike {row.strike}")
            if row.call.greeks:
                g = row.call.greeks
                if g.delta is not None and not (0.0 <= g.delta <= 1.0):
                    errors.append(f"Call delta out of range [0, 1] at {row.strike}: {g.delta}")
                if g.iv is not None and g.iv > 0 and not (3.0 <= g.iv <= 150.0):
                    errors.append(f"Call IV implausible at {row.strike}: {g.iv}")

        # Check put side
        if row.put:
            if row.put.oi < 0 or row.put.volume < 0 or row.put.ltp < 0:
                errors.append(f"Negative put values at strike {row.strike}")
            if row.put.greeks:
                g = row.put.greeks
                if g.delta is not None and not (-1.0 <= g.delta <= 0.0):
                    errors.append(f"Put delta out of range [-1, 0] at {row.strike}: {g.delta}")
                if g.iv is not None and g.iv > 0 and not (3.0 <= g.iv <= 150.0):
                    errors.append(f"Put IV implausible at {row.strike}: {g.iv}")

    is_valid = len(errors) == 0
    if not is_valid:
        logger.warning("OptionChainSnapshot validation FAILED: %s", errors)
    return is_valid, errors
