"""Detailed DOM exploration for Widgets and Option Chain in DexT3."""

from pathlib import Path
from src.config import load_config
from src.browser.session import BrowserSessionManager

cfg = load_config()
mgr = BrowserSessionManager(cfg.browser)
mgr.get_or_create_context(headless=False)
page = mgr.get_page()

page.goto("https://dext.dhan.co/dashboard", wait_until="domcontentloaded")
page.wait_for_timeout(3000)

print("\n--- 1. Inspecting Top Header Ticker Elements ---")
# Look at top ticker where Nifty 50 is displayed
ticker_elements = page.query_selector_all("div.header, header, nav, div:has-text('Nifty 50')")
for el in ticker_elements[:5]:
    try:
        print("Ticker text snippet:", el.inner_text()[:150].replace('\n', ' | '))
    except Exception:
        pass

print("\n--- 2. Clicking '+ Widgets' / 'Widgets' ---")
widget_btn = page.query_selector("span:has-text('Widgets'), div:has-text('+ Widgets')")
if widget_btn:
    print("Found widget button, clicking...")
    widget_btn.click()
    page.wait_for_timeout(1500)
    page.screenshot(path="screenshots/debug/widgets_opened.png")

    # Find all visible text in dialog / popover / drawer
    popovers = page.query_selector_all("[role='dialog'], [role='menu'], div.popover, div.modal, div.drawer, div.dropdown-menu")
    print(f"Found {len(popovers)} dialog/popover elements.")
    for p in popovers:
        print("Dialog text:", p.inner_text().replace('\n', ' | '))

    # Check for any element with 'Option Chain' anywhere on page now
    oc_elements = page.query_selector_all("*:has-text('Option Chain'), *:has-text('Options')")
    print(f"Elements mentioning Option Chain after click: {len(oc_elements)}")
    for el in oc_elements:
        try:
            txt = el.inner_text().strip()
            if txt and len(txt) < 50:
                print("  •", el.evaluate("e => e.tagName"), repr(txt), el.get_attribute("class"))
        except Exception:
            pass

print("\n--- 3. Checking Right Panel Tabs & Watchlist ---")
right_panel_tabs = page.query_selector_all("[role='tab'], button.tab, div.tab")
for t in right_panel_tabs:
    try:
        txt = t.inner_text().strip()
        if txt and len(txt) < 30:
            print("Tab:", repr(txt))
    except Exception:
        pass

# Check Watchlist for Nifty 50 options
page.screenshot(path="screenshots/debug/dext3_state_deep.png")
mgr.close()
