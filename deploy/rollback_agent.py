"""Route all traffic of the hosted agent back to an earlier version.

Usage: python deploy/rollback_agent.py [VERSION]
Without VERSION, the script picks the version before the one that serves traffic now.
"""

import sys

from foundry import active_versions, ask_agent, project_client, route_all_traffic_to, served_version, write_summary


def main() -> int:
    project = project_client()
    current = served_version(project)
    target = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] else None
    if target is None:
        older = [v for v in active_versions(project) if int(v) < int(current)]
        if not older:
            print(f"No active version is older than version {current}.")
            return 1
        target = older[-1]

    route_all_traffic_to(project, target)
    answer = ask_agent(project)
    print(f"--- answer from the agent endpoint ---\n{answer}\n---", flush=True)
    if f"agent version {target}" not in answer:
        raise RuntimeError(f"The agent endpoint does not serve version {target}.")

    print(f"Rolled back from version {current} to version {target}.")
    write_summary(["## Rollback", "", f"- From version {current} to version **{target}**", "", "```", answer, "```"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
