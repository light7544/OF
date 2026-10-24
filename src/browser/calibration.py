from __future__ import annotations
import time
import logging
from typing import Any, Tuple, Optional

logger = logging.getLogger("dhan_calibration")

try:
    from selenium.webdriver.remote.webdriver import WebDriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.common.action_chains import ActionChains
    from selenium.webdriver.common.actions.wheel_input import ScrollOrigin
    HAS_SELENIUM = True
except ImportError:
    WebDriver = Any
    HAS_SELENIUM = False

try:
    from playwright.sync_api import Page, Locator
    HAS_PLAYWRIGHT = True
except ImportError:
    Page = Any
    Locator = Any
    HAS_PLAYWRIGHT = False


# ==============================================================================
# 1. SELENIUM CHROMIUM CALIBRATION IMPLEMENTATION (STEP 2 SPECIFICATION)
# ==============================================================================

def _switch_to_chart_iframe_selenium(driver: WebDriver) -> bool:
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


def _click_auto_scale_button_selenium(driver: WebDriver, main_canvas, price_axis_canvas, send_alt_r: bool = True) -> bool:
    """
    Explicitly clicks the 'auto' button at the bottom-right of the TradingView chart
    (next to '%' and 'log') AND double-clicks the right Y-axis price scale if needed.
    When send_alt_r=False, skips Alt+R to prevent resetting horizontal footprint zoom.
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


def _find_chart_and_price_canvases_selenium(driver: WebDriver):
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


def _set_orderflow_timeframe_selenium(driver: WebDriver, target_tf: str = "5m") -> bool:
    """
    Reliably switches the Dext T3 / TradingView Order Flow timeframe between '15m' and '5m'.
    target_tf: '5m' or '15m'
    """
    target_num = "".join(ch for ch in target_tf if ch.isdigit())  # '5' or '15'
    switched_iframe = _switch_to_chart_iframe_selenium(driver)

    try:
        # 1. Check if chart is ALREADY on target_tf by checking the top toolbar button text
        current_tf_check = driver.find_elements(
            By.XPATH,
            f"//div[@id='header-toolbar-intervals']//*[normalize-space(text())='{target_tf}']"
        )
        if any(el.is_displayed() for el in current_tf_check):
            return True

        # 2. Click the interval dropdown button in the top toolbar
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

        # 3. Once the dropdown menu is open, click the target option
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

        # 4. Fallback: Click directly on center of chart canvas, press Escape, type digits, press Enter
        main_canvas, _ = _find_chart_and_price_canvases_selenium(driver)
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


def _zoom_footprint_horizontally_selenium(driver: WebDriver, main_canvas, steps: int = 3):
    """
    Scrolls UP on the chart canvas to zoom in horizontally so ~6 footprint
    candles are visible and their internal Bid x Ask numbers render clearly.
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


def calibrate_dhan_orderflow_selenium(
    driver: WebDriver,
    is_initial_load: bool = False,
    zoom_steps: int = 0,
):
    """
    Fits ~6 footprint candles onto the Dhan/Dext T3 Order Flow screen:
    - Uses Alt+R + 'auto' button to center the latest candles and auto-fit Y-axis price.
    - Does NOT over-zoom (default view already displays 5-6 candles cleanly).
    - Pans slightly left (-50px, 0px vertical) so the latest candle isn't flush against the right edge.
    """
    time.sleep(1.8)
    switched = _switch_to_chart_iframe_selenium(driver)

    try:
        main_canvas, price_axis_canvas = _find_chart_and_price_canvases_selenium(driver)

        # Step 1: Click 'auto' button & send Alt + R to jump to current live price & latest candle
        _click_auto_scale_button_selenium(driver, main_canvas, price_axis_canvas, send_alt_r=True)

        # Step 2: Only zoom if explicitly requested (zoom_steps=0 keeps the clean 6-candle default width!)
        if is_initial_load and zoom_steps > 0:
            _zoom_footprint_horizontally_selenium(driver, main_canvas, steps=zoom_steps)
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
        _click_auto_scale_button_selenium(driver, main_canvas, price_axis_canvas, send_alt_r=False)
        time.sleep(0.7)

    finally:
        if switched:
            driver.switch_to.default_content()


# ==============================================================================
# 2. PLAYWRIGHT CHROMIUM CALIBRATION IMPLEMENTATION (MATCHING PARITY)
# ==============================================================================

def _find_chart_and_price_canvases_playwright(page: Page):
    """Identifies main chart pane canvas and right Y-axis price scale in Playwright."""
    best_main = None
    best_main_box = None
    max_area = 0.0
    all_canvases = []

    for fr in page.frames:
        try:
            loc = fr.locator("canvas")
            count = loc.count()
        except Exception:
            continue
        for i in range(min(count, 30)):
            c = loc.nth(i)
            try:
                if not c.is_visible():
                    continue
                box = c.bounding_box()
                if not box or box["width"] < 20 or box["height"] < 20:
                    continue
                area = box["width"] * box["height"]
                all_canvases.append((c, box, area))
                if area > max_area:
                    max_area = area
                    best_main = c
                    best_main_box = box
            except Exception:
                continue

    if not best_main or not best_main_box:
        logger.warning("Order Flow TradingView canvas not found on screen.")
        return None, None, None, None

    price_axis = None
    price_axis_box = None
    for c, box, _ in all_canvases:
        if c == best_main:
            continue
        if (
            abs(box["y"] - best_main_box["y"]) < 50
            and abs(box["height"] - best_main_box["height"]) < 100
            and box["x"] >= (best_main_box["x"] + best_main_box["width"] - 25)
            and 30 <= box["width"] <= 150
        ):
            price_axis = c
            price_axis_box = box
            break

    return best_main, best_main_box, price_axis, price_axis_box


def _click_auto_scale_button_playwright(page: Page, main_canvas, price_axis, price_box, send_alt_r: bool = True) -> bool:
    """Clicks 'auto' scale button in TradingView footer and triggers Alt+R in Playwright."""
    clicked_auto = False
    auto_selectors = [
        "//div[normalize-space(text())='auto']",
        "//button[normalize-space(text())='auto']",
        "//span[normalize-space(text())='auto']",
        "//*[contains(@data-name, 'auto') or contains(@title, 'Auto') or contains(@aria-label, 'Auto')]",
    ]

    for fr in page.frames:
        for sel in auto_selectors:
            try:
                loc = fr.locator(sel)
                count = loc.count()
                for i in range(count):
                    el = loc.nth(i)
                    if not el.is_visible():
                        continue
                    box = el.bounding_box()
                    if box and box["y"] > 400:  # Bottom footer bar
                        cls = (el.get_attribute("class") or "")
                        parent_cls = el.evaluate("e => e.parentElement ? e.parentElement.className : ''")
                        full_cls = f"{cls} {parent_cls}".lower()
                        if "active" not in full_cls and "selected" not in full_cls:
                            el.click(timeout=2000)
                            page.wait_for_timeout(500)
                        else:
                            el.click(timeout=2000)
                            page.wait_for_timeout(200)
                            el.click(timeout=2000)
                            page.wait_for_timeout(500)
                        clicked_auto = True
                        break
                if clicked_auto:
                    break
            except Exception:
                continue
        if clicked_auto:
            break

    # Method B: Send Alt + R if allowed
    if send_alt_r:
        try:
            if main_canvas:
                box = main_canvas.bounding_box()
                if box:
                    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                    page.wait_for_timeout(200)
            page.keyboard.down("Alt")
            page.keyboard.press("r")
            page.keyboard.up("Alt")
            page.wait_for_timeout(600)
        except Exception:
            pass

    # Method C: Fallback double-click on Price Scale
    if not clicked_auto and price_box:
        try:
            px = price_box["x"] + price_box["width"] / 2
            py = price_box["y"] + price_box["height"] / 2
            page.mouse.dblclick(px, py)
            page.wait_for_timeout(500)
            clicked_auto = True
        except Exception:
            pass

    return clicked_auto


def _set_orderflow_timeframe_playwright(page: Page, target_tf: str = "5m") -> bool:
    """
    Reliably switches the Dext T3 / TradingView Order Flow timeframe between '15m' and '5m' in Playwright.
    target_tf: '5m' or '15m'
    """
    target_num = "".join(ch for ch in target_tf if ch.isdigit())
    try:
        # 1. Check if chart is ALREADY on target_tf by checking top toolbar button text
        for fr in page.frames:
            try:
                active_btn = fr.locator(f"#header-toolbar-intervals :text-is('{target_tf}')")
                if active_btn.count() > 0 and active_btn.first.is_visible():
                    return True
            except Exception:
                pass

        # 2. Click the interval dropdown button in the top toolbar
        dropdown_opened = False
        interval_selectors = [
            "#header-toolbar-intervals button",
            "#header-toolbar-intervals div[class*='button']",
            "#header-toolbar-intervals div[class*='value']",
            "button:has-text('15m')",
            "button:has-text('5m')",
            "div:text-is('15m')",
            "div:text-is('5m')",
        ]
        for fr in page.frames:
            for sel in interval_selectors:
                try:
                    loc = fr.locator(sel)
                    for i in range(loc.count()):
                        el = loc.nth(i)
                        if el.is_visible():
                            box = el.bounding_box()
                            if box and 30 < box["y"] < 160 and box["x"] < 350:
                                el.click(timeout=1500)
                                page.wait_for_timeout(600)
                                dropdown_opened = True
                                break
                    if dropdown_opened:
                        break
                except Exception:
                    continue
            if dropdown_opened:
                break

        # 3. Once dropdown is open, click the target option ('5 minutes' / '15 minutes' / '5m' / '15m')
        if dropdown_opened:
            menu_selectors = [
                f"[data-name*='menu'] :text-is('{target_num} minutes')",
                f"[data-name*='menu'] :text-is('{target_tf}')",
                f"[data-value='{target_num}']",
                f":text-is('{target_num} minutes')",
                f"div.item:text-is('{target_tf}')",
                f":text-is('{target_tf}')",
            ]
            for fr in page.frames:
                for sel in menu_selectors:
                    try:
                        loc = fr.locator(sel)
                        for i in range(loc.count()):
                            el = loc.nth(i)
                            if el.is_visible():
                                el.click(timeout=2000)
                                page.wait_for_timeout(1800)
                                return True
                    except Exception:
                        continue

        # 4. Fallback: Click main canvas, press Escape, type digits, press Enter
        main_canvas, main_box, _, _ = _find_chart_and_price_canvases_playwright(page)
        if main_box and target_num:
            page.mouse.click(main_box["x"] + main_box["width"] / 2, main_box["y"] + main_box["height"] / 2)
            page.wait_for_timeout(200)
            page.keyboard.press("Escape")
            page.wait_for_timeout(200)
            page.keyboard.type(target_num)
            page.wait_for_timeout(300)
            page.keyboard.press("Enter")
            page.wait_for_timeout(1800)
            return True
        return False
    except Exception:
        return False


def _zoom_footprint_horizontally_playwright(page: Page, canvas_locator, steps: int = 3):
    """Dispatches horizontal zoom-in wheel scrolls in Playwright (~6 candles)."""
    for _ in range(steps):
        try:
            box = canvas_locator.bounding_box()
            if box:
                page.mouse.move(box["x"] + box["width"] * 0.65, box["y"] + box["height"] * 0.50)
                page.mouse.wheel(0, -120)
        except Exception:
            pass

        try:
            canvas_locator.evaluate(
                """(canvas) => {
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
                }"""
            )
        except Exception:
            pass
        page.wait_for_timeout(250)


def calibrate_dhan_orderflow_playwright(
    page: Page,
    is_initial_load: bool = False,
    zoom_steps: int = 0,
):
    """
    Fits ~6 footprint candles onto the Dhan/Dext T3 Order Flow screen:
    - Uses Alt+R + 'auto' button to center the latest candles and auto-fit Y-axis price.
    - Does NOT over-zoom (default view already displays 5-6 candles cleanly).
    - Pans slightly left (-50px, 0px vertical) so the latest candle isn't flush against the right edge.
    """
    page.wait_for_timeout(1800)

    main_canvas, main_box, price_axis, price_box = _find_chart_and_price_canvases_playwright(page)
    if not main_canvas or not main_box:
        logger.warning("Could not find TradingView canvases for calibration.")
        return

    try:
        center_x = main_box["x"] + main_box["width"] / 2
        center_y = main_box["y"] + main_box["height"] / 2

        # Step 1: Click 'auto' button & send Alt + R to jump to current live price & latest candle
        _click_auto_scale_button_playwright(page, main_canvas, price_axis, price_box, send_alt_r=True)

        # Step 2: Only zoom if explicitly requested (zoom_steps=0 keeps clean 6-candle default width)
        if is_initial_load and zoom_steps > 0:
            _zoom_footprint_horizontally_playwright(page, main_canvas, steps=zoom_steps)
            page.wait_for_timeout(400)

        # Step 3: Slight horizontal-only nudge (-50px, 0) so the right-most candle isn't cut off
        page.mouse.move(center_x, center_y)
        page.mouse.down()
        page.mouse.move(center_x - 50, center_y)
        page.wait_for_timeout(200)
        page.mouse.up()
        page.wait_for_timeout(300)

        # Step 4: Ensure 'auto' stays active without re-sending Alt+R
        _click_auto_scale_button_playwright(page, main_canvas, price_axis, price_box, send_alt_r=False)
        page.wait_for_timeout(700)
        logger.info("Order Flow calibration completed (is_initial_load=%s, zoom_steps=%s)", is_initial_load, zoom_steps)
    except Exception as e:
        logger.warning("Order Flow calibration error: %s", e)


# ==============================================================================
# 3. UNIFIED CALIBRATION DISPATCHER & ALIASES
# ==============================================================================

def set_orderflow_timeframe(driver_or_page: Any, target_tf: str = "5m") -> bool:
    """Unified timeframe switcher supporting Selenium WebDriver and Playwright Page."""
    if hasattr(driver_or_page, "switch_to"):
        return _set_orderflow_timeframe_selenium(driver_or_page, target_tf=target_tf)
    elif hasattr(driver_or_page, "keyboard") and hasattr(driver_or_page, "mouse"):
        return _set_orderflow_timeframe_playwright(driver_or_page, target_tf=target_tf)
    return False


def calibrate_dhan_orderflow_chromium(
    driver_or_page: Any,
    is_initial_load: bool = False,
    zoom_steps: int = 0,
):
    """
    Unified entrypoint supporting both Selenium WebDriver and Playwright Page instances.
    """
    if hasattr(driver_or_page, "switch_to"):
        calibrate_dhan_orderflow_selenium(driver_or_page, is_initial_load=is_initial_load, zoom_steps=zoom_steps)
    elif hasattr(driver_or_page, "keyboard") and hasattr(driver_or_page, "mouse"):
        calibrate_dhan_orderflow_playwright(driver_or_page, is_initial_load=is_initial_load, zoom_steps=zoom_steps)
    else:
        raise TypeError(f"Unsupported driver/page object type: {type(driver_or_page)}")


# Aliases for exact naming compatibility with user script
_switch_to_chart_iframe = _switch_to_chart_iframe_selenium
_click_auto_scale_button = _click_auto_scale_button_selenium
_find_chart_and_price_canvases = _find_chart_and_price_canvases_selenium
_zoom_footprint_horizontally = _zoom_footprint_horizontally_selenium
_set_orderflow_timeframe = _set_orderflow_timeframe_selenium

__all__ = [
    "calibrate_dhan_orderflow_chromium",
    "calibrate_dhan_orderflow_selenium",
    "calibrate_dhan_orderflow_playwright",
    "set_orderflow_timeframe",
    "_set_orderflow_timeframe",
    "_switch_to_chart_iframe",
    "_click_auto_scale_button",
    "_find_chart_and_price_canvases",
    "_zoom_footprint_horizontally",
]
