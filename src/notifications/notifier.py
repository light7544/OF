"""Alert notifications for Telegram, Webhook, and Console."""

from __future__ import annotations

from datetime import datetime
import logging
from typing import Optional
from zoneinfo import ZoneInfo
import requests

from src.config import NotificationsConfig
from src.models.schemas import PaperTrade, SignalDecision, SignalType

logger = logging.getLogger("notifications")


def format_signal_message(decision: SignalDecision) -> str:
    """Format signal alert matching specification."""
    # Convert UTC timestamp to IST for display
    try:
        dt = datetime.fromisoformat(decision.timestamp.replace("Z", "+00:00"))
        ist_dt = dt.astimezone(ZoneInfo("Asia/Kolkata"))
        ts_str = ist_dt.strftime("%Y-%m-%d %H:%M:%S IST")
    except Exception:
        ts_str = decision.timestamp

    mode = "MOCK / SIMULATION" if decision.is_mock else "PAPER TRADING"
    cvd_val = decision.factors.get("order_flow_score", "N/A")
    if isinstance(cvd_val, (int, float)):
        cvd_val = f"{cvd_val:+.2f}"

    oi_val = decision.factors.get("option_chain_score", "N/A")
    if isinstance(oi_val, (int, float)):
        oi_val = f"{oi_val:+.2f}"

    pcr_val = decision.factors.get("pcr_score", "N/A")
    if isinstance(pcr_val, (int, float)):
        pcr_val = f"{pcr_val:+.2f}"

    msg = [
        "========================================",
        "      DEXT3 ORDER FLOW ALERT",
        "========================================",
        f"Instrument: {decision.symbol}",
        f"Signal: {decision.signal.value if hasattr(decision.signal, 'value') else decision.signal}",
        f"Strike: {decision.strike or 'N/A'}",
        f"Expiry: {decision.expiry or 'N/A'}",
        "",
        f"Entry: {decision.entry_price or 'N/A'}",
        f"Stop Loss: {decision.stop_loss or 'N/A'}",
        f"Target 1: {decision.target_1 or 'N/A'}",
        f"Target 2: {decision.target_2 or 'N/A'}",
        "",
        f"CVD Score: {cvd_val}",
        f"OI Buildup Score: {oi_val}",
        f"PCR Factor: {pcr_val}",
        "",
        f"Score: {int(decision.confidence * 100)}/100",
        f"Risk/Reward: {decision.risk_reward or 'N/A'}",
        f"Timestamp: {ts_str}",
        "",
        f"Reason: {decision.reason}",
        "",
    ]

    angel = decision.factors.get("angel_option_chain")
    confluence = decision.factors.get("confluence_verdict")

    if angel:
        msg.extend([
            "----------------------------------------",
            "       ANGEL ONE OPTION CHAIN",
            "----------------------------------------",
            f"Spot: {angel.get('spot', 'N/A')} | ATM: {angel.get('atm', 'N/A')}",
            f"PCR (OI): {angel.get('pcr_oi', 'N/A')} | PCR (Vol): {angel.get('pcr_vol', 'N/A')}",
            f"Support: {angel.get('support', 'N/A')} | Resistance: {angel.get('resistance', 'N/A')}",
            f"Max Pain: {angel.get('max_pain', 'N/A')} | Bias: {angel.get('bias', 'N/A')}",
            f"Fresh Writing: CE {angel.get('fresh_call_writing', 'N/A')} / PE {angel.get('fresh_put_writing', 'N/A')}",
            "",
        ])

    if confluence:
        msg.extend([
            f"Confluence: {confluence}",
            "",
        ])

    msg.extend([
        f"Mode: {mode}",
        "========================================",
    ])
    return "\n".join(msg)


class Notifier:
    def __init__(self, config: NotificationsConfig):
        self.config = config

    def broadcast_signal(self, decision: SignalDecision) -> bool:
        """Broadcast signal alert to Telegram, webhook, and console."""
        text = format_signal_message(decision)

        if self.config.console_output:
            print("\n" + text + "\n")

        # Telegram Bot
        if self.config.telegram_bot_token and self.config.telegram_chat_id:
            try:
                url = f"https://api.telegram.org/bot{self.config.telegram_bot_token}/sendMessage"
                payload = {
                    "chat_id": self.config.telegram_chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                }
                resp = requests.post(url, json=payload, timeout=10)
                if not resp.ok:
                    logger.warning("Telegram send failed: %s - %s", resp.status_code, resp.text)
            except Exception as e:
                logger.error("Error sending Telegram message: %s", e)

        # Webhook
        if self.config.webhook_url:
            try:
                resp = requests.post(self.config.webhook_url, json={"content": text}, timeout=10)
                if not resp.ok:
                    logger.warning("Webhook send failed: %s", resp.status_code)
            except Exception as e:
                logger.error("Error sending webhook: %s", e)

        return True

    def broadcast_trade_update(self, trade: PaperTrade) -> None:
        text = (
            f"[PAPER TRADE UPDATE] ID: {trade.id} | {trade.symbol} {trade.strike} {trade.option_type}\n"
            f"Status: {trade.status} | Entry: {trade.entry_price} -> Cur: {trade.current_price}\n"
            f"SL: {trade.stop_loss} | PnL: {trade.pnl_points:+.1f} pts (₹{trade.pnl_amount:+,.2f})"
        )
        if self.config.console_output:
            print(f"\n{text}\n")
