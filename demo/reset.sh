#!/usr/bin/env bash
# Put the demo back to its starting state. Run it as the repository owner, outside the demo,
# with az signed in to the demo subscription.
#  - main returns to the tag demo-start, and the pipeline runs on it, so production serves that code;
#  - the feature branch returns to the tag demo-feature, the commit with the planted flaw;
#  - open pull requests from demo branches are closed;
#  - the prompt agent in the dev project gets a new version with the instructions from main.
set -euo pipefail
cd "$(dirname "$0")/.."
source infra/demo.env
repo="$GITHUB_REPO"
ruleset_id=$(gh api "repos/$repo/rulesets" --jq '.[] | select(.name == "main-delivery-gate") | .id')

for pr in $(gh pr list -R "$repo" --state open --json number,headRefName \
    --jq '.[] | select(.headRefName | test("^(feature|prompt-agent)/")) | .number'); do
  gh pr close "$pr" -R "$repo" --comment "Closed by the demo reset."
done

echo "Lifting the ruleset for the reset ..."
gh api -X PUT "repos/$repo/rulesets/$ruleset_id" -f enforcement=disabled --silent
trap 'gh api -X PUT "repos/$repo/rulesets/$ruleset_id" -f enforcement=active --silent; echo "Ruleset active again."' EXIT

git fetch -q origin --tags
git push -q --force origin demo-start:refs/heads/main
git push -q --force origin demo-feature:refs/heads/feature/report-missing-items
git push -q origin --delete prompt-agent/deviation-note-writer 2>/dev/null || true

export FOUNDRY_DEV_PROJECT_ENDPOINT="https://${ACCOUNT_NAME}.services.ai.azure.com/api/projects/${DEV_PROJECT}"
export PROMPT_AGENT_JSON="$(git show demo-start:prompt-agents/deviation-note-writer.json)"
.venv/bin/python - <<'PY'
import json, os, time
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import PromptAgentDefinition
from azure.core.exceptions import ServiceRequestError
from azure.identity import DefaultAzureCredential
d = json.loads(os.environ["PROMPT_AGENT_JSON"])
project = AIProjectClient(endpoint=os.environ["FOUNDRY_DEV_PROJECT_ENDPOINT"], credential=DefaultAzureCredential())
for attempt in range(4):  # a dropped connection should not stop the reset
    try:
        v = project.agents.create_version(agent_name=d["name"], definition=PromptAgentDefinition(model=d["model"], instructions=d["instructions"]), description="Demo reset")
        break
    except ServiceRequestError:
        if attempt == 3:
            raise
        time.sleep(5)
print(f"Dev prompt agent reset to the instructions in main (dev version {v.version}).")
PY

# GitHub does not start a workflow for a forced push, so start the pipeline explicitly. It deploys
# the code of demo-start, or nothing when production already runs it.
gh workflow run deliver.yml -R "$repo" --ref main
echo "Started 'Deliver agent' on main. It routes production back to the code of demo-start."
