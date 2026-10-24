"""Find the exact Option Chain widget container and crop screenshot."""

from pathlib import Path
from src.config import load_config
from src.browser.session import BrowserSessionManager

cfg = load_config()
mgr = BrowserSessionManager(cfg.browser)
mgr.get_or_create_context(headless=False)
page = mgr.get_page()

page.goto("https://dext.dhan.co/dashboard", wait_until="domcontentloaded")
page.wait_for_timeout(3000)

# Check if Option Chain is already open, if not open it
has_strike = page.query_selector("*:has-text('Strike')")
if not has_strike:
    w_btn = page.query_selector("span:has-text('Widgets'), div:has-text('+ Widgets')")
    if w_btn:
        w_btn.click()
        page.wait_for_timeout(1000)
    oc_item = page.query_selector("span.item-name:has-text('Options Chain'), div.category-item:has-text('Options Chain')")
    if oc_item:
        oc_item.click()
        page.wait_for_timeout(3000)

# Find container element containing 'Strike' and 'OI'
containers = page.query_selector_all("div, section")
best_container = None
best_area = 0

for c in containers:
    try:
        box = c.bounding_box()
        if not box:
            continue
        # We want container that has width > 600 and height > 300, but not full screen (e.g. height < 1000)
        if box["width"] >= 500 and box["height"] >= 300 and box["height"] <= 900:
            txt = c.inner_text()
            if "Strike" in txt and "OI" in txt:
                area = box["width"] * box["height"]
                # pick largest appropriate container or modal/tab
                if area > best_area:
                    best_area = area
                    best_container = c
    except Exception:
        pass

if best_container:
    print(f"Found dedicated Option Chain container! Bounding box area: {best_area}")
    best_container.screenshot(path="screenshots/debug/dedicated_option_chain.png")
    print("Saved dedicated cropped screenshot to screenshots/debug/dedicated_option_chain.png")
else:
    print("Dedicated container not isolated, taking full viewport screenshot.")
    page.screenshot(path="screenshots/debug/dedicated_option_chain.png")

mgr.close()
