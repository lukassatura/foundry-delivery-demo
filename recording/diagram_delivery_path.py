"""The delivery path diagram that the main video shows before each step, with that step highlighted.

Usage: python diagram_delivery_path.py OUT_DIR   (writes delivery-path.drawio, .svg and boxes.json)

It uses BigHub's diagram library (bhdg) and its icons, so the figure looks like the strategy's
figures. Put the library's folder on PYTHONPATH and run the script with its dependencies (Pillow,
cairosvg); render the SVG to PNG with the library's render_png.py. boxes.json holds, per video
step, the boxes to highlight, in diagram units.
"""
import json
import sys
from pathlib import Path

from bhdg import ACCENT, G50, STYLES, TINT, Diagram, measure

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
LINE = 1.3
AF = "ai_machine_learning/"

d = Diagram("delivery-path", 1256, 476)
d.text(16, 12, [("Two gates stand between a change and production", "title"),
                ("GitHub requires both gates on every pull request; the local review is a practice", "note")])

laptop = d.group(16, 64, 216, 400, "Developer laptop", fill=G50)
claude = d.node(124, 150, "local:claude", [("Claude Code", "name"), ("in the Claude app", "sub"),
                                           ("local review first", "sub")], size=40)
d.text(124, 330, [("Practice, not a gate:", "cap"), ("a shared review skill", "note"),
                  ("supports the local review", "note")], align="center")

gh = d.group(252, 64, 664, 400, "GitHub organisation", icon="local:github", fill=G50)
d.node(322, 150, "general/TFS_VC_Repository.svg", [("Repository", "name"), ("from the template", "sub")], size=40)
pr = d.node(456, 150, "general/Branch.svg", [("Pull request", "name"), ("the proposed change", "sub")], size=40)

gate1 = d.group(522, 104, 212, 196, "Gate 1 · automated", fill=TINT, stroke=ACCENT, sw=1.75, title_style="acc")
d.node(580, 150, "local:claude", [("Code Review", "name"), ("REVIEW.md rubric", "sub")], size=40)
d.node(680, 150, "general/Load_Test.svg", [("Checks", "name"), ("unit tests", "sub")], size=40)
d.text(628, 242, [("required on every pull request;", "acc"), ("merge blocked while an", "note"),
                  ("Important finding is open", "note")], align="center")

gate2 = d.group(750, 104, 150, 196, "Gate 2 · approval", fill=TINT, stroke=ACCENT, sw=1.75, title_style="acc")
d.node(825, 150, "identity/Users.svg", [("Named approver", "name"), ("in CODEOWNERS", "sub")], size=40)

main = d.node(656, 340, "general/Commit.svg", [("main, protected", "name"), ("ruleset blocks the merge", "sub"),
                                              ("until both gates pass", "acc")], size=40)
deploy = d.node(828, 340, "local:github", [("Deploy workflow", "name"), ("tests, then evaluation", "sub"),
                                           ("from main only", "sub"), ("service identity", "acc")], size=40)

foundry = d.group(940, 64, 300, 400, "Microsoft Foundry", fill=G50)
version = d.node(1090, 120, AF + "Foundry_Project.svg", [("New version", "name"), ("of the hosted agent,", "sub"),
                                                         ("tested in its own session", "sub")], size=40)
active = d.node(1090, 300, "general/Versions.svg", [("Active version", "name"), ("serves all traffic;", "sub"),
                                                    ("a rollback switches back", "acc")], size=40)

d.edge([(146, 170), (300, 170)], both=True)
d.edge([(344, 170), (434, 170)])
d.edge([(478, 170), (558, 170)])
d.edge([(702, 170), (803, 170)])
d.edge([(825, 300), (825, 316), (656, 316), (656, 338)])
d.edge([(678, 360), (806, 360)])
d.edge([(850, 360), (1000, 360), (1000, 140), (1068, 140)])
d.edge([(1090, 228), (1090, 298)])
d.edge([(556, 300), (556, 310), (124, 310), (124, 252)], dashed=True)
d.text(356, 292, [("findings or failures: fix and push", "note")], align="center")

d.badge(146, 150, 1)
d.badge(478, 150, 2)
d.badge(750, 104, 3)
d.badge(678, 340, 4)
d.badge(1112, 120, 5)
d.badge(1112, 300, 6)


def node_box(c, pad=10):
    width = max([c["w"]] + [measure(t, s) for t, s in c["lines"]])
    height = c["h"] + 3 + sum(STYLES[s][0] * LINE for _, s in c["lines"])
    cx = c["x"] + c["w"] / 2
    return [cx - width / 2 - pad, c["y"] - pad, width + 2 * pad, height + 2 * pad]


def group_box(c, pad=4):
    return [c["x"] - pad, c["y"] - pad, c["w"] + 2 * pad, c["h"] + 2 * pad]


def union(*boxes):
    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    x1 = max(b[0] + b[2] for b in boxes)
    y1 = max(b[1] + b[3] for b in boxes)
    return [x0, y0, x1 - x0, y1 - y0]


boxes = {
    "1": [group_box(laptop)],
    "2": [union(node_box(pr), group_box(gate1))],
    "3": [group_box(gate2), [250, 284, 312, 26]],
    "4": [union(node_box(main), node_box(deploy))],
    "5": [node_box(version)],
    "6": [node_box(active)],
}
OUT.mkdir(parents=True, exist_ok=True)
d.save(str(OUT))
(OUT / "boxes.json").write_text(json.dumps({"size": [d.W, d.H], "steps": boxes}, indent=1))
print("ok", OUT / "delivery-path.svg")
