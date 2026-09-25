from __future__ import annotations

from pathlib import Path

from noetrium import api
from noetrium_platform.composition.research_execution_content import (
    compose_research_execution_content,
)
from noetrium_platform.composition.research_os_local import compose_local_research_os
from noetrium_platform.foundation.governance.api import ScopeIdentity, ScopeKind
from noetrium_platform.product.research_os import ResearchExecutionTarget


def _bootstrap() -> None:
    return None


def test_research_execution_content_survives_reopen_and_is_shared_with_research_os(
    tmp_path: Path,
) -> None:
    content = compose_research_execution_content(tmp_path / "content")
    scope = ScopeIdentity(ScopeKind.PROJECT, "benchmark-fixture")
    payload = b'{"answer":"4","question":"2+2?"}'
    reference = content.publish(
        reference_id="task:gsm8k:test:00000",
        scope=scope,
        payload=payload,
        media_type="application/json",
        metadata={"benchmark_id": "gsm8k"},
    )
    assert content.read(reference) == payload

    reopened = compose_research_execution_content(tmp_path / "content")
    assert reopened.references.resolve(reference.reference_id, scope) == reference
    assert reopened.read(reference) == payload

    builder = api.ResearchProgramBuilder("fixture")
    builder.definition(
        "bootstrap",
        kind=api.ResearchDefinitionKind.CUSTOM,
        implementation=_bootstrap,
    )
    builder.node(
        "root",
        kind=api.ResearchNodeKind.CUSTOM,
        definitions=("bootstrap",),
    )
    portfolio = api.ResearchPortfolio("fixture", (builder.freeze(),))

    composition = compose_local_research_os(
        tmp_path / "research-os",
        content_authorities=reopened,
    )
    try:
        assert composition.content is reopened
        revision = composition.research_os.commit(
            portfolio,
            message="shared-content",
        )
        receipt = composition.research_os.run(
            ResearchExecutionTarget("run", revision)
        )
        assert receipt.state == "succeeded"
        assert composition.content.read(reference) == payload
    finally:
        composition.close()


def test_research_execution_content_reference_is_immutable(tmp_path: Path) -> None:
    content = compose_research_execution_content(tmp_path / "content")
    scope = ScopeIdentity(ScopeKind.PROJECT, "project")

    first = content.publish(
        reference_id="task:1",
        scope=scope,
        payload=b"first",
        media_type="text/plain",
    )
    repeated = content.publish(
        reference_id="task:1",
        scope=scope,
        payload=b"first",
        media_type="text/plain",
    )
    assert repeated == first

    import pytest

    with pytest.raises(ValueError, match="different content"):
        content.publish(
            reference_id="task:1",
            scope=scope,
            payload=b"second",
            media_type="text/plain",
        )
