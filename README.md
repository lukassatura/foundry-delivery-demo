# Foundry delivery demo

This repository shows one rule of a delivery path for AI agents:

> A change to an agent cannot reach production without Claude's code review, a named approver and a passing evaluation. Only the pipeline deploys.

The agent is small on purpose. It compares two short CSV reports and lists the items that moved by a threshold or more, with a one-line reason each. It runs as a Microsoft Foundry hosted agent. All data in this repository is synthetic.

## What is in the repository

| Path | What it is |
|---|---|
| `agent/` | The hosted agent. `report_compare.py` finds the deviations without a model. `reasons.py` asks the model for the one-line reasons. `main.py` serves the Foundry Responses protocol. |
| `tests/` | Unit tests. They do not call the model. |
| `evals/` | The evaluation set (`cases.json`), the grader (`run_eval.py`) and its thresholds (`thresholds.json`). The grader runs every case through the agent with the model. |
| `deploy/` | Scripts that the pipeline runs: deploy a new version, roll back, ask the agent, and export or deploy a prompt agent. |
| `prompt-agents/` | The definition of the prompt agent `deviation-note-writer`, as it runs in production. |
| `.github/workflows/` | `pull-request.yml` (checks on every pull request), `deliver.yml` (test, evaluate, deploy), `rollback.yml`, `promote-prompt-agent.yml` and `deliver-prompt-agents.yml`. |
| `.claude/skills/review-change/` | The shared review skill. Developers run it locally; `REVIEW.md` gives the same rules to Claude Code Review. |
| `infra/` | Set-up and teardown scripts for Azure and GitHub, and the branch ruleset. |
| `demo/` | The reset script. |
| `samples/` | An input that shows the difference between the starting version and the new version. |
| `recording/` | The scripts that record the demo video. |

## How the path works

1. **Change.** A developer changes the agent with Claude Code and runs the `review-change` skill. The local review is a practice, not a gate.
2. **Pull request.** Claude Code Review reviews every push. Its check never fails on its own, so the `review-gate` job reads the review's severity counts and fails while an Important finding is open. The ruleset also blocks the merge until every review conversation is resolved.
3. **Approval.** The ruleset requires one approval from someone other than the last pusher. `CODEOWNERS` names the approver.
4. **Merge and pipeline.** `Deliver agent` runs the unit tests and then the evaluation set against the model. A metric below its threshold fails the job, like a failed test.
5. **Deploy.** The deploy job runs only for `main`, in the GitHub environment `production`. It signs in to Azure with a federated credential: no stored secret, no personal account. It creates a new version of the hosted agent, tests that version in its own session, and only then routes all traffic to it.
6. **Rollback.** `Roll back agent` routes all traffic back to an earlier version.
7. **Prompt agents.** A business owner edits a prompt agent in the dev project. `Promote prompt agent` exports the new dev version to a branch. The pull request goes through the same review and approval, and `Deliver prompt agents` creates the production version from the definition in Git.

The merge gate is the ruleset in `infra/ruleset.json`:

| Rule | Setting |
|---|---|
| Pull request | 1 approval, code owner review, approval of the last push, stale approvals dismissed, all conversations resolved, squash merge only |
| Required checks | `unit-tests`, `review-gate`, `Claude Code Review` |
| Branch | no force push, no deletion, no bypass |

## Set-up from zero

### Prerequisites

- Azure: Owner on a resource group in a region with hosted agents (this demo uses Sweden Central).
- GitHub: a repository where rulesets work. That is a public repository, or a private one on GitHub Pro, Team or Enterprise.
- Claude: a Team or Enterprise organisation with Code Review switched on and usage credits.
- A second GitHub account for the approver, with write access to the repository.
- Tools: `az` 2.80 or later, `gh`, `jq`, Python 3.13.

### 1. Create the repository and push

```bash
gh repo create OWNER/foundry-delivery-demo --public
git remote add origin https://github.com/OWNER/foundry-delivery-demo.git
```

Do not push yet. The first push to `main` deploys the agent, so Azure must be ready first.

### 2. Create the Azure resources and the GitHub settings

```bash
cp infra/demo.env.example infra/demo.env   # fill in the values
./infra/setup.sh
```

The script creates:

- A Foundry resource with two projects, `agents-prod` and `agents-dev`, and a `gpt-5.4-mini` Global Standard deployment.
- A user-assigned managed identity for the pipeline. Its federated credentials trust only the GitHub environments `development`, `evaluation` and `production` of this repository. GitHub repositories created after 15 July 2026 use the immutable subject `repo:OWNER@OWNER_ID/REPO@REPO_ID:environment:NAME`; the script builds it.
- Role assignments: **Foundry User** on both projects for the pipeline identity and for you, and **Foundry User** on the Foundry resource for each project.
- A monthly budget with alerts at 50 % and 90 % of actual cost and at 100 % of forecast cost, on the resources tagged `demo=foundry-delivery`.
- The GitHub environments `development`, `evaluation` and `production`. `production` accepts deployments from `main` only.
- The repository secrets `AZURE_CLIENT_ID`, `AZURE_TENANT_ID` and `AZURE_SUBSCRIPTION_ID`. They are identifiers, not credentials. They are secrets only so that GitHub masks them in public logs.
- The repository variables `FOUNDRY_PROJECT_ENDPOINT`, `FOUNDRY_DEV_PROJECT_ENDPOINT` and `MODEL_DEPLOYMENT_NAME`.

### 3. Deploy the first version

```bash
git push -u origin main
```

`Deliver agent` runs the tests and the evaluation, and deploys the first version of the hosted agent.

### 4. Switch on Claude Code Review

1. In claude.ai, open **Admin settings → Claude Code → Code review** and turn on **Allow code review**.
2. Connect GitHub and install the Claude GitHub App on the repository.
3. Edit the repository row: **Review runs** = *After every push*, **Review level** = *Standard*.

### 5. Add the approver and the ruleset

```bash
gh api -X PUT repos/OWNER/foundry-delivery-demo/collaborators/APPROVER -f permission=push
echo "* @APPROVER" > .github/CODEOWNERS   # commit and push
gh api -X POST repos/OWNER/foundry-delivery-demo/rulesets --input infra/ruleset.json
```

### 6. Prepare your terminal

```bash
python3.13 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
export FOUNDRY_PROJECT_ENDPOINT=$(gh variable get FOUNDRY_PROJECT_ENDPOINT)
export MODEL_DEPLOYMENT_NAME=$(gh variable get MODEL_DEPLOYMENT_NAME)
```

With these variables and `az login`, you can run `python evals/run_eval.py` and `python deploy/ask_agent.py`. Your account has **Foundry User** on the projects, so it can call agents and models, but the demo never deploys from a laptop.

### 7. Tag the starting state

```bash
git tag -f demo-start main
git tag -f demo-feature feature/report-missing-items
git push -f origin demo-start demo-feature
```

`demo/reset.sh` returns the repository to these tags.

## The demo

The demo takes about 20 minutes live, most of it waiting for the review and the pipeline. Use the waiting time for questions. The recording in `recording/out/` is the backup.

### Before the call

1. Run the reset at least 15 minutes before the call (see [Reset the demo](#reset-the-demo)).
2. Check that `Deliver agent` on `main` is green and that production serves the starting code:
   ```bash
   python deploy/ask_agent.py samples/two-reports.txt
   ```
   The answer starts with `Deviations of 10% or more (agent version N)` and lists Travel and Training only, not Printing or Cloud hosting. Note the version number N.
3. Open a terminal in the repository on the branch `feature/report-missing-items`.
4. Open the repository in the browser as the developer, and in a second browser profile as the approver.
5. Open the Foundry portal on the production project, on the agent `report-deviation-agent`.
6. Switch on Do Not Disturb and close everything that does not belong to the demo.

### Step 1: Change

**Do:** show the change and run the local review.

```bash
git diff main --stat
claude -p "/review-change"
```

**Say:** "A developer used Claude Code to add a feature: the agent now also reports items that appear in only one of the two reports. Before the pull request, the developer runs the team's shared review skill. The same rules drive the review on the pull request. The local review is a practice, not a gate: nothing stops the developer from pushing anyway, and that is what happens here."

### Step 2: Pull request

**Do:** push and open the pull request.

```bash
git push
gh pr create --fill
```

Open the pull request in the browser. Show the checks: `unit-tests` passes, `Claude Code Review` runs, `review-gate` waits for it. When the review is done, show Claude's comment on `exceeds_threshold` and the blocked merge box.

**Say:** "Claude Code Review reviews every push. It found a real defect: the comparison uses 'greater than', so a change of exactly the threshold is no longer reported. The unit tests did not catch it. The review gate turns the finding into a failed check, and the ruleset blocks the merge while the conversation is open. There is no bypass, not even for the repository owner."

### Step 3: Fix and approval

**Do:** fix the comparison and add a boundary test, then push.

```bash
claude -p "Fix the Important finding from the code review on this pull request and add a unit test for a change of exactly the threshold."
python -m pytest -q
git commit -am "Report a change of exactly the threshold" && git push
```

When the new review passes, resolve the conversation. As the approver, approve the pull request.

**Say:** "The developer fixes the defect. Claude reviews the new push and the gate passes. The approver named in CODEOWNERS approves. The approval must come after the last push, so nobody can slip a change in after the approval."

### Step 4: Merge and pipeline

**Do:** squash and merge. Open the `Deliver agent` run.

**Say:** "Merging starts the pipeline. First the unit tests, then the evaluation set: every case runs through the agent with the model, billed per token. The grader checks which items the agent flags and whether each reason uses the note. A metric below its threshold fails the pipeline, exactly like a failed test."

### Step 5: Deploy

**Do:** open the `deploy` job log.

**Say:** "Only this job deploys, only from main, in the production environment. It signs in to Azure with a federated identity: there is no secret in GitHub and no personal account. It creates a new version of the hosted agent and tests it in its own session while production still serves the previous version. Only then does it switch all traffic. If the agent source has not changed, it deploys nothing."

### Step 6: Result and rollback

**Do:** ask the agent, then run `Roll back agent` from the Actions tab, then ask again.

```bash
python deploy/ask_agent.py samples/two-reports.txt
```

**Say:** "The new version reports the new and the missing items. If something goes wrong in production, the rollback is one pipeline run: it routes all traffic back to the previous version. The new version stays available, so we can switch forward again."

### Step 7 (optional): A business owner changes a prompt agent

**Do:** in the Foundry portal, open the dev project, open the prompt agent `deviation-note-writer`, change its instructions (for example, add "End with one recommended next step.") and save. Saving creates a new version. Then run `Promote prompt agent` from the Actions tab and open the pull request from the branch it pushes.

**Say:** "Business owners can change prompts without code. The change still reaches production only through the same path: a pull request, a review, an approval, and the pipeline."

## Fallback: a failing evaluation

To show that a failed evaluation stops the deploy, run `Deliver agent` on the branch with the planted flaw:

```bash
gh workflow run deliver.yml --ref feature/report-missing-items
```

The unit tests pass, the evaluation fails on the two boundary cases, and the deploy job does not run. The deploy job runs only for `main` in any case.

## Reset the demo

```bash
./demo/reset.sh
```

The script closes the open demo pull requests, lifts the ruleset for a moment, moves `main` back to `demo-start` and the feature branch back to `demo-feature`, and turns the ruleset on again. The push to `main` starts `Deliver agent`, which routes production back to the code of `demo-start`. The script also gives the dev prompt agent a new version with the instructions from `main`. Foundry keeps the older versions; the demo does not need them deleted.

## Delete everything

```bash
./infra/teardown.sh
```

The script lists the resources tagged `demo=foundry-delivery` and asks before it deletes them. It deletes the Foundry resource with its projects, agents and model deployment, purges the soft-deleted Foundry resource, and deletes the pipeline identity and the budget. The resource group stays. Delete the GitHub repository separately if you no longer need it:

```bash
gh repo delete OWNER/foundry-delivery-demo
```
