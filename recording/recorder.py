"""Record a Playwright page frame by frame and turn the clips into a captioned MP4.

The recorder uses the Chrome DevTools screencast, so only the page content is captured:
no browser chrome, no other windows and no system notifications. Captions are drawn in a
strip below the page, so they never cover page content. Each clip is saved to disk, so a
demo can be recorded in several runs and rendered at the end.
"""

import base64
import json
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

VIEWPORT = {"width": 1280, "height": 640}
SCALE = 1.5
PAGE_SIZE = (1920, 960)
CAPTION_HEIGHT = 120
VIDEO_SIZE = (1920, PAGE_SIZE[1] + CAPTION_HEIGHT)
FPS = 30
FONT = ImageFont.truetype("/System/Library/Fonts/HelveticaNeue.ttc", 40, index=1)
SMALL_FONT = ImageFont.truetype("/System/Library/Fonts/HelveticaNeue.ttc", 28, index=0)
BACKGROUND = (24, 28, 38)
TEXT = (245, 247, 250)
ACCENT = (138, 180, 248)
MUTED = (150, 160, 180)


@dataclass
class Clip:
    name: str
    frames: list[tuple[float, str]] = field(default_factory=list)
    captions: list[tuple[float, str, str]] = field(default_factory=list)
    speeds: list[tuple[float, float]] = field(default_factory=list)
    events: list[tuple[float, str, dict]] = field(default_factory=list)
    frame_size: list[int] | None = None
    end: float = 0.0


class Recorder:
    def __init__(self, out_dir: Path):
        self.out_dir = out_dir
        self.clip: Clip | None = None
        self.cdp = None
        self.page = None
        self.step = ""
        self.caption = ""
        self.speed = 1.0

    # Recording ---------------------------------------------------------------------------

    def start(self, page, name: str) -> None:
        """Start a new clip on the page. The current caption carries over."""
        self.stop()
        self.page = page
        self.clip = Clip(name)
        (self.out_dir / name).mkdir(parents=True, exist_ok=True)
        now = time.time()
        self.clip.captions.append((now, self.step, self.caption))
        self.clip.speeds.append((now, self.speed))
        self.cdp = page.context.new_cdp_session(page)
        self.cdp.on("Page.screencastFrame", self._on_frame)
        self.cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 95, "everyNthFrame": 1})

    def switch(self, page) -> None:
        """Continue the current clip on another page or tab."""
        name = self.clip.name if self.clip else "clip"
        clip = self.clip
        self._stop_screencast()
        self.page = page
        self.clip = clip or Clip(name)
        self.cdp = page.context.new_cdp_session(page)
        self.cdp.on("Page.screencastFrame", self._on_frame)
        self.cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 95, "everyNthFrame": 1})

    def stop(self) -> None:
        if self.clip is None:
            return
        self._stop_screencast()
        self.clip.end = time.time()
        (self.out_dir / self.clip.name / "clip.json").write_text(json.dumps(asdict(self.clip)))
        self.clip = None

    def _stop_screencast(self) -> None:
        try:
            self.cdp.send("Page.stopScreencast")
            self.cdp.detach()
        except Exception:
            pass

    def say(self, caption: str, step: str | None = None) -> None:
        """Show a caption from now on. The step label stays until it is changed."""
        if step is not None:
            self.step = step
        self.caption = caption
        if self.clip is not None:
            self.clip.captions.append((time.time(), self.step, caption))

    def fast(self, factor: float = 4.0) -> None:
        """Play what follows faster in the video. The caption strip shows the factor."""
        self.speed = factor
        if self.clip is not None:
            self.clip.speeds.append((time.time(), factor))

    def normal(self) -> None:
        self.fast(1.0)

    def event(self, kind: str, **args) -> None:
        """Log an interaction for the renderer: focus, unfocus, move, click, hide, ring or ring_off.

        Coordinates are in page pixels of the viewport, which are also the frame pixels.
        """
        if self.clip is not None:
            self.clip.events.append((time.time(), kind, args))

    def hold(self, seconds: float) -> None:
        """Keep the current picture on screen for a while."""
        self.page.wait_for_timeout(seconds * 1000)

    def _on_frame(self, params: dict) -> None:
        clip = self.clip
        if clip is None:
            return
        path = self.out_dir / clip.name / f"{len(clip.frames):06d}.jpg"
        path.write_bytes(base64.b64decode(params["data"]))
        clip.frames.append((params["metadata"]["timestamp"], str(path)))
        try:
            self.cdp.send("Page.screencastFrameAck", {"sessionId": params["sessionId"]})
        except Exception:
            pass


# Rendering -------------------------------------------------------------------------------


def render(out_dir: Path, clip_names: list[str], output: Path, edits: dict | None = None) -> Path:
    """Composite the clips with their captions and encode one MP4.

    edits maps a clip name to (start_s, end_s, speed): keep only that part of the clip,
    played at that speed. End None keeps the clip to its end.
    """
    parts = [render_clip(out_dir, name) for name in clip_names]
    parts = [cut(part, *(edits or {}).get(name, (0, None, 1.0))) for part, name in zip(parts, clip_names)]
    listing = out_dir / "clips.txt"
    listing.write_text("".join(f"file '{p.resolve()}'\n" for p in parts))
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
         "-c", "copy", "-movflags", "+faststart", str(output)],
        check=True,
    )
    return output


def cut(path: Path, start: float, end: float | None, speed: float) -> Path:
    if start == 0 and end is None and speed == 1.0:
        return path
    output = path.with_suffix(".cut.mp4")
    window = ["-ss", str(start)] + (["-to", str(end)] if end is not None else [])
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", *window, "-i", str(path), "-vf", f"setpts=PTS/{speed},fps={FPS}",
         "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-an", str(output)],
        check=True,
    )
    return output


def render_clip(out_dir: Path, name: str) -> Path:
    data = json.loads((out_dir / name / "clip.json").read_text())
    work = out_dir / name / "composited"
    work.mkdir(exist_ok=True)
    events = sorted(
        [(t, "frame", p) for t, p in data["frames"]]
        + [(t, "caption", (s, c)) for t, s, c in data["captions"]]
        + [(t, "speed", f) for t, f in data["speeds"]],
        key=lambda e: e[0],
    )
    frame_path, step, caption, speed = None, "", "", 1.0
    shots: list[tuple[float, float, Path]] = []
    cache: dict[tuple, Path] = {}
    for t, kind, value in events:
        if kind == "frame":
            frame_path = value
        elif kind == "caption":
            step, caption = value
        else:
            speed = value
        if frame_path is None:
            continue
        key = (frame_path, step, caption, speed)
        if key not in cache:
            cache[key] = work / f"{len(cache):06d}.png"
            compose(Path(frame_path), step, caption, speed).save(cache[key])
        shots.append((t, speed, cache[key]))

    lines = []
    total = 0.0
    for (t, speed, path), nxt in zip(shots, shots[1:] + [(data["end"], 1.0, None)]):
        duration = max((nxt[0] - t) / speed, 0)
        if duration > 0:
            lines.append(f"file '{path.resolve()}'\nduration {duration:.4f}\n")
            total += duration
    # The concat demuxer needs the last file twice; give the repeat one frame, not a full extra duration.
    lines.append(f"file '{shots[-1][2].resolve()}'\nduration {1 / FPS:.4f}\n")
    listing = work / "frames.txt"
    listing.write_text("".join(lines))
    output = out_dir / f"{name}.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
         "-vf", f"fps={FPS},format=yuv420p", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
         "-r", str(FPS), "-t", f"{total:.3f}", str(output)],
        check=True,
    )
    return output


def compose(frame_path: Path, step: str, caption: str, speed: float = 1.0) -> Image.Image:
    canvas = Image.new("RGB", VIDEO_SIZE, BACKGROUND)
    frame = Image.open(frame_path).convert("RGB")
    if frame.size != PAGE_SIZE:
        frame = frame.resize(PAGE_SIZE, Image.LANCZOS)
    canvas.paste(frame, (0, 0))
    draw = ImageDraw.Draw(canvas)
    top = PAGE_SIZE[1]
    middle = top + CAPTION_HEIGHT / 2
    draw.rectangle([0, top, VIDEO_SIZE[0], top + 4], fill=ACCENT)
    x = 48
    if step:
        draw.text((x, middle), step.upper(), font=SMALL_FONT, fill=ACCENT, anchor="lm")
        x += int(draw.textlength(step.upper(), font=SMALL_FONT)) + 36
    room = VIDEO_SIZE[0] - x - (220 if speed > 1 else 48)
    font = FONT
    for size in range(40, 25, -2):
        font = ImageFont.truetype("/System/Library/Fonts/HelveticaNeue.ttc", size, index=1)
        if draw.textlength(caption, font=font) <= room:
            break
    draw.text((x, middle), caption, font=font, fill=TEXT, anchor="lm")
    if speed > 1:
        draw.text((VIDEO_SIZE[0] - 48, middle), f"▶▶ {speed:g}×", font=SMALL_FONT, fill=MUTED, anchor="rm")
    return canvas


def title_card(out_dir: Path, name: str, lines: list[str], seconds: float) -> None:
    """Write a still clip with centred text, for the opening and closing of the video."""
    clip_dir = out_dir / name
    clip_dir.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", PAGE_SIZE, BACKGROUND)
    draw = ImageDraw.Draw(image)
    y = PAGE_SIZE[1] / 2 - (len(lines) - 1) * 40
    for i, line in enumerate(lines):
        font = FONT if i == 0 else SMALL_FONT
        draw.text((PAGE_SIZE[0] / 2, y), line, font=font, fill=TEXT if i == 0 else MUTED, anchor="mm")
        y += 80
    frame = clip_dir / "000000.jpg"
    image.save(frame, quality=95)
    start = time.time()
    clip = Clip(name, frames=[(start, str(frame))], captions=[(start, "", "")], speeds=[(start, 1.0)], end=start + seconds)
    (clip_dir / "clip.json").write_text(json.dumps(asdict(clip)))
