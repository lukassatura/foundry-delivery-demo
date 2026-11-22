# Recording

`record_demo.py` runs the demo for real and records it as a captioned MP4. Every step happens on GitHub and in Microsoft Foundry while it is recorded; the script waits for each review and pipeline run before it records the result.

## How the recording works

- `recorder.py` captures a browser page frame by frame through the Chrome DevTools screencast. Only page content is captured: no browser chrome, no other windows, no notifications. Captions go in a strip below the page. Long waits are either cut between clips or played faster, and the caption strip then shows the speed, for example `▶▶ 12×`.
- `terminal.py` shows a terminal inside a page. Each command runs for real in a pseudo-terminal, and its output streams into the page. The demo uses it only for the local review in step 1.
- `foundry.py` opens the hosted agent in the Foundry portal. It signs in with the saved Microsoft session and goes straight to the agent page. It never records the portal's start page or project list, because they show the account and other projects. It hides the profile button, the subscription name and the agent's identity IDs.

## One-time set-up

1. Create a Python environment with Playwright and Pillow, and download Chromium:
   ```bash
   uv venv ~/.cache/foundry-demo-recorder --python 3.13
   uv pip install --python ~/.cache/foundry-demo-recorder/bin/python playwright pillow
   ~/.cache/foundry-demo-recorder/bin/python -m playwright install chromium
   ```
2. Put xterm.js 5.5.0 (`xterm.js` and `xterm.css` from https://cdn.jsdelivr.net/npm/@xterm/xterm@5.5.0/) in `~/.cache/foundry-demo-recorder/xterm/`.
3. Sign in once in each browser profile, then quit the browser with Cmd+Q:
   ```bash
   ~/.cache/foundry-demo-recorder/bin/python recording/login.py developer   # GitHub as the developer, and ai.azure.com
   ~/.cache/foundry-demo-recorder/bin/python recording/login.py approver    # GitHub as the approver
   ```
   For the Microsoft sign-in, answer **Yes** to "Stay signed in?".

## Record

Reset the demo first (`demo/reset.sh`). Then run the phases in order, with `az` signed in to the demo subscription:

```bash
for phase in change review fix pipeline result render; do
  ~/.cache/foundry-demo-recorder/bin/python recording/record_demo.py $phase || break
done
```

A full take takes about 25 minutes and two Claude Code Review runs. `fallback` records the failing evaluation on the branch with the planted flaw; run it after a reset. `render` writes `recording/out/delivery-demo.mp4` and `recording/out/delivery-demo-failing-evaluation.mp4`. `EDITS` in `record_demo.py` cuts page loads and long pauses from the clip edges.

When a phase fails, fix the cause and run the remaining phases. `approve`, `merge` and `fixshots` resume step 3 and step 4 for the pull request in `recording/out/state.json`.

## Record the prompt agent journey

`record_prompt_demo.py` records a business owner who creates and changes a prompt agent in the Foundry portal, and the release of that agent through the same gates as code:

```bash
export PROMPT_AGENT_NAME=deviation-email-writer-2   # a name that does not exist in Foundry yet
for phase in build release production render; do
  ~/.cache/foundry-demo-recorder/bin/python recording/record_prompt_demo.py $phase || break
done
```

`build` records the portal part in the dev project. `release` starts `Promote prompt agent` and opens the pull request as the platform engineer, records Claude's review and the approval, then answers and resolves Claude's comments and merges. `production` records the pipeline and the agent in the production project. The output is `recording/out-prompt/prompt-agent-demo.mp4`. A take uses one Claude Code Review run. Foundry keeps the agents, so every take needs a new agent name.

## Styled videos

`record_main_video.py` and `record_prompt_video.py` make the BigHub-styled versions of the two videos. They add an artificial cursor with click ripples, a camera that zooms on what is clicked, typed or read, a ring around a field being typed in, intro and outro cards, and a caption bar that says what happens in the frame.

- `actions.py` performs each click and each typing step for real and logs where it happens. The browser renders a 1280 x 640 layout at device scale 2, so zoomed shots stay sharp.
- `studio.py` renders every frame from the recorded frames and the logged events, and streams them into the encoder.
- `brand.py` draws the cards, the caption bar and the cursor in HTML after the BigHub design system. It reads the brand font and logos from `BRAND_DIR` (default: the `brand` folder of the BigHub client page template). The font is commercial, so it never goes into this repository.
- `annotations/` adds the cursor and the camera to clips recorded without them, for example the pull request footage. Times are seconds from the clip start; coordinates are pixels of the clip's frames.

The styled videos reuse the pull request footage of `record_demo.py` and `record_prompt_demo.py`, so making them again opens no pull request and starts no Claude Code Review:

```bash
~/.cache/foundry-demo-recorder/bin/python recording/record_main_video.py foundry    # production must serve the version that PR #2 deployed
~/.cache/foundry-demo-recorder/bin/python recording/record_main_video.py rollback
~/.cache/foundry-demo-recorder/bin/python recording/record_main_video.py render
~/.cache/foundry-demo-recorder/bin/python recording/record_prompt_video.py foundry  # the dev agent must not exist yet
~/.cache/foundry-demo-recorder/bin/python recording/record_prompt_video.py pipeline
~/.cache/foundry-demo-recorder/bin/python recording/record_prompt_video.py production
~/.cache/foundry-demo-recorder/bin/python recording/record_prompt_video.py render
```

### Concept beats and the desktop review

- `diagram_delivery_path.py` draws the delivery path diagram that the main video shows before each step. It needs BigHub's diagram library (`bhdg`) and its icons on `PYTHONPATH`; render the SVG to PNG at scale 3 into `DIAGRAM_DIR` (default `~/.cache/foundry-demo-recorder/diagram`). `boxes.json` holds the boxes each step highlights.
- `diagram_beats.py` turns the diagram into a beat: the step highlighted, the rest dimmed, the camera easing in.
- `window_capture.py` records the local review in the Claude app. Run it from a terminal of the Claude app after granting it Screen Recording permission; a person does the review in a new session. `annotations/m1-desktop-review.json` adds the captions, the camera, the click on Not now and a mask over a folder name.

