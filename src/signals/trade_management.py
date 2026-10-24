"""Paper Trade Management: Stop Loss, Targets, and Trailing Ratchet."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Dict, List, Optional
from src.config import TradeManagementConfig
from src.models.schemas import PaperTrade, SignalDecision, SignalType

logger = logging.getLogger("trade_management")


class TradeManager:
    def __init__(self, config: TradeManagementConfig):
        self.config = config

    def create_paper_trade(
        self, decision: SignalDecision, existing_open_count: int = 0
    ) -> Optional[PaperTrade]:
        """Create a new simulated paper trade if signal is CALL_BUY or PUT_BUY and limits permit."""
        if decision.signal not in (SignalType.CALL_BUY, SignalType.PUT_BUY):
            return None

        if existing_open_count >= self.config.max_open_trades:
            logger.warning(
                "Max open paper trades limit (%d) reached. Skipping new trade.",
                self.config.max_open_trades,
            )
            return None

        if not decision.strike or not decision.entry_price:
            logger.warning("Cannot open trade without valid strike and entry price.")
            return None

        entry_price = decision.entry_price
        sl_points = self.config.stop_loss_points
        t1_points = self.config.target1_points

        stop_loss = max(1.0, round(entry_price - sl_points, 2))
        target1 = round(entry_price + t1_points, 2)

        return PaperTrade(
            symbol=decision.symbol,
            strike=decision.strike,
            option_type=decision.option_type or "CE",
            expiry=decision.expiry or "",
            entry_price=entry_price,
            current_price=entry_price,
            stop_loss=stop_loss,
            target1=target1,
            quantity=self.config.lot_size,
            status="OPEN",
            pnl_points=0.0,
            pnl_amount=0.0,
            opened_at=datetime.now(timezone.utc).isoformat(),
            is_mock=decision.is_mock,
        )

    def update_trade_price(self, trade: PaperTrade, new_price: float) -> PaperTrade:
        """Update current price and execute dynamic trailing stop loss logic."""
        if trade.status == "CLOSED":
            return trade

        trade.current_price = round(new_price, 2)
        gain_points = trade.current_price - trade.entry_price

        # Check Stop Loss
        if trade.current_price <= trade.stop_loss:
            trade.status = "CLOSED"
            trade.exit_price = trade.stop_loss
            trade.closed_at = datetime.now(timezone.utc).isoformat()
            trade.exit_reason = "STOP_LOSS_HIT"
            trade.pnl_points = round(trade.exit_price - trade.entry_price, 2)
            trade.pnl_amount = round(trade.pnl_points * trade.quantity, 2)
            logger.info("Paper Trade %s STOP LOSS HIT at %.2f (PnL: %.1f pts)", trade.id, trade.exit_price, trade.pnl_points)
            return trade

        # Check Target 1 Hit (+12 pts)
        if trade.status == "OPEN" and trade.current_price >= trade.target1:
            trade.status = "TARGET1_HIT"
            # Move SL to breakeven
            trade.stop_loss = max(trade.stop_loss, trade.entry_price)
            logger.info(
                "Paper Trade %s TARGET 1 HIT (+%.1f pts). SL adjusted to breakeven (%.2f)",
                trade.id,
                gain_points,
                trade.stop_loss,
            )

        # Dynamic trailing stop ratchet (+8 pts step after Target 1)
        if trade.status == "TARGET1_HIT":
            excess = trade.current_price - trade.target1
            if excess >= self.config.trailing_step_points:
                steps = int(excess // self.config.trailing_step_points)
                ratchet_sl = round(trade.entry_price + (steps * self.config.trailing_step_points), 2)
                if ratchet_sl > trade.stop_loss:
                    trade.stop_loss = ratchet_sl
                    logger.info("Paper Trade %s Trailing SL ratcheted to %.2f", trade.id, trade.stop_loss)

        # Update running PnL
        trade.pnl_points = round(trade.current_price - trade.entry_price, 2)
        trade.pnl_amount = round(trade.pnl_points * trade.quantity, 2)

        return trade
