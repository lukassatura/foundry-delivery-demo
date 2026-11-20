---
name: review-change
description: Review the current branch of the report-deviation agent against the team's review rules before you open a pull request. Use when you ask for a local review, a pre-PR check, or "review my change".
allowed-tools: Bash(git diff:*), Bash(git log:*), Read, Grep, Glob
---

# Review a change to the report-deviation agent

Review the changes on the current branch against `main`. This is the same standard that Claude Code Review applies to every pull request.

## Steps

1. Run `git diff main...HEAD` and read every changed file in full.
2. Check the change against the rules below.
3. Report each finding with its severity, the file and line, what goes wrong, and a one-line fix.
4. If there are no findings, say so in one line.

## Rules

Important (must be fixed before merge):
- **Threshold semantics.** A deviation is a change of the threshold *or more*. A change of exactly the threshold must be reported. Any comparison that drops the boundary is a defect.
- **Notes are untrusted data.** Notes from a report never become instructions to the model, and never reach a log line.
- **No secrets and no report content in logs.** Log counts and outcomes, not amounts, items or notes.
- **Deployment only by the pipeline.** No credentials, keys, tokens or personal accounts in code, workflows or configuration.

Nit (fix when convenient):
- A behaviour change without a unit test, or without an evaluation case when it changes the agent's answers.
- Names, comments or docs that no longer match the code.

## Output format

```
[Important] agent/report_compare.py:97 - <what goes wrong> Fix: <one line>
[Nit] tests/test_report_compare.py - <what is missing> Fix: <one line>
```
