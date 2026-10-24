"""CLI Entrypoint and Scheduler for DexT3 Nifty Signal Engine."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from apscheduler.schedulers.blocking import BlockingScheduler

from src.config import load_config
from src.pipeline import PipelineOrchestrator
from src.browser.session import BrowserSessionManager, SessionExpiredError

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("main")


def is_market_open(tz_name: str = "Asia/Kolkata", start_str: str = "09:15", end_str: str = "15:30") -> bool:
    """Check if current time is within Indian market trading hours (09:15 - 15:30 IST, Mon-Fri)."""
    ist = ZoneInfo(tz_name)
    now = datetime.now(ist)

    # Monday=0, Friday=4
    if now.weekday() > 4:
        return False

    start_h, start_m = map(int, start_str.split(":"))
    end_h, end_m = map(int, end_str.split(":"))

    market_start = now.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
    market_end = now.replace(hour=end_h, minute=end_m, second=0, microsecond=0)

    return market_start <= now <= market_end


def scheduled_job(orchestrator: PipelineOrchestrator, mock_mode: bool = False) -> None:
    """Invoked by APScheduler every 5 minutes."""
    config = orchestrator.config
    if not mock_mode and not is_market_open(
        config.scheduler.timezone,
        config.scheduler.market_start_time,
        config.scheduler.market_end_time,
    ):
        logger.info("Market is closed. Skipping 5-minute capture cycle.")
        return

    try:
        orchestrator.execute_cycle(mock_mode=mock_mode)
    except SessionExpiredError:
        logger.critical("Cycle halted due to session expiration. Scheduler pausing.")
    except Exception as e:
        logger.error("Error executing scheduled cycle: %s", e)


def verify_database(config_path: str = None) -> None:
    """Display records from the SQLite database."""
    config = load_config(config_path)
    from src.storage.db import Database
    db = Database(config.storage.database_path)

    print("\n" + "=" * 60)
    print(" DATABASE AUDIT SUMMARY: " + config.storage.database_path)
    print("=" * 60)

    # Signals
    signals = db.get_recent_signals(limit=5)
    print(f"\n[SIGNALS - Last {len(signals)}]")
    for s in signals:
        print(f"  • {s['timestamp']} | {s['signal']} | Conf: {s['confidence']*100:.1f}% | Spot: {s['underlying_price']}")

    # Paper Trades
    trades = db.get_open_paper_trades()
    print(f"\n[OPEN PAPER TRADES - {len(trades)} active]")
    for t in trades:
        print(f"  • {t.id} | {t.strike} {t.option_type} | Entry: {t.entry_price} -> Cur: {t.current_price} | PnL: {t.pnl_points:+.1f} pts")

    # Order Flows
    of = db.get_latest_order_flow()
    print(f"\n[LATEST ORDER FLOW]: {of.symbol if of else 'None'} ({of.timestamp if of else ''})")

    # Option Chains
    oc = db.get_latest_option_chain()
    print(f"[LATEST OPTION CHAIN]: Spot {oc.underlying_price if oc else 'None'} | PCR {oc.pcr if oc else 'None'}")
    print("=" * 60 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Nifty Order Flow + Option Chain Signal Engine (DexT3)"
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to custom config.yaml",
    )
    parser.add_argument(
        "--setup",
        action="store_true",
        help="One-time manual 2FA/OTP login setup for persistent Chrome profile.",
    )
    parser.add_argument(
        "--login-only",
        action="store_true",
        help="Alias for --setup (opens persistent browser for manual login).",
    )
    parser.add_argument(
        "--run-once",
        action="store_true",
        help="Execute one single 5-minute capture/signal cycle immediately and exit.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Run continuous scheduler every 5 minutes during market hours (09:15 - 15:30 IST).",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Use synthetic mock snapshots (works without API key or live DexT3 session).",
    )
    parser.add_argument(
        "--verify-db",
        action="store_true",
        help="Inspect existing records stored in the SQLite database.",
    )

    args = parser.parse_args()
    config = load_config(args.config)

    # 1. Manual Login Setup Mode
    if args.setup or args.login_only:
        session_mgr = BrowserSessionManager(config.browser)
        try:
            success = session_mgr.interactive_login(timeout_seconds=600)
        finally:
            session_mgr.close()
        sys.exit(0 if success else 1)

    # 2. Verify Database
    if args.verify_db:
        verify_database(args.config)
        sys.exit(0)

    # 3. Instantiate Pipeline Orchestrator
    orchestrator = PipelineOrchestrator(config)

    # 4. Run Single Cycle
    if args.run_once:
        result = orchestrator.execute_cycle(mock_mode=args.mock)
        print("\nCycle Run Result:", result)
        sys.exit(0 if result.get("status") == "SUCCESS" else 1)

    # 5. Live Scheduler
    if args.live:
        ist = ZoneInfo(config.scheduler.timezone)
        scheduler = BlockingScheduler(timezone=ist)

        # Schedule every 5 minutes
        interval_min = config.scheduler.interval_minutes
        scheduler.add_job(
            scheduled_job,
            "cron",
            minute=f"*/{interval_min}",
            args=[orchestrator, args.mock],
            id="dext3_signal_cycle",
            replace_existing=True,
        )

        logger.info(
            "Scheduler started. Running every %d minutes (IST) during market hours (%s - %s).",
            interval_min,
            config.scheduler.market_start_time,
            config.scheduler.market_end_time,
        )
        print("\nPress Ctrl+C to terminate the scheduler.\n")

        # Execute first cycle immediately if market open or mock mode
        scheduled_job(orchestrator, mock_mode=args.mock)

        try:
            scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            logger.info("Scheduler stopped by user.")
            sys.exit(0)

    # If no flags passed, display help
    parser.print_help()


if __name__ == "__main__":
    main()
