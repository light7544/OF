"""Unit tests for SQLite database repository."""

from pathlib import Path
import tempfile
from src.models.schemas import (
    OptionChainSnapshot,
    OrderFlowSnapshot,
    PaperTrade,
    SignalDecision,
    SignalType,
)
from src.storage.db import Database


def test_database_operations():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_signals.db"
        db = Database(str(db_path))

        # 1. Order Flow Snapshot
        of_id = db.save_order_flow(OrderFlowSnapshot(current_price=24850.0, cumulative_delta=500))
        assert of_id > 0
        latest_of = db.get_latest_order_flow()
        assert latest_of is not None
        assert latest_of.current_price == 24850.0

        # 2. Option Chain Snapshot
        oc_id = db.save_option_chain(OptionChainSnapshot(underlying_price=24850.0, pcr=1.25))
        assert oc_id > 0
        latest_oc = db.get_latest_option_chain()
        assert latest_oc is not None
        assert latest_oc.pcr == 1.25

        # 3. Signal Decision
        sig_id = db.save_signal(
            SignalDecision(
                signal=SignalType.CALL_BUY,
                confidence=0.72,
                underlying_price=24850.0,
                strike=24850.0,
                option_type="CE",
            )
        )
        assert sig_id > 0
        recent_signals = db.get_recent_signals(limit=1)
        assert len(recent_signals) == 1
        assert recent_signals[0]["signal"] == "CALL_BUY"

        # 4. Paper Trade
        trade = PaperTrade(
            symbol="NIFTY",
            strike=24850.0,
            option_type="CE",
            entry_price=100.0,
            current_price=100.0,
            stop_loss=85.0,
            target1=112.0,
            quantity=75,
            status="OPEN",
            pnl_points=0.0,
            pnl_amount=0.0,
        )
        trade_id = db.save_paper_trade(trade)
        assert trade_id > 0

        open_trades = db.get_open_paper_trades()
        assert len(open_trades) == 1
        assert open_trades[0].strike == 24850.0

        # Update paper trade
        open_trades[0].current_price = 115.0
        open_trades[0].pnl_points = 15.0
        db.update_paper_trade(open_trades[0])

        updated = db.get_open_paper_trades()[0]
        assert updated.current_price == 115.0
        assert updated.pnl_points == 15.0
