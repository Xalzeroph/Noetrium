"""Run a reusable ReAct component without editing Platform source."""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from components.reference.single_agent.agent import (
    ReferenceAgentAction, ReferenceAgentActionKind, ReferenceAgentDecision, ReferenceReActMethod,
    ReferenceToolRegistryPort,
)
from components.reference.single_agent.tools import ToolArguments, ToolDefinition, ToolRegistry, ToolResult


class Policy:
    def decide(self, state):
        if state.step == 0:
            return ReferenceAgentDecision(
                ReferenceAgentAction.from_mapping(
                    ReferenceAgentActionKind.TOOL,
                    "lookup",
                    {"query": state.task},
                    content="look up the task",
                )
            )
        return ReferenceAgentDecision(ReferenceAgentAction(ReferenceAgentActionKind.FINAL, "answer", content="reused component"))


def main() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition("lookup", "deterministic lookup", "lookup.v1"),
        lambda args: ToolResult("lookup", True, f"found:{args.as_mapping()['query']}"),
    )
    result = ReferenceReActMethod(Policy(), ReferenceToolRegistryPort(registry)).run("hello", max_steps=4)
    print(result.status.value, result.answer)


if __name__ == "__main__":
    main()
