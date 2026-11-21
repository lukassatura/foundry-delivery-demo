"""BigHub-styled graphics for the demo videos: title cards, the caption bar and the cursor.

The graphics are HTML and CSS after the BigHub design system, rendered once in headless Chromium.
The brand font is commercial, so it stays outside this public repository: the code reads the
font and the logos from BRAND_DIR at render time (default: the brand folder of the BigHub client
page template).
"""

import base64
import hashlib
import os
from functools import cache
from pathlib import Path

from playwright.sync_api import sync_playwright

BRAND_DIR = Path(os.environ.get("BRAND_DIR", Path.home() / "bighub/client-page-template/brand"))
CACHE = Path.home() / ".cache/foundry-demo-recorder/graphics"

# Colours of the BigHub design system (Figma "BigHub | Webdesign & Other").
WHITE = "#ffffff"
GRAY_300, GRAY_400, GRAY_700, GRAY_950 = "#d0d5dd", "#98a2b3", "#344054", "#0c111d"
BRAND_100, BRAND_300, BRAND_500, BRAND_600 = "#ecebfc", "#c2bcf6", "#856ce6", "#734cdb"
BRAND_700, BRAND_800, BRAND_900 = "#633ac7", "#5230a7", "#432885"
SUCCESS_500 = "#11cf63"


@cache
def _font_face() -> str:
    faces = []
    for weight, name in ((400, "Regular"), (500, "Medium"), (600, "SemiBold"), (700, "Bold")):
        data = base64.b64encode((BRAND_DIR / f"fonts/EuclidCircularB-{name}.woff2").read_bytes()).decode()
        faces.append(f"@font-face{{font-family:'Euclid Circular B';font-weight:{weight};"
                     f"src:url(data:font/woff2;base64,{data}) format('woff2');}}")
    return "".join(faces)


@cache
def _logo(variant: str = "white") -> str:
    return (BRAND_DIR / f"logos/logo_{variant}.svg").read_text()


def _page(body: str, css: str, width: int, height: int) -> str:
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
{_font_face()}
* {{ box-sizing: border-box; margin: 0; }}
html, body {{ width: {width}px; height: {height}px; background: transparent; overflow: hidden;
  font-family: 'Euclid Circular B', sans-serif; -webkit-font-smoothing: antialiased; }}
{css}
</style></head><body>{body}</body></html>"""


def _render(html: str, width: int, height: int, transparent: bool = False) -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    out = CACHE / (hashlib.sha256(f"{width}x{height}{transparent}{html}".encode()).hexdigest()[:24] + ".png")
    if not out.exists():
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": width, "height": height})
            page.set_content(html)
            page.wait_for_timeout(300)
            page.screenshot(path=str(out), omit_background=transparent)
            browser.close()
    return out


HERO_CSS = f"""
.hero {{ position: absolute; inset: 0; color: {WHITE}; padding: 128px 160px; background-color: {BRAND_900};
  background-image:
    repeating-linear-gradient(120deg, rgba(255,255,255,0.045) 0 1px, transparent 1px 22px),
    radial-gradient(ellipse 60% 90% at 100% 0%, rgba(115,76,219,0.60), transparent 70%),
    radial-gradient(ellipse 40% 60% at 85% 100%, rgba(115,76,219,0.35), transparent 70%); }}
.logo svg {{ height: 44px; width: auto; }}
.eyebrow {{ display: inline-flex; align-items: center; border-radius: 6px; padding: 6px 14px; font-size: 24px;
  font-weight: 500; color: {BRAND_100}; background: rgba(255,255,255,0.10); box-shadow: inset 0 0 0 1.5px rgba(255,255,255,0.20); }}
h1 {{ font-size: 84px; line-height: 1.12; font-weight: 600; letter-spacing: -0.02em; margin: 36px 0 0; max-width: 1450px; }}
.lead {{ font-size: 34px; line-height: 1.45; color: {BRAND_100}; margin-top: 28px; max-width: 1350px; }}
.chips {{ position: absolute; left: 160px; bottom: 120px; display: flex; gap: 14px; }}
.checks {{ margin-top: 48px; display: flex; flex-direction: column; gap: 22px; }}
.check {{ display: flex; align-items: center; gap: 22px; font-size: 38px; font-weight: 500; }}
.check i {{ width: 44px; height: 44px; border-radius: 50%; background: {SUCCESS_500}; display: inline-flex;
  align-items: center; justify-content: center; font-style: normal; color: {GRAY_950}; font-size: 28px; font-weight: 700; }}
"""


def title_card(eyebrow: str, title: str, lead: str, chips: list[str]) -> Path:
    chips_html = "".join(f'<span class="eyebrow">{c}</span>' for c in chips)
    body = f"""<div class="hero"><div class="logo">{_logo()}</div>
      <div style="margin-top:120px"><span class="eyebrow">{eyebrow}</span></div>
      <h1>{title}</h1><p class="lead">{lead}</p><div class="chips">{chips_html}</div></div>"""
    return _render(_page(body, HERO_CSS, 1920, 1080), 1920, 1080)


def end_card(title: str, checks: list[str], closing: str) -> Path:
    checks_html = "".join(f'<div class="check"><i>✓</i>{c}</div>' for c in checks)
    body = f"""<div class="hero"><div class="logo">{_logo()}</div>
      <h1 style="margin-top:110px">{title}</h1><div class="checks">{checks_html}</div>
      <p class="lead" style="margin-top:44px">{closing}</p></div>"""
    return _render(_page(body, HERO_CSS, 1920, 1080), 1920, 1080)


BAR_CSS = f"""
.bar {{ position: absolute; inset: 0; background: {GRAY_950}; display: flex; align-items: center; padding: 0 48px; gap: 28px;
  border-top: 2px solid {GRAY_700}; }}
.step {{ flex: none; display: inline-flex; align-items: center; gap: 12px; border-radius: 8px; padding: 10px 16px;
  background: rgba(133,108,230,0.16); box-shadow: inset 0 0 0 1.5px rgba(164,150,239,0.45); color: {BRAND_100};
  font-size: 22px; font-weight: 600; letter-spacing: 0.02em; text-transform: uppercase; }}
.step b {{ display: inline-flex; width: 34px; height: 34px; border-radius: 50%; background: {BRAND_600}; color: {WHITE};
  align-items: center; justify-content: center; font-size: 20px; }}
.text {{ flex: 1; color: {WHITE}; font-size: 34px; font-weight: 500; letter-spacing: -0.01em; line-height: 1.25;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.speed {{ flex: none; color: {BRAND_300}; font-size: 22px; font-weight: 600; border-radius: 6px; padding: 6px 12px;
  box-shadow: inset 0 0 0 1.5px rgba(194,188,246,0.4); }}
.logo svg {{ height: 26px; width: auto; opacity: 0.85; display: block; }}
"""


def caption_bar(step: str, text: str, speed: float = 1.0) -> Path:
    number, _, label = step.partition("  ")
    step_html = (f'<span class="step"><b>{number}</b>{label}</span>' if label else
                 f'<span class="step">{number}</span>' if number else "")
    speed_html = f'<span class="speed">▶▶ {speed:g}×</span>' if speed > 1 else ""
    body = f'<div class="bar">{step_html}<div class="text">{text}</div>{speed_html}<div class="logo">{_logo()}</div></div>'
    return _render(_page(body, BAR_CSS, 1920, 120), 1920, 120)


CURSOR_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 32 32">
<defs><filter id="s" x="-50%" y="-50%" width="200%" height="200%"><feDropShadow dx="0" dy="1.2" stdDeviation="1.2" flood-opacity="0.45"/></filter></defs>
<path filter="url(#s)" d="M7 4 L7 25 L12.2 20.2 L15.6 27.6 L19 26.1 L15.7 18.8 L22.8 18.8 Z"
 fill="#ffffff" stroke="#0c111d" stroke-width="1.6" stroke-linejoin="round"/></svg>"""


def cursor() -> Path:
    body = f'<div style="position:absolute;left:0;top:0">{CURSOR_SVG}</div>'
    return _render(_page(body, "", 64, 64), 64, 64, transparent=True)
