"""One-time manual 2FA/OTP login setup script for DexT3 persistent profile."""

from pathlib import Path
import sys
from playwright.sync_api import sync_playwright

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

PROFILE_DIR = "./browser_profile/dext3_automation"
LOGIN_URL = "https://dext.dhan.co/dashboard"


def main():
    profile_path = Path(PROFILE_DIR).resolve()
    profile_path.mkdir(parents=True, exist_ok=True)

    print("\n" + "=" * 70)
    print(" DexT3 Order Flow & Option Chain Engine - First Run Setup")
    print("=" * 70)
    print(f"Launching Chrome with persistent profile: {profile_path}")

    launch_args = [
        "--start-maximized",
        "--window-position=0,0",
        "--window-size=1920,1080",
        "--disable-blink-features=AutomationControlled",
    ]

    with sync_playwright() as p:
        try:
            context = p.chromium.launch_persistent_context(
                str(profile_path),
                headless=False,
                channel="chrome",
                no_viewport=True,
                args=launch_args,
                ignore_default_args=["--enable-automation"],
            )
        except Exception as e:
            print(f"Note: Standard Chrome launch ({e}) - falling back to bundled Chromium.")
            context = p.chromium.launch_persistent_context(
                str(profile_path),
                headless=False,
                no_viewport=True,
                args=launch_args,
                ignore_default_args=["--enable-automation"],
            )

        page = context.pages[0] if context.pages else context.new_page()
        print(f"Navigating to {LOGIN_URL} ...")
        page.goto(LOGIN_URL, wait_until="domcontentloaded")

        print("\n" + "-" * 70)
        print("Browser is open. Please complete DexT3 login (including OTP) in the window that just opened.")
        print("-" * 70 + "\n")

        # Indefinite blocking pause until user explicitly presses Enter
        input(">>> Once you are fully logged in and see the DexT3 dashboard, press Enter here to save the session and close: ")

        print("\nSession saved to", str(profile_path))
        context.close()
        print("Setup complete! You can now test with 'python dext3_navigator.py' or run 'python main.py --run-once'.\n")


if __name__ == "__main__":
    main()
