"""CLI Entrypoint, Diagnostics, and Scheduler for DexT3 Nifty Signal Engine."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import json
import logging
from pathlib import Path
import sys
import time
from typing import Optional
from zoneinfo import ZoneInfo
from apscheduler.schedulers.blocking import BlockingScheduler

from src.browser.capture import DexT3CaptureEngine
from src.browser.session import BrowserSessionManager, SessionExpiredError
from src.config import load_config
from src.logger import setup_loggers
from src.pipeline import PipelineOrchestrator
from src.storage.db import Database

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

setup_loggers()
logger = logging.getLogger("main")


def get_next_market_open_ist(tz_name: str = "Asia/Kolkata", start_str: str = "09:15") -> datetime:
    """Calculate the next IST market opening datetime."""
    ist = ZoneInfo(tz_name)
    now = datetime.now(ist)
    start_h, start_m = map(int, start_str.split(":"))

    candidate = now.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
    if candidate <= now or candidate.weekday() > 4:
        # Move forward until a weekday at 09:15
        candidate += timedelta(days=1)
        while candidate.weekday() > 4:
            candidate += timedelta(days=1)
        candidate = candidate.replace(hour=start_h, minute=start_m, second=0, microsecond=0)

    return candidate


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


def run_browser_debug(config) -> bool:
    """Phase 2 diagnostic command: Inspect DexT3 DOM, tabs, and authentication visually."""
    print("\n" + "=" * 70)
    print(" DEXT3 BROWSER AUTOMATION DIAGNOSTIC (--browser-debug)")
    print("=" * 70)
    session_mgr = BrowserSessionManager(config.browser)
    capture_engine = DexT3CaptureEngine(session_mgr, "screenshots")

    try:
        print("[1/5] Launching visible Chromium browser...")
        session_mgr.get_or_create_context(headless=False)
        page = session_mgr.get_page()

        print(f"[2/5] Navigating to {config.browser.url}...")
        page.goto(config.browser.url, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)

        # Basic Info
        title = page.title()
        url = page.url
        print(f"      • Current URL  : {url}")
        print(f"      • Page Title   : {title}")

        # Check authentication
        is_auth = session_mgr.is_session_valid(page)
        print(f"      • Authenticated: {'YES (Logged In)' if is_auth else 'NO (Login Required)'}")

        # Initial Diagnostic Screenshot
        before_shot = capture_engine.capture_debug_screenshot(page, label="debug_initial")
        print(f"      • Initial Screenshot: {before_shot}")

        if not is_auth:
            print("\n[!] Session is not authenticated. Please log in using 'python main.py --setup'.")
            return False

        # Inspect visible navigation and tabs
        print("\n[3/5] Inspecting visible DOM navigation controls...")
        tabs = page.query_selector_all("button, [role='tab'], span")
        visible_tab_names = []
        for t in tabs:
            try:
                txt = t.inner_text().strip()
                if txt and len(txt) < 30 and txt not in visible_tab_names:
                    visible_tab_names.append(txt)
            except Exception:
                pass

        matching_controls = [name for name in visible_tab_names if any(k in name.lower() for k in ["order flow", "chart", "option", "widget", "nifty"])]
        print(f"      • Relevant Visible Controls: {matching_controls[:10]}")

        # Attempt to switch to Order Flow
        print("\n[4/5] Attempting navigation to Order Flow tab...")
        switched = capture_engine.switch_to_order_flow_view(page)
        print(f"      • Order Flow Tab Navigation: {'TRIGGERED' if switched else 'ALREADY ACTIVE / SKIPPED'}")

        # After Screenshot
        after_shot = capture_engine.capture_debug_screenshot(page, label="debug_after_nav")
        print(f"      • Post-Navigation Screenshot: {after_shot}")

        print("\n[5/5] Diagnostic checks complete.")
        print(f"Inspect diagnostic screenshots in: {Path('screenshots/debug').resolve()}")
        print("=" * 70 + "\n")
        return True

    except Exception as e:
        logger.error("Browser debug failed: %s", e, exc_info=True)
        return False
    finally:
        session_mgr.close()


def run_capture_test(config) -> bool:
    """Phase 3 diagnostic command: Capture real screenshots with validation and metadata."""
    print("\n" + "=" * 70)
    print(" DEXT3 LIVE CAPTURE TEST (--capture-test)")
    print("=" * 70)
    session_mgr = BrowserSessionManager(config.browser)
    capture_engine = DexT3CaptureEngine(session_mgr, "screenshots")

    try:
        session_mgr.get_or_create_context(headless=False)
        page = session_mgr.get_page()

        # Footprint Capture
        print("\n[1/2] Capturing NIFTY Order Flow Footprint Chart...")
        of_path = capture_engine.capture_order_flow(page)
        of_files = [Path(p) for p in of_path] if isinstance(of_path, list) else [Path(of_path)]
        for of_file in of_files:
            if of_file.exists() and of_file.stat().st_size > 1000:
                print(f"      • SUCCESS: {of_file.resolve()} ({of_file.stat().st_size / 1024:.1f} KB)")
            else:
                print(f"      • FAILED: File missing or empty: {of_file}")

        # Option Chain Capture
        print("\n[2/2] Capturing Option Chain Interface...")
        oc_paths = capture_engine.capture_option_chain(page)
        for p in oc_paths:
            f = Path(p)
            if f.exists() and f.stat().st_size > 1000:
                print(f"      • SUCCESS: {f.resolve()} ({f.stat().st_size / 1024:.1f} KB)")
            else:
                print(f"      • FAILED: File missing or empty: {p}")

        print("\n" + "=" * 70)
        print("Capture Test Finished. Verified files saved to 'screenshots/'")
        print("=" * 70 + "\n")
        return True

    except Exception as e:
        logger.error("Capture test failed: %s", e, exc_info=True)
        return False
    finally:
        session_mgr.close()


def run_data_debug(config) -> None:
    """Phase 5 diagnostic command: Display detailed data extraction provenance, age, and validity."""
    print("\n" + "=" * 70)
    print(" DEXT3 DATA EXTRACTION PROVENANCE & DEBUG AUDIT (--data-debug)")
    print("=" * 70)

    db = Database(config.storage.database_path)
    state_file = Path("data/runtime_state.json")
    state = {}
    if state_file.exists():
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    of = db.get_latest_order_flow()
    oc = db.get_latest_option_chain()
    signals = db.get_recent_signals(limit=1)
    latest_sig = signals[0] if signals else None

    source_tag = state.get("source", "MOCK" if config.vision.mock_mode else "LIVE")
    print(f"  • Source                    : {source_tag}")
    print(f"  • Instrument                : {of.symbol if of else 'NIFTY'}")
    print(f"  • Chart Timeframe           : {of.candle_interval if of else '5m'}")
    print(f"  • Last Cycle Timestamp      : {state.get('last_cycle', 'N/A')}")
    print(f"  • Last Cycle Status         : {state.get('status', 'N/A')}")
    print(f"  • Validation Errors         : {state.get('validation_errors', 'None')}")
    print("-" * 70)

    if of:
        print("  [ORDER FLOW]")
        print(f"  • Current Price             : {of.current_price or 'DATA_UNAVAILABLE'}")
        print(f"  • Cumulative Volume Delta   : {of.cumulative_delta if of.cumulative_delta is not None else 'DATA_UNAVAILABLE'}")
        print(f"  • Price Levels Captured     : {len(of.price_levels)}")
        print(f"  • Candle Deltas Captured    : {len(of.candle_deltas)}")
        print(f"  • POC / VAH / VAL           : {of.poc_price or 'N/A'} / {of.vah_price or 'N/A'} / {of.val_price or 'N/A'}")
    else:
        print("  [ORDER FLOW] No snapshots in database.")

    print("-" * 70)
    if oc:
        print("  [OPTION CHAIN]")
        print(f"  • Underlying Spot Price     : {oc.underlying_price or 'DATA_UNAVAILABLE'}")
        print(f"  • Expiry                    : {oc.expiry or 'N/A'}")
        print(f"  • PCR                       : {oc.pcr if oc.pcr is not None else 'DATA_UNAVAILABLE'}")
        print(f"  • ATM IV (%)                : {oc.atm_iv if oc.atm_iv is not None else 'DATA_UNAVAILABLE'}")
        print(f"  • Max Pain                  : {oc.max_pain if oc.max_pain is not None else 'DATA_UNAVAILABLE'}")
        print(f"  • Active Strike Rows        : {len(oc.strikes)}")
    else:
        print("  [OPTION CHAIN] No snapshots in database.")

    print("-" * 70)
    if latest_sig:
        print("  [LATEST SIGNAL DECISION]")
        print(f"  • Signal                    : {latest_sig.get('signal')}")
        print(f"  • Confidence                : {float(latest_sig.get('confidence', 0))*100:.1f}%")
        print(f"  • Action Strike & Option    : {latest_sig.get('strike')} {latest_sig.get('option_type')}")
        print(f"  • Reason                    : {latest_sig.get('reason')}")
    print("=" * 70 + "\n")


def run_dashboard(config, port: int = 8501) -> None:
    """Phase 8 diagnostic command: Start local lightweight HTTP status dashboard."""
    import http.server
    import socketserver

    db = Database(config.storage.database_path)

    class DashboardHandler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/" or self.path == "/index.html":
                self.send_response(200)
                self.send_header("Content-type", "text/html; charset=utf-8")
                self.end_headers()

                # Gather live data
                of = db.get_latest_order_flow()
                oc = db.get_latest_option_chain()
                signals = db.get_recent_signals(limit=5)
                trades = db.get_open_paper_trades()
                state_file = Path("data/runtime_state.json")
                state = {}
                if state_file.exists():
                    try:
                        state = json.loads(state_file.read_text(encoding="utf-8"))
                    except Exception:
                        pass

                source = state.get("source", "MOCK" if config.vision.mock_mode else "LIVE")
                status = state.get("status", "IDLE")

                sig_rows = "".join(
                    f"<tr><td>{s.get('timestamp','')}</td><td><b>{s.get('signal','')}</b></td><td>{s.get('confidence',0)*100:.1f}%</td><td>{s.get('underlying_price','')}</td><td>{s.get('strike','')} {s.get('option_type','')}</td></tr>"
                    for s in signals
                )

                trade_rows = "".join(
                    f"<tr><td>{t.id}</td><td>{t.strike} {t.option_type}</td><td>{t.entry_price}</td><td>{t.current_price}</td><td>{t.stop_loss}</td><td>{t.pnl_points:+.1f} pts</td><td>{t.status}</td></tr>"
                    for t in trades
                )

                html = f"""<!DOCTYPE html>
<html>
<head>
    <title>DexT3 Trading Bot Diagnostic Dashboard</title>
    <meta http-equiv="refresh" content="10">
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 24px; }}
        .header {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #334155; padding-bottom: 16px; margin-bottom: 24px; }}
        .badge {{ padding: 6px 12px; border-radius: 6px; font-weight: bold; font-size: 14px; text-transform: uppercase; }}
        .badge-live {{ background: #059669; color: white; }}
        .badge-mock {{ background: #d97706; color: white; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; margin-bottom: 24px; }}
        .card {{ background: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 18px; }}
        .card h3 {{ margin-top: 0; color: #94a3b8; font-size: 14px; text-transform: uppercase; }}
        .val {{ font-size: 24px; font-weight: bold; color: #38bdf8; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 12px; }}
        th, td {{ padding: 10px; border-bottom: 1px solid #334155; text-align: left; font-size: 14px; }}
        th {{ color: #94a3b8; font-weight: 600; }}
    </style>
</head>
<body>
    <div class="header">
        <div>
            <h1 style="margin: 0; font-size: 24px;">DexT3 Order Flow & Option Chain Engine</h1>
            <p style="margin: 4px 0 0; color: #94a3b8; font-size: 14px;">Diagnostic Status Dashboard (Auto-refresh: 10s)</p>
        </div>
        <div>
            <span class="badge {'badge-live' if source == 'LIVE' else 'badge-mock'}">{source} MODE</span>
            <span class="badge" style="background: #3b82f6; margin-left: 8px;">{status}</span>
        </div>
    </div>

    <div class="grid">
        <div class="card">
            <h3>Underlying Spot</h3>
            <div class="val">{oc.underlying_price if oc and oc.underlying_price else (of.current_price if of and of.current_price else 'N/A')}</div>
        </div>
        <div class="card">
            <h3>Cumulative Delta</h3>
            <div class="val">{of.cumulative_delta if of and of.cumulative_delta is not None else 'N/A'}</div>
        </div>
        <div class="card">
            <h3>Option Chain PCR</h3>
            <div class="val">{f'{oc.pcr:.3f}' if oc and oc.pcr else 'N/A'}</div>
        </div>
        <div class="card">
            <h3>Max Pain</h3>
            <div class="val">{f'{oc.max_pain:.0f}' if oc and oc.max_pain else 'N/A'}</div>
        </div>
    </div>

    <div class="card" style="margin-bottom: 24px;">
        <h3>Open Paper Trades ({len(trades)} active)</h3>
        <table>
            <thead><tr><th>ID</th><th>Contract</th><th>Entry</th><th>Current</th><th>Stop Loss</th><th>PnL</th><th>Status</th></tr></thead>
            <tbody>{trade_rows if trade_rows else '<tr><td colspan="7" style="color: #64748b;">No active trades</td></tr>'}</tbody>
        </table>
    </div>

    <div class="card">
        <h3>Recent Generated Signals</h3>
        <table>
            <thead><tr><th>Timestamp</th><th>Signal</th><th>Confidence</th><th>Spot</th><th>Strike</th></tr></thead>
            <tbody>{sig_rows if sig_rows else '<tr><td colspan="5" style="color: #64748b;">No signals generated yet</td></tr>'}</tbody>
        </table>
    </div>
</body>
</html>"""
                self.wfile.write(html.encode("utf-8"))
            else:
                super().do_GET()

    print("\n" + "=" * 70)
    print(f" Starting Local Diagnostic Dashboard on http://127.0.0.1:{port}")
    print(" Press Ctrl+C to terminate the dashboard server.")
    print("=" * 70 + "\n")

    with socketserver.TCPServer(("", port), DashboardHandler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nDashboard stopped.")


def scheduled_job(orchestrator: PipelineOrchestrator, mock_mode: bool = False, force: bool = False) -> None:
    """Invoked by APScheduler every 5 minutes."""
    config = orchestrator.config
    if not mock_mode and not force and not is_market_open(
        config.scheduler.timezone,
        config.scheduler.market_start_time,
        config.scheduler.market_end_time,
    ):
        next_open = get_next_market_open_ist(config.scheduler.timezone, config.scheduler.market_start_time)
        print(f"\nMARKET CLOSED — NEXT CHECK: {next_open.strftime('%Y-%m-%d %H:%M:%S IST')}")
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
    parser.add_argument("--config", type=str, default=None, help="Path to custom config.yaml")
    parser.add_argument("--setup", action="store_true", help="One-time manual 2FA/OTP login setup.")
    parser.add_argument("--login-only", action="store_true", help="Alias for --setup.")
    parser.add_argument("--browser-debug", action="store_true", help="Inspect visible browser, tabs, and DOM navigation.")
    parser.add_argument("--capture-test", action="store_true", help="Capture real screenshots to screenshots/ and validate.")
    parser.add_argument("--data-debug", action="store_true", help="Display extracted data provenance, values, and age.")
    parser.add_argument("--dashboard", action="store_true", help="Launch local HTTP diagnostic status dashboard.")
    parser.add_argument("--run-once", action="store_true", help="Execute one single 5-minute capture/signal cycle and exit.")
    parser.add_argument("--live", action="store_true", help="Run continuous scheduler every 5 minutes during market hours.")
    parser.add_argument("--mock", action="store_true", help="Use synthetic mock snapshots (offline).")
    parser.add_argument("--force", action="store_true", help="Force cycle execution even when market is closed.")
    parser.add_argument("--verify-db", action="store_true", help="Inspect existing records stored in the SQLite database.")
    parser.add_argument("--angel-test", action="store_true", help="Test live Angel One Option Chain fetch and confluence.")

    args = parser.parse_args()
    config = load_config(args.config)

    # 1. Manual Login Setup
    if args.setup or args.login_only:
        session_mgr = BrowserSessionManager(config.browser)
        try:
            success = session_mgr.interactive_login(timeout_seconds=600)
        finally:
            session_mgr.close()
        sys.exit(0 if success else 1)

    # 2. Browser Debug
    if args.browser_debug:
        success = run_browser_debug(config)
        sys.exit(0 if success else 1)

    # 3. Capture Test
    if args.capture_test:
        success = run_capture_test(config)
        sys.exit(0 if success else 1)

    # 4. Data Debug
    if args.data_debug:
        run_data_debug(config)
        sys.exit(0)

    # 5. Diagnostic Dashboard
    if args.dashboard:
        run_dashboard(config)
        sys.exit(0)

    # 6. Verify Database
    if args.verify_db:
        verify_database(args.config)
        sys.exit(0)

    # 6b. Test Angel One Option Chain
    if args.angel_test:
        import angel_chain
        try:
            api = angel_chain.login()
            master = angel_chain.load_master()
            contracts = angel_chain.option_contracts(master, name="NIFTY")
            spot = angel_chain.get_spot(api)
            chain = angel_chain.add_oi_change(angel_chain.fetch_chain(api, contracts, spot))
            summary = angel_chain.analyze(chain, spot)
            print("\n[ANGEL ONE LIVE FETCH SUCCESS]")
            print(json.dumps(summary, indent=2))
            print("Verdict (BUY test):", angel_chain.confirm_signal("BUY", summary))
        except Exception as e:
            print(f"\n[ANGEL ONE ERROR]: {e}")
        sys.exit(0)

    # 7. Instantiate Pipeline Orchestrator
    orchestrator = PipelineOrchestrator(config)

    # 8. Run Single Cycle
    if args.run_once:
        result = orchestrator.execute_cycle(mock_mode=args.mock)
        print("\nCycle Run Result:", result)
        sys.exit(0 if result.get("status") in ("SUCCESS", "DISCARDED_INVALID_DATA") else 1)

    if args.live:
        ist = ZoneInfo(config.scheduler.timezone)
        scheduler = BlockingScheduler(
            timezone=ist,
            job_defaults={"max_instances": 1, "coalesce": True},
        )

        interval_min = config.scheduler.interval_minutes
        scheduler.add_job(
            scheduled_job,
            "cron",
            minute=f"*/{interval_min}",
            args=[orchestrator, args.mock, args.force],
            id="dext3_signal_cycle",
            replace_existing=True,
        )

        logger.info(
            "Scheduler started. Interval: %d min (IST) | Market hours: %s - %s.",
            interval_min,
            config.scheduler.market_start_time,
            config.scheduler.market_end_time,
        )

        # Initial trigger
        scheduled_job(orchestrator, mock_mode=args.mock, force=args.force)

        try:
            scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            logger.info("Scheduler stopped by user.")
            sys.exit(0)

    parser.print_help()


if __name__ == "__main__":
    main()
