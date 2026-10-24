# DexT3 Pipeline Operational Notes & Potential Live Blockers

This document details external dependencies, live browser considerations, and mitigation strategies for the **Nifty Order Flow + Option Chain Signal Engine**.

---

## 1. DexT3 Live DOM Selectors (Terminal UI Specifics)

### Status: Resilient Fallback Configured
- **Observation**: Dhan's DexT3 terminal is a dynamic Single Page Application (SPA). Dhan occasionally updates frontend component class names (e.g. minified CSS modules like `._orderFlow_1a2b`).
- **Mitigation Implemented**:
  - All selectors are defined in `config/config.yaml` rather than hardcoded in the codebase.
  - Multi-selector fallback logic is used (e.g. `button:has-text('+ Widgets'), [aria-label*='Widget'], div:has-text('+ Widgets')`).
  - If a widget container is not immediately matched, the capture engine gracefully falls back to bounding-box / active modal detection.
  - If selectors change after a major Dhan platform redesign, update the corresponding CSS/text selector in `config/config.yaml` under `browser.selectors`.

---

## 2. Canvas-Rendered Footprint Charts

### Status: Solved via Vision LLM Architecture
- **Observation**: DexT3's 15m footprint / order flow chart renders bid/ask volume clusters on an HTML5 `<canvas>`. Standard DOM scraping (e.g. `document.querySelector`) cannot extract text or numbers from canvas pixels.
- **Solution**:
  - The pipeline takes high-resolution cropped PNG screenshots of the `<canvas>` widget.
  - Claude 3.5 Sonnet's vision model reads the bid $\times$ ask clusters, delta bars, and price axis directly from pixel imagery.
  - Strict Pydantic domain validators discard any hallucinations or misreads before data enters the analytical pipeline.

---

## 3. Manual 2FA / OTP Authentication (By Design)

### Status: Permanent Manual Step
- **Constraint**: DexT3 enforces multi-factor authentication (mobile number / password / OTP / QR code).
- **Security Rule**: The pipeline **NEVER** stores passwords or attempts to bypass 2FA.
- **Workflow**:
  1. Run `python main.py --login-only`.
  2. Complete your login manually in the opened browser window.
  3. The browser context saves cookies, session tokens, and localStorage into `data/browser_state/`.
  4. Subsequent automated runs reuse this state.
  5. If the session expires during market hours, the engine pauses with `SessionExpiredError` and alerts you via console and notification.

---

## 4. API Keys & Live Mode Configuration

### Status: Configurable with Offline Fallback
1. **Anthropic API Key (`ANTHROPIC_API_KEY`)**:
   - Required for live Claude 3.5 Sonnet extraction.
   - If not set, the pipeline automatically runs with `MockVisionExtractor`, generating high-fidelity synthetic market snapshots for testing and closed-market verification.
2. **Telegram Bot (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`)**:
   - Optional. If omitted, notifications are printed to standard output in clean formatted markdown.
