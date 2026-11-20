"""Compare two short CSV reports and find the items that moved by at least a threshold."""

import csv
import io
import re
from dataclasses import dataclass

DEFAULT_THRESHOLD_PCT = 10.0


class InputError(ValueError):
    """The request cannot be read. The message tells the user what to fix."""


@dataclass(frozen=True)
class ReportRow:
    amount: float
    note: str


@dataclass(frozen=True)
class Request:
    threshold_pct: float
    baseline: dict[str, ReportRow]
    current: dict[str, ReportRow]


@dataclass(frozen=True)
class Deviation:
    item: str
    baseline: float
    current: float
    change_pct: float
    note: str


_SECTION = re.compile(r"^\s*(baseline|current)\b[^:\n]*:?\s*$", re.IGNORECASE)
_THRESHOLD = re.compile(r"^\s*threshold\b\D*(-?\d+(?:\.\d+)?)\s*%?\s*$", re.IGNORECASE)


def parse_request(text: str) -> Request:
    """Read a request with an optional threshold line, a baseline report and a current report.

    Each report is CSV with the columns item and amount. The current report can have a note column.
    """
    threshold_pct = DEFAULT_THRESHOLD_PCT
    sections: dict[str, list[str]] = {}
    section = None
    for line in text.splitlines():
        if match := _THRESHOLD.match(line):
            threshold_pct = float(match.group(1))
            continue
        if match := _SECTION.match(line):
            section = match.group(1).lower()
            sections[section] = []
            continue
        if section and line.strip():
            sections[section].append(line)

    if threshold_pct <= 0:
        raise InputError("The threshold must be greater than 0%.")
    for name in ("baseline", "current"):
        if name not in sections:
            raise InputError(f"The {name} report is missing. Start it with a line '{name.capitalize()}:'.")
    return Request(
        threshold_pct=threshold_pct,
        baseline=parse_report("baseline", sections["baseline"]),
        current=parse_report("current", sections["current"]),
    )


def parse_report(name: str, lines: list[str]) -> dict[str, ReportRow]:
    reader = csv.DictReader(io.StringIO("\n".join(lines)))
    columns = {c.strip().lower() for c in reader.fieldnames or []}
    if not {"item", "amount"} <= columns:
        raise InputError(f"The {name} report needs the columns item and amount.")

    rows: dict[str, ReportRow] = {}
    for raw in reader:
        row = {k.strip().lower(): (v or "").strip() for k, v in raw.items() if k}
        item = row["item"]
        try:
            amount = float(row["amount"].replace(" ", ""))
        except ValueError:
            raise InputError(f"The amount of '{item}' in the {name} report is not a number.") from None
        rows[item] = ReportRow(amount=amount, note=row.get("note", ""))
    return rows


def change_pct(baseline: float, current: float) -> float:
    if baseline == 0:
        return 0.0 if current == 0 else float("inf")
    return (current - baseline) * 100 / abs(baseline)


def find_deviations(request: Request) -> list[Deviation]:
    """Return the items in both reports whose amount changed by the threshold or more.

    The threshold is inclusive: a change of exactly the threshold is a deviation.
    """
    deviations = []
    for item, base in request.baseline.items():
        if item not in request.current:
            continue
        cur = request.current[item]
        change = change_pct(base.amount, cur.amount)
        if abs(change) >= request.threshold_pct:
            deviations.append(Deviation(item, base.amount, cur.amount, change, cur.note))
    return sorted(deviations, key=lambda d: -abs(d.change_pct))
