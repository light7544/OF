"""
Robust DexT3 navigator: Widgets -> Order Flow (latest NIFTY FUT) + Options Chain -> screenshots.

Run:  python dext3_navigator.py
Pehle first_run_setup.py se login ho chuka hona chahiye (same profile use hota hai).

Har step ke baad debug screenshot screenshots/debug/ me save hota hai,
aur har step PASS/FAIL print karta hai - jahan FAIL aaye wahi problem hai.
"""
import hashlib
import re
import sys
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

PROFILE_DIR = Path("./browser_profile/dext3_automation").resolve()
URL = "https://dext.dhan.co/dashboard"
OUT = Path("screenshots")
DBG = OUT / "debug"
for d in (OUT / "footprint", OUT / "option_chain", DBG):
    d.mkdir(parents=True, exist_ok=True)

MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


def ts():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def step(name, ok, extra=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {extra}")


def exact(page, text):
    """INNERMOST element whose full text is exactly `text`.
    (div:has-text() ancestors ko bhi match karta hai -> click galat jagah padta tha. Ye wo bug fix karta hai.)"""
    rx = re.compile(rf"^\s*\+?\s*{re.escape(text)}\s*$", re.I)
    return page.locator("button, [role='tab'], [role='button'], span, a, li, div").filter(has_text=rx).last


def snap(page, name):
    p = DBG / f"{ts()}_{name}.png"
    page.screenshot(path=str(p))
    return p


def current_month_candidates():
    now = datetime.now()
    nxt = (now.month % 12)
    return [MONTHS[now.month - 1], MONTHS[nxt]]  # current + next month


def fix_symbol_if_expired(page):
    if page.get_by_text("This symbol doesn't exist").count() == 0:
        step("Symbol valid (expired banner nahi hai)", True)
        return
    step("Expired symbol detected, change kar raha hu", True)
    exact(page, "Change symbol").click(timeout=5000)
    page.wait_for_timeout(800)
    page.keyboard.type("NIFTY FUT", delay=60)
    page.wait_for_timeout(1500)
    for mon in current_month_candidates():
        item = page.locator("div, li, span").filter(
            has_text=re.compile(rf"NIFTY\s*{mon}.*FUT|NIFTY.*{mon}.*FUT", re.I)).last
        if item.count():
            item.click(timeout=4000)
            page.wait_for_timeout(2500)
            step(f"Futures select hua: {mon}", True)
            return
    step("Active NIFTY FUT search result nahi mila", False, "-> debug screenshot dekho")
    snap(page, "symbol_search_fail")


def open_order_flow(page):
    tab = page.locator("[role='tab']").filter(has_text=re.compile(r"Order\s*Flow", re.I)).first
    if tab.count() == 0:
        tab = exact(page, "Order Flow")
    tab.click(timeout=8000)
    page.wait_for_timeout(3000)
    snap(page, "after_order_flow_click")
    step("Order Flow tab click", True)


def open_option_chain(page):
    if page.get_by_text("Strike", exact=True).count() > 0:
        step("Option chain already open", True)
        return True
    exact(page, "Widgets").click(timeout=8000)
    page.wait_for_timeout(1200)
    snap(page, "widgets_menu")
    exact(page, "Options Chain").click(timeout=8000)
    page.wait_for_timeout(3500)
    ok = page.get_by_text("Strike", exact=True).count() > 0 or page.get_by_text("OI").count() > 0
    snap(page, "after_option_chain")
    step("Option Chain widget open", ok)
    return ok


def shoot_option_chain(page):
    # 'Strike' header se upar jaakar sabse chhota container nikalo jo >=500x300 ho
    handle = page.evaluate_handle("""() => {
        const all = [...document.querySelectorAll('*')].filter(e => e.children.length === 0 && /^\\s*Strike\\s*$/i.test(e.textContent));
        for (const leaf of all) {
            let el = leaf;
            while (el && el !== document.body) {
                const r = el.getBoundingClientRect();
                if (r.width >= 500 && r.height >= 300 && /OI/.test(el.innerText)) return el;
                el = el.parentElement;
            }
        }
        return null;
    }""").as_element()
    path = OUT / "option_chain" / f"{ts()}_option_chain.png"
    if handle:
        handle.screenshot(path=str(path))
        step("Option chain container crop", True, str(path))
    else:
        page.screenshot(path=str(path))
        step("Option chain container nahi mila, full page liya", False, str(path))
    return path


def shoot_order_flow(page):
    # sabse bada visible canvas = footprint chart
    canv = page.locator("canvas")
    best, area = None, 0
    for i in range(canv.count()):
        b = canv.nth(i).bounding_box()
        if b and b["width"] * b["height"] > area:
            best, area = canv.nth(i), b["width"] * b["height"]
    path = OUT / "footprint" / f"{ts()}_order_flow.png"
    if best and area > 200_000:
        best.screenshot(path=str(path))
        step("Order flow canvas crop", True, str(path))
    else:
        page.screenshot(path=str(path))
        step("Canvas nahi mila, full page liya", False, str(path))
    return path


def md5(p):
    return hashlib.md5(Path(p).read_bytes()).hexdigest()


def main():
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(PROFILE_DIR), headless=False, no_viewport=True,
            args=["--start-maximized", "--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"],
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.set_default_timeout(8000)
        page.goto(URL, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except PWTimeout:
            pass
        page.wait_for_timeout(3000)
        logged_in = "login" not in page.url.lower()
        step("Logged in", logged_in, page.url)
        if not logged_in:
            print("Pehle first_run_setup.py chalao.")
            ctx.close()
            sys.exit(1)

        try:
            fix_symbol_if_expired(page)
            open_order_flow(page)
            of = shoot_order_flow(page)
            if open_option_chain(page):
                oc = shoot_option_chain(page)
                same = md5(of) == md5(oc)
                step("OrderFlow aur OptionChain screenshots alag hain", not same)
        except Exception as e:
            step("Exception", False, repr(e))
            snap(page, "exception")
        input("Check karke Enter dabao (browser close hoga)...")
        ctx.close()


if __name__ == "__main__":
    main()
