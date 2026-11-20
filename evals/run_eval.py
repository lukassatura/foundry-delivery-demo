"""Run every evaluation case through the agent with the model, grade the answers and enforce the thresholds.

The exit code is 1 when a metric is below its threshold, so a failed evaluation fails the pipeline.
"""

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))

from analysis import Analysis, analyse  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parent
MAX_REASON_WORDS = 25


def grade_detection(case: dict, result: Analysis) -> list[str]:
    expect = case["expect"]
    if expect.get("error"):
        return [] if result.error else ["expected an input error, got an answer"]
    if result.error:
        return [f"unexpected input error: {result.error}"]
    flagged = [d.item for d in result.deviations]
    if sorted(flagged) != sorted(expect["flagged"]):
        return [f"flagged {flagged or 'nothing'}, expected {expect['flagged'] or 'nothing'}"]
    return []


def grade_reasons(case: dict, result: Analysis) -> tuple[int, list[str]]:
    """Return the number of checked statements and the problems found."""
    expect = case["expect"]
    if expect.get("error") or result.error or not result.explanation:
        return 0, []
    explanation = result.explanation
    problems = []
    statements = [("summary", explanation.summary)]
    statements += [(d.item, explanation.reasons.get(d.item, "")) for d in result.deviations]
    for name, text in statements:
        words = len(text.split())
        if not 0 < words <= MAX_REASON_WORDS:
            problems.append(f"{name}: {words} words")
    flagged = {d.item for d in result.deviations}
    for item, keywords in expect.get("reason_keywords", {}).items():
        reason = explanation.reasons.get(item, "").lower()
        if item in flagged and not any(k in reason for k in keywords):
            problems.append(f"{item}: reason does not use the note ({' / '.join(keywords)})")
    for item in expect.get("no_note", []):
        if item in flagged and "no explanation" not in explanation.reasons.get(item, "").lower():
            problems.append(f"{item}: reason should say that no explanation is given")
    for phrase in expect.get("summary_must_not_contain", []):
        if phrase.lower() in explanation.summary.lower():
            problems.append(f"summary contains '{phrase}'")
    return len(statements), problems


def main() -> int:
    cases = json.loads((EVAL_DIR / "cases.json").read_text())
    thresholds = json.loads((EVAL_DIR / "thresholds.json").read_text())

    detection_passed = reason_checked = reason_failed = tokens_in = tokens_out = 0
    rows = []
    started = time.monotonic()
    for case in cases:
        result = analyse("\n".join(case["input"]))
        detection = grade_detection(case, result)
        checked, reason_problems = grade_reasons(case, result)
        detection_passed += not detection
        reason_checked += checked
        reason_failed += len(reason_problems)
        if result.explanation:
            tokens_in += result.explanation.input_tokens
            tokens_out += result.explanation.output_tokens
        status = "PASS" if not detection and not reason_problems else "FAIL"
        rows.append((case["id"], status, "; ".join(detection + reason_problems)))
        print(f"{status}  {case['id']:<38} {'; '.join(detection + reason_problems)}", flush=True)

    metrics = {
        "detection_accuracy": detection_passed / len(cases),
        "reason_quality": 1 - reason_failed / reason_checked if reason_checked else 1.0,
    }
    failed = [name for name, value in metrics.items() if value < thresholds[name]]

    print()
    for name, value in metrics.items():
        verdict = "below threshold" if name in failed else "ok"
        print(f"{name}: {value:.0%} (threshold {thresholds[name]:.0%}) {verdict}")
    print(f"cases: {len(cases)}, model tokens: {tokens_in} in / {tokens_out} out, {time.monotonic() - started:.0f} s")
    print("EVALUATION FAILED" if failed else "EVALUATION PASSED")

    write_summary(rows, metrics, thresholds, failed, tokens_in, tokens_out)
    Path("eval-results.json").write_text(json.dumps({"metrics": metrics, "cases": rows}, indent=2))
    return 1 if failed else 0


def write_summary(rows, metrics, thresholds, failed, tokens_in, tokens_out) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    lines = ["## Evaluation", "", "| Case | Result | Problems |", "|---|---|---|"]
    lines += [f"| {case_id} | {status} | {problems} |" for case_id, status, problems in rows]
    lines += ["", "| Metric | Value | Threshold |", "|---|---|---|"]
    lines += [f"| {name} | {value:.0%} | {thresholds[name]:.0%} |" for name, value in metrics.items()]
    lines += ["", f"Model tokens: {tokens_in} in / {tokens_out} out.", ""]
    lines += ["**Evaluation failed.**" if failed else "**Evaluation passed.**"]
    with open(path, "a") as summary:
        summary.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    sys.exit(main())
