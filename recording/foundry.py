"""Show the hosted agent in the Foundry portal without showing account details.

The portal start page lists every project of the signed-in account, so the recording never
shows it: the browser signs in, opens the agent page, and only then the recorder starts.
"""

from pathlib import Path

from playwright.sync_api import Page

from recorder import SCALE, VIEWPORT

PORTAL = "https://ai.azure.com"
AGENT = "report-deviation-agent"
# Hide the profile button, the subscription name under the project switcher and the
# card with the agent's Entra identity IDs.
HIDE_SCRIPT = """() => {
  const hide = e => { if (e) e.style.visibility = 'hidden'; };
  document.querySelectorAll('button[aria-label="My profile settings"]').forEach(hide);
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const node = walker.currentNode;
    if (node.textContent.includes('Sponsorship') || node.textContent.includes('Subscription')) hide(node.parentElement);
    if (node.textContent.trim() === 'Identity & access') {
      let card = node.parentElement;
      while (card && !card.innerText.includes('Entra agent blueprint')) card = card.parentElement;
      hide(card);
    }
  }
}"""


def open_portal(playwright, profiles: Path, zoomed: bool = False):
    """Start the developer profile in English and sign in silently with the saved Microsoft session.

    zoomed records at device scale 2 (see actions.py).
    """
    if zoomed:
        import actions
        context = actions.launch_profile(playwright, profiles / "developer", locale="en-US")
    else:
        context = playwright.chromium.launch_persistent_context(
            profiles / "developer", channel="chromium", headless=True, viewport=VIEWPORT,
            device_scale_factor=SCALE, locale="en-US", color_scheme="light",
        )
    page = context.pages[0] if context.pages else context.new_page()
    page.goto(PORTAL, wait_until="load")
    page.wait_for_timeout(4000)
    reject = page.get_by_role("button", name="Reject")
    if reject.count():
        reject.first.click()
    sign_in = page.get_by_role("button", name="Sign in")
    (sign_in.first if sign_in.count() else page.get_by_role("link", name="Sign in").first).click()
    page.wait_for_timeout(12000)
    return context, page


def hide_personal(page: Page) -> None:
    page.evaluate(HIDE_SCRIPT)
    close_notices(page)


def close_notices(page: Page) -> None:
    """Close the portal's transient notices, such as an unavailable policy check, when they offer a close button."""
    for notice in page.locator("[role=alert], [role=status], .fui-MessageBar").all():
        try:
            if "unavailable" in (notice.inner_text() or "").lower():
                close = notice.get_by_role("button").last
                if close.count():
                    close.click()
                    page.wait_for_timeout(500)
        except Exception:
            pass


def open_agent(page: Page) -> None:
    """From the project home, open the agent's page with the side panels collapsed."""
    page.get_by_role("link", name="Agents").first.click()
    page.wait_for_timeout(6000)
    page.get_by_role("link", name=AGENT).first.click()
    page.wait_for_timeout(8000)
    collapse = page.get_by_role("button", name="Collapse left navigation")
    if collapse.count():
        collapse.first.click()
    hide_personal(page)


def show_details(page: Page) -> None:
    page.get_by_role("tab", name="Details").first.click()
    page.wait_for_timeout(4000)
    hide_personal(page)


def show_playground(page: Page) -> None:
    page.get_by_role("tab", name="Playground").first.click()
    page.wait_for_timeout(4000)
    setup = page.get_by_role("button", name="Collapse panel")
    if setup.count():
        setup.first.click()
        page.wait_for_timeout(800)
    hide_personal(page)


def ask_in_playground(page: Page, text: str, timeout_s: int = 180) -> str:
    """Type a multi-line message, send it, and wait until the answer has stopped changing."""
    box = page.locator("[aria-label='Message the agent...'][contenteditable=true]").first
    box.click()
    lines = text.strip().splitlines()
    for i, line in enumerate(lines):
        page.keyboard.insert_text(line)
        if i < len(lines) - 1:
            page.keyboard.press("Shift+Enter")
        page.wait_for_timeout(120)
    page.wait_for_timeout(600)
    before = page.evaluate("() => document.body.innerText")
    page.get_by_role("button", name="Send").first.click()
    last, stable = before, 0
    for _ in range(timeout_s // 2):
        page.wait_for_timeout(2000)
        body = page.evaluate("() => document.body.innerText")
        changed_since_send = len(body) > len(before) + 40
        stable = stable + 1 if body == last and changed_since_send else 0
        last = body
        if stable >= 3:
            break
    page.wait_for_timeout(1000)
    return last


def select_model(page: Page, model: str = "gpt-5.4-mini") -> None:
    """Pick the model deployment when a new agent has none selected yet."""
    picker = page.get_by_role("combobox", name="Model:").first
    if model in (picker.inner_text() or ""):
        return
    picker.click()
    page.wait_for_timeout(1200)
    page.get_by_role("option", name=model).first.click()
    page.wait_for_timeout(1500)
