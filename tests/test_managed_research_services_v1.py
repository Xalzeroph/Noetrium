from __future__ import annotations

from pathlib import Path

from noetrium_platform.composition.managed_research_services import (
    build_managed_research_services,
)
from noetrium_platform.composition.platform_meta import build_platform_meta
from noetrium_platform.evidence.data.fact.api import (
    DurableFact,
    FactCriticality,
)
from noetrium_platform.foundation.kernel.kernel import InMemoryMachineJournal
from noetrium_platform.capabilities.environment.category.api import EnvironmentCategoryId


def test_managed_research_services_bind_default_durable_authorities(
    tmp_path: Path,
) -> None:
    meta = build_platform_meta(tmp_path / "meta")
    services = build_managed_research_services(
        tmp_path / "services",
        meta=meta,
    )

    receipt = services.facts.append(
        DurableFact(
            fact_id="fact:test:1",
            fact_type="test.fact",
            schema_version="1",
            criticality=FactCriticality.REQUIRED,
            payload={"value": 7},
            artifact_refs=(),
            state_refs=(),
        )
    )
    assert receipt.fact_id == "fact:test:1"
    assert services.facts.get("fact:test:1").payload["value"] == 7

    categories = {
        row.category_id for row in services.environment_categories.categories()
    }
    assert categories == set(EnvironmentCategoryId)
    assert services.environment_categories.implementation(
        "software.repository"
    ).category_id is EnvironmentCategoryId.SOFTWARE
    assert services.environment_categories.implementation(
        "embodied.simulator"
    ).category_id is EnvironmentCategoryId.EMBODIED

    identity = services.project_identity("demo-project", "1.0.0")
    assert identity.key == "demo-project@1.0.0"


def test_managed_research_services_supply_workload_and_evaluation_binding(
    tmp_path: Path,
) -> None:
    meta = build_platform_meta(tmp_path / "meta")
    services = build_managed_research_services(
        tmp_path / "services",
        meta=meta,
    )

    class Compiler:
        digest = "c" * 64

        def compile(self, *args, **kwargs):
            raise AssertionError("not executed in binding test")

    class ResultAdapter:
        digest = "d" * 64

        def evaluate(self, *args, **kwargs):
            raise AssertionError("not executed in binding test")

    workload = services.bind_workload(
        compiler=Compiler(),
        result_adapter=ResultAdapter(),
    )
    assert callable(workload.execute_one)

    host = services.paired_evaluation(
        journal=InMemoryMachineJournal(),
    )
    assert host.program.kind.value == "evaluation"


def test_managed_research_services_cross_query_is_platform_owned(
    tmp_path: Path,
) -> None:
    meta = build_platform_meta(tmp_path / "meta")
    services = build_managed_research_services(
        tmp_path / "services",
        meta=meta,
    )
    assert callable(services.research_results.query)
