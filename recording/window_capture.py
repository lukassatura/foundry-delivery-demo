"""Record a desktop app window as a clip, frame by frame, for studio.py.

  python window_capture.py OUT_DIR CLIP_NAME --window 1234 [--max-seconds 600]
  python window_capture.py OUT_DIR CLIP_NAME --owner Claude --exclude-window 1234

Captures one window (--window), or waits for a new window of the owner app, with
`screencapture -l` about four times a second until the file OUT_DIR/CLIP_NAME/STOP exists or the
time is up. Other windows covering it do not matter: macOS captures the window itself. A frame is
kept only when the picture changed, so a long wait costs little disk space. Each frame is padded to 2:1 on a neutral background, so the renderer can
zoom it like a browser clip. The clip has no captions or events; add them with an annotation file.

macOS lets a process capture windows only with Screen Recording permission. Run this script from
a process whose app has it (for example a terminal of that app), not from a sandboxed tool shell.
"""

import argparse
import json
import subprocess
import time
from pathlib import Path

import Quartz
from PIL import Image, ImageChops

BACKGROUND = (234, 236, 240)  # Gray 200


def app_windows(owner: str) -> list[dict]:
    options = Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements
    return [w for w in Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID)
            if w.get("kCGWindowOwnerName", "") == owner and w.get("kCGWindowLayer", 0) == 0]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("out_dir")
    parser.add_argument("clip")
    parser.add_argument("--owner", default="Claude")
    parser.add_argument("--exclude-window", type=int, action="append", default=[])
    parser.add_argument("--window", type=int)
    parser.add_argument("--max-seconds", type=float, default=240)
    args = parser.parse_args()
    if not Quartz.CGPreflightScreenCaptureAccess():
        raise SystemExit("No Screen Recording permission for this process.")

    folder = Path(args.out_dir) / args.clip
    raw = folder / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    stop = folder / "STOP"
    print("Waiting for a new window ...", flush=True)
    window = args.window
    deadline = time.time() + 300
    while window is None and time.time() < deadline:
        candidates = [w for w in app_windows(args.owner) if w["kCGWindowNumber"] not in args.exclude_window]
        window = candidates[0]["kCGWindowNumber"] if candidates else None
        time.sleep(0.3)
    if window is None:
        raise SystemExit("No new window appeared.")
    print(f"Capturing window {window}", flush=True)

    frames, started, previous = [], time.time(), None
    while not stop.exists() and time.time() - started < args.max_seconds:
        t = time.time()
        path = raw / f"{len(frames):06d}.jpg"
        result = subprocess.run(["screencapture", "-x", "-o", "-t", "jpg", f"-l{window}", str(path)], capture_output=True)
        if result.returncode == 0 and path.exists():
            thumb = Image.open(path).convert("L").resize((240, 140))
            if previous is not None and ImageChops.difference(thumb, previous).getbbox() is None:
                path.unlink()  # unchanged: the previous frame stays on screen
            else:
                frames.append((t, path))
                previous = thumb
        time.sleep(max(0.0, 0.25 - (time.time() - t)))
    end = time.time()

    print(f"Padding {len(frames)} frames to 2:1 ...", flush=True)
    clip_frames = []
    for i, (t, path) in enumerate(frames):
        image = Image.open(path).convert("RGB")
        w, h = image.size
        width, height = max(w, 2 * h), max(h, (w + 1) // 2)
        canvas = Image.new("RGB", (width, height), BACKGROUND)
        canvas.paste(image, ((width - w) // 2, (height - h) // 2))
        target = folder / f"{i:06d}.jpg"
        canvas.save(target, quality=92)
        clip_frames.append((t, str(target)))
        path.unlink()
    raw.rmdir()
    clip = {"name": args.clip, "frames": clip_frames, "captions": [[started, "", ""]], "speeds": [[started, 1.0]],
            "events": [], "end": end}
    (folder / "clip.json").write_text(json.dumps(clip))
    print(f"Done: {len(clip_frames)} frames, {end - started:.0f} s", flush=True)


if __name__ == "__main__":
    main()
