"""Configuration models and loader for DexT3 Signal Engine."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional
import yaml
from pydantic import BaseModel, Field


class BrowserViewport(BaseModel):
    width: int = 1920
    height: int = 1080


class BrowserConfig(BaseModel):
    url: str = "https://dext.dhan.co/"
    user_data_dir: str = "./browser_profile/dext3_automation"
    headless: bool = False
    timeout_ms: int = 30000
    viewport: BrowserViewport = Field(default_factory=BrowserViewport)
    selectors: Dict[str, str] = Field(default_factory=lambda: {
        "widgets_button": "button:has-text('+ Widgets'), [aria-label*='Widget'], div:has-text('+ Widgets')",
        "order_flow_tab": "button:has-text('Order Flow'), div[role='tab']:has-text('Order Flow'), span:has-text('Order Flow')",
        "chart_tab": "button:has-text('Chart'), div[role='tab']:has-text('Chart'), span:has-text('Chart')",
        "order_flow_container": "div.orderflow-container, div[data-widget='order-flow'], div.chart-container, canvas",
        "option_chain_widget": "div[data-widget='option-chain'], div.option-chain-container, div:has-text('Option Chain')",
        "option_chain_greeks_toggle": "button:has-text('Greeks'), input[name='greeks-toggle'], div:has-text('Greeks')",
        "login_indicator": "button:has-text('Sign In'), button:has-text('Log in'), form[action*='login']",
        "user_avatar": "[aria-label*='Account'], [aria-label*='Profile'], div.user-profile, span:has-text('Funds')",
    })


class SchedulerConfig(BaseModel):
    timezone: str = "Asia/Kolkata"
    market_start_time: str = "09:15"
    market_end_time: str = "15:30"
    interval_minutes: int = 5


class StorageConfig(BaseModel):
    database_path: str = "data/signals.db"
    screenshots_dir: str = "data/screenshots"


class SignalWeights(BaseModel):
    order_flow_cumulative_delta: float = 0.35
    option_chain_buildup: float = 0.35
    pcr_trend: float = 0.15
    max_pain_drift: float = 0.15
    angel_chain: float = 0.0


class SignalsConfig(BaseModel):
    min_confidence: float = 0.65
    weights: SignalWeights = Field(default_factory=SignalWeights)


class TradeManagementConfig(BaseModel):
    target1_points: float = 12.0
    trailing_step_points: float = 8.0
    stop_loss_points: float = 15.0
    lot_size: int = 75
    max_risk_per_trade: float = 2000.0
    daily_loss_limit: float = 5000.0
    max_open_trades: int = 2


class VisionConfig(BaseModel):
    provider: str = "anthropic"
    model: str = "claude-3-5-sonnet-20241022"
    max_tokens: int = 2500
    temperature: float = 0.0
    mock_mode: bool = False


class NotificationsConfig(BaseModel):
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    webhook_url: str = ""
    console_output: bool = True


class AppConfig(BaseModel):
    browser: BrowserConfig = Field(default_factory=BrowserConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    signals: SignalsConfig = Field(default_factory=SignalsConfig)
    trade_management: TradeManagementConfig = Field(default_factory=TradeManagementConfig)
    vision: VisionConfig = Field(default_factory=VisionConfig)
    notifications: NotificationsConfig = Field(default_factory=NotificationsConfig)


def load_config(config_path: Optional[str] = None) -> AppConfig:
    """Load configuration from YAML file and apply environment variable overrides."""
    data: Dict[str, Any] = {}

    target_path = Path(config_path) if config_path else Path("config/config.yaml")
    if target_path.exists():
        with open(target_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

    config = AppConfig(**data)

    # Route SQLite database to DATA_DIR (default C:\bot_data) outside OneDrive
    data_dir_env = os.getenv("DATA_DIR", "C:\\bot_data").strip()
    data_dir = Path(data_dir_env)
    data_dir.mkdir(parents=True, exist_ok=True)
    config.storage.database_path = str(data_dir / "signals.db")

    # Environment variable overrides
    if os.getenv("TELEGRAM_BOT_TOKEN"):
        config.notifications.telegram_bot_token = os.environ["TELEGRAM_BOT_TOKEN"]
    if os.getenv("TELEGRAM_CHAT_ID"):
        config.notifications.telegram_chat_id = os.environ["TELEGRAM_CHAT_ID"]
    if os.getenv("WEBHOOK_URL"):
        config.notifications.webhook_url = os.environ["WEBHOOK_URL"]

    # Select vision provider based on available env keys if not specified
    if os.getenv("ANTHROPIC_API_KEY"):
        config.vision.provider = "anthropic"
    elif os.getenv("GEMINI_API_KEY"):
        config.vision.provider = "gemini"
    elif os.getenv("OPENAI_API_KEY"):
        config.vision.provider = "openai"
    elif os.getenv("NVIDIA_API_KEY"):
        config.vision.provider = "nvidia"
    else:
        config.vision.mock_mode = True

    return config
