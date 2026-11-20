# Report-deviation agent

- `agent/` is the hosted agent. `report_compare.py` holds the deterministic comparison; `reasons.py` asks the model for the one-line reasons.
- A deviation is a change of the threshold or more. The threshold is inclusive.
- Run `python -m pytest -q` for the unit tests and `python evals/run_eval.py` for the evaluation set (it calls the model).
- Before you open a pull request, run the `review-change` skill.
- Only the `Deliver agent` workflow deploys. Never deploy from a laptop.
