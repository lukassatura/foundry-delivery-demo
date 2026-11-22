"""Record the main delivery demo in BigHub style, with a cursor, zoom and slow typing.

  python recording/record_main_video.py foundry    # 5-6: the active version and the new version answering
  python recording/record_main_video.py rollback   # 6: the rollback, started in GitHub, and Foundry afterwards
  python recording/record_main_video.py summary    # 6 again: the summary of the newest rollback run (read only)
  python recording/record_main_video.py render

Steps 1-5 up to the deploy log are the footage of pull request #2, recorded with record_demo.py;
annotations/ adds the cursor and the zoom to it. Re-recording this video opens no pull request and
starts no Claude Code Review. Before the foundry phase, production must serve the version that
pull request #2 deployed (run "Roll back agent" with that version).
"""

import json
import os
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
import actions  # noqa: E402
import brand  # noqa: E402
import diagram_beats  # noqa: E402
import foundry  # noqa: E402
import studio  # noqa: E402
from record_demo import PROFILES, REPO, gh_json, goto, latest_run, wait_for  # noqa: E402
from recorder import Recorder  # noqa: E402

HERE = Path(__file__).resolve().parent
OUT = HERE / "out-main-v2"
OLD = HERE / "out"
SAMPLE = (HERE.parent / "samples/two-reports.txt").read_text().strip().splitlines()


def smallest_box_with(page: Page, texts: list[str]) -> list[float]:
    """The smallest visible element whose text contains all the given strings, in frame pixels."""
    box = page.evaluate(
        """texts => {
          let best = null;
          for (const e of document.querySelectorAll('body *')) {
            const t = e.innerText || '';
            if (!texts.every(x => t.includes(x))) continue;
            const r = e.getBoundingClientRect();
            if (r.width < 20 || r.height < 10) continue;
            if (!best || r.width * r.height < best.width * best.height) best = r;
          }
          return best ? [best.x, best.y, best.width, best.height] : null;
        }""",
        texts,
    )
    return [v * actions.SCALE for v in box] if box else None


def open_agent_page(playwright):
    context, page = foundry.open_portal(playwright, PROFILES, zoomed=True)
    foundry.open_agent(page)
    page.wait_for_timeout(2000)
    return context, page


def show_active_version(rec: Recorder, page: Page, caption: str) -> None:
    actions.click(rec, page, page.get_by_role("tab", name="Details").first)
    page.wait_for_timeout(2500)
    foundry.hide_personal(page)
    rec.say(caption)
    box = smallest_box_with(page, ["Active version", "Applies to all endpoints"])
    actions.focus(rec, actions.pad(box, 60, 40))
    rec.hold(4.5)


def phase_foundry(playwright) -> None:
    rec = Recorder(OUT)
    context, page = open_agent_page(playwright)
    rec.say("In Microsoft Foundry, the hosted agent's Details show which version serves traffic", step="5  Deploy")
    rec.start(page, "m5-foundry")
    rec.hold(2)
    show_active_version(rec, page, "Active version 4: the version the pipeline just deployed")
    actions.unfocus(rec)
    rec.hold(1)

    rec.say("Back to the playground to try the new version", step="6  Result")
    actions.click(rec, page, page.get_by_role("tab", name="Playground").first)
    page.wait_for_timeout(3000)
    setup = page.get_by_role("button", name="Collapse panel")
    if setup.count():
        setup.first.click()
        page.wait_for_timeout(1000)
    foundry.hide_personal(page)
    rec.say("Types two short CSV reports: a baseline and the current month")
    field = page.locator("[aria-label='Message the agent...'][contenteditable=true]").first
    actions.type_text(rec, page, field, SAMPLE, delay_ms=38, newline="Shift+Enter")
    rec.hold(1.0)
    rec.say("Sends them to the hosted agent")
    actions.click(rec, page, page.get_by_role("button", name="Send").first, zoom=None)
    rec.say("The hosted agent compares the reports and asks the model for the reasons")
    rec.fast(4)
    before = page.evaluate("() => document.body.innerText")
    for _ in range(60):
        page.wait_for_timeout(2000)
        if "Summary:" in page.evaluate("() => document.body.innerText")[len(before) - 200:]:
            break
    page.wait_for_timeout(3000)
    rec.normal()
    foundry.hide_personal(page)
    rec.say("Version 4 answers: it now also reports the new and the missing items")
    answer = smallest_box_with(page, ["Cloud hosting", "Printing", "Summary:"])
    if answer:
        actions.focus(rec, actions.pad(answer, 40, 30))
    rec.hold(8)
    rec.say("The log stream shows the hosted container at work")
    log = smallest_box_with(page, ["Compared reports"])
    if log:
        actions.focus(rec, [log[0] - 40, log[1] - 300, log[2] + 80, 700])
    rec.hold(5)
    actions.unfocus(rec)
    rec.hold(1)
    rec.stop()
    context.close()


def phase_rollback(playwright) -> None:
    rec = Recorder(OUT)
    context = actions.launch_profile(playwright, PROFILES / "developer")
    page = context.pages[0] if context.pages else context.new_page()
    goto(page, f"https://github.com/{REPO}/actions/workflows/rollback.yml")
    page.wait_for_timeout(1000)
    rec.say("If production misbehaves, a rollback is one pipeline run", step="6  Rollback")
    rec.start(page, "m6-rollback")
    rec.hold(1.5)
    actions.click(rec, page, page.get_by_role("button", name="Run workflow").first)
    page.wait_for_timeout(1500)
    rec.say("Runs Roll back agent on main, with no version: back to the version that served before")
    dialog = page.get_by_role("dialog").last
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 5))
    actions.click(rec, page, dialog.locator("button[type=submit]", has_text="Run workflow"), zoom=None)
    page.wait_for_timeout(3000)
    rec.stop()
    run = wait_for("the rollback run", lambda: latest_run("rollback.yml", after=started), every_s=5)
    wait_for("the rollback to finish",
             lambda: gh_json(f"repos/{REPO}/actions/runs/{run['id']}")["status"] == "completed", timeout_s=900)
    context.close()
    record_summary(playwright, rec, run["html_url"])

    context, page = open_agent_page(playwright)
    rec.say("Foundry shows version 1 as active again. Version 4 stays available", step="6  Rollback")
    rec.start(page, "m6-foundry")
    rec.hold(1)
    show_active_version(rec, page, "Foundry shows version 1 as active again. Version 4 stays available")
    actions.unfocus(rec)
    rec.hold(1)
    rec.stop()
    context.close()


def record_summary(playwright, rec: Recorder, run_url: str) -> None:
    """Show the rollback run's job summary. GitHub renders a summary only when it comes into view."""
    context = actions.launch_profile(playwright, PROFILES / "developer")
    page = context.pages[0] if context.pages else context.new_page()
    goto(page, run_url)
    page.wait_for_timeout(1500)
    rec.say("The pipeline routed all traffic from version 4 back to version 1", step="6  Rollback")
    rec.start(page, "m6-rollback-done")
    rec.hold(1.5)
    actions.scroll_to(page, page.locator("h2:visible").filter(has_text="rollback summary").first)
    page.wait_for_timeout(1500)
    heading = page.locator("h2:visible").filter(has_text=re.compile(r"^\s*Rollback\s*$")).first
    actions.scroll_to(page, heading, top_css=140)
    box = actions.rect(heading)
    actions.focus(rec, [box[0] - 60, box[1] - 40, max(box[2] + 120, 1200), box[3] + 380])
    rec.hold(6)
    rec.stop()
    context.close()


def phase_summary(playwright) -> None:
    """Record the summary of the newest rollback run again."""
    run = gh_json(f"'repos/{REPO}/actions/workflows/rollback.yml/runs?per_page=1'")["workflow_runs"][0]
    record_summary(playwright, Recorder(OUT), run["html_url"])


DIAGRAM = Path(os.environ.get("DIAGRAM_DIR", Path.home() / ".cache/foundry-demo-recorder/diagram"))
# What each step means, said on the delivery path diagram before the step's footage.
BEATS = {
    "0": ("", "The path every change takes, from a developer's laptop to production"),
    "1": ("1  Change", "The developer changes the agent and asks Claude for a local review first"),
    "2": ("2  Pull request", "A pull request proposes the change; Claude's review must pass to merge"),
    "3": ("3  Fix and approval", "The developer fixes the finding; the named approver approves the change"),
    "4": ("4  Merge and pipeline", "Merging starts the pipeline: unit tests, then an evaluation with the model"),
    "5": ("5  Deploy", "Only the pipeline deploys: a new version of the hosted agent in Foundry"),
    "6": ("6  Result and rollback", "The new version serves all traffic; a rollback switches back in one run"),
}


def beat(step: str, seconds: float = 6.0, caption: str | None = None, name: str | None = None) -> tuple:
    """A clip of the delivery path diagram with the step highlighted (see diagram_beats.py)."""
    meta = json.loads((DIAGRAM / "boxes.json").read_text())
    label, text = BEATS[step]
    frame, focus = diagram_beats.highlight_frame(DIAGRAM / "delivery-path.png", meta["steps"].get(step, []),
                                                 meta["size"], OUT / f"beat-{name or step}.png")
    folder = diagram_beats.beat_clip(OUT, f"beat-{name or step}", frame, focus, seconds, label, caption or text)
    return ("clip", folder)


def card(kind, title: str, subtitle: str) -> tuple:
    return ("card", kind(title, subtitle), brand.card_seconds(title, subtitle))


def phase_render(_playwright) -> None:
    review = OUT / "m1-desktop-review"
    parts = [
        card(brand.title_card, "A delivery path for AI agents",
             "Every change passes Claude's code review, a named approver and an evaluation. "
             "Only the pipeline deploys it to Microsoft Foundry."),
        beat("0", 6.5),
        beat("1"),
        # The local review in the Claude app: typing, the skill at work (4x), the finding, Not now.
        # The still frames of the results are held longer so that they can be read.
        ("clip", review, (239.0, 251.3, 1.0)),
        ("clip", review, (251.3, 281.2, 4.0)),
        ("clip", review, (281.2, 286.0, 1.0)),
        ("clip", review, (286.0, 301.1, 4.0)),
        ("clip", review, (301.1, 304.9, 0.4)),
        ("clip", review, (304.9, 306.5, 1.0)),
        ("clip", review, (306.5, 310.0, 0.55)),
        beat("2"),
        ("clip", OLD / "02a-open", (0.0, None, 1.6)),
        ("clip", OLD / "02b-finding"),
        beat("3"),
        ("clip", OLD / "03a-fix"),
        ("clip", OLD / "03b-resolve"),
        ("clip", OLD / "03c-approve"),
        ("clip", OLD / "03b-gate"),
        beat("4"),
        ("clip", OLD / "03d-merge"),
        ("clip", OLD / "04a-run"),
        ("clip", OLD / "04b-evaluation"),
        beat("5"),
        ("clip", OLD / "05-deploy"),
        ("clip", OUT / "m5-foundry", (0.0, 11.7, 1.0)),
        beat("6"),
        ("clip", OUT / "m5-foundry", (11.7, 18.1, 1.0)),
        ("clip", OUT / "m5-foundry", (18.1, 36.0, 2.0)),   # typing the two CSV reports
        ("clip", OUT / "m5-foundry", (36.0, None, 1.0)),
        ("clip", OUT / "m6-rollback"),
        ("clip", OUT / "m6-rollback-done"),
        ("clip", OUT / "m6-foundry"),
        card(brand.end_card, "No change reaches production unchecked",
             "Claude reviews it, a named person approves it and an evaluation tests it. "
             "Then the pipeline deploys, with no personal account and no stored secret."),
    ]
    studio.render_video(OUT / "delivery-demo.mp4", parts, annotations_dir=HERE / "annotations")

    studio.render_video(
        OUT / "delivery-demo-failing-evaluation.mp4",
        [
            card(brand.title_card, "A failing evaluation stops the deploy",
                 "The same pipeline, run on the branch with the planted flaw: the unit tests pass, the evaluation does not."),
            beat("4", 6.0, "If a flaw gets past the review, the evaluation in the pipeline still stops it", "f4"),
            ("clip", OLD / "f1-start"),
            ("clip", OLD / "f2-run"),
            card(brand.end_card, "A failed evaluation fails the pipeline",
                 "The evaluation catches both boundary cases, so the deploy job never runs."),
        ],
        annotations_dir=HERE / "annotations",
    )


PHASES = {"foundry": phase_foundry, "rollback": phase_rollback, "summary": phase_summary}

if __name__ == "__main__":
    if sys.argv[1] == "render":
        phase_render(None)
    else:
        with sync_playwright() as pw:
            PHASES[sys.argv[1]](pw)
