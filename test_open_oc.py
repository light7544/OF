"""Test opening Options Chain via keyboard shortcut Alt+O or click."""

from src.config import load_config
from src.browser.session import BrowserSessionManager

cfg = load_config()
mgr = BrowserSessionManager(cfg.browser)
mgr.get_or_create_context(headless=False)
page = mgr.get_page()

page.goto("https://dext.dhan.co/dashboard", wait_until="domcontentloaded")
page.wait_for_timeout(3000)

print("\n--- Trying to open Options Chain ---")
# Try clicking item-name with 'Options Chain'
oc_item = page.query_selector("span.item-name:has-text('Options Chain'), div.item-content:has-text('Options Chain'), div:has-text('Options Chain')")
if not oc_item:
    # First click widgets
    w_btn = page.query_selector("span:has-text('Widgets'), div:has-text('+ Widgets')")
    if w_btn:
        w_btn.click()
        page.wait_for_timeout(1000)
    oc_item = page.query_selector("span.item-name:has-text('Options Chain'), div.category-item:has-text('Options Chain')")

if oc_item:
    print("Found Options Chain item in menu, clicking...")
    oc_item.click()
    page.wait_for_timeout(3000)
else:
    print("Trying keyboard shortcut Alt+O...")
    page.keyboard.press("Alt+KeyO")
    page.wait_for_timeout(3000)

# Take screenshot of the screen now
page.screenshot(path="screenshots/debug/options_chain_opened.png")
print("Saved screenshot to screenshots/debug/options_chain_opened.png")

# Inspect the DOM for Option Chain table headers and strikes
print("\n--- Checking for Option Chain Table Elements ---")
tables = page.query_selector_all("table, div[role='grid'], div[role='table'], div.ag-root, div.table-container, div.option-chain")
print(f"Found {len(tables)} table containers.")

# Check for strike / call / put headers or text
strike_elements = page.query_selector_all("th, td, div:has-text('Strike'), div:has-text('CALLS'), div:has-text('PUTS'), div:has-text('OI')")
found_texts = []
for el in strike_elements:
    try:
        t = el.inner_text().strip()
        if t and len(t) < 30 and t not in found_texts:
            found_texts.append(t)
    except Exception:
        pass
print("Found table header/cell texts:", found_texts[:20])

mgr.close()
