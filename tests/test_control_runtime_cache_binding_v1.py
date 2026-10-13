from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_control_worker_binds_runtime_cache_to_host_visible_acceleration_root() -> None:
    text = (ROOT / "deploy" / "build-environments.sh").read_text(encoding="utf-8")
    assert 'CONTROL_RUNTIME_CACHE_ROOT="${NOETRIUM_RUNTIME_CACHE_ROOT:-$MACHINE_STATE_ROOT/runtime-cache}"' in text
    assert '-v $CONTROL_RUNTIME_CACHE_ROOT:$CONTROL_RUNTIME_CACHE_ROOT' in text
    assert '-e NOETRIUM_RUNTIME_CACHE_ROOT=$CONTROL_RUNTIME_CACHE_ROOT' in text
    assert '"cache=$CONTROL_RUNTIME_CACHE_ROOT"' in text


def test_control_worker_can_bind_external_huggingface_cache_read_only() -> None:
    text = (ROOT / "deploy" / "build-environments.sh").read_text(encoding="utf-8")
    assert 'CONTROL_HUGGINGFACE_CACHE_ROOT="${NOETRIUM_HUGGINGFACE_CACHE_ROOT:-}"' in text
    assert '-v $CONTROL_HUGGINGFACE_CACHE_ROOT:$CONTROL_HUGGINGFACE_CACHE_ROOT:ro' in text
    assert '-e NOETRIUM_HUGGINGFACE_CACHE_ROOT=$CONTROL_HUGGINGFACE_CACHE_ROOT' in text
    assert '"hf_cache=$CONTROL_HUGGINGFACE_CACHE_ROOT"' in text
