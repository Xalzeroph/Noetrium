"""Non-Method Unit failure cause must survive projection into ResearchOS."""
from noetrium_platform.composition.research_runtime import _machine_failure_cause


def test_machine_journal_failure_provenance_is_not_replaced_with_status_only():
    provenance = {
        "unit_failure": {
            "code": "unit.node_exception",
            "cursor": "invoke",
            "error_digest": "d" * 64,
            "message": "builtins.KeyError: 'memory_treatment'",
        },
    }
    text = _machine_failure_cause(provenance)
    assert "unit.node_exception" in text
    assert "cursor='invoke'" in text
    assert "lower_error_digest=" in text
    assert "KeyError" in text
    assert "memory_treatment" in text
    # Absence of a committed lower failure is not invented.
    assert _machine_failure_cause({}) == ""
    assert _machine_failure_cause({"unit_failure": None}) == ""
    assert _machine_failure_cause(None) == ""
