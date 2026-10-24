"""Capture engine for DexT3: widgets, order flow tab, option chain, rollover, diagnostics.

v2 fixes (vs original):
  * page.is_visible()/query_selector() with multi-match selectors raised Playwright
    "strict mode violation" -> exception swallowed -> bot silently took a FULL-PAGE
    screenshot for both order flow and option chain. Now we use smallest-visible-element
    lookup and never rely on strict selectors.
  * div:has-text() matched huge ancestor divs, so clicks landed on empty space.
  * Option chain widget was NEVER opened (no Widgets -> Options Chain click). Now it is.
  * Menu text is "Options Chain" (with s), old selector said "Option Chain".
  * Option chain is cropped from the container that holds the 'Strike' header.
  * Expired symbol ("This symbol doesn't exist") is auto-fixed, else a clear error is raised
    instead of sending a garbage screenshot to the vision model.
"""

from __future__ import annotations

import calendar
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import re
from typing import List, Optional
from zoneinfo import ZoneInfo
from playwright.sync_api import Page, TimeoutError as PWTimeout

import shutil
from src.browser.session import BrowserSessionManager, SessionExpiredError
from src.browser.calibration import calibrate_dhan_orderflow_chromium, set_orderflow_timeframe
from src.logger import StageLogger

logger = logging.getLogger("browser_capture")

CLICKABLE = "button, [role='tab'], [role='button'], [role='menuitem'], [role='option'], a, li, span, p, div"

WIDGETS_RX = re.compile(r"^\s*\+?\s*Widgets\s*$", re.I)
OPTION_CHAIN_RX = re.compile(r"^\s*Options?\s*Chain\s*$", re.I)
ORDER_FLOW_RX = re.compile(r"^\s*Order\s*Flow\s*$", re.I)
CHANGE_SYMBOL_RX = re.compile(r"^\s*Change\s*symbol\s*$", re.I)
GREEKS_RX = re.compile(r"^\s*Greeks\s*$", re.I)
STRIKE_RX = re.compile(r"^\s*Strike\s*$", re.I)
EXPIRED_TXT = "This symbol doesn't exist"
NOT_NIFTY_RX = re.compile(r"BANK|FIN|MIDCP|NXT", re.I)


class CaptureError(RuntimeError):
    """Raised when DexT3 is not in a state that allows a trustworthy capture."""


def get_last_thursday_of_month(year: int, month: int) -> int:
    """Return the day of month for the last Thursday of a given year and month."""
    cal = calendar.monthcalendar(year, month)
    last_thursday = [week[3] for week in cal if week[3] != 0][-1]
    return last_thursday


def determine_active_future_contract(dt: Optional[datetime] = None, tz_name: str = "Asia/Kolkata") -> str:
    """Determine the active monthly Nifty future contract based on last Thursday rollover (15:30 IST).

    NOTE: NSE moved Nifty expiries to Tuesday in 2025 - verify rollover day near month end.
    """
    ist = ZoneInfo(tz_name)
    now = dt or datetime.now(ist)
    if now.tzinfo is None:
        now = now.replace(tzinfo=ist)
    else:
        now = now.astimezone(ist)

    year = now.year
    month = now.month

    last_thursday_day = get_last_thursday_of_month(year, month)
    expiry_dt = now.replace(day=last_thursday_day, hour=15, minute=30, second=0, microsecond=0)

    if now > expiry_dt:
        if month == 12:
            month = 1
            year += 1
        else:
            month += 1

    month_abbr = calendar.month_abbr[month].upper()
    return f"NIFTY-{month_abbr}-{year}-FUT"


# --------------------------------------------------------------------------- helpers
def find_smallest_visible(page: Page, rx: re.Pattern, limit: int = 40):
    """Innermost visible element whose text matches rx (fixes 'clicked the big parent div')."""
    try:
        loc = page.locator(CLICKABLE).filter(has_text=rx)
        n = min(loc.count(), limit)
    except Exception:
        return None
    best, best_area = None, None
    for i in range(n):
        el = loc.nth(i)
        try:
            if not el.is_visible():
                continue
            box = el.bounding_box()
            if not box or box["width"] < 2 or box["height"] < 2:
                continue
            area = box["width"] * box["height"]
            if best is None or area < best_area:
                best, best_area = el, area
        except Exception:
            continue
    return best


def click_text(page: Page, rx: re.Pattern, wait_ms: int = 1200) -> bool:
    el = find_smallest_visible(page, rx)
    if el is None:
        return False
    try:
        el.scroll_into_view_if_needed(timeout=3000)
        el.click(timeout=5000)
    except Exception:
        try:
            el.click(timeout=5000, force=True)
        except Exception as e:
            logger.warning("Click failed for %s: %s", rx.pattern, e)
            return False
    page.wait_for_timeout(wait_ms)
    return True


_FIND_CHAIN_JS = """() => {
  const leaves = [...document.querySelectorAll('*')].filter(
    e => e.children.length === 0 && /^\\s*Strike\\s*$/i.test(e.textContent || ''));
  for (const leaf of leaves) {
    let el = leaf;
    while (el && el !== document.body) {
      const r = el.getBoundingClientRect();
      if (r.width >= 450 && r.height >= 250 && /OI/.test(el.innerText || '')) return el;
      el = el.parentElement;
    }
  }
  return null;
}"""


class DexT3CaptureEngine:
    def __init__(self, session_manager: BrowserSessionManager, base_screenshots_dir: str = "screenshots"):
        self.session_manager = session_manager
        self.config = session_manager.config
        self.base_dir = Path(base_screenshots_dir)
        self.debug_dir = self.base_dir / "debug"
        self.footprint_dir = self.base_dir / "footprint"
        self.opt_chain_dir = self.base_dir / "option_chain"
        for d in (self.debug_dir, self.footprint_dir, self.opt_chain_dir):
            d.mkdir(parents=True, exist_ok=True)
        self._order_flow_calibrated: bool = False
        self._tab_just_switched: bool = False

    # ------------------------------------------------------------------ session / page
    def prepare_dashboard(self, page: Optional[Page] = None) -> Page:
        p = page or self.session_manager.get_page()

        StageLogger.log("auth", "Checking DexT3 login session", "browser")
        if "dext.dhan.co" not in p.url:
            StageLogger.log("navigation", f"Navigating to {self.config.url}", "browser")
            p.goto(self.config.url, wait_until="domcontentloaded")
            try:
                p.wait_for_load_state("networkidle", timeout=15000)
            except PWTimeout:
                pass
            p.wait_for_timeout(3000)

        if not self.session_manager.is_session_valid(p):
            raise SessionExpiredError(
                "DexT3 session expired or login required. Run 'python main.py --setup' to re-authenticate."
            )
        return p

    # ------------------------------------------------------------------ symbol recovery
    def _symbol_is_expired(self, page: Page) -> bool:
        try:
            return page.get_by_text(EXPIRED_TXT).first.is_visible()
        except Exception:
            return False

    def ensure_active_symbol(self, page: Page) -> None:
        if not self._symbol_is_expired(page):
            return
        logger.info("Expired symbol banner detected - selecting active NIFTY future")
        self.capture_debug_screenshot(page, "expired_symbol")

        if not click_text(page, CHANGE_SYMBOL_RX, 1500):
            raise CaptureError("Expired symbol and 'Change symbol' button not found. Select NIFTY FUT manually once.")

        # search box
        box = page.locator("input[type='text'], input[type='search'], input[placeholder*='earch']").first
        try:
            box.wait_for(state="visible", timeout=4000)
            box.click()
            box.fill("")
            page.keyboard.type("NIFTY", delay=80)
        except Exception as e:
            raise CaptureError(f"Symbol search box not usable: {e}")
        page.wait_for_timeout(2000)

        now = datetime.now(ZoneInfo("Asia/Kolkata"))
        cur = calendar.month_abbr[now.month].upper()
        nxt = calendar.month_abbr[now.month % 12 + 1].upper()
        picked = False
        for mon in (cur, nxt):
            rx = re.compile(rf"NIFTY.*\b{mon}\b.*FUT|NIFTY.*FUT.*\b{mon}\b", re.I | re.S)
            loc = page.locator(CLICKABLE).filter(has_text=rx)
            for i in range(min(loc.count(), 30)):
                el = loc.nth(i)
                try:
                    txt = (el.inner_text() or "").strip()
                    if el.is_visible() and not NOT_NIFTY_RX.search(txt) and len(txt) < 80:
                        el.click(timeout=4000)
                        picked = True
                        logger.info("Selected symbol result: %r", txt)
                        break
                except Exception:
                    continue
            if picked:
                break
        page.wait_for_timeout(3000)
        if not picked or self._symbol_is_expired(page):
            self.capture_debug_screenshot(page, "symbol_fix_failed")
            raise CaptureError(
                "Could not auto-select active NIFTY FUT. Select it manually once in the browser "
                "(Change symbol -> NIFTY <current month> FUT); DexT3 remembers it."
            )

    # ------------------------------------------------------------------ order flow
    def switch_to_order_flow_view(self, page: Page) -> bool:
        StageLogger.log("navigation", "Switching to Order Flow tab", "browser")
        self.ensure_active_symbol(page)

        tab = page.get_by_role("tab", name=ORDER_FLOW_RX).first
        switched = False
        try:
            tab.wait_for(state="visible", timeout=4000)
            tab.click(timeout=5000)
            page.wait_for_timeout(2500)
            logger.info("Clicked Order Flow tab (role=tab)")
            switched = True
        except Exception:
            pass
        if not switched and click_text(page, ORDER_FLOW_RX, 2500):
            logger.info("Clicked Order Flow tab (text match)")
            switched = True
        if not switched:
            self.capture_debug_screenshot(page, "order_flow_tab_missing")
            logger.warning("Order Flow tab not found; assuming already active")

        # Calibrate right after switching to the Order Flow tab (is_initial_load=True)
        try:
            calibrate_dhan_orderflow_chromium(page, is_initial_load=True)
            self._order_flow_calibrated = True
            self._tab_just_switched = True
            logger.info("Order Flow initial calibration executed successfully")
        except Exception as e:
            logger.warning("Order Flow calibration failed after switching tab: %s", e)

        return switched

    def capture_order_flow(self, page: Optional[Page] = None) -> List[str]:
        p = self.prepare_dashboard(page)
        self.switch_to_order_flow_view(p)
        StageLogger.log("navigation", "Opening footprint chart", "browser")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        captured_paths: List[str] = []

        # Automatically switch timeframes and capture both 15m and 5m Order Flow screenshots
        for tf in ["15m", "5m"]:
            StageLogger.log("navigation", f"Switching Order Flow chart timeframe to {tf}", "browser")
            try:
                set_orderflow_timeframe(p, target_tf=tf)
            except Exception as e:
                logger.warning("Failed to switch timeframe to %s: %s", tf, e)

            # Calibrate right before capture: Alt+R, auto-fit, zoom=0 (keeps clean 6-candle view)
            try:
                calibrate_dhan_orderflow_chromium(p, is_initial_load=False, zoom_steps=0)
                logger.info("Order Flow calibration executed for timeframe %s (zoom_steps=0)", tf)
            except Exception as e:
                logger.warning("Order Flow calibration failed for %s: %s", tf, e)

            output_file = self.footprint_dir / f"{timestamp}_order_flow_{tf}.png"
            meta_file = self.footprint_dir / f"{timestamp}_order_flow_{tf}_meta.json"

            # Find largest visible canvas
            best, best_area = None, 0.0
            canv = p.locator("canvas")
            for i in range(min(canv.count(), 20)):
                el = canv.nth(i)
                try:
                    if not el.is_visible():
                        continue
                    b = el.bounding_box()
                    if b and b["width"] * b["height"] > best_area:
                        best, best_area = el, b["width"] * b["height"]
                except Exception:
                    continue

            status = "CAPTURED"
            if best is not None and best_area > 150_000:
                best.screenshot(path=str(output_file))
            else:
                logger.warning("No large canvas found for %s - falling back to full viewport", tf)
                p.screenshot(path=str(output_file))
                status = "FALLBACK_FULLPAGE"

            StageLogger.log("capture", f"Footprint ({tf}) screenshot saved: {output_file}", "browser")
            named_file = self.footprint_dir / f"footprint_{tf}.png"
            try:
                shutil.copyfile(str(output_file), str(named_file))
            except Exception:
                pass

            meta_file.write_text(json.dumps({
                "instrument": "NIFTY-FUT", "timeframe": tf, "url": p.url,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "screenshot_path": str(output_file),
                "named_path": str(named_file),
                "file_size_bytes": output_file.stat().st_size if output_file.exists() else 0,
                "status": status,
            }, indent=2), encoding="utf-8")
            captured_paths.append(str(output_file))

        # Backward compatibility: write legacy footprint_main.png and {timestamp}_order_flow.png pointing to 5m screenshot
        five_m_file = self.footprint_dir / f"{timestamp}_order_flow_5m.png"
        legacy_file = self.footprint_dir / f"{timestamp}_order_flow.png"
        footprint_main = self.footprint_dir / "footprint_main.png"
        if five_m_file.exists():
            try:
                shutil.copyfile(five_m_file, legacy_file)
                shutil.copyfile(five_m_file, footprint_main)
            except Exception as e:
                logger.debug("Legacy copy failed: %s", e)

        self._tab_just_switched = False
        return captured_paths

    # ------------------------------------------------------------------ option chain
    def _option_chain_open(self, page: Page) -> bool:
        try:
            return page.get_by_text(STRIKE_RX).first.is_visible()
        except Exception:
            return False

    def open_option_chain_widget(self, page: Page) -> bool:
        if self._option_chain_open(page):
            return True
        StageLogger.log("navigation", "Opening Widgets -> Options Chain", "browser")
        if not click_text(page, WIDGETS_RX, 1500):
            self.capture_debug_screenshot(page, "widgets_button_missing")
            return False
        self.capture_debug_screenshot(page, "widgets_menu")
        if not click_text(page, OPTION_CHAIN_RX, 2500):
            self.capture_debug_screenshot(page, "options_chain_item_missing")
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass
            return False
        try:
            page.get_by_text(STRIKE_RX).first.wait_for(state="visible", timeout=8000)
        except Exception:
            self.capture_debug_screenshot(page, "options_chain_not_rendered")
            return False
        page.wait_for_timeout(1500)
        return True

    def _chain_container(self, page: Page):
        try:
            return page.evaluate_handle(_FIND_CHAIN_JS).as_element()
        except Exception:
            return None

    def capture_option_chain(self, page: Optional[Page] = None) -> List[str]:
        p = self.prepare_dashboard(page)
        self.ensure_active_symbol(p)

        if not self.open_option_chain_widget(p):
            raise CaptureError(
                "Options Chain widget could not be opened (see screenshots/debug/). "
                "Not sending a full-page screenshot to the vision model."
            )

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        main_file = self.opt_chain_dir / f"{timestamp}_option_chain_main.png"
        meta_file = self.opt_chain_dir / f"{timestamp}_option_chain_meta.json"

        target = self._chain_container(p)
        status = "CAPTURED"
        if target is not None:
            target.screenshot(path=str(main_file))
        else:
            logger.warning("Option chain container not isolated - using full viewport")
            p.screenshot(path=str(main_file))
            status = "FALLBACK_FULLPAGE"

        StageLogger.log("capture", f"Option chain screenshot saved: {main_file}", "browser")
        captured = [str(main_file)]

        # Optional Greeks view
        try:
            g = find_smallest_visible(p, GREEKS_RX)
            if g is not None and target is not None:
                g.click(timeout=3000)
                p.wait_for_timeout(1200)
                greeks_file = self.opt_chain_dir / f"{timestamp}_option_chain_greeks.png"
                target.screenshot(path=str(greeks_file))
                captured.append(str(greeks_file))
                g.click(timeout=3000)
                p.wait_for_timeout(500)
        except Exception as e:
            logger.debug("Greeks toggle skipped: %s", e)

        meta_file.write_text(json.dumps({
            "instrument": "NIFTY", "url": p.url,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "screenshots": captured,
            "file_size_bytes": main_file.stat().st_size if main_file.exists() else 0,
            "status": status,
        }, indent=2), encoding="utf-8")
        return captured

    # ------------------------------------------------------------------ diagnostics
    def capture_debug_screenshot(self, page: Optional[Page] = None, label: str = "debug") -> str:
        p = page or self.session_manager.get_page()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = self.debug_dir / f"{timestamp}_{label}.png"
        p.screenshot(path=str(dest))
        logger.info("Saved diagnostic screenshot: %s", dest)
        return str(dest)
