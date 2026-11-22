"""Concept beats: a diagram shown before a step of the video, with that step highlighted.

A beat is a short clip of one still frame: the whole diagram, everything but the step's boxes
dimmed, the boxes ringed in the brand colour. The camera starts on the whole diagram and eases
into the highlighted part, so the viewer first sees where the step sits and then what it is.

    frame, focus = highlight_frame(Path("diagram.png"), boxes, units_size, Path("beat-2.png"))
    beat_clip(Path("out"), "b2", frame, focus, 6.0, "2  Pull request", "Claude reviews every change")

Boxes are [x, y, w, h] in the diagram's own units; units_size is the diagram's [width, height]
in the same units (for a PNG drawn at scale 3 from an SVG, the SVG's size).
"""

import json
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

FRAME = (2560, 1280)
MARGIN = 40
DIM = (255, 255, 255, 178)
RING = (115, 76, 219)  # Brand 600


def _layout(diagram: Image.Image) -> tuple[float, int, int]:
    scale = min((FRAME[0] - 2 * MARGIN) / diagram.width, (FRAME[1] - 2 * MARGIN) / diagram.height)
    left = int((FRAME[0] - diagram.width * scale) / 2)
    top = int((FRAME[1] - diagram.height * scale) / 2)
    return scale, left, top


def highlight_frame(diagram_png: Path, boxes: list[list[float]], units_size: list[float], out_png: Path,
                    pad: float = 6) -> tuple[Path, list[float] | None]:
    """Draw the diagram on a 2:1 frame with the boxes highlighted. Return the frame and the focus box.

    With no boxes, the frame shows the whole diagram undimmed and the focus box is None.
    """
    diagram = Image.open(diagram_png).convert("RGBA")
    scale, left, top = _layout(diagram)
    frame = Image.new("RGBA", FRAME, (255, 255, 255, 255))
    frame.alpha_composite(diagram.resize((int(diagram.width * scale), int(diagram.height * scale)), Image.LANCZOS),
                          (left, top))
    if not boxes:
        frame.convert("RGB").save(out_png)
        return out_png, None

    unit = diagram.width / units_size[0] * scale
    rects = [(left + (x - pad) * unit, top + (y - pad) * unit, left + (x + w + pad) * unit, top + (y + h + pad) * unit)
             for x, y, w, h in boxes]
    veil = Image.new("RGBA", FRAME, DIM)
    holes = ImageDraw.Draw(veil)
    for r in rects:
        holes.rounded_rectangle(r, radius=22, fill=(0, 0, 0, 0))
    frame.alpha_composite(veil)

    glow = Image.new("RGBA", FRAME, (0, 0, 0, 0))
    ImageDraw.Draw(glow).rectangle([0, 0, 0, 0])
    draw = ImageDraw.Draw(glow)
    for r in rects:
        draw.rounded_rectangle(r, radius=22, outline=RING + (150,), width=16)
    frame.alpha_composite(glow.filter(ImageFilter.GaussianBlur(10)))
    draw = ImageDraw.Draw(frame)
    for r in rects:
        draw.rounded_rectangle(r, radius=22, outline=RING + (255,), width=6)
    frame.convert("RGB").save(out_png)

    x0, y0 = min(r[0] for r in rects), min(r[1] for r in rects)
    x1, y1 = max(r[2] for r in rects), max(r[3] for r in rects)
    return out_png, [x0 - 120, y0 - 90, x1 - x0 + 240, y1 - y0 + 180]


def beat_clip(out_dir: Path, name: str, frame_png: Path, focus: list[float] | None, seconds: float, step: str,
              caption: str, zoom_max: float = 1.45, zoom_at: float = 0.9) -> Path:
    """Write a clip folder that studio.py renders like a recorded clip."""
    folder = Path(out_dir) / name
    folder.mkdir(parents=True, exist_ok=True)
    start = time.time()
    events = [] if focus is None else [[start + zoom_at, "focus", {"box": focus, "zoom": None, "dur": 1.4}]]
    clip = {"name": name, "frames": [[start, str(frame_png)]], "captions": [[start, step, caption]],
            "speeds": [[start, 1.0]], "events": events, "end": start + seconds, "zoom_max": zoom_max}
    (folder / "clip.json").write_text(json.dumps(clip))
    return folder
