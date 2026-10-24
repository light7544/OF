"""Unit tests for notifications."""

from src.models.schemas import SignalDecision, SignalType
from src.notifications.notifier import format_signal_message


def test_format_signal_message():
    decision = SignalDecision(
        signal=SignalType.CALL_BUY,
        confidence=0.78,
        underlying_price=24850.0,
        symbol="NIFTY",
        strike=24850.0,
        option_type="CE",
        expiry="24-OCT-2024",
        entry_price=105.0,
        stop_loss=90.0,
        target_1=117.0,
        target_2=129.0,
        risk_reward=0.8,
        reason="Strong confluence across CVD and near-ATM Put writing.",
        is_mock=True,
    )
    msg = format_signal_message(decision)
    assert "DEXT3 ORDER FLOW ALERT" in msg
    assert "Signal: CALL_BUY" in msg
    assert "Strike: 24850.0" in msg
    assert "Entry: 105.0" in msg
    assert "MOCK / SIMULATION" in msg
