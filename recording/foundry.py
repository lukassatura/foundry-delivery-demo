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


def open_portal(playwright, profiles: Path):
    """Start the developer profile in English and sign in silently with the saved Microsoft session."""
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


def ask_in_playground(page: Page, text: str, timeout_s: int = 150) -> str:
    """Type a multi-line message, send it and wait until the answer is complete."""
    box = page.locator("[aria-label='Message the agent...'][contenteditable=true]").first
    box.click()
    lines = text.strip().splitlines()
    for i, line in enumerate(lines):
        page.keyboard.insert_text(line)
        if i < len(lines) - 1:
            page.keyboard.press("Shift+Enter")
        page.wait_for_timeout(120)
    page.wait_for_timeout(600)
    page.get_by_role("button", name="Send").first.click()
    for _ in range(timeout_s // 3):
        page.wait_for_timeout(3000)
        body = page.evaluate("() => document.body.innerText")
        if "Summary:" in body:
            page.wait_for_timeout(1500)
            return body
    return page.evaluate("() => document.body.innerText")
