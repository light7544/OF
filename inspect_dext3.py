"""Inspect live DexT3 DOM controls, widgets, and option chain availability."""

import json
from pathlib import Path
from src.config import load_config
from src.browser.session import BrowserSessionManager

cfg = load_config()
mgr = BrowserSessionManager(cfg.browser)
mgr.get_or_create_context(headless=False)
page = mgr.get_page()

page.goto("https://dext.dhan.co/", wait_until="domcontentloaded")
page.wait_for_timeout(3000)

print("URL:", page.url)
print("Title:", page.title())

# 1. Search for all interactive elements mentioning widget or option chain
elements = page.query_selector_all("button, [role='button'], [role='tab'], span, div, a")
matching = []
for el in elements:
    try:
        txt = el.inner_text().strip()
        if txt and len(txt) < 50:
            low = txt.lower()
            if any(k in low for k in ["widget", "option chain", "option", "chain", "+ widget"]):
                tag = el.evaluate("e => e.tagName")
                cls = el.get_attribute("class") or ""
                matching.append({"tag": tag, "text": txt, "class": cls})
    except Exception:
        pass

print(f"Found {len(matching)} matching elements:")
seen = set()
for m in matching:
    key = (m["tag"], m["text"])
    if key not in seen:
        seen.add(key)
        print(f"  [{m['tag']}] {m['text']!r} (class: {m['class'][:30]})")

# 2. Check if '+ Widgets' button exists and click it to see what drawer/modal opens
widgets_btn = page.query_selector("button:has-text('+ Widgets'), span:has-text('+ Widgets'), div:has-text('+ Widgets')")
if widgets_btn:
    print("\nClicking '+ Widgets' button...")
    widgets_btn.click()
    page.wait_for_timeout(2000)
    page.screenshot(path="screenshots/debug/after_widgets_click.png")
    
    # Inspect drawer/modal items
    drawer_items = page.query_selector_all("div, span, button, li")
    widget_options = []
    for item in drawer_items:
        try:
            itxt = item.inner_text().strip()
            if itxt and len(itxt) < 40 and any(k in itxt.lower() for k in ["option", "chain", "order flow", "depth", "market"]):
                widget_options.append(itxt)
        except Exception:
            pass
    print("Widget drawer options:", set(widget_options))

# 3. Also check top ticker or watchlist for NIFTY option chain
page.screenshot(path="screenshots/debug/dext3_full_state.png")
print("Saved screenshots to screenshots/debug/")

mgr.close()
