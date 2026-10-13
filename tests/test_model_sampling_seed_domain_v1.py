from noetrium_platform.research.execution.workflow.composition.model_agent import (
    _model_sampling_seed,
)


def test_model_sampling_seed_is_openai_compatible_signed_int64() -> None:
    values = (
        0,
        (1 << 63) - 1,
        1 << 63,
        13072850635434765789,
        15778959251045670429,
        (1 << 64) - 1,
    )
    normalized = tuple(_model_sampling_seed(value) for value in values)
    assert all(0 <= value <= (1 << 63) - 1 for value in normalized)
    assert normalized[2] == 0
    assert normalized[-1] == (1 << 63) - 1


def test_model_sampling_seed_is_deterministic() -> None:
    source = 13072850635434765789
    assert _model_sampling_seed(source) == _model_sampling_seed(source)
    assert _model_sampling_seed(source) == 3849478598579989981
