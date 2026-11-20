"""Record a Playwright page frame by frame and turn the clips into a captioned MP4.

The recorder uses the Chrome DevTools screencast, so only the page content is captured:
no browser chrome, no other windows and no system notifications. Captions are drawn in a
strip below the page, so they never cover page content.
"""

import base64
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

VIEWPORT = {"width": 1280, "height": 640}
SCALE = 1.5
PAGE_SIZE = (1920, 960)
CAPTION_HEIGHT = 120
VIDEO_SIZE = (1920, PAGE_SIZE[1] + CAPTION_HEIGHT)
FPS = 30
FONT = ImageFont.truetype("/System/Library/Fonts/HelveticaNeue.ttc", 40, index=1)
STEP_FONT = ImageFont.truetype("/System/Library/Fonts/HelveticaNeue.ttc", 28, index=0)
BACKGROUND = (24, 28, 38)
TEXT = (245, 247, 250)
ACCENT = (138, 180, 248)


@dataclass
class Clip:
    name: str
    frames: list[tuple[float, Path]] = field(default_factory=list)
    captions: list[tuple[float, str, str]] = field(default_factory=list)
    end: float = 0.0


class Recorder:
    def __init__(self, out_dir: Path):
        self.out_dir = out_dir
        self.clips: list[Clip] = []
        self.clip: Clip | None = None
        self.cdp = None
        self.page = None
        self.step = ""
        self.caption = ""

    # Recording ---------------------------------------------------------------------------

    def start(self, page, name: str) -> None:
        """Start a new clip on the page. The current caption carries over."""
        self.stop()
        self.page = page
        self.clip = Clip(name)
        (self.out_dir / name).mkdir(parents=True, exist_ok=True)
        self.clip.captions.append((time.time(), self.step, self.caption))
        self.cdp = page.context.new_cdp_session(page)
        self.cdp.on("Page.screencastFrame", self._on_frame)
        self.cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 95, "everyNthFrame": 1})

    def stop(self) -> None:
        if self.clip is None:
            return
        try:
            self.cdp.send("Page.stopScreencast")
            self.cdp.detach()
        except Exception:
            pass
        self.clip.end = time.time()
        self.clips.append(self.clip)
        self.clip = None

    def say(self, caption: str, step: str | None = None) -> None:
        """Show a caption from now on. The step label stays until it is changed."""
        if step is not None:
            self.step = step
        self.caption = caption
        if self.clip is not None:
            self.clip.captions.append((time.time(), self.step, caption))

    def hold(self, seconds: float) -> None:
        """Keep the current picture on screen for a while."""
        self.page.wait_for_timeout(seconds * 1000)

    def _on_frame(self, params: dict) -> None:
        clip = self.clip
        if clip is None:
            return
        path = self.out_dir / clip.name / f"{len(clip.frames):06d}.jpg"
        path.write_bytes(base64.b64decode(params["data"]))
        clip.frames.append((params["metadata"]["timestamp"], path))
        try:
            self.cdp.send("Page.screencastFrameAck", {"sessionId": params["sessionId"]})
        except Exception:
            pass

    # Rendering ---------------------------------------------------------------------------

    def render(self, output: Path) -> Path:
        """Composite every clip with its captions and encode one MP4."""
        self.stop()
        parts = [self._render_clip(clip) for clip in self.clips if clip.frames]
        listing = self.out_dir / "clips.txt"
        listing.write_text("".join(f"file '{p.resolve()}'\n" for p in parts))
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
             "-c", "copy", "-movflags", "+faststart", str(output)],
            check=True,
        )
        return output

    def _render_clip(self, clip: Clip) -> Path:
        work = self.out_dir / clip.name / "composited"
        work.mkdir(exist_ok=True)
        events = sorted([(t, "frame", p) for t, p in clip.frames] + [(t, "caption", (s, c)) for t, s, c in clip.captions],
                        key=lambda e: e[0])
        start = min(e[0] for e in events)
        frame_path, step, caption = None, "", ""
        shots: list[tuple[float, Path]] = []
        cache: dict[tuple, Path] = {}
        for t, kind, value in events:
            if kind == "frame":
                frame_path = value
            else:
                step, caption = value
            if frame_path is None:
                continue
            key = (frame_path, step, caption)
            if key not in cache:
                cache[key] = work / f"{len(cache):06d}.png"
                compose(frame_path, step, caption).save(cache[key])
            shots.append((max(t, start), cache[key]))

        listing = work / "frames.txt"
        lines = []
        for (t, path), nxt in zip(shots, shots[1:] + [(clip.end, None)]):
            duration = max(nxt[0] - t, 1 / FPS)
            lines.append(f"file '{path.resolve()}'\nduration {duration:.3f}\n")
        lines.append(f"file '{shots[-1][1].resolve()}'\n")
        listing.write_text("".join(lines))
        output = self.out_dir / f"{clip.name}.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
             "-vf", f"fps={FPS},format=yuv420p", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
             "-r", str(FPS), str(output)],
            check=True,
        )
        return output


def compose(frame_path: Path, step: str, caption: str) -> Image.Image:
    canvas = Image.new("RGB", VIDEO_SIZE, BACKGROUND)
    frame = Image.open(frame_path).convert("RGB")
    if frame.size != PAGE_SIZE:
        frame = frame.resize(PAGE_SIZE, Image.LANCZOS)
    canvas.paste(frame, (0, 0))
    draw = ImageDraw.Draw(canvas)
    top = PAGE_SIZE[1]
    draw.rectangle([0, top, VIDEO_SIZE[0], top + 4], fill=ACCENT)
    x = 48
    if step:
        draw.text((x, top + CAPTION_HEIGHT / 2), step.upper(), font=STEP_FONT, fill=ACCENT, anchor="lm")
        x += int(draw.textlength(step.upper(), font=STEP_FONT)) + 36
    draw.text((x, top + CAPTION_HEIGHT / 2), caption, font=FONT, fill=TEXT, anchor="lm")
    return canvas
