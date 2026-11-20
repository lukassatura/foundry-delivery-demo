"""Shared helpers for the deploy, rollback and smoke-test scripts."""

import os
import time

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    AgentEndpointConfig,
    FixedRatioVersionSelectionRule,
    ProtocolConfiguration,
    ResponsesProtocolConfiguration,
    VersionSelector,
)
from azure.identity import DefaultAzureCredential

AGENT_NAME = os.environ.get("AGENT_NAME", "report-deviation-agent")
SMOKE_INPUT = "\n".join(
    [
        "Threshold: 10%",
        "Baseline:",
        "item,amount",
        "Travel,1000",
        "Office rent,5000",
        "Current:",
        "item,amount,note",
        "Travel,1250,Two customer workshops moved from the first quarter",
        "Office rent,5000,",
    ]
)


def project_client() -> AIProjectClient:
    return AIProjectClient(endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"], credential=DefaultAzureCredential())


def served_version(project: AIProjectClient) -> str | None:
    """Return the version that the agent endpoint serves.

    When the endpoint follows the latest version, return the newest active version instead.
    Return None when the agent has no active version.
    """
    agent = project.agents.get(agent_name=AGENT_NAME).as_dict()
    rules = ((agent.get("agent_endpoint") or {}).get("version_selector") or {}).get("version_selection_rules") or []
    if rules and rules[0]["agent_version"] != "@latest":
        return rules[0]["agent_version"]
    active = active_versions(project)
    return active[-1] if active else None


def active_versions(project: AIProjectClient) -> list[str]:
    """Return the versions that finished provisioning, oldest first.

    The status in the version list does not show failed provisioning, so read each version.
    """
    numbers = sorted(int(v.version) for v in project.agents.list_versions(agent_name=AGENT_NAME))
    return [
        str(n)
        for n in numbers
        if project.agents.get_version(agent_name=AGENT_NAME, agent_version=str(n))["status"] == "active"
    ]


def route_all_traffic_to(project: AIProjectClient, version: str) -> None:
    project.agents.update_details(
        agent_name=AGENT_NAME,
        agent_endpoint=AgentEndpointConfig(
            version_selector=VersionSelector(
                version_selection_rules=[FixedRatioVersionSelectionRule(agent_version=version, traffic_percentage=100)]
            ),
            protocol_configuration=ProtocolConfiguration(responses=ResponsesProtocolConfiguration()),
        ),
    )


def wait_until_active(project: AIProjectClient, version: str, timeout_s: int = 900) -> None:
    deadline = time.monotonic() + timeout_s
    while True:
        details = project.agents.get_version(agent_name=AGENT_NAME, agent_version=version)
        status = details["status"]
        print(f"version {version}: {status}", flush=True)
        if status == "active":
            return
        if status == "failed":
            raise RuntimeError(f"Version {version} failed to provision: {details.get('error')}")
        if time.monotonic() > deadline:
            raise TimeoutError(f"Version {version} is not active after {timeout_s} s")
        time.sleep(10)


def ask_agent(project: AIProjectClient, text: str = SMOKE_INPUT) -> str:
    return project.get_openai_client(agent_name=AGENT_NAME).responses.create(input=text).output_text


def write_summary(lines: list[str]) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a") as summary:
            summary.write("\n".join(lines) + "\n")
