from __future__ import annotations

from typing import Any, get_type_hints

from noetrium_platform.infrastructure.reliability.forensics.api.ports import ForensicWriteActorPort


def test_forensic_write_actor_preserves_callable_parameter_types_without_any() -> None:
    hints = get_type_hints(ForensicWriteActorPort.call)

    assert hints["operation"] is str
    assert "Callable[~P, ~T]" in str(hints["fn"])
    assert str(hints["args"]) == "P.args"
    assert str(hints["kwargs"]) == "P.kwargs"
    assert hints["return"].__name__ == "T"
    assert all(value is not Any for value in hints.values())
