# DexT3 Order Flow Engine — Complete Diagnostic Audit Report

**Date & Time**: 2026-10-09 13:05 IST  
**Environment**: Windows 11, Python 3.14.5 (.venv), Playwright 1.63.0, Chromium  
**Workspace**: `C:\Users\abhin\OneDrive\Desktop\OF`

---

## 1. Executive Summary

A comprehensive live runtime and code audit was conducted on the DexT3 trading bot. The audit confirmed that the Playwright persistent browser context **launches successfully in headed mode** and reuses the saved authenticated profile without data loss. Live screenshots **are genuinely captured to disk** and passed to the Vision AI model (Gemini 2.5 Flash).

However, live signal generation was halting because:
1. **Expired Contract in UI**: The DexT3 terminal in the persistent profile was left viewing an expired contract (`NSED68407:NIFTY SEP FUT - 5`), displaying a platform error banner (*"This symbol doesn't exist"*).
2. **Missing Tab Navigation**: The automated browser did not actively click the **"Order Flow"** tab next to the **"Chart"** tab in DexT3 or switch to the active current-month futures contract.
3. **Pydantic Validation Crash on Nulls**: When the Vision model accurately reported `null` for `current_price` and `cumulative_delta` from the empty/error chart, Pydantic threw an unhandled `ValidationError` (`Input should be a valid number, got None`) instead of gracefully marking the cycle as `DATA_UNAVAILABLE`.

---

## 2. Component-by-Component Classification

| Component | Status | Empirical Finding & Evidence |
| :--- | :--- | :--- |
| **Python Virtual Environment** | **WORKING** | `.venv` verified with 28 passing pytest suites. `pip check` reports 0 broken packages. |
| **Playwright & Chromium** | **WORKING** | Launches Chromium via `sync_playwright` with persistent profile. |
| **Persistent Profile Reuse** | **WORKING** | Reuses `browser_profile/dext3_automation` without requiring re-login. User funds and account are visible. |
| **Headed Mode Display** | **WORKING** | Runs with `headless=False` on viewport `1920x1080`. |
| **Screenshot Disk Persistence** | **WORKING** | Actual PNGs verified on disk: `20261009_125709_order_flow.png` (326 KB) and `20261009_125712_option_chain_main.png` (326 KB). |
| **Vision Model Connectivity** | **WORKING** | Connected to Google Gemini 2.5 Flash via `GEMINI_API_KEY`. Image payload was sent and parsed. |
| **DexT3 Chart Navigation** | **FAILED** | DexT3 was stuck on expired September Futures (`This symbol doesn't exist`). Tab switching to "Order Flow" was not actively enforced. |
| **Schema Robustness for Empty Charts** | **FAILED** | `OrderFlowSnapshot` defined `current_price: float = 0.0`. When LLM returned `null`, Pydantic 2 crashed on `ValidationError`. |
| **Signal Engine Confluence** | **WORKING (Mock/Offline)** | Validated across 28 unit tests. Does not execute on live data when chart is empty. |
| **Market Hours Scheduler** | **WORKING** | APScheduler is configured for 5-minute cycles during 09:15–15:30 IST Mon–Fri. |
| **Telegram Notifications** | **NOT VERIFIED (Live)** | Alert template verified with mock badge; actual sending requires user credentials and authorization. |

---

## 3. Detailed Answers to Audit Questions

1. **Does `main.py --live` start a real scheduler?**  
   **YES**. It configures an `APScheduler.BlockingScheduler` with 5-minute cron triggers (`*/5`). It checks `is_market_open` (09:15 - 15:30 IST, Mon-Fri).

2. **Does `--run-once` actually invoke the live browser capture pipeline?**  
   **YES**. Calling `python main.py --run-once` executed `PipelineOrchestrator.execute_cycle(mock_mode=False)`, launched Chromium, navigated to DexT3, and saved screenshots to `data/screenshots/`.

3. **Is the bot silently using mock data?**  
   **NO**. In `--run-once`, `mock_mode` is explicitly `False`. Real screenshots were saved and dispatched to the real Gemini Vision API.

4. **Does the Playwright browser context launch successfully?**  
   **YES**. Launched with PID and window coordinates `(0,0, 1920, 1080)` without error.

5. **Is the persistent browser profile reused correctly?**  
   **YES**. `C:\Users\abhin\OneDrive\Desktop\OF\browser_profile\dext3_automation` was loaded. Session remained active and logged-in.

6. **Is the browser headless or headed?**  
   **HEADED**. Visible browser window is created (`headless=False`).

7. **Is DexT3 navigation implemented?**  
   **PARTIALLY**. Page navigated to `https://dext.dhan.co/`, but DexT3 opened to the last viewed expired contract. Symbol search and "Order Flow" tab activation were not handling the expired contract error state.

8. **Are real chart selectors implemented?**  
   **PARTIALLY**. Selectors exist in `config.yaml`, but DexT3 uses dynamic class names and canvas rendering. We need resilient multi-strategy locators that specifically select the **"Order Flow"** tab and handle symbol search.

9. **Are screenshots genuinely saved to disk?**  
   **YES**. Files `20261009_125709_order_flow.png` and `20261009_125712_option_chain_main.png` exist with non-zero size (326 KB).

10. **Do AI extraction functions receive those screenshots?**  
    **YES**. Verified via direct API probe: Gemini received the PNG image and returned structured JSON.

11. **Does the signal engine receive genuine validated data?**  
    **FAILED in live run**. Because the chart was empty, Gemini returned `current_price: null`, which triggered a Pydantic `ValidationError` before reaching the signal engine.

12. **Are any exceptions being swallowed?**  
    **NO**. The `ValidationError` propagated and terminated the cycle with a full traceback.

13. **Is the scheduler running outside Indian market hours?**  
    **NO**. When current time is outside 09:15–15:30 IST or on weekends, `scheduled_job` skips with an informative log message.

14. **Does the application exit early because of configuration or missing variables?**  
    **NO**. Configuration loaded cleanly; `GEMINI_API_KEY` was found and used.

---

## 4. Root Causes Identified & Fix Plan

1. **Fix Pydantic Schema**: Change `current_price: Optional[float] = None` and `cumulative_delta: Optional[int] = None` in `OrderFlowSnapshot` and `OptionChainSnapshot`. When the chart has no data, validator catches it as `DATA_UNAVAILABLE` and discards gracefully without crashing.
2. **Implement Resilient DexT3 Navigation**:
   - Detect the "Order Flow" tab in the central widget and click it.
   - Detect if "This symbol doesn't exist" or expired contract is shown, and provide symbol search for current active contract (e.g., `NIFTY OCT FUT` / `NIFTY FUT`).
   - Add dedicated diagnostic commands: `--browser-debug`, `--capture-test`, `--data-debug`.
3. **Structured Live Logging**:
   - Create logs under `logs/bot_runtime.log`, `logs/browser_debug.log`, `logs/capture_debug.log`, `logs/signal_debug.log` with sequence tags `[START]`, `[BROWSER]`, `[AUTH]`, etc.
4. **Diagnostic Status Dashboard**:
   - Built-in lightweight dashboard to inspect live state, screenshots, and logs.
