"""Open a recording browser profile so that a person can sign in once.

  python recording/login.py developer   # GitHub as the developer, and the Foundry portal
  python recording/login.py approver    # GitHub as the approver

Sign in in the window that opens, then close the window. The profile keeps the session for
the recording runs.
"""

import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

PROFILES = Path.home() / ".cache/foundry-demo-recorder/profiles"
REPO = os.environ.get("DEMO_REPO", "lukassatura/foundry-delivery-demo")
START_PAGES = {
    "developer": ["https://github.com/login", "https://ai.azure.com/"],
    "approver": ["https://github.com/login", f"https://github.com/{REPO}/invitations"],
}


def main() -> None:
    role = sys.argv[1]
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            PROFILES / role, channel="chromium", headless=False, viewport={"width": 1280, "height": 800}
        )
        for i, url in enumerate(START_PAGES[role]):
            page = context.pages[0] if i == 0 and context.pages else context.new_page()
            page.goto(url)
        print(f"Sign in as the {role} in the browser window, then close it.")
        context.wait_for_event("close", timeout=0)


if __name__ == "__main__":
    main()
