# Recording

These scripts record the demo as an MP4 with captions.

- `recorder.py` captures a browser page frame by frame through the Chrome DevTools screencast. Only page content is captured: no browser chrome, no other windows, no notifications. Captions go in a strip below the page.
- `terminal.py` shows a terminal inside a page. Each command runs for real in a pseudo-terminal on the recording machine, and its output streams into the page.

The scripts need Playwright, Pillow and a local copy of xterm.js 5.5.0 in `~/.cache/foundry-demo-recorder/xterm/` (`xterm.js` and `xterm.css` from https://cdn.jsdelivr.net/npm/@xterm/xterm@5.5.0/). Output goes to `recording/out/`, which Git ignores.
