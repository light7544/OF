# Nifty Order Flow + Option Chain Signal Engine (DexT3 Browser Automation)

An autonomous, end-to-end algorithmic intelligence system that automates Dhan's DexT3 web terminal, captures Order Flow footprint and Option Chain widgets every 5 minutes during Indian market hours (09:15 - 15:30 IST), extracts structured numerical metrics via Vision LLM (Claude 3.5 Sonnet), validates data against strict financial domain rules, calculates multi-factor trading signals (`CALL_BUY`, `PUT_BUY`, `NO_SIGNAL`), manages paper trade positions with dynamic trailing stops, and broadcasts reports to Telegram/webhooks.

---

## ⚠️ Terms of Use & Personal Automation Notice

> **Important**: This software automates your personal authenticated UI view on Dhan's web platform for personal analytical and paper-trading purposes. It does **not** bypass security, reverse-engineer internal private APIs, or trade live funds.
> 
> Before running this system continuously, please review **Dhan's Terms of Use** to confirm that automated UI interaction for personal viewing and analysis conforms with their user guidelines.

---

## Key Features

1. **Persistent Browser Session (No Stored Credentials)**:
   - Playwright persistent browser context (`data/browser_state/`).
   - One-time manual login with 2FA/OTP.
   - Detects session expiry and pauses with alerts instead of crashing silently.
2. **Dynamic Contract Rollover**:
   - Automatically determines the active monthly Nifty future contract (`NIFTY-<Mon><YYYY>-FUT`) based on the last Thursday of each month and market cutoff (15:30 IST).
3. **Multi-View Option Chain Capture**:
   - Captures both the primary table (OI, Volume, LTP, Buildup) and toggled Greeks view (Delta, Gamma, Theta, Vega, IV).
4. **Vision LLM Extraction (Claude 3.5 Sonnet)**:
   - High-resolution cropped image extraction using strict JSON schemas.
   - Offline / closed-market mock mode for development and automated testing without consuming API credits.
5. **Domain Sanity Validation**:
   - Enforces non-negative OI/volume, Call delta $\in [0, 1]$, Put delta $\in [-1, 0]$, plausible IV $(5-100\%)$, strictly ascending strikes.
   - **Invalid snapshots are discarded immediately** — missing data is strictly preferred over corrupted data.
6. **Analytical Engines**:
   - **Order Flow**: 5-minute candle delta, running cumulative delta from market open, price-vs-delta absorption divergences.
   - **Option Chain**: Near-ATM (ATM $\pm 5$ strikes) net buildup pressure score, UI buildup tag cross-check against the Price/OI matrix, PCR trend analysis, Max Pain drift calculation.
7. **Scored Signal Engine**:
   - Multi-factor weighted confluence scoring with configurable weights in `config.yaml`.
   - Generates confidence score and explicit decision reasoning.
8. **Dynamic Trade Management**:
   - Paper trading position tracking.
   - Book 50% partial profit at $+12$ points, move SL to breakeven, and dynamically trail the remainder with an $+8$-point ratchet.
9. **Instant Alerts**:
   - Telegram Bot API and Webhook notifications with formatted markdown tables, emojis, and contract recommendations.

---

## Project Structure

```
dext t3/
├── config/
│   └── config.yaml             # All thresholds, selectors, weights, and timeouts
├── data/
│   ├── browser_state/          # Playwright persistent context profile (cookies/tokens)
│   ├── screenshots/            # Cropped widget screenshots (audit log)
│   └── signals.db              # SQLite time-series database
├── src/
│   ├── analysis/
│   │   ├── order_flow_analyzer.py    # Cumulative delta & divergence
│   │   └── option_chain_analyzer.py  # Buildup matrix, PCR trend & Max Pain
│   ├── browser/
│   │   ├── capture.py          # DexT3 widget navigation & screenshot cropping
│   │   └── session.py          # Persistent context & interactive 2FA login
│   ├── models/
│   │   ├── schemas.py          # Pydantic data schemas
│   │   └── validators.py       # Domain sanity check validators
│   ├── notifications/
│   │   └── notifier.py         # Telegram / Webhook / Console broadcaster
│   ├── signals/
│   │   ├── signal_engine.py    # Multi-factor confluence scorer
│   │   └── trade_management.py # Partial booking & dynamic trailing stop loss
│   ├── storage/
│   │   └── db.py               # SQLite storage repository
│   ├── vision/
│   │   ├── extractor.py        # Claude Vision + Mock extractor
│   │   └── prompts.py          # Strict JSON system prompts
│   ├── config.py               # YAML configuration loader
│   └── pipeline.py             # 5-minute orchestrator cycle
├── tests/                      # 23 comprehensive unit and integration tests
├── BLOCKERS.md                 # Live UI notes and selector mitigation
├── main.py                     # CLI entrypoint and APScheduler daemon
├── requirements.txt            # Python dependencies
└── README.md
```

---

## Installation & Setup

### 1. Install Dependencies

```powershell
pip install -r requirements.txt
python -m playwright install chromium
```

### 2. Configure Environment Variables (Optional)

Set your API credentials in your environment or PowerShell session:

```powershell
$env:ANTHROPIC_API_KEY="your-anthropic-api-key"
$env:TELEGRAM_BOT_TOKEN="your-telegram-bot-token"
$env:TELEGRAM_CHAT_ID="your-telegram-chat-id"
$env:WEBHOOK_URL="https://discord.com/api/webhooks/..."
```

*(If `ANTHROPIC_API_KEY` is not set, the system automatically runs with `MockVisionExtractor` for risk-free simulation).*

---

## First-Run Manual Login Flow

DexT3 requires 2FA authentication (mobile number / password / OTP / QR code). **Credentials are never stored.**

Run `python first_run_setup.py` once, complete OTP login in the window that opens, then press Enter in the terminal. After that, the scheduled 5-min capture script will reuse this session automatically until it expires.

```powershell
python first_run_setup.py
```

- A dedicated Chrome window will open using the project profile (`./browser_profile/dext3_automation`).
- Complete your OTP/2FA login in the browser window.
- Switch back to the terminal and press **Enter** to save the session state.
- If the session ever expires during market hours, the engine will alert you: *"Session expired — run first_run_setup.py again to log in"*.

---

## Running the Engine

### A. Run a Single Test Cycle (Mock / Simulation)
Verify the entire pipeline end-to-end without connecting to DexT3 or spending API tokens:
```powershell
python main.py --run-once --mock
```

### B. Run a Single Live Cycle
Execute one immediate capture cycle on your active DexT3 session:
```powershell
python main.py --run-once
```

### C. Run the Continuous Live Scheduler
Runs the engine every 5 minutes during Indian market hours (09:15 – 15:30 IST, Monday to Friday):
```powershell
python main.py --live
```

*(You can also run continuous simulation by adding `--mock`: `python main.py --live --mock`).*

### D. Audit Stored Data & Paper Trades
Inspect stored snapshots, signals, and paper trade PnL from the local SQLite database:
```powershell
python main.py --verify-db
```

---

## Configuration Reference (`config/config.yaml`)

| Setting | Default | Description |
| :--- | :--- | :--- |
| `browser.url` | `https://dext.dhan.co/` | Dhan DexT3 web platform entrypoint |
| `browser.headless` | `false` | Headless toggle (keep false for visible inspection) |
| `scheduler.interval_minutes` | `5` | Cycle frequency |
| `scheduler.market_start_time`| `09:15` | Market open time (IST) |
| `scheduler.market_end_time` | `15:30` | Market close time (IST) |
| `signals.min_confidence` | `0.65` | Minimum score $(0.0 - 1.0)$ required to trigger an option signal |
| `signals.weights.order_flow_cumulative_delta` | `0.35` | Confluence weight for cumulative delta & divergence |
| `signals.weights.option_chain_buildup` | `0.35` | Confluence weight for near-ATM Put vs Call buildup |
| `signals.weights.pcr_trend` | `0.15` | Confluence weight for PCR slope |
| `signals.weights.max_pain_drift` | `0.15` | Confluence weight for Max Pain drift |
| `trade_management.target1_points` | `12.0` | Points gain to trigger 50% partial profit booking |
| `trade_management.trailing_step_points`| `8.0` | Points interval to trail stop loss after Target 1 |
| `trade_management.stop_loss_points` | `15.0` | Initial stop loss in option points |

---

## Interpreting Validation Warnings in Logs

The engine runs strict domain sanity checks on every snapshot:

1. **`OrderFlowSnapshot validation FAILED`**:
   - *Cause*: A negative bid/ask volume was reported, or price levels were empty.
   - *Engine Action*: The cycle is immediately **discarded** and logged as `DISCARDED_INVALID_DATA`. No false signals are generated.
2. **`OptionChainSnapshot validation FAILED`**:
   - *Cause*: Call delta $> 1.0$, Put delta $> 0.0$, negative OI, or strike prices are not in strictly ascending order.
   - *Engine Action*: Discarded immediately.
3. **`UI tag 'Short Buildup' differs from matrix 'Long Buildup'`**:
   - *Cause*: The UI tag displayed on the screen differs from the price & OI direction matrix ($\Delta \text{Price} > 0, \Delta \text{OI} > 0$).
   - *Engine Action*: Emitted as an informational data-quality warning, allowing you to cross-reference terminal feed latency.
4. **`SessionExpiredError`**:
   - *Cause*: DexT3 session expired or forced a re-login.
   - *Engine Action*: The pipeline pauses and prompts you to run `python main.py --login-only`.

---

## Running Automated Tests

Run the complete test suite:
```powershell
python -m pytest tests/ -v
```
All 23 unit and integration tests validate:
- Financial sanity rules (OI, Call/Put deltas, IV ranges, strike spacing).
- Order flow cumulative delta and price absorption divergences.
- Buildup tag direction matrix cross-checking.
- Max Pain calculation.
- Signal engine scoring and confidence thresholds.
- Paper trade partial booking (+12 pts) and trailing stop ratchet.
- Dynamic monthly Nifty future rollover calculation across month boundaries.
