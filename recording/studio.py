"""Render recorded clips into one MP4: camera zoom on the active element, an artificial cursor with
click ripples, a highlight ring around a field that is being typed in, and BigHub-styled captions
and title cards.

A clip is a folder with clip.json, written by recorder.Recorder: the screencast frames, the
captions, the playback speeds and the interaction events, all with wall-clock timestamps.
An annotation file can add events to a clip that was recorded without them.
"""

import json
import math
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

import brand

FPS = 30
OUT_W, OUT_H = 1920, 1080
PAGE_W, PAGE_H = 1920, 960
BAR_H = OUT_H - PAGE_H
DARK = (12, 11, 35)
RING = (133, 108, 230)
MOVE_S, FOCUS_S, RIPPLE_S = 0.6, 0.9, 0.5


def ease(p: float) -> float:
    p = min(max(p, 0.0), 1.0)
    return 4 * p ** 3 if p < 0.5 else 1 - (-2 * p + 2) ** 3 / 2


@dataclass
class Camera:
    width: int
    height: int
    zoom_max: float
    keys: list = field(default_factory=list)  # (t_start, t_end, from_state, to_state)

    def full(self):
        return (self.width / 2, self.height / 2, 1.0)

    def target(self, box, zoom=None):
        x, y, w, h = box
        z = zoom or min(self.width / max(w * 1.5, 1), self.height / max(h * 1.6, 1))
        z = min(max(z, 1.0), self.zoom_max)
        vw, vh = self.width / z, self.height / z
        cx = min(max(x + w / 2, vw / 2), self.width - vw / 2)
        cy = min(max(y + h / 2, vh / 2), self.height - vh / 2)
        return (cx, cy, z)

    def add(self, t, state, duration=FOCUS_S):
        self.keys.append((t, t + duration, self.at(t), state))

    def at(self, t):
        state = self.full()
        for start, end, origin, goal in self.keys:
            if t >= end:
                state = goal
            elif t >= start:
                p = ease((t - start) / (end - start))
                state = tuple(a + (b - a) * p for a, b in zip(origin, goal))
        return state


@dataclass
class Pointer:
    moves: list = field(default_factory=list)  # (t, from, to)
    clicks: list = field(default_factory=list)  # (t, x, y)
    hidden: list = field(default_factory=list)  # t
    rings: list = field(default_factory=list)  # (t_on, t_off, box)

    def position(self, t):
        """Where the cursor is at t, or None before its first move and after a hide until the next move."""
        pos, last_move = None, None
        for start, origin, goal in self.moves:
            if t < start:
                break
            p = ease((t - start) / MOVE_S)
            pos = (origin[0] + (goal[0] - origin[0]) * p, origin[1] + (goal[1] - origin[1]) * p)
            last_move = start
        last_hide = max([h for h in self.hidden if h <= t], default=None)
        if pos is None or (last_hide is not None and last_hide >= last_move):
            return None
        return pos


def load_clip(clip_dir: Path, annotations: Path | None = None) -> dict:
    data = json.loads((clip_dir / "clip.json").read_text())
    data.setdefault("events", [])
    start = min([t for t, _ in data["frames"]] + [t for t, _, _ in data["captions"]])
    data["start"] = start
    if annotations and annotations.exists():
        extra = json.loads(annotations.read_text())
        data["events"] += [[start + t, kind, args] for t, kind, args in extra.get("events", [])]
        if "captions" in extra:
            data["captions"] = [[start + t, step, text] for t, step, text in extra["captions"]]
        data["masks"] = data.get("masks", []) + [[start + t0, start + t1, box, fill] for t0, t1, box, fill in extra.get("masks", [])]
        data["zoom_max"] = extra.get("zoom_max", data.get("zoom_max"))
    first = Image.open(data["frames"][0][1])
    data["frame_size"] = data.get("frame_size") or list(first.size)
    data["zoom_max"] = data.get("zoom_max") or (1.8 if first.size[0] >= 2560 else 1.35)
    return data


def build_motion(data: dict) -> tuple[Camera, Pointer]:
    width, height = data["frame_size"]
    camera = Camera(width, height, data["zoom_max"])
    pointer = Pointer()
    last = (width * 0.82, height * 0.86)
    ring_on = None
    for t, kind, args in sorted(data["events"], key=lambda e: e[0]):
        if kind == "focus":
            camera.add(t, camera.target(args["box"], args.get("zoom")), args.get("dur", FOCUS_S))
        elif kind == "unfocus":
            camera.add(t, camera.full(), args.get("dur", FOCUS_S))
        elif kind == "move":
            goal = (args["x"], args["y"])
            pointer.moves.append((t, last, goal))
            last = goal
        elif kind == "click":
            pointer.clicks.append((t, args["x"], args["y"]))
        elif kind == "hide":
            pointer.hidden.append(t)
        elif kind == "ring":
            ring_on = (t, args["box"])
        elif kind == "ring_off" and ring_on:
            pointer.rings.append((ring_on[0], t, ring_on[1]))
            ring_on = None
    if ring_on:
        pointer.rings.append((ring_on[0], data["end"], ring_on[1]))
    return camera, pointer


class Encoder:
    def __init__(self, output: Path):
        self.process = subprocess.Popen(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{OUT_W}x{OUT_H}",
             "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
             "-movflags", "+faststart", str(output)],
            stdin=subprocess.PIPE,
        )
        self.frames = 0

    def write(self, image: Image.Image) -> None:
        self.process.stdin.write(image.tobytes())
        self.frames += 1

    def close(self) -> None:
        self.process.stdin.close()
        self.process.wait()


def write_card(encoder: Encoder, image_path: Path, seconds: float, fade_in=0.5, fade_out=0.5) -> None:
    card = Image.open(image_path).convert("RGB").resize((OUT_W, OUT_H))
    dark = Image.new("RGB", (OUT_W, OUT_H), DARK)
    total = int(seconds * FPS)
    for i in range(total):
        t = i / FPS
        alpha = min(1.0, t / fade_in if fade_in else 1.0, (seconds - t) / fade_out if fade_out else 1.0)
        encoder.write(card if alpha >= 1 else Image.blend(dark, card, max(alpha, 0.0)))


def redact(image: Image.Image, masks: list) -> Image.Image:
    """Cover private details: each mask is [t_from, t_to, [x, y, w, h], fill], fill an [r, g, b] colour
    (match the background around the box) or "blur"."""
    if not masks:
        return image
    image = image.copy()
    for _, _, (x, y, w, h), fill in masks:
        box = tuple(int(v) for v in (x, y, x + w, y + h))
        if fill == "blur":
            image.paste(image.crop(box).filter(ImageFilter.GaussianBlur(18)), box[:2])
        else:
            ImageDraw.Draw(image).rectangle(box, fill=tuple(fill))
    return image


def write_clip(encoder: Encoder, data: dict, cut=(0.0, None, 1.0)) -> float:
    """Render one clip; return its length in the video, in seconds."""
    camera, pointer = build_motion(data)
    frames = sorted(data["frames"], key=lambda f: f[0])
    captions = sorted(data["captions"], key=lambda c: c[0])
    speeds = sorted(data.get("speeds", []), key=lambda s: s[0]) or [[data["start"], 1.0]]
    cursor_sprite = Image.open(brand.cursor()).convert("RGBA")
    cursor_sprite = cursor_sprite.resize((52, 52), Image.LANCZOS)
    width, height = data["frame_size"]

    t = data["start"] + cut[0]
    end = data["end"] if cut[1] is None else min(data["end"], data["start"] + cut[1])
    frame_index, caption_index, speed_index = 0, 0, 0
    current_path, source = None, None
    page_cache_key, page_image = None, None
    bars: dict = {}
    written = 0
    while t < end:
        while frame_index + 1 < len(frames) and frames[frame_index + 1][0] <= t:
            frame_index += 1
        while caption_index + 1 < len(captions) and captions[caption_index + 1][0] <= t:
            caption_index += 1
        while speed_index + 1 < len(speeds) and speeds[speed_index + 1][0] <= t:
            speed_index += 1
        speed = speeds[speed_index][1] * cut[2]

        path = frames[frame_index][1]
        active = tuple(i for i, m in enumerate(data.get("masks", [])) if m[0] <= t < m[1])
        if (path, active) != current_path:
            source = Image.open(path).convert("RGB")
            if source.size != (width, height):
                source = source.resize((width, height), Image.LANCZOS)
            source = redact(source, [data["masks"][i] for i in active])
            current_path = (path, active)
        cx, cy, z = camera.at(t)
        vw, vh = width / z, height / z
        left, top = cx - vw / 2, cy - vh / 2
        key = (path, active, round(cx, 1), round(cy, 1), round(z, 4))
        if key != page_cache_key:
            page_image = source.resize((PAGE_W, PAGE_H), Image.BICUBIC, box=(left, top, left + vw, top + vh))
            page_cache_key = key

        frame = Image.new("RGB", (OUT_W, OUT_H), DARK)
        frame.paste(page_image, (0, 0))
        scale = PAGE_W / vw

        def project(x, y):
            return (x - left) * scale, (y - top) * scale

        overlay = None
        for on, off, box in pointer.rings:
            if on <= t < off:
                overlay = overlay or Image.new("RGBA", (PAGE_W, PAGE_H), (0, 0, 0, 0))
                draw = ImageDraw.Draw(overlay)
                x0, y0 = project(box[0], box[1])
                x1, y1 = project(box[0] + box[2], box[1] + box[3])
                fade = min(1.0, (t - on) / 0.3, (off - t) / 0.3)
                for grow, alpha in ((14, 40), (9, 70), (4, 255)):
                    draw.rounded_rectangle([x0 - grow, y0 - grow, x1 + grow, y1 + grow], radius=12 + grow,
                                           outline=RING + (int(alpha * fade),), width=3 if alpha == 255 else 6)
        for when, x, y in pointer.clicks:
            p = (t - when) / RIPPLE_S
            if 0 <= p <= 1:
                overlay = overlay or Image.new("RGBA", (PAGE_W, PAGE_H), (0, 0, 0, 0))
                draw = ImageDraw.Draw(overlay)
                px, py = project(x, y)
                radius = 12 + 44 * ease(p)
                draw.ellipse([px - radius, py - radius, px + radius, py + radius],
                             fill=RING + (int(90 * (1 - p)),), outline=RING + (int(230 * (1 - p)),), width=4)
        position = pointer.position(t)
        if position:
            overlay = overlay or Image.new("RGBA", (PAGE_W, PAGE_H), (0, 0, 0, 0))
            px, py = project(*position)
            pressed = any(0 <= t - when < 0.16 for when, _, _ in pointer.clicks)
            sprite = cursor_sprite.resize((46, 46), Image.LANCZOS) if pressed else cursor_sprite
            tip = 11 * sprite.size[0] / 52, 6 * sprite.size[0] / 52
            overlay.alpha_composite(sprite, (int(px - tip[0]), int(py - tip[1])))
        if overlay:
            frame.paste(overlay, (0, 0), overlay)

        _, step, text = captions[caption_index]
        bar_key = (step, text, speed)
        if bar_key not in bars:
            bars[bar_key] = Image.open(brand.caption_bar(step, text, speed)).convert("RGB")
        frame.paste(bars[bar_key], (0, PAGE_H))

        encoder.write(frame)
        written += 1
        t += speed / FPS
    return written / FPS


def render_video(output: Path, parts: list[tuple], annotations_dir: Path | None = None) -> Path:
    """parts: ("card", image_path, seconds) or ("clip", clip_dir, (start_s, end_s, speed))."""
    encoder = Encoder(output)
    for part in parts:
        if part[0] == "card":
            write_card(encoder, part[1], part[2])
        else:
            clip_dir = Path(part[1])
            annotations = annotations_dir / f"{clip_dir.name}.json" if annotations_dir else None
            seconds = write_clip(encoder, load_clip(clip_dir, annotations), part[2] if len(part) > 2 else (0.0, None, 1.0))
            print(f"{clip_dir.name}: {seconds:.1f} s", flush=True)
    encoder.close()
    print(f"{output}: {encoder.frames / FPS:.1f} s")
    return output
