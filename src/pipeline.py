"""Pipeline Orchestrator for 5-minute capture and analysis cycle."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from src.analysis.option_chain_analyzer import OptionChainAnalyzer
from src.analysis.order_flow_analyzer import OrderFlowAnalyzer
from src.browser.capture import DexT3CaptureEngine
from src.browser.session import BrowserSessionManager, SessionExpiredError
from src.config import AppConfig
from src.logger import StageLogger
from src.models.schemas import SignalType
from src.models.validators import (
    validate_option_chain_snapshot,
    validate_order_flow_snapshot,
)
from src.notifications.notifier import Notifier
from src.signals.signal_engine import SignalEngine
from src.signals.trade_management import TradeManager
from src.storage.db import Database
from src.vision.extractor import (
    AnthropicVisionExtractor,
    GeminiVisionExtractor,
    MockVisionExtractor,
    NvidiaVisionExtractor,
    OpenAIVisionExtractor,
)

logger = logging.getLogger("pipeline")


class PipelineOrchestrator:
    def __init__(self, config: AppConfig):
        self.config = config
        self.db = Database(config.storage.database_path)
        self.notifier = Notifier(config.notifications)
        self.trade_manager = TradeManager(config.trade_management)
        self.signal_engine = SignalEngine(config.signals)
        self.of_analyzer = OrderFlowAnalyzer()
        self.oc_analyzer = OptionChainAnalyzer()
        self._session_mgr: Optional[BrowserSessionManager] = None
        self._angel_api = None
        self._angel_master = None
        self._angel_cooldown_until: Optional[datetime] = None
        self.state_file = Path("data/runtime_state.json")
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

    def _get_session_manager(self) -> BrowserSessionManager:
        if not self._session_mgr:
            self._session_mgr = BrowserSessionManager(self.config.browser)
        return self._session_mgr

    def _build_vision_extractor(self):
        provider = self.config.vision.provider.lower()
        if provider == "anthropic":
            return AnthropicVisionExtractor(self.config.vision)
        elif provider == "gemini":
            return GeminiVisionExtractor(self.config.vision)
        elif provider == "openai":
            return OpenAIVisionExtractor(self.config.vision)
        elif provider in ("nvidia", "paligemma_nvidia"):
            model = "google/paligemma" if provider == "paligemma_nvidia" else "meta/llama-3.2-11b-vision-instruct"
            return NvidiaVisionExtractor(self.config.vision, model=model)
        elif provider == "mock":
            return MockVisionExtractor(self.config.vision)
        else:
            raise ValueError(f"Unsupported vision provider: {provider}")

    @staticmethod
    def _sanitize_order_flow(snap):
        """Sanitize order flow: fill missing prices/deltas and derive cumulative delta."""
        if snap is None:
            return snap

        spot = snap.current_price or 0.0

        # Filter price levels with valid positive price
        snap.price_levels = [pl for pl in snap.price_levels if pl.price is not None and pl.price > 0]

        # For candles: keep candles that have delta/volume, fill missing OHLC with spot
        good_c = []
        for c in snap.candle_deltas:
            c.delta = c.delta if c.delta is not None else 0
            c.total_volume = c.total_volume if c.total_volume is not None else 0
            if c.close is None or c.close <= 0:
                c.close = spot
            if c.open is None or c.open <= 0:
                c.open = c.close
            if c.high is None or c.high <= 0:
                c.high = c.close
            if c.low is None or c.low <= 0:
                c.low = c.close
            good_c.append(c)
        snap.candle_deltas = good_c

        # If cumulative_delta is missing, compute it from candles or price levels
        if snap.cumulative_delta is None:
            if snap.candle_deltas:
                snap.cumulative_delta = sum(c.delta for c in snap.candle_deltas)
            elif snap.price_levels:
                snap.cumulative_delta = sum(pl.delta for pl in snap.price_levels)
            else:
                snap.cumulative_delta = 0

        return snap

    def execute_cycle(self, mock_mode: bool = False) -> Dict[str, Any]:
        """Execute one complete capture, extraction, validation, and signal cycle."""
        StageLogger.log("start", "Trading bot cycle initialized")
        is_mock = mock_mode or self.config.vision.mock_mode
        cycle_start = datetime.now(timezone.utc).isoformat()

        of_snapshot = None
        oc_snapshot = None
        of_img_path = None
        oc_img_paths = []

        # 1. Capture & Extraction
        if is_mock:
            StageLogger.log("extraction", "Processing mock synthetic snapshots")
            extractor = MockVisionExtractor(self.config.vision)
            of_snapshot = extractor.extract_order_flow()
            oc_snapshot = extractor.extract_option_chain()
        else:
            StageLogger.log("browser", "Launching Playwright Chromium")
            session_mgr = BrowserSessionManager(self.config.browser)
            try:
                capture_engine = DexT3CaptureEngine(session_mgr, "screenshots")
                of_img_path = capture_engine.capture_order_flow()
                oc_img_paths = capture_engine.capture_option_chain()
            except SessionExpiredError as e:
                StageLogger.log("auth", "Session expired / manual login required")
                logger.warning("DexT3 manual login required: %s - skipping cycle and broadcasting alert", e)
                try:
                    self.notifier.broadcast_signal(
                        self.signal_engine.evaluate(None, None, None, None, is_mock=False)
                    )
                except Exception as alert_err:
                    logger.debug("Broadcast alert error: %s", alert_err)
                self.db.log_audit("LOGIN_REQUIRED", str(e))
                return {"status": "LOGIN_REQUIRED", "reason": str(e)}
            except Exception as e:
                logger.error("Browser capture error: %s", e)
                self.db.log_audit("CAPTURE_ERROR", str(e))
                return {"status": "ERROR", "reason": f"Browser capture failed: {e}"}
            finally:
                session_mgr.close()

            StageLogger.log("extraction", f"Processing real screenshots via {self.config.vision.provider}")
            vision_extractor = self._build_vision_extractor()
            try:
                of_snapshot = vision_extractor.extract_order_flow(of_img_path)
                oc_snapshot = vision_extractor.extract_option_chain(oc_img_paths)
            except Exception as e:
                logger.error("Vision extraction error: %s", e)
                self.db.log_audit("EXTRACTION_ERROR", str(e))
                return {"status": "EXTRACTION_ERROR", "reason": str(e)}

        # 2. Domain Sanity Validation
        of_snapshot = self._sanitize_order_flow(of_snapshot)
        logger.info(
            "Extracted: price=%s cum_delta=%s candles=%d levels=%d | OC spot=%s strikes=%d",
            of_snapshot.current_price, of_snapshot.cumulative_delta,
            len(of_snapshot.candle_deltas), len(of_snapshot.price_levels),
            oc_snapshot.underlying_price, len(oc_snapshot.strikes),
        )
        StageLogger.log("validation", "Checking extracted market data")
        of_valid, of_errs = validate_order_flow_snapshot(of_snapshot)
        oc_valid, oc_errs = validate_option_chain_snapshot(oc_snapshot)

        if not of_valid or not oc_valid:
            all_errs = of_errs + oc_errs
            msg = f"Validation rejected: {all_errs}"
            logger.warning("[VALIDATION] %s", msg)
            self.db.log_audit("DISCARDED_INVALID_DATA", msg)

            # Record state
            self._save_runtime_state({
                "last_cycle": cycle_start,
                "status": "DISCARDED_INVALID_DATA",
                "source": "MOCK" if is_mock else "LIVE",
                "validation_errors": all_errs,
                "signal": "DATA_UNAVAILABLE",
            })
            return {"status": "DISCARDED_INVALID_DATA", "errors": all_errs}

        # 3. Persist Snapshots
        self.db.save_order_flow(of_snapshot)
        self.db.save_option_chain(oc_snapshot)

        # 4. Analysis
        StageLogger.log("analysis", "Calculating order-flow indicators and option buildup")
        try:
            of_res = self.of_analyzer.analyze(of_snapshot)
            oc_res = self.oc_analyzer.analyze(oc_snapshot)
        except Exception as e:
            logger.exception("Analysis failed")
            self.db.log_audit("ANALYSIS_ERROR", str(e))
            return {"status": "ANALYSIS_ERROR", "reason": str(e)}

        # 5. Fetch / Generate Angel One Option Chain (before signal generation)
        angel_summary = None
        chain_df = None
        angel_spot = float(oc_snapshot.underlying_price or of_snapshot.current_price or 24850.0)
        expiry_str = "CURRENT"

        if is_mock:
            try:
                import angel_chain
                chain_df = angel_chain.generate_mock_chain(spot=angel_spot)
                angel_summary = angel_chain.analyze(chain_df, angel_spot)
                angel_summary["timestamp"] = datetime.now(timezone.utc).isoformat()
                expiry_str = "MOCK"
            except Exception as e:
                logger.warning("Mock angel chain generation failed: %s", e)
        else:
            now_utc = datetime.now(timezone.utc)
            if self._angel_cooldown_until and now_utc < self._angel_cooldown_until:
                logger.debug(
                    "Angel One in cooldown until %s; skipping fetch.",
                    self._angel_cooldown_until.isoformat(),
                )
            else:
                try:
                    import angel_chain
                    creds = angel_chain.get_env_credentials()
                    if creds.get("api_key") and creds.get("api_key") != "your_key":
                        if not hasattr(self, "_angel_api") or self._angel_api is None:
                            self._angel_api = angel_chain.login(creds)
                            self._angel_master = angel_chain.load_master()

                        contracts = angel_chain.option_contracts(self._angel_master, name="NIFTY")
                        if not contracts.empty and "expiry" in contracts.columns:
                            expiry_str = str(contracts["expiry"].iloc[0])
                        live_spot = angel_chain.get_spot(self._angel_api)
                        if live_spot > 0:
                            angel_spot = live_spot
                        chain_df = angel_chain.fetch_chain(self._angel_api, contracts, angel_spot)
                        chain_df = angel_chain.add_oi_change(chain_df)
                        angel_summary = angel_chain.analyze(chain_df, angel_spot)
                        angel_summary["timestamp"] = datetime.now(timezone.utc).isoformat()
                except Exception as e:
                    self._angel_api = None
                    self._angel_cooldown_until = datetime.now(timezone.utc) + timedelta(minutes=15)
                    logger.warning(
                        "Angel One fetch/login failed; entering 15-minute cooldown until %s. Error: %s",
                        self._angel_cooldown_until.isoformat(),
                        e,
                    )

        # 6. Signal Generation (With Angel Option Chain factor)
        StageLogger.log("signal", "Evaluating multi-factor confluence and recording signal decision")
        decision = self.signal_engine.evaluate(
            of_res, oc_res, of_snapshot, oc_snapshot, angel_summary=angel_summary, is_mock=is_mock
        )

        if angel_summary:
            decision.factors["angel_option_chain"] = angel_summary

            # Confluence verification: ONLY call confirm_signal when signal is a real BUY or SELL
            if decision.signal == SignalType.CALL_BUY:
                confluence = angel_chain.confirm_signal("BUY", angel_summary)
                decision.factors["confluence_verdict"] = confluence
                logger.info("Angel One Confluence Verdict: %s", confluence)
            elif decision.signal == SignalType.PUT_BUY:
                confluence = angel_chain.confirm_signal("SELL", angel_summary)
                decision.factors["confluence_verdict"] = confluence
                logger.info("Angel One Confluence Verdict: %s", confluence)
            else:
                logger.info("Non-directional signal (%s); skipping confluence confirmation", decision.signal)

            if chain_df is not None:
                try:
                    self.db.save_angel_chain_snapshot(
                        expiry=expiry_str,
                        spot=angel_spot,
                        summary=angel_summary,
                        chain_df=chain_df,
                        is_mock=is_mock,
                    )
                except Exception as e:
                    logger.warning("Failed to save angel chain snapshot: %s", e)

        signal_id = self.db.save_signal(decision)

        # 6. Database and Trade Management
        StageLogger.log("database", "Saving analysis record and updating paper trades")
        open_trades = self.db.get_open_paper_trades()

        for trade in open_trades:
            cur_price = trade.current_price
            matched_row = next((s for s in oc_snapshot.strikes if s.strike == trade.strike), None)
            if matched_row:
                if trade.option_type == "CE" and matched_row.call and matched_row.call.ltp > 0:
                    cur_price = matched_row.call.ltp
                elif trade.option_type == "PE" and matched_row.put and matched_row.put.ltp > 0:
                    cur_price = matched_row.put.ltp

            prev_status = trade.status
            self.trade_manager.update_trade_price(trade, cur_price)
            self.db.update_paper_trade(trade)

            if trade.status != prev_status:
                self.notifier.broadcast_trade_update(trade)

        if decision.signal in (SignalType.CALL_BUY, SignalType.PUT_BUY):
            is_duplicate = any(
                t.strike == decision.strike and t.option_type == decision.option_type
                for t in open_trades
            )
            if is_duplicate:
                logger.info("Duplicate signal suppressed: %s %s already active", decision.strike, decision.option_type)
            else:
                new_trade = self.trade_manager.create_paper_trade(decision, existing_open_count=len(open_trades))
                if new_trade:
                    new_trade.signal_id = signal_id
                    self.db.save_paper_trade(new_trade)
                    self.notifier.broadcast_trade_update(new_trade)

        # Broadcast
        self.notifier.broadcast_signal(decision)

        # Save Runtime State for Dashboard
        self._save_runtime_state({
            "last_cycle": cycle_start,
            "status": "SUCCESS",
            "source": "MOCK" if is_mock else "LIVE",
            "signal": decision.signal.value,
            "confidence": decision.confidence,
            "underlying_price": decision.underlying_price,
            "strike": decision.strike,
            "entry_price": decision.entry_price,
            "of_screenshot": of_img_path,
            "oc_screenshot": oc_img_paths[0] if oc_img_paths else None,
        })

        StageLogger.log("cycle", "Processing cycle completed successfully")

        return {
            "status": "SUCCESS",
            "signal": decision.signal.value,
            "confidence": decision.confidence,
            "underlying_price": decision.underlying_price,
            "strike": decision.strike,
            "entry_price": decision.entry_price,
            "is_mock": is_mock,
        }

    def _save_runtime_state(self, state: Dict[str, Any]):
        try:
            self.state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
        except Exception as e:
            logger.debug("Failed to write runtime_state: %s", e)
