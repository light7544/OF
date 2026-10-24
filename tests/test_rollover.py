"""Unit tests for Nifty contract rollover."""

from datetime import datetime
from zoneinfo import ZoneInfo
from src.browser.capture import determine_active_future_contract, get_last_thursday_of_month


def test_last_thursday_calculation():
    # October 2024: Thursdays are 3, 10, 17, 24, 31 -> Last Thursday is 31
    assert get_last_thursday_of_month(2024, 10) == 31
    # November 2024: Thursdays are 7, 14, 21, 28 -> Last Thursday is 28
    assert get_last_thursday_of_month(2024, 11) == 28


def test_contract_before_expiry():
    # Oct 15, 2024 is before Oct 31 expiry
    dt = datetime(2024, 10, 15, 11, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    contract = determine_active_future_contract(dt)
    assert contract == "NIFTY-OCT-2024-FUT"


def test_contract_after_expiry():
    # Oct 31, 2024 at 16:00 is after 15:30 cutoff -> Rolls to November
    dt = datetime(2024, 10, 31, 16, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    contract = determine_active_future_contract(dt)
    assert contract == "NIFTY-NOV-2024-FUT"


def test_contract_december_year_rollover():
    # Dec 26, 2024 at 16:00 (after Dec expiry) -> Rolls to Jan 2025
    dt = datetime(2024, 12, 26, 16, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    contract = determine_active_future_contract(dt)
    assert contract == "NIFTY-JAN-2025-FUT"
