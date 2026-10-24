"""Playwright Persistent Session Management for DexT3."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional
from playwright.sync_api import BrowserContext, Page, sync_playwright

from src.config import BrowserConfig

logger = logging.getLogger("browser_session")


class SessionExpiredError(Exception):
    """Raised when the DexT3 browser session has expired or requires re-authentication."""
    pass


class BrowserSessionManager:
    def __init__(self, config: BrowserConfig):
        self.config = config
        self._playwright = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

    def get_or_create_context(self, headless: Optional[bool] = None) -> BrowserContext:
        """Launch or return existing persistent browser context using saved profile."""
        if self._context:
            return self._context

        if headless is None:
            headless = self.config.headless

        profile_path = Path(self.config.user_data_dir).resolve()
        profile_path.mkdir(parents=True, exist_ok=True)

        self._playwright = sync_playwright().start()

        launch_args = [
            "--start-maximized",
            "--window-position=0,0",
            f"--window-size={self.config.viewport.width},{self.config.viewport.height}",
            "--disable-blink-features=AutomationControlled",
        ]

        logger.info("Launching browser with persistent profile: %s (headless=%s)", profile_path, headless)

        try:
            self._context = self._playwright.chromium.launch_persistent_context(
                str(profile_path),
                headless=headless,
                channel="chrome",
                no_viewport=True,
                args=launch_args,
                ignore_default_args=["--enable-automation"],
            )
        except Exception as e:
            logger.info("Chrome channel launch failed (%s). Falling back to bundled Chromium.", e)
            self._context = self._playwright.chromium.launch_persistent_context(
                str(profile_path),
                headless=headless,
                no_viewport=True,
                args=launch_args,
                ignore_default_args=["--enable-automation"],
            )

        self._context.set_default_timeout(self.config.timeout_ms)
        self._page = self._context.pages[0] if self._context.pages else self._context.new_page()
        return self._context

    def get_page(self) -> Page:
        if not self._page:
            self.get_or_create_context()
        return self._page

    def _visible(self, page: Page, selector: str, timeout_ms: int = 3000) -> bool:
        """Non-strict visibility check (page.is_visible raises on multi-match selectors)."""
        try:
            page.locator(selector).first.wait_for(state="visible", timeout=timeout_ms)
            return True
        except Exception:
            return False

    def is_session_valid(self, page: Optional[Page] = None) -> bool:
        """Check if current page shows an authenticated DexT3 session."""
        target_page = page or self.get_page()

        url = target_page.url.lower()
        if "login" in url or "signin" in url:
            return False

        login_sel = self.config.selectors.get("login_indicator", "button:has-text('Sign In'), button:has-text('Log in')")
        if self._visible(target_page, login_sel, 2000):
            return False

        return True

    def interactive_login(self, timeout_seconds: int = 600) -> bool:
        """Launch browser in visible mode for manual 2FA/OTP login, then save session."""
        profile_path = Path(self.config.user_data_dir).resolve()
        profile_path.mkdir(parents=True, exist_ok=True)

        print("\n" + "=" * 70)
        print(" DexT3 Manual Authentication / Setup Mode")
        print("=" * 70)
        print(f"Profile Directory: {profile_path}")
        print("Opening browser window for manual login...")

        self.get_or_create_context(headless=False)
        page = self.get_page()
        page.goto(self.config.url, wait_until="domcontentloaded")

        print("-" * 70)
        print("Please complete your mobile/password and 2FA/OTP login in the opened window.")
        print("-" * 70 + "\n")

        try:
            input(">>> Once you are logged in and see the DexT3 dashboard, press Enter here to save and close: ")
            print("\nSession saved successfully to", profile_path)
            return True
        except (KeyboardInterrupt, EOFError):
            print("\nSetup cancelled.")
            return False

    def close(self) -> None:
        """Cleanly close browser context and playwright instance."""
        if self._context:
            try:
                self._context.close()
            except Exception as e:
                logger.debug("Context close error: %s", e)
            self._context = None
            self._page = None

        if self._playwright:
            try:
                self._playwright.stop()
            except Exception as e:
                logger.debug("Playwright stop error: %s", e)
            self._playwright = None
