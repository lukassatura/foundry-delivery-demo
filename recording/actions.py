"""Interactions for the recordings. Each one acts on the page for real and logs what the renderer
needs to show it: the cursor glides to the element, a ripple marks the click, a ring marks the
field being typed in, and the camera zooms on what the viewer should read.

The browser renders a 1280 x 640 layout at device scale 2, so every frame has 2560 x 1280 pixels
and zoomed shots stay sharp. Coordinates in the logged events are frame pixels.
"""

from playwright.sync_api import Locator, Page

from recorder import Recorder

VIEWPORT = {"width": 1280, "height": 640}
SCALE = 2
LAUNCH_ARGS = [f"--force-device-scale-factor={SCALE}"]


def launch_profile(playwright, profile_dir, **options):
    """Open a persistent browser profile that records at device scale 2."""
    return playwright.chromium.launch_persistent_context(
        profile_dir, channel="chromium", headless=True, viewport=VIEWPORT, device_scale_factor=SCALE,
        args=LAUNCH_ARGS, color_scheme="light", **options,
    )


def rect(locator: Locator) -> list[float]:
    """The element's box in frame pixels."""
    box = locator.evaluate("e => { const r = e.getBoundingClientRect(); return [r.x, r.y, r.width, r.height]; }")
    return [v * SCALE for v in box]


def pad(box: list[float], x: float, y: float) -> list[float]:
    return [box[0] - x, box[1] - y, box[2] + 2 * x, box[3] + 2 * y]


def focus(rec: Recorder, box: list[float], zoom: float | None = None) -> None:
    rec.event("focus", box=box, zoom=zoom)


def focus_on(rec: Recorder, locator: Locator, zoom: float | None = None, margin=(120, 80)) -> None:
    locator.scroll_into_view_if_needed()
    focus(rec, pad(rect(locator), *margin), zoom)


def scroll_to(page: Page, locator: Locator, top_css: int = 90) -> None:
    """Scroll the window smoothly so that the element starts top_css pixels below the top edge."""
    locator.evaluate("(e, top) => window.scrollTo({top: e.getBoundingClientRect().top + window.scrollY - top, behavior: 'smooth'})", top_css)
    page.wait_for_timeout(1400)


def unfocus(rec: Recorder) -> None:
    rec.event("unfocus")


def point(rec: Recorder, page: Page, locator: Locator, settle_s: float = 0.9) -> tuple[float, float]:
    locator.scroll_into_view_if_needed()
    x, y, w, h = rect(locator)
    target = (x + w / 2, y + h / 2)
    rec.event("move", x=target[0], y=target[1])
    page.wait_for_timeout(int(settle_s * 1000))
    return target


def click(rec: Recorder, page: Page, locator: Locator, zoom: float | None = 1.5, settle_s: float = 0.9,
          context=(840, 440)) -> None:
    """Glide to the element, zoom on it with some context around it, then click."""
    locator.scroll_into_view_if_needed()
    if zoom:
        focus(rec, pad(rect(locator), *context), zoom)
    x, y = point(rec, page, locator, settle_s)
    rec.event("click", x=x, y=y)
    page.wait_for_timeout(150)
    locator.click()
    page.wait_for_timeout(500)


def type_text(rec: Recorder, page: Page, locator: Locator, lines: list[str], delay_ms: int = 55,
              newline: str = "Enter", zoom: float | None = None, at_end: bool = False, ring_box=None) -> None:
    """Click into the field and type line by line at a readable pace, with the field ringed."""
    locator.scroll_into_view_if_needed()
    box = ring_box or rect(locator)
    focus(rec, pad(box, 80, 60), zoom)
    x, y = point(rec, page, locator, 0.9)
    rec.event("click", x=x, y=y)
    locator.click()
    if at_end:
        locator.evaluate("e => { e.focus(); if (e.setSelectionRange) e.setSelectionRange(e.value.length, e.value.length); }")
        page.keyboard.press(newline)
    page.wait_for_timeout(300)
    rec.event("hide")
    rec.event("ring", box=box)
    for i, line in enumerate(lines):
        page.keyboard.type(line, delay=delay_ms)
        if i < len(lines) - 1:
            page.keyboard.press(newline)
            page.wait_for_timeout(delay_ms * 4)
    page.wait_for_timeout(700)
    rec.event("ring_off")
