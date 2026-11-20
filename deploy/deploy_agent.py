"""Deploy the agent source as a new version of the Foundry hosted agent, test it, then route traffic to it.

Production stays on its current version until the new version is active and answers correctly.
"""

import hashlib
import io
import os
import sys
import zipfile
from pathlib import Path

from azure.ai.projects.models import (
    CodeConfiguration,
    HostedAgentDefinition,
    ProtocolVersionRecord,
    VersionRefIndicator,
)
from azure.core.exceptions import ResourceNotFoundError
from foundry import (
    AGENT_NAME,
    SMOKE_INPUT,
    ask_agent,
    project_client,
    route_all_traffic_to,
    served_version,
    wait_until_active,
    write_summary,
)

AGENT_DIR = Path(__file__).resolve().parent.parent / "agent"
AGENT_FILES = ["main.py", "analysis.py", "reasons.py", "report_compare.py", "requirements.txt"]


def build_zip() -> bytes:
    """Zip the agent source with fixed timestamps, so that the same source gives the same hash."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in AGENT_FILES:
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.external_attr = 0o100644 << 16  # regular file, rw-r--r--
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, (AGENT_DIR / name).read_bytes())
    return buffer.getvalue()


def definition() -> HostedAgentDefinition:
    return HostedAgentDefinition(
        cpu="0.5",
        memory="1Gi",
        code_configuration=CodeConfiguration(
            runtime="python_3_13",
            entry_point=["python", "main.py"],
            dependency_resolution="remote_build",
        ),
        protocol_versions=[ProtocolVersionRecord(protocol="responses", version="2.0.0")],
        environment_variables={
            "MODEL_DEPLOYMENT_NAME": os.environ["MODEL_DEPLOYMENT_NAME"],
            "PYTHONNOUSERSITE": "1",
        },
    )


def test_candidate(project, version: str) -> None:
    """Call the new version in its own session, before it serves any production traffic."""
    session = project.agents.create_session(
        agent_name=AGENT_NAME, version_indicator=VersionRefIndicator(agent_version=version)
    )
    answer = (
        project.get_openai_client(agent_name=AGENT_NAME)
        .responses.create(input=SMOKE_INPUT, extra_body={"agent_session_id": session.agent_session_id})
        .output_text
    )
    print(f"--- answer from candidate version {version} ---\n{answer}\n---", flush=True)
    if f"agent version {version}" not in answer or "Travel" not in answer:
        raise RuntimeError(f"Version {version} did not give the expected answer.")


def main() -> int:
    project = project_client()
    try:
        production = served_version(project)
    except ResourceNotFoundError:
        production = None
    if production:
        route_all_traffic_to(project, production)
        print(f"Production stays on version {production} while the new version is tested.", flush=True)
    else:
        print("The agent has no active version yet.", flush=True)

    code = build_zip()
    commit = os.environ.get("GITHUB_SHA", "local")
    created = project.agents.create_version_from_code(
        agent_name=AGENT_NAME,
        definition=definition(),
        code=("agent.zip", code, "application/zip"),
        code_zip_sha256=hashlib.sha256(code).hexdigest(),
        description=f"Source commit {commit[:7]}",
        metadata={"git_commit": commit, "pipeline_run": os.environ.get("PIPELINE_RUN_URL", "local")},
    )
    candidate = created.version
    print(f"Created version {candidate}.", flush=True)
    if candidate == production:
        print("The source is unchanged, so Foundry returned the version that already serves traffic.")
        return 0

    wait_until_active(project, candidate)
    test_candidate(project, candidate)
    route_all_traffic_to(project, candidate)
    answer = ask_agent(project)
    print(f"--- answer from the agent endpoint ---\n{answer}\n---", flush=True)
    if f"agent version {candidate}" not in answer:
        raise RuntimeError("The agent endpoint does not serve the new version.")

    print(f"Version {candidate} now serves all traffic. Previous version: {production or 'none'}.")
    write_summary(
        [
            "## Deployment",
            "",
            f"- Agent: `{AGENT_NAME}`",
            f"- New version: **{candidate}** (source commit `{commit[:7]}`)",
            f"- Previous version: {production or 'none'}",
            "",
            "```",
            answer,
            "```",
        ]
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
