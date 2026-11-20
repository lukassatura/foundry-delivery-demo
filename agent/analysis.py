"""Run one comparison end to end and render the answer."""

import os
from dataclasses import dataclass

from reasons import Explanation, explain
from report_compare import Deviation, InputError, find_deviations, parse_request


@dataclass(frozen=True)
class Analysis:
    threshold_pct: float
    deviations: list[Deviation]
    explanation: Explanation | None
    error: str | None = None


def analyse(text: str) -> Analysis:
    try:
        request = parse_request(text)
    except InputError as error:
        return Analysis(threshold_pct=0, deviations=[], explanation=None, error=str(error))
    deviations = find_deviations(request)
    return Analysis(request.threshold_pct, deviations, explain(request, deviations))


def render(analysis: Analysis) -> str:
    version = os.environ.get("FOUNDRY_AGENT_VERSION", "local")
    if analysis.error:
        return f"Error: {analysis.error}\n(agent version {version})"

    threshold = f"{analysis.threshold_pct:g}%"
    if analysis.deviations:
        lines = [f"Deviations of {threshold} or more (agent version {version}):"]
        for d in analysis.deviations:
            reason = analysis.explanation.reasons.get(d.item, "No reason returned.")
            lines.append(f"- {d.item}: {_amount(d.baseline)} -> {_amount(d.current)} ({_change(d)}). {reason}")
    else:
        lines = [f"No deviations of {threshold} or more (agent version {version})."]
    lines.append(f"Summary: {analysis.explanation.summary}")
    return "\n".join(lines)


def _amount(value: float) -> str:
    return f"{value:,.0f}"


def _change(d: Deviation) -> str:
    if d.change_pct == float("inf"):
        return "new amount from zero"
    return f"{d.change_pct:+.1f}%"
