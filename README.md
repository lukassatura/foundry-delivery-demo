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
| `deploy/` | Scripts that the pipeline runs: deploy a new version, roll back, ask the agent. |
| `.github/workflows/` | `pull-request.yml` (checks on every pull request), `deliver.yml` (test, evaluate, deploy), `rollback.yml`. |
| `.claude/skills/review-change/` | The shared review skill. Developers run it locally; `REVIEW.md` gives the same rules to Claude Code Review. |
| `infra/` | Set-up and teardown scripts for Azure and GitHub, and the branch ruleset. |
| `recording/` | The scripts that record the demo video. |

## How the path works

1. **Change.** A developer changes the agent with Claude Code and runs the `review-change` skill. The local review is a practice, not a gate.
2. **Pull request.** Claude Code Review reviews every push. Its check never fails on its own, so the `review-gate` job reads the review's severity counts and fails while an Important finding is open. The ruleset also blocks the merge until every review conversation is resolved.
3. **Approval.** The ruleset requires one approval from someone other than the last pusher. `CODEOWNERS` names the approver.
4. **Merge and pipeline.** `Deliver agent` runs the unit tests and then the evaluation set against the model. A metric below its threshold fails the job, like a failed test.
5. **Deploy.** The deploy job runs only for `main`, in the GitHub environment `production`. It signs in to Azure with a federated credential: no stored secret, no personal account. It creates a new version of the hosted agent, tests that version in its own session, and only then routes all traffic to it.
6. **Rollback.** `Roll back agent` routes all traffic back to an earlier version.

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

Do not push yet. The first push to `main` deploys version 1, so Azure must be ready first.

### 2. Create the Azure resources and the GitHub settings

```bash
cp infra/demo.env.example infra/demo.env   # fill in the values
./infra/setup.sh
```

The script creates:

- A Foundry resource with two projects, `agents-prod` and `agents-dev`, and a `gpt-5.4-mini` Global Standard deployment.
- A user-assigned managed identity for the pipeline. Its federated credentials trust only the GitHub environments `evaluation` and `production` of this repository.
- Role assignments: **Foundry User** on both projects for the pipeline identity and for you, and **Foundry User** on the Foundry resource for each project.
- A monthly budget with alerts at 50 % and 90 % of actual cost and at 100 % of forecast cost, on the resources tagged `demo=foundry-delivery`.
- The GitHub environments `evaluation` and `production`. `production` accepts deployments from `main` only.
- The repository secrets `AZURE_CLIENT_ID`, `AZURE_TENANT_ID` and `AZURE_SUBSCRIPTION_ID`. They are identifiers, not credentials. They are secrets only so that GitHub masks them in public logs.
- The repository variables `FOUNDRY_PROJECT_ENDPOINT`, `FOUNDRY_DEV_PROJECT_ENDPOINT` and `MODEL_DEPLOYMENT_NAME`.

### 3. Deploy version 1

```bash
git push -u origin main
```

`Deliver agent` runs the tests and the evaluation, and deploys version 1.

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

## Delete everything

```bash
./infra/teardown.sh
```

The script lists the resources tagged `demo=foundry-delivery` and asks before it deletes them. It deletes the Foundry resource with its projects, agents and model deployment, purges the soft-deleted Foundry resource, and deletes the pipeline identity and the budget. The resource group stays. Delete the GitHub repository separately if you no longer need it:

```bash
gh repo delete OWNER/foundry-delivery-demo
```
