"""A terminal view in a Playwright page. Commands run for real in a pseudo-terminal on this machine,
and their output streams into an xterm.js view while the recorder captures the page."""

import fcntl
import os
import pty
import select
import struct
import subprocess
import termios
import time
from pathlib import Path

# xterm.js 5.5.0 from https://cdn.jsdelivr.net/npm/@xterm/xterm@5.5.0, cached locally (see recording/README.md).
XTERM_DIR = Path.home() / ".cache/foundry-demo-recorder/xterm"
COLS, ROWS = 128, 31
PROMPT = "\x1b[1;34mdeveloper\x1b[0m \x1b[90m$\x1b[0m "

PAGE = f"""<!doctype html>
<html><head><meta charset="utf-8">
<style>__XTERM_CSS__</style>
<script>__XTERM_JS__</script>
<style>
  html, body {{ margin: 0; height: 100%; background: #1e1e2e; }}
  #bar {{ height: 34px; background: #2a2a3c; color: #a6adc8; font: 14px -apple-system, sans-serif;
          display: flex; align-items: center; padding-left: 16px; gap: 8px; }}
  .dot {{ width: 12px; height: 12px; border-radius: 50%; display: inline-block; }}
  #term {{ padding: 12px 16px; }}
</style></head>
<body>
<div id="bar"><span class="dot" style="background:#f38ba8"></span><span class="dot" style="background:#f9e2af"></span>
<span class="dot" style="background:#a6e3a1"></span><span id="title" style="margin-left:12px">terminal</span></div>
<div id="term"></div>
<script>
  window.term = new Terminal({{cols: {COLS}, rows: {ROWS}, fontSize: 16, lineHeight: 1.1,
    fontFamily: 'Menlo, monospace', cursorBlink: false,
    theme: {{background: '#1e1e2e', foreground: '#e6e6e6', cursor: '#e6e6e6'}}}});
  term.open(document.getElementById('term'));
</script></body></html>"""


class TerminalView:
    def __init__(self, page, cwd: str, env: dict[str, str] | None = None, title: str = "terminal"):
        self.page = page
        self.cwd = cwd
        self.env = {**os.environ, "GIT_PAGER": "cat", "PAGER": "cat", "TERM": "xterm-256color",
                    "COLUMNS": str(COLS), "LINES": str(ROWS), **(env or {})}
        page.set_content(
            PAGE.replace("__XTERM_CSS__", (XTERM_DIR / "xterm.css").read_text())
            .replace("__XTERM_JS__", (XTERM_DIR / "xterm.js").read_text())
        )
        page.evaluate("t => document.getElementById('title').textContent = t", title)
        self.write(PROMPT)

    def write(self, text: str) -> None:
        self.page.evaluate("d => new Promise(r => term.write(d, r))", text.replace("\n", "\r\n") if "\r" not in text else text)

    def clear(self) -> None:
        self.page.evaluate("() => term.reset()")
        self.write(PROMPT)

    def type(self, command: str, delay_s: float = 0.035) -> None:
        for char in command:
            self.write(char)
            time.sleep(delay_s)
        time.sleep(0.3)
        self.write("\r\n")

    def run(self, command: str, shown: str | None = None, timeout_s: float = 600) -> int:
        """Type the command (or the text shown instead of it), run it in a pseudo-terminal and stream its output."""
        self.type(shown or command)
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLS, 0, 0))
        process = subprocess.Popen(["/bin/bash", "-c", command], cwd=self.cwd, env=self.env,
                                   stdin=slave, stdout=slave, stderr=slave, close_fds=True)
        os.close(slave)
        deadline = time.monotonic() + timeout_s
        buffer = b""
        while True:
            ready, _, _ = select.select([master], [], [], 0.1)
            if ready:
                try:
                    chunk = os.read(master, 65536)
                except OSError:
                    chunk = b""
                if not chunk:
                    break
                buffer += chunk
                text = buffer.decode("utf-8", errors="ignore")
                buffer = b""
                self.page.evaluate("d => new Promise(r => term.write(d, r))", text)
            elif process.poll() is not None:
                break
            if time.monotonic() > deadline:
                process.kill()
                break
        os.close(master)
        code = process.wait()
        self.write(PROMPT)
        return code
