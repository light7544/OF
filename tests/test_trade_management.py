"""Unit tests for TradeManager."""

from src.config import TradeManagementConfig
from src.models.schemas import SignalDecision, SignalType
from src.signals.trade_management import TradeManager


def test_create_paper_trade():
    tm = TradeManager(TradeManagementConfig(target1_points=12.0, stop_loss_points=15.0, lot_size=75))
    decision = SignalDecision(
        signal=SignalType.CALL_BUY,
        strike=24850.0,
        option_type="CE",
        entry_price=100.0,
    )
    trade = tm.create_paper_trade(decision)
    assert trade is not None
    assert trade.entry_price == 100.0
    assert trade.stop_loss == 85.0
    assert trade.target1 == 112.0
    assert trade.status == "OPEN"


def test_partial_booking_moves_sl_to_breakeven():
    tm = TradeManager(TradeManagementConfig(target1_points=12.0, stop_loss_points=15.0, trailing_step_points=8.0))
    decision = SignalDecision(signal=SignalType.CALL_BUY, strike=24850.0, option_type="CE", entry_price=100.0)
    trade = tm.create_paper_trade(decision)

    # Price moves to +12 points (Target 1)
    tm.update_trade_price(trade, 112.0)
    assert trade.status == "TARGET1_HIT"
    assert trade.stop_loss == 100.0  # moved to breakeven


def test_trailing_stop_ratchet():
    tm = TradeManager(TradeManagementConfig(target1_points=12.0, stop_loss_points=15.0, trailing_step_points=8.0))
    decision = SignalDecision(signal=SignalType.CALL_BUY, strike=24850.0, option_type="CE", entry_price=100.0)
    trade = tm.create_paper_trade(decision)

    # Price reaches target1 (112.0)
    tm.update_trade_price(trade, 112.0)
    assert trade.stop_loss == 100.0

    # Price reaches target1 + 8 = 120.0 (+8 pts step)
    tm.update_trade_price(trade, 120.0)
    assert trade.stop_loss == 108.0  # 100 + 8

    # Price reaches target1 + 16 = 128.0 (+16 pts step)
    tm.update_trade_price(trade, 128.0)
    assert trade.stop_loss == 116.0  # 100 + 16


def test_stop_loss_hit():
    tm = TradeManager(TradeManagementConfig(target1_points=12.0, stop_loss_points=15.0))
    decision = SignalDecision(signal=SignalType.CALL_BUY, strike=24850.0, option_type="CE", entry_price=100.0)
    trade = tm.create_paper_trade(decision)

    # Price drops to 84.0 (below SL 85.0)
    tm.update_trade_price(trade, 84.0)
    assert trade.status == "CLOSED"
    assert trade.exit_reason == "STOP_LOSS_HIT"
    assert trade.pnl_points == -15.0  # exit_price (85.0) - entry (100.0)


def test_max_open_trades_limit():
    tm = TradeManager(TradeManagementConfig(max_open_trades=1))
    decision = SignalDecision(signal=SignalType.CALL_BUY, strike=24850.0, option_type="CE", entry_price=100.0)
    trade = tm.create_paper_trade(decision, existing_open_count=1)
    assert trade is None
