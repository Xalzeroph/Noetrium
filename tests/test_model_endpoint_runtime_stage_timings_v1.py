"""Physical model timing evidence must survive without changing response truth."""
import pytest

from noetrium_platform.capabilities.model.serving.endpoint.api.contracts import (
    ModelEndpointResponse,
)


def test_stage_timings_do_not_modify_scientific_response_identity():
    base = ModelEndpointResponse(
        request_id="request:x",
        deployment_id="deployment:y",
        text='{"action":"observe"}',
        input_tokens=100,
        output_tokens=5,
    )
    measured = ModelEndpointResponse(
        request_id="request:x",
        deployment_id="deployment:y",
        text='{"action":"observe"}',
        input_tokens=100,
        output_tokens=5,
        stage_timings_ns=(
            ("authority_admission", 17),
            ("http_headers_wait", 1024),
            ("http_json_decode", 8),
        ),
    )
    assert measured.response_digest == base.response_digest
    assert dict(measured.stage_timings_ns)["http_headers_wait"] == 1024


@pytest.mark.parametrize("bad", [
    [("request_encode", 2)],
    (("request_encode", -1),),
    (("request_encode", True),),
    (("request_encode", 1), ("request_encode", 2)),
    (("", 0),),
    ((1, 0),),
])
def test_stage_timings_are_unique_named_nonnegative_nanoseconds(bad):
    with pytest.raises(ValueError, match="stage timings"):
        ModelEndpointResponse(
            request_id="request:x",
            deployment_id="deployment:y",
            text="valid",
            stage_timings_ns=bad,
        )
