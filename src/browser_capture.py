"""Browser capture module and calibration utilities for Dhan / DexT3 Order Flow."""

from __future__ import annotations
import sys
import time
import shutil
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger("browser_capture")

try:
    from selenium.webdriver.remote.webdriver import WebDriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.common.action_chains import ActionChains
    from selenium.webdriver.common.actions.wheel_input import ScrollOrigin
    from selenium.webdriver.chrome.options import Options
    HAS_SELENIUM = True
except ImportError:
    class _DummyOptions:
        def add_argument(self, *args, **kwargs): pass
        def add_experimental_option(self, *args, **kwargs): pass

    WebDriver = Any  # type: ignore[misc,assignment]
    HAS_SELENIUM = False
    Options = _DummyOptions  # type: ignore[misc,assignment]

# ==============================================================================
# STEP 1: ChromeOptions (Removes Top --no-sandbox Warning Bar Permanently)
# ==============================================================================

def get_chrome_options() -> Any:
    """
    Configures ChromeOptions:
    1. Removes '--no-sandbox' on Windows (only needed in Linux Docker root containers).
    2. Adds '--test-type', '--disable-infobars', and excludeSwitches so Chrome NEVER
       shows the top warning bar that obscures the bottom TradingView toolbar.
    """
    if not HAS_SELENIUM:
        return None

    options = Options()
    if sys.platform != "win32":
        options.add_argument("--no-sandbox")
    options.add_argument("--test-type")
    options.add_argument("--disable-infobars")
    options.add_argument("--start-maximized")
    options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
    return options


# ==============================================================================
# STEP 2: Order Flow Auto-Fit & Footprint Zoom Calibration
# ==============================================================================

def _switch_to_chart_iframe(driver: WebDriver) -> bool:
    """Switches into the TradingView iframe inside Dhan/Dext T3 if present."""
    driver.switch_to.default_content()
    iframes = driver.find_elements(By.TAG_NAME, "iframe")
    for frame in iframes:
        try:
            driver.switch_to.frame(frame)
            if len(driver.find_elements(By.TAG_NAME, "canvas")) >= 2:
                return True
            driver.switch_to.default_content()
        except Exception:
            driver.switch_to.default_content()
    return False


def _click_auto_scale_button(driver: WebDriver, main_canvas, price_axis_canvas, send_alt_r: bool = True) -> bool:
    """
    Explicitly clicks the 'auto' button at the bottom-right of the TradingView chart
    (next to '%' and 'log') AND double-clicks the right Y-axis price scale if needed.
    When send_alt_r=False, skips Alt+R to avoid resetting horizontal zoom.
    """
    clicked_auto = False

    # Method A: Find the 'auto' button in the DOM inside the chart footer
    auto_selectors = [
        "//div[normalize-space(text())='auto']",
        "//button[normalize-space(text())='auto']",
        "//span[normalize-space(text())='auto']",
        "//*[contains(@data-name, 'auto') or contains(@title, 'Auto') or contains(@aria-label, 'Auto')]",
    ]
    for xpath in auto_selectors:
        try:
            elems = driver.find_elements(By.XPATH, xpath)
            for el in elems:
                if el.is_displayed() and el.rect["y"] > 400:  # Must be in the bottom footer bar
                    # Check if 'auto' is already active (TradingView adds an 'isActive' or blue class)
                    cls = (el.get_attribute("class") or "") + " " + (
                        el.find_element(By.XPATH, "..").get_attribute("class") or ""
                    )
                    if "active" not in cls.lower() and "selected" not in cls.lower():
                        ActionChains(driver).move_to_element(el).click().perform()
                        time.sleep(0.5)
                    else:
                        # Toggle off and on once to force immediate Y-axis snap to latest price
                        ActionChains(driver).move_to_element(el).click().pause(0.2).click().perform()
                        time.sleep(0.5)
                    clicked_auto = True
                    break
            if clicked_auto:
                break
        except Exception:
            continue

    # Method B: Also send Alt + R (TradingView native Reset Chart View) if allowed
    if send_alt_r:
        try:
            ActionChains(driver).move_to_element(main_canvas).click().perform()
            time.sleep(0.2)
            ActionChains(driver).key_down(Keys.ALT).send_keys("r").key_up(Keys.ALT).perform()
            time.sleep(0.6)
        except Exception:
            pass

    # Method C: Fallback double-click on the Right Y-axis Price Scale canvas
    if not clicked_auto and price_axis_canvas:
        try:
            ActionChains(driver).move_to_element(price_axis_canvas).double_click().perform()
            time.sleep(0.5)
            clicked_auto = True
        except Exception:
            pass

    return clicked_auto


def _find_chart_and_price_canvases(driver: WebDriver):
    """Finds the main chart canvas and the right-hand Y-axis price scale canvas."""
    canvases = driver.find_elements(By.TAG_NAME, "canvas")
    main_canvas = None
    max_area = 0
    canvas_rects = []

    for c in canvases:
        try:
            if not c.is_displayed():
                continue
            rect = c.rect
            area = rect["width"] * rect["height"]
            canvas_rects.append((c, rect, area))
            if area > max_area:
                max_area = area
                main_canvas = c
        except Exception:
            continue

    if not main_canvas:
        raise RuntimeError("Order Flow TradingView canvas not found.")

    main_rect = main_canvas.rect
    price_axis_canvas = None

    for c, rect, _ in canvas_rects:
        if c == main_canvas:
            continue
        if (
            abs(rect["y"] - main_rect["y"]) < 50
            and abs(rect["height"] - main_rect["height"]) < 100
            and rect["x"] >= (main_rect["x"] + main_rect["width"] - 15)
            and 40 <= rect["width"] <= 150
        ):
            price_axis_canvas = c
            break

    return main_canvas, price_axis_canvas


def _set_orderflow_timeframe(driver: WebDriver, target_tf: str = "5m") -> bool:
    """
    Reliably switches the Dext T3 / TradingView Order Flow timeframe between '15m' and '5m'.
    target_tf: '5m' or '15m'
    """
    target_num = "".join(ch for ch in target_tf if ch.isdigit())  # '5' or '15'
    switched_iframe = _switch_to_chart_iframe(driver)

    try:
        # 1. Check if chart is ALREADY on target_tf by checking the top toolbar button text
        current_tf_check = driver.find_elements(
            By.XPATH,
            f"//div[@id='header-toolbar-intervals']//*[normalize-space(text())='{target_tf}']"
        )
        if any(el.is_displayed() for el in current_tf_check):
            return True

        # 2. Click the interval dropdown button in the top toolbar (sits inside #header-toolbar-intervals
        # or displays '1m', '3m', '5m', '15m', '30m', '1h', 'D')
        dropdown_opened = False
        interval_btn_selectors = [
            "//div[@id='header-toolbar-intervals']//button",
            "//div[@id='header-toolbar-intervals']//div[contains(@class, 'button') or contains(@class, 'value')]",
            "//*[normalize-space(text())='15m' or normalize-space(text())='5m' or normalize-space(text())='1m' or normalize-space(text())='3m']",
        ]
        for xpath in interval_btn_selectors:
            elems = driver.find_elements(By.XPATH, xpath)
            for el in elems:
                if el.is_displayed() and 30 < el.rect["y"] < 160 and el.rect["x"] < 350:
                    ActionChains(driver).move_to_element(el).click().perform()
                    time.sleep(0.6)
                    dropdown_opened = True
                    break
            if dropdown_opened:
                break

        # 3. Once the dropdown menu is open, click the target option ('5 minutes' / '15 minutes' / '5m' / '15m')
        if dropdown_opened:
            menu_item_selectors = [
                f"//div[contains(@class, 'menu') or contains(@data-name, 'menu')]//*[normalize-space(text())='{target_num} minutes' or normalize-space(text())='{target_tf}']",
                f"//*[@data-value='{target_num}']",
                f"//span[normalize-space(text())='{target_num} minutes' or normalize-space(text())='{target_tf}']",
                f"//div[normalize-space(text())='{target_num} minutes']",
            ]
            for m_xpath in menu_item_selectors:
                items = driver.find_elements(By.XPATH, m_xpath)
                for item in items:
                    if item.is_displayed():
                        ActionChains(driver).move_to_element(item).click().perform()
                        time.sleep(1.8)
                        return True

        # 4. Fallback: Click directly on the center of the chart canvas, press Escape (to close any menu),
        # then type the digits ('5' or '15') via ActionChains and press Enter
        main_canvas, _ = _find_chart_and_price_canvases(driver)
        ActionChains(driver).move_to_element(main_canvas).click().send_keys(Keys.ESCAPE).perform()
        time.sleep(0.2)
        ActionChains(driver).send_keys(target_num).pause(0.3).send_keys(Keys.ENTER).perform()
        time.sleep(1.8)
        return True

    except Exception:
        return False
    finally:
        if switched_iframe:
            driver.switch_to.default_content()


def _zoom_footprint_horizontally(driver: WebDriver, main_canvas, steps: int = 3):
    """
    Scrolls UP on the chart canvas (steps=3) so ~6 footprint candles are visible
    on screen with their internal Bid x Ask numbers and bottom Delta/Vol cards clear.
    """
    for _ in range(steps):
        try:
            origin = ScrollOrigin.from_element(main_canvas, 80, 0)
            ActionChains(driver).scroll_from_origin(origin, 0, -120).perform()
        except Exception:
            pass

        driver.execute_script(
            """
            const canvas = arguments[0];
            const rect = canvas.getBoundingClientRect();
            const evt = new WheelEvent('wheel', {
                deltaY: -120,
                deltaMode: 0,
                clientX: rect.left + (rect.width * 0.65),
                clientY: rect.top + (rect.height * 0.50),
                bubbles: true,
                cancelable: true,
                view: window
            });
            canvas.dispatchEvent(evt);
            """,
            main_canvas,
        )
        time.sleep(0.25)


def calibrate_dhan_orderflow_chromium(
    driver: Any,
    is_initial_load: bool = False,
    zoom_steps: int = 0,
):
    """
    Fits ~6 footprint candles onto the Dhan/Dext T3 Order Flow screen:
    - Uses Alt+R + 'auto' button to center the latest candles and auto-fit Y-axis price.
    - Does NOT over-zoom (default view already displays 5-6 candles cleanly).
    - Pans slightly left (-50px, 0px vertical) so the latest candle isn't flush against the right edge.
    """
    # Support Playwright pages dynamically if passed
    if hasattr(driver, "keyboard") and hasattr(driver, "mouse"):
        from src.browser.calibration import calibrate_dhan_orderflow_playwright
        return calibrate_dhan_orderflow_playwright(driver, is_initial_load=is_initial_load, zoom_steps=zoom_steps)

    time.sleep(1.8)
    switched = _switch_to_chart_iframe(driver)

    try:
        main_canvas, price_axis_canvas = _find_chart_and_price_canvases(driver)

        # Step 1: Click 'auto' button & send Alt + R to jump to current live price & latest candle
        _click_auto_scale_button(driver, main_canvas, price_axis_canvas, send_alt_r=True)

        # Step 2: Only zoom if explicitly requested (zoom_steps=0 keeps the clean 6-candle default width!)
        if is_initial_load and zoom_steps > 0:
            _zoom_footprint_horizontally(driver, main_canvas, steps=zoom_steps)
            time.sleep(0.4)

        # Step 3: Slight horizontal-only nudge (-50px, 0) so the right-most candle isn't cut off
        (
            ActionChains(driver)
            .move_to_element(main_canvas)
            .click_and_hold()
            .move_by_offset(-50, 0)
            .pause(0.2)
            .release()
            .perform()
        )
        time.sleep(0.3)

        # Step 4: Ensure 'auto' stays active without re-sending Alt+R
        _click_auto_scale_button(driver, main_canvas, price_axis_canvas, send_alt_r=False)
        time.sleep(0.7)

    finally:
        if switched:
            driver.switch_to.default_content()


# ==============================================================================
# STEP 3: Sequential 15m and 5m Order Flow Screenshot Workflow
# ==============================================================================

def switch_to_order_flow_tab(driver: WebDriver) -> bool:
    """Switches to the Order Flow tab on Dhan / DexT3."""
    driver.switch_to.default_content()
    tab_selectors = [
        "//div[@role='tab'][contains(translate(., 'ORDER FLOW', 'order flow'), 'order flow')]",
        "//button[@role='tab'][contains(translate(., 'ORDER FLOW', 'order flow'), 'order flow')]",
        "//*[contains(translate(text(), 'ORDER FLOW', 'order flow'), 'order flow')]",
    ]
    for xpath in tab_selectors:
        try:
            elems = driver.find_elements(By.XPATH, xpath)
            for el in elems:
                if el.is_displayed():
                    ActionChains(driver).move_to_element(el).click().perform()
                    time.sleep(2.0)
                    return True
        except Exception:
            continue
    return False


def capture_orderflow_screenshots(
    driver: WebDriver,
    output_dir: Union[str, Path] = "screenshots/footprint",
) -> Dict[str, str]:
    """
    Captures both 15m and 5m Order Flow screenshots in sequence:
    1. Switches to Order Flow tab.
    2. Switches to '15m' timeframe -> Calibrates (zoom_steps=3) -> Saves footprint_15m.png.
    3. Switches to '5m' timeframe  -> Calibrates (zoom_steps=3) -> Saves footprint_5m.png.
    4. Saves footprint_main.png as backward-compatible alias to 5m screenshot.
    5. Returns dictionary with all captured paths {'15m': ..., '5m': ..., 'main': ...}.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")

    # Step 1: Switch to Order Flow tab
    switch_to_order_flow_tab(driver)
    time.sleep(1.0)

    results: Dict[str, str] = {}

    for tf in ["15m", "5m"]:
        # Step 2: Switch timeframe (15m then 5m)
        _set_orderflow_timeframe(driver, target_tf=tf)
        time.sleep(0.5)

        # Step 3: Calibrate view (zoom_steps=0 preserves the clean 6-candle default width, offset -50px)
        calibrate_dhan_orderflow_chromium(driver, is_initial_load=False, zoom_steps=0)

        # Step 4: Save timeframe screenshot (e.g., footprint_15m.png, footprint_5m.png)
        tf_named_file = out_dir / f"footprint_{tf}.png"
        tf_timestamped_file = out_dir / f"{timestamp}_order_flow_{tf}.png"

        switched = _switch_to_chart_iframe(driver)
        captured = False
        try:
            main_canvas, _ = _find_chart_and_price_canvases(driver)
            if main_canvas:
                main_canvas.screenshot(str(tf_named_file))
                captured = True
        except Exception as e:
            logger.warning("Failed to screenshot canvas for %s: %s", tf, e)
        finally:
            if switched:
                driver.switch_to.default_content()

        if not captured:
            driver.save_screenshot(str(tf_named_file))

        try:
            shutil.copyfile(str(tf_named_file), str(tf_timestamped_file))
        except Exception:
            pass

        results[tf] = str(tf_named_file)

    # Step 5: Save footprint_main.png aliased to 5m screenshot for legacy compatibility
    main_named_file = out_dir / "footprint_main.png"
    main_timestamped_file = out_dir / f"{timestamp}_order_flow.png"
    if "5m" in results and Path(results["5m"]).exists():
        try:
            shutil.copyfile(results["5m"], str(main_named_file))
            shutil.copyfile(results["5m"], str(main_timestamped_file))
            results["main"] = str(main_named_file)
        except Exception as e:
            logger.debug("Failed to create footprint_main.png alias: %s", e)

    return results


capture_order_flow_selenium = capture_orderflow_screenshots


# Forward exports from src.browser.capture for complete modular compatibility
from src.browser.capture import (
    DexT3CaptureEngine,
    determine_active_future_contract,
    CaptureError,
)

__all__ = [
    "get_chrome_options",
    "calibrate_dhan_orderflow_chromium",
    "switch_to_order_flow_tab",
    "capture_orderflow_screenshots",
    "capture_order_flow_selenium",
    "_switch_to_chart_iframe",
    "_click_auto_scale_button",
    "_find_chart_and_price_canvases",
    "_zoom_footprint_horizontally",
    "_set_orderflow_timeframe",
    "DexT3CaptureEngine",
    "determine_active_future_contract",
    "CaptureError",
]

