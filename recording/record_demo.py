"""Run the demo for real and record it, one phase at a time.

  python recording/record_demo.py change      # 1 and 2: the local review, then the pull request in GitHub
  python recording/record_demo.py review      # 2: Claude Code Review blocks the merge
  python recording/record_demo.py fix         # 3: the fix, the passing gate and the approval, then the merge
  python recording/record_demo.py approve     # 3 again from the passing gate, when the fix is already pushed
  python recording/record_demo.py pipeline    # 4 and 5: tests, evaluation and deploy
  python recording/record_demo.py result      # 6: the new version answers in Foundry, then the rollback
  python recording/record_demo.py fallback    # a failing evaluation on the branch with the planted flaw
  python recording/record_demo.py render      # title cards and the final MP4 files

Each phase waits for the real event it shows (a review, a pipeline run) before it records it.
The phases share state in recording/out/state.json.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from recorder import SCALE, VIEWPORT, Recorder, render, title_card  # noqa: E402
from terminal import TerminalView  # noqa: E402
import foundry  # noqa: E402

REPO = os.environ.get("DEMO_REPO", "lukassatura/foundry-delivery-demo")
FEATURE_BRANCH = "feature/report-missing-items"
OUT = Path(__file__).resolve().parent / "out"
STATE = OUT / "state.json"
PROFILES = Path.home() / ".cache/foundry-demo-recorder/profiles"
DEVBOX = Path(os.environ.get("DEMO_DEVBOX", str(Path.home() / ".cache/foundry-demo-recorder/devbox")))
CLONE = DEVBOX / "foundry-delivery-demo"
COMMIT_EMAIL = os.environ.get("DEMO_COMMIT_EMAIL", "49922924+lukassatura@users.noreply.github.com")
REVIEW_TOOLS = '--allowedTools "Bash(git diff:*)" "Bash(git log:*)" Read Grep Glob'
FIX_TOOLS = '--allowedTools Read Edit Grep Glob "Bash(git diff:*)" "Bash(python -m pytest:*)" "Bash(.venv/bin/python -m pytest:*)"'
GITHUB_HIDE_CSS = """
  .AppHeader-globalBar-end .AppHeader-user, .Header-item--full ~ .Header-item img.avatar { visibility: hidden !important; }
  .js-notification-shelf, .flash-full, [data-target="feature-callout.callout"] { display: none !important; }
"""


# State and shell helpers -----------------------------------------------------------------


def load_state() -> dict:
    return json.loads(STATE.read_text()) if STATE.exists() else {}


def save_state(**values) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({**load_state(), **values}, indent=2))


def sh(command: str, cwd: Path | None = None) -> str:
    return subprocess.run(command, shell=True, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def gh_json(path: str) -> dict | list:
    return json.loads(sh(f"gh api {path}"))


def wait_for(description: str, check, timeout_s: int = 3600, every_s: int = 15):
    print(f"Waiting for {description} ...", flush=True)
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(every_s)
    raise TimeoutError(description)


def claude_check(sha: str) -> dict | None:
    """Return the newest finished review on this commit, ignoring reviews that did not run."""
    runs = gh_json(f"'repos/{REPO}/commits/{sha}/check-runs?check_name=Claude%20Code%20Review'")["check_runs"]
    runs = [r for r in runs if r["app"]["slug"] == "claude"]
    if not runs:
        return None
    newest = max(runs, key=lambda r: r["started_at"] or "")
    title = (newest["output"]["title"] or "").lower()
    if newest["status"] != "completed" or any(w in title for w in ("declined", "skipped", "failed", "timed out")):
        return None
    return newest


def job_check(sha: str, name: str) -> dict | None:
    """Return the newest run of a check on this commit once it has finished."""
    runs = gh_json(f"'repos/{REPO}/commits/{sha}/check-runs?check_name={name}'")["check_runs"]
    if not runs:
        return None
    newest = max(runs, key=lambda r: r["started_at"] or "")
    return newest if newest["status"] == "completed" else None


def latest_run(workflow: str, branch: str = "main", after: str = "") -> dict | None:
    runs = gh_json(f"'repos/{REPO}/actions/workflows/{workflow}/runs?branch={branch}&per_page=5'")["workflow_runs"]
    runs = [r for r in runs if r["created_at"] > after]
    return runs[0] if runs else None


# Browser helpers ---------------------------------------------------------------------------


def open_profile(playwright, role: str):
    context = playwright.chromium.launch_persistent_context(
        PROFILES / role, channel="chromium", headless=True, viewport=VIEWPORT, device_scale_factor=SCALE,
        color_scheme="light",
    )
    page = context.pages[0] if context.pages else context.new_page()
    return context, page


def goto(page: Page, url: str) -> None:
    """Open a page and let it settle. GitHub pages keep live connections open, so they never go network-idle."""
    page.goto(url, wait_until="load")
    page.wait_for_timeout(2500)
    page.add_style_tag(content=GITHUB_HIDE_CSS)
    dismiss_popovers(page)


def scroll_to(page: Page, selector: str, offset: int = 120) -> None:
    page.evaluate(
        "([s, o]) => { const e = document.querySelector(s); if (e) window.scrollTo({top: e.getBoundingClientRect().top + window.scrollY - o, behavior: 'smooth'}); }",
        [selector, offset],
    )
    page.wait_for_timeout(1200)


def scroll_to_text(page: Page, text: str, offset: int = 120) -> None:
    """Scroll so that the first element with this text sits just below the sticky header."""
    page.evaluate(
        """([t, o]) => {
            const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
            while (walker.nextNode()) {
                const node = walker.currentNode;
                if (node.textContent.includes(t) && node.parentElement.offsetParent !== null) {
                    const top = node.parentElement.getBoundingClientRect().top + window.scrollY - o;
                    window.scrollTo({top, behavior: 'smooth'});
                    return;
                }
            }
        }""",
        [text, offset],
    )
    page.wait_for_timeout(1500)


def show_merge_box(page: Page) -> None:
    scroll_to_text(page, "Review required", offset=70) if page.get_by_text("Review required").count() else scroll_to_text(page, "Merging is blocked", offset=300)


def dismiss_popovers(page: Page) -> None:
    """Close GitHub's one-time feature tips, so they stay out of the recording."""
    for name in ("Dismiss", "Not now", "Got it"):
        button = page.get_by_role("button", name=name, exact=True)
        if button.count() and button.first.is_visible():
            button.first.click()
            page.wait_for_timeout(600)


def smooth_scroll(page: Page, pixels: int, steps: int = 20) -> None:
    for _ in range(steps):
        page.mouse.wheel(0, pixels / steps)
        page.wait_for_timeout(40)
    page.wait_for_timeout(600)


def terminal_page(playwright):
    browser = playwright.chromium.launch()
    context = browser.new_context(viewport=VIEWPORT, device_scale_factor=SCALE)
    return browser, context.new_page()


def prepare_devbox() -> None:
    """A clean clone of the repository on the feature branch, as on a developer's laptop."""
    if not CLONE.exists():
        DEVBOX.mkdir(parents=True, exist_ok=True)
        sh(f"git clone -q https://github.com/{REPO}.git", cwd=DEVBOX)
    sh(f"git fetch -q --force origin && git switch -q -C {FEATURE_BRANCH} origin/{FEATURE_BRANCH} && git branch -q -f main origin/main", cwd=CLONE)
    sh(f"git config user.name 'Lukáš Šatura' && git config user.email '{COMMIT_EMAIL}'", cwd=CLONE)
    if not (CLONE / ".venv").exists():
        sh("uv venv -q --python 3.13 .venv && uv pip install -q --python .venv/bin/python -r requirements-dev.txt", cwd=CLONE)


# Phases ------------------------------------------------------------------------------------


def phase_change(playwright) -> None:
    prepare_devbox()
    browser, page = terminal_page(playwright)
    term = TerminalView(page, cwd=str(CLONE), title="foundry-delivery-demo")
    rec = Recorder(OUT)
    rec.say("A developer changed the agent with Claude Code and runs the team's review skill", step="1  Change")
    rec.start(page, "01-change")
    rec.fast(12)
    term.run(f'claude -p "/review-change" {REVIEW_TOOLS}', shown='claude -p "/review-change"')
    rec.normal()
    rec.say("The local review flags a problem. It is advice only: nothing stops the push")
    rec.hold(5)
    rec.stop()
    browser.close()

    context, page = open_profile(playwright, "developer")
    goto(page, f"https://github.com/{REPO}/compare/main...{FEATURE_BRANCH}?expand=1")
    rec.say("The developer opens a pull request", step="2  Pull request")
    rec.start(page, "02a-open")
    rec.hold(2.5)
    page.get_by_role("button", name="Create pull request").last.click()
    page.wait_for_url("**/pull/*", timeout=30000)
    page.wait_for_timeout(8000)
    pr_url = page.url.split("#")[0].split("?")[0]
    goto(page, pr_url)
    rec.say("Claude Code Review and the unit tests start on every push")
    show_merge_box(page)
    rec.hold(4)
    rec.stop()
    context.close()
    save_state(pr_url=pr_url, pr_number=int(pr_url.rstrip("/").split("/")[-1]))
    print(f"Pull request: {pr_url}")


def phase_review(playwright) -> None:
    state = load_state()
    pr = state["pr_number"]
    head = gh_json(f"repos/{REPO}/pulls/{pr}")["head"]["sha"]
    context, page = open_profile(playwright, "developer")
    rec = Recorder(OUT)
    rec.step = "2  Pull request"
    wait_for("Claude Code Review", lambda: claude_check(head))
    wait_for("the review gate", lambda: job_check(head, "review-gate"), timeout_s=600)
    goto(page, f"https://github.com/{REPO}/pull/{pr}")
    rec.say("Claude finds a real defect: a change of exactly 10% is no longer reported")
    rec.start(page, "02b-finding")
    scroll_to_text(page, "(Important)", offset=200)
    rec.hold(8)
    rec.say("The review gate fails and the ruleset blocks the merge")
    show_merge_box(page)
    rec.hold(5)
    rec.stop()
    context.close()
    save_state(first_head=head)


def phase_fix(playwright) -> None:
    """The developer fixes the finding with Claude Code and pushes. The recording shows the commit in GitHub."""
    prompt = ("Fix the Important finding from the code review on this branch, and add a unit test "
              "for a change of exactly the threshold. Keep the change small.")
    print(sh(f'claude -p "{prompt}" {FIX_TOOLS}', cwd=CLONE)[-600:])
    print(sh(".venv/bin/python -m pytest -q", cwd=CLONE).splitlines()[-1])
    sh('git commit -qam "Report a change of exactly the threshold" && git push -q origin HEAD', cwd=CLONE)
    phase_approve(playwright)


def phase_approve(playwright) -> None:
    pr = load_state()["pr_number"]
    rec = Recorder(OUT)
    rec.step = "3  Fix and approval"
    head = gh_json(f"repos/{REPO}/pulls/{pr}")["head"]["sha"]
    wait_for("the new Claude Code Review", lambda: claude_check(head))
    gate = wait_for("the review gate", lambda: job_check(head, "review-gate"), timeout_s=600)
    print(f"review-gate: {gate['conclusion']}")

    context, page = open_profile(playwright, "developer")
    goto(page, f"https://github.com/{REPO}/pull/{pr}/commits/{head}")
    rec.say("The developer fixes it with Claude Code: >= instead of >, and a boundary test")
    rec.start(page, "03a-fix")
    rec.hold(4)
    smooth_scroll(page, 450)
    rec.hold(4)
    rec.stop()

    goto(page, f"https://github.com/{REPO}/pull/{pr}")
    rec.say("Claude reviews the new push and the gate passes. The finding is resolved")
    rec.start(page, "03b-resolve")
    scroll_to_text(page, "(Important)", offset=200)
    rec.hold(2)
    resolve = page.get_by_role("button", name="Resolve conversation").first
    if resolve.count():
        resolve.click()
        rec.hold(1.5)
    show_merge_box(page)
    rec.say("Still blocked: the approver named in CODEOWNERS must approve")
    rec.hold(3.5)
    rec.stop()

    approver, apage = open_profile(playwright, "approver")
    goto(apage, f"https://github.com/{REPO}/pull/{pr}/files")
    rec.say("The approver reviews the change and approves it")
    rec.start(apage, "03c-approve")
    rec.hold(2)
    dismiss_popovers(apage)
    apage.get_by_role("button", name="Submit review").first.click()
    apage.wait_for_timeout(1200)
    apage.locator("input[type=radio][value=approve]").check()
    apage.wait_for_timeout(1200)
    dialog = apage.get_by_role("dialog")
    (dialog if dialog.count() else apage).get_by_role("button", name="Submit review").last.click()
    apage.wait_for_timeout(2500)
    rec.hold(2)
    rec.stop()
    approver.close()

    goto(page, f"https://github.com/{REPO}/pull/{pr}")
    rec.say("All gates pass. The developer merges", step="4  Merge and pipeline")
    rec.start(page, "03d-merge")
    scroll_to_text(page, "Squash and merge", offset=400)
    rec.hold(2)
    page.get_by_role("button", name="Squash and merge").first.click()
    page.wait_for_timeout(1000)
    page.get_by_role("button", name="Confirm squash and merge").first.click()
    page.wait_for_timeout(3000)
    rec.stop()
    context.close()
    save_state(merged_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 120)))


def phase_pipeline(playwright) -> None:
    state = load_state()
    run = wait_for("the Deliver agent run", lambda: latest_run("deliver.yml", after=state["merged_at"]), every_s=5)
    run_url = run["html_url"]
    context, page = open_profile(playwright, "developer")
    goto(page, run_url)
    rec = Recorder(OUT)
    rec.say("The merge starts the pipeline: unit tests, then the evaluation set", step="4  Merge and pipeline")
    rec.start(page, "04a-run")
    rec.hold(5)
    rec.stop()

    wait_for("the evaluation job", lambda: job_done(run["id"], "evaluation"))
    open_job_step(page, run["id"], "evaluation", "Run the evaluation set against the model")
    rec.say("Every case runs through the agent with the model. The grader checks the thresholds")
    rec.start(page, "04b-evaluation")
    smooth_scroll(page, 500)
    rec.hold(8)
    rec.stop()

    wait_for("the deploy job", lambda: job_done(run["id"], "deploy"), timeout_s=1800)
    open_job_step(page, run["id"], "deploy", "Deploy a new version of the hosted agent")
    rec.say("Only this job deploys: from main, with a federated identity, no stored secret", step="5  Deploy")
    rec.start(page, "05-deploy")
    rec.hold(3)
    rec.say("It tests the new version in its own session, then switches all traffic")
    smooth_scroll(page, 700)
    rec.hold(7)
    rec.stop()
    context.close()
    save_state(deliver_run=run_url)

    context, page = foundry.open_portal(playwright, PROFILES)
    foundry.open_agent(page)
    foundry.show_details(page)
    rec.say("In Microsoft Foundry, the version from the pipeline is now the active version")
    rec.start(page, "05b-foundry")
    rec.hold(6)
    rec.stop()
    context.close()


def job_done(run_id: int, name: str) -> dict | None:
    jobs = gh_json(f"repos/{REPO}/actions/runs/{run_id}/jobs")["jobs"]
    job = next((j for j in jobs if j["name"] == name), None)
    return job if job and job["status"] == "completed" else None


def open_job_step(page: Page, run_id: int, job_name: str, step_name: str) -> None:
    job = job_done(run_id, job_name)
    goto(page, f"https://github.com/{REPO}/actions/runs/{run_id}/job/{job['id']}")
    step = page.get_by_text(step_name, exact=False).first
    step.click()
    page.wait_for_timeout(2500)
    step.scroll_into_view_if_needed()


def phase_result(playwright) -> None:
    sample = (Path(__file__).resolve().parent.parent / "samples/two-reports.txt").read_text()
    rec = Recorder(OUT)
    context, page = foundry.open_portal(playwright, PROFILES)
    foundry.open_agent(page)
    foundry.show_playground(page)
    rec.say("The new version answers in the Foundry playground", step="6  Result and rollback")
    rec.start(page, "06a-answer")
    rec.fast(6)
    foundry.ask_in_playground(page, sample)
    rec.normal()
    rec.say("It now reports new and missing items. The log stream is the hosted container")
    rec.hold(7)
    rec.stop()
    context.close()

    context, page = open_profile(playwright, "developer")
    goto(page, f"https://github.com/{REPO}/actions/workflows/rollback.yml")
    rec.say("A rollback is one pipeline run, started in GitHub")
    rec.start(page, "06b-rollback")
    rec.hold(2)
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 5))
    run_workflow_from_ui(page, "rollback.yml")
    rec.hold(2)
    rec.stop()
    run = wait_for("the rollback run", lambda: latest_run("rollback.yml", after=started), every_s=5)
    wait_for("the rollback job", lambda: job_done(run["id"], "rollback"), timeout_s=900)
    goto(page, run["html_url"])
    rec.say("The pipeline routes all traffic back to the version that served before")
    rec.start(page, "06c-rollback-done")
    scroll_to_text(page, "Rollback", offset=90)
    rec.hold(6)
    rec.stop()
    context.close()

    context, page = foundry.open_portal(playwright, PROFILES)
    foundry.open_agent(page)
    foundry.show_details(page)
    rec.say("Foundry shows the previous version as active. The new one stays available")
    rec.start(page, "06d-foundry")
    rec.hold(6)
    rec.stop()
    context.close()


def run_workflow_from_ui(page: Page, workflow_file: str, branch: str = "main") -> None:
    """Start a workflow with the Run workflow button on its Actions page."""
    goto(page, f"https://github.com/{REPO}/actions/workflows/{workflow_file}")
    page.get_by_role("button", name="Run workflow").first.click()
    page.wait_for_timeout(1500)
    dialog = page.get_by_role("dialog").last
    if branch != "main":
        dialog.locator("button", has_text="main").first.click()
        page.wait_for_timeout(800)
        page.get_by_placeholder("Find a branch...").fill(branch)
        page.wait_for_timeout(800)
        page.get_by_role("menuitemradio", name=branch).first.click()
        page.wait_for_timeout(1000)
    dialog.locator("button[type=submit]", has_text="Run workflow").click()
    page.wait_for_timeout(4000)


def phase_fallback(playwright) -> None:
    context, page = open_profile(playwright, "developer")
    rec = Recorder(OUT)
    rec.say("What if a flaw got past the review? Run the pipeline on the flawed branch", step="Fallback")
    goto(page, f"https://github.com/{REPO}/actions/workflows/deliver.yml")
    rec.start(page, "f1-start")
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 5))
    run_workflow_from_ui(page, "deliver.yml", FEATURE_BRANCH)
    rec.hold(3)
    rec.stop()

    run = wait_for("the fallback run", lambda: latest_run("deliver.yml", branch=FEATURE_BRANCH, after=started), every_s=5)
    wait_for("the fallback run to finish", lambda: gh_json(f"repos/{REPO}/actions/runs/{run['id']}")["status"] == "completed")
    goto(page, run["html_url"])
    rec.say("The unit tests pass. The evaluation fails, so nothing is deployed")
    rec.start(page, "f2-run")
    rec.hold(5)
    scroll_to_text(page, "Evaluation", offset=80)
    rec.say("Two boundary cases fail: detection accuracy is below its threshold")
    rec.hold(4)
    smooth_scroll(page, 260)
    rec.hold(5)
    rec.stop()
    context.close()


def phase_render(_playwright) -> None:
    title_card(OUT, "00-title", ["A delivery path for AI agents", "Claude Code · GitHub · Microsoft Foundry · synthetic data"], 4)
    title_card(OUT, "99-end", ["No change reaches production without", "Claude's code review, a named approver and a passing evaluation. Only the pipeline deploys."], 5)
    title_card(OUT, "f0-title", ["Fallback: a failing evaluation", "The same pipeline on the branch with the planted flaw"], 3)
    main = ["00-title", "01-change", "02a-open", "02b-finding", "03a-fix", "03b-resolve", "03c-approve", "03d-merge",
            "04a-run", "04b-evaluation", "05-deploy", "05b-foundry", "06a-answer", "06b-rollback", "06c-rollback-done",
            "06d-foundry", "99-end"]
    fallback = ["f0-title", "f1-start", "f2-run"]
    for name, clips in (("delivery-demo.mp4", main), ("delivery-demo-failing-evaluation.mp4", fallback)):
        present = [c for c in clips if (OUT / c / "clip.json").exists()]
        print(f"{name}: {render(OUT, present, OUT / name)}")


PHASES = {
    "change": phase_change, "review": phase_review, "fix": phase_fix, "approve": phase_approve, "pipeline": phase_pipeline,
    "result": phase_result, "fallback": phase_fallback, "render": phase_render,
}

if __name__ == "__main__":
    with sync_playwright() as pw:
        PHASES[sys.argv[1]](pw)
