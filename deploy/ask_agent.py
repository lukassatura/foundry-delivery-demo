"""Send the sample comparison, or the text of a file, to the hosted agent and print the answer.

Usage: python deploy/ask_agent.py [FILE]
"""

import sys
from pathlib import Path

from foundry import SMOKE_INPUT, ask_agent, project_client


def main() -> int:
    text = Path(sys.argv[1]).read_text() if len(sys.argv) > 1 else SMOKE_INPUT
    print(ask_agent(project_client(), text))
    return 0


if __name__ == "__main__":
    sys.exit(main())
