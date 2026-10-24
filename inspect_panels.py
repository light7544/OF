"""DexT3 panels (Watchlist / News / Portfolio) ke close buttons ki DOM info nikalta hai.
Chalao:  python inspect_panels.py (venv ke andar)
Output logs/panel_inspect.json me save hota hai - wo file bhej do.
"""
import json
from pathlib import Path
from src.config import load_config
from src.browser.session import BrowserSessionManager

JS = """(names) => {
  const out = [];
  const leaf = n => [...document.querySelectorAll('*')].find(
    e => e.children.length === 0 && (e.textContent || '').trim() === n && e.getBoundingClientRect().width > 0);
  for (const n of names) {
    const el = leaf(n);
    if (!el) { out.push({name: n, found: false}); continue; }
    let p = el, panel = null;
    for (let i = 0; i < 12 && p.parentElement; i++) {
      p = p.parentElement;
      const r = p.getBoundingClientRect();
      if (r.width > 250 && r.width < innerWidth * 0.7 && r.height > 150) { panel = p; break; }
    }
    const info = {name: n, found: true, panel: null, buttons: []};
    if (panel) {
      const pr = panel.getBoundingClientRect();
      info.panel = {tag: panel.tagName, cls: String(panel.getAttribute('class') || '').slice(0, 100),
                    x: Math.round(pr.left), y: Math.round(pr.top), w: Math.round(pr.width), h: Math.round(pr.height)};
      panel.querySelectorAll('button,[role=button],svg,i,span,div').forEach(b => {
        const r = b.getBoundingClientRect();
        if (r.width > 0 && r.width <= 34 && r.height <= 34 && r.top - pr.top < 50) {
          info.buttons.push({tag: b.tagName, cls: String(b.getAttribute('class') || '').slice(0, 70),
            aria: b.getAttribute('aria-label'), title: b.getAttribute('title'),
            x: Math.round(r.left), y: Math.round(r.top), html: b.outerHTML.slice(0, 180)});
        }
      });
    }
    out.push(info);
  }
  return out;
}"""

cfg = load_config()
mgr = BrowserSessionManager(cfg.browser)
mgr.get_or_create_context(headless=False)
page = mgr.get_page()
page.goto(cfg.browser.url, wait_until="domcontentloaded")
page.wait_for_timeout(6000)
res = page.evaluate(JS, ["Watchlist", "News", "Portfolio"])
Path("logs").mkdir(exist_ok=True)
Path("logs/panel_inspect.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
print(json.dumps(res, indent=2)[:3000])
print("\nSaved: logs/panel_inspect.json")
mgr.close()
