"""Data schemas for DexT3 Signal Engine."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, model_validator


class SignalType(str, Enum):
    CALL_BUY = "CALL_BUY"
    PUT_BUY = "PUT_BUY"
    CALL_EXIT = "CALL_EXIT"
    PUT_EXIT = "PUT_EXIT"
    NO_TRADE = "NO_TRADE"
    DATA_UNAVAILABLE = "DATA_UNAVAILABLE"


class BuildupType(str, Enum):
    LONG_BUILDUP = "Long Buildup"
    SHORT_BUILDUP = "Short Buildup"
    SHORT_COVERING = "Short Covering"
    LONG_UNWINDING = "Long Unwinding"
    NEUTRAL = "Neutral"


class OptionGreek(BaseModel):
    delta: Optional[float] = None
    gamma: Optional[float] = None
    theta: Optional[float] = None
    vega: Optional[float] = None
    iv: Optional[float] = None


class OptionData(BaseModel):
    ltp: Optional[float] = 0.0
    change: Optional[float] = 0.0
    volume: Optional[int] = 0
    oi: Optional[int] = 0
    oi_change: Optional[int] = 0
    buildup: BuildupType = BuildupType.NEUTRAL
    greeks: Optional[OptionGreek] = None


class StrikeRow(BaseModel):
    strike: float
    call: Optional[OptionData] = None
    put: Optional[OptionData] = None


class PriceLevel(BaseModel):
    price: float
    bid_volume: int = 0
    ask_volume: int = 0
    total_volume: int = 0
    delta: int = 0
    imbalance_buy: bool = False
    imbalance_sell: bool = False


class CandleDelta(BaseModel):
    timestamp: str = ""
    open: Optional[float] = 0.0
    high: Optional[float] = 0.0
    low: Optional[float] = 0.0
    close: Optional[float] = 0.0
    delta: Optional[int] = 0
    cumulative_delta: Optional[int] = 0
    total_volume: Optional[int] = 0
    poc_price: Optional[float] = None
    vah_price: Optional[float] = None
    val_price: Optional[float] = None


class OrderFlowSnapshot(BaseModel):
    symbol: str = "NIFTY-FUT"
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    current_price: Optional[float] = None
    candle_interval: Optional[str] = "5m"
    cumulative_delta: Optional[int] = None
    price_levels: List[PriceLevel] = Field(default_factory=list)
    candle_deltas: List[CandleDelta] = Field(default_factory=list)
    poc_price: Optional[float] = None
    vah_price: Optional[float] = None
    val_price: Optional[float] = None
    is_mock: bool = False


class OptionChainSnapshot(BaseModel):
    symbol: str = "NIFTY"
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    underlying_price: Optional[float] = None
    expiry: Optional[str] = ""
    days_to_expiry: Optional[int] = 0
    pcr: Optional[float] = 1.0
    atm_iv: Optional[float] = 14.0
    max_pain: Optional[float] = 0.0
    strikes: List[StrikeRow] = Field(default_factory=list)
    is_mock: bool = False


class SignalDecision(BaseModel):
    signal: SignalType = SignalType.NO_TRADE
    confidence: float = 0.0
    underlying_price: float = 0.0
    symbol: str = "NIFTY"
    strike: Optional[float] = None
    option_type: Optional[str] = None  # "CE" or "PE"
    expiry: Optional[str] = None
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    target_1: Optional[float] = None
    target_2: Optional[float] = None
    risk_reward: Optional[float] = None
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    reason: str = ""
    evidence: List[str] = Field(default_factory=list)
    factors: Dict[str, Any] = Field(default_factory=dict)
    is_mock: bool = False


class PaperTrade(BaseModel):
    id: Optional[int] = None
    signal_id: Optional[int] = None
    symbol: str = "NIFTY"
    strike: float = 0.0
    option_type: str = "CE"
    expiry: str = ""
    entry_price: float = 0.0
    current_price: float = 0.0
    stop_loss: float = 0.0
    target1: float = 0.0
    quantity: int = 75
    status: str = "OPEN"  # OPEN, TARGET1_HIT, CLOSED
    pnl_points: float = 0.0
    pnl_amount: float = 0.0
    opened_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    closed_at: Optional[str] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None
    is_mock: bool = False
