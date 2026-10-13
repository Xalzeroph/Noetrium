from __future__ import annotations

from resource_test_support import make_execution_pool

from noetrium_platform.foundation.scope.api import scope_unit
from pathlib import Path

from noetrium_platform.composition.research_execution_content import (
    compose_research_execution_content,
)
from noetrium_platform.composition.research_runtime_local import compose_local_research_runtime
from noetrium_platform.foundation.governance.api import NoetriumUnit, ScopeKind
from noetrium_platform.product.research_control import ResearchExecutionTarget
from noetrium_platform.foundation.kernel.structure import structure_unit, symbol_unit
from noetrium_platform.product.research_implementation import (
    python_implementation_from_callable,
)


def _bootstrap() -> None:
    return None


def test_research_execution_content_survives_reopen_and_is_shared_with_research(
    tmp_path: Path,
) -> None:
    content = compose_research_execution_content(tmp_path / "content")
    scope = scope_unit(ScopeKind.PROJECT, "benchmark-fixture")
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

    implementation = python_implementation_from_callable(
        "root.implementation",
        _bootstrap,
    )
    runtime = structure_unit(
        "root",
        traits=("research.runtime",),
        symbols=(
            symbol_unit(
                "root.implementation",
                traits=("research.runtime", "noetrium.implementation"),
                implementation=implementation,
            ),
        ),
    )
    portfolio = structure_unit(
        "fixture",
        traits=("research.portfolio",),
        members=(runtime,),
    )


    pool = make_execution_pool()
    composition = compose_local_research_runtime(
        tmp_path / "research",
        content_authorities=reopened,
        execution_pool=pool,
    )
    try:
        assert composition.content is reopened
        revision = composition.control.commit(
            portfolio,
            message="shared-content",
        )
        receipt = composition.control.run(
            ResearchExecutionTarget("run", revision)
        )
        assert receipt.state == "succeeded"
        assert composition.content.read(reference) == payload
    finally:
        composition.close()
        pool.close()


def test_research_execution_content_reference_is_immutable(tmp_path: Path) -> None:
    content = compose_research_execution_content(tmp_path / "content")
    scope = scope_unit(ScopeKind.PROJECT, "project")

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
