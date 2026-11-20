"""Move a Foundry prompt agent from the dev project to production through Git.

  python deploy/prompt_agent.py export NAME   # read the newest version in dev, write prompt-agents/NAME.json
  python deploy/prompt_agent.py deploy NAME   # create a production version from prompt-agents/NAME.json

The export runs in a workflow that pushes a branch, so the change goes through a pull request
with the same review and approval as code. Only the deploy job on main writes to production.
"""

import json
import os
import sys
from pathlib import Path

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import PromptAgentDefinition
from azure.identity import DefaultAzureCredential
from foundry import write_summary

DEFINITIONS = Path(__file__).resolve().parent.parent / "prompt-agents"
SAMPLE_INPUT = "Deviations of 10% or more:\n- Travel: 1,000 -> 1,250 (+25.0%). Two customer workshops moved from the first quarter."


def client(variable: str) -> AIProjectClient:
    return AIProjectClient(endpoint=os.environ[variable], credential=DefaultAzureCredential())


def export(name: str) -> None:
    project = client("FOUNDRY_DEV_PROJECT_ENDPOINT")
    latest = project.agents.get(agent_name=name).as_dict()["versions"]["latest"]
    definition = latest["definition"]
    content = {
        "name": name,
        "source": {"project": "dev", "version": latest["version"]},
        "model": definition["model"],
        "instructions": definition["instructions"],
    }
    path = DEFINITIONS / f"{name}.json"
    path.write_text(json.dumps(content, indent=2) + "\n")
    print(f"Wrote {path.name} from dev version {latest['version']}.")


def deploy(name: str) -> None:
    content = json.loads((DEFINITIONS / f"{name}.json").read_text())
    project = client("FOUNDRY_PROJECT_ENDPOINT")
    created = project.agents.create_version(
        agent_name=name,
        definition=PromptAgentDefinition(model=content["model"], instructions=content["instructions"]),
        description=f"From dev version {content['source']['version']}, commit {os.environ.get('GITHUB_SHA', 'local')[:7]}",
    )
    answer = project.get_openai_client(agent_name=name).responses.create(input=SAMPLE_INPUT).output_text
    if not answer.strip():
        raise RuntimeError(f"Version {created.version} of {name} gave an empty answer.")
    print(f"Production version {created.version} of {name}.\n--- sample answer ---\n{answer}\n---")
    write_summary([f"## Prompt agent `{name}`", "", f"- Production version: **{created.version}**", "", "```", answer, "```"])


if __name__ == "__main__":
    command, agent_name = sys.argv[1], sys.argv[2]
    {"export": export, "deploy": deploy}[command](agent_name)
