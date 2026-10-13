from __future__ import annotations

import pytest

from noetrium_platform.capabilities.participant.agent.api import AgentSkillRecord
from noetrium_platform.foundation.kernel.kernel import CanonicalEncodingError


def test_skill_record_preserves_typed_recipe_without_platform_skill_manager() -> None:
    record = AgentSkillRecord(
        skill_id="skill.move",
        version="1",
        summary="learned move",
        tags=("learned",),
        source_refs=("test",),
        recipe=(("move", {"target": {"x": 1, "y": 2}, "path": [1, 2, 3]}),),
        success_count=3,
        failure_count=0,
    )
    assert record.success_count == 3
    assert record.recipe[0][1]["path"] == (1, 2, 3)


def test_skill_record_rejects_non_finite_recipe_values() -> None:
    with pytest.raises(CanonicalEncodingError, match="non-finite"):
        AgentSkillRecord(
            skill_id="skill.bad",
            version="1",
            summary="bad recipe",
            recipe=(("move", {"distance": float("nan")}),),
        )
