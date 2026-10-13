from noetrium_platform.foundation.kernel.kernel import freeze_json
from noetrium_platform.foundation.scope.api import (
    ScopeKind,
    scope_from_data,
    scope_id,
    scope_kind,
    scope_to_data,
    scope_unit,
)


def test_scope_codec_accepts_canonical_frozen_json_object() -> None:
    scope = scope_unit(ScopeKind.RUN, "run-1")
    payload = freeze_json({"scope": scope_to_data(scope)})
    decoded = scope_from_data(payload["scope"])
    assert scope_kind(decoded) is ScopeKind.RUN
    assert scope_id(decoded) == "run-1"
    assert decoded.semantic_digest == scope.semantic_digest
