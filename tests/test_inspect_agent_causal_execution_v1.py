"""A causal trace reader must join exact raw requests with Method evidence."""
from __future__ import annotations

import base64
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path


_SCRIPT = Path(__file__).resolve().parents[1] / "scripts/inspect_agent_causal_execution.py"


def _reader():
    spec = spec_from_file_location("agent_causal_reader", _SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_exact_model_context_and_action_history_join(tmp_path):
    inspector = _reader()
    research = tmp_path / "research"
    raw_dir = research / "platform-runtime/state/observability/raw/run-a"
    raw_dir.mkdir(parents=True)
    request = {
        "model": "Qwen3-8B",
        "messages": [
            {"role": "system", "content": "Authorized tools only."},
            {"role": "user", "content": "## GOAL\nobtain oak logs\n\n## MEMORY\nrecalled hypothesis"},
        ],
        "chat_template_kwargs": {"enable_thinking": False},
    }
    response = {
        "choices": [{
            "finish_reason": "stop",
            "message": {"content": '{"action":{"action_type":"collect_block"}}'},
        }],
        "usage": {"prompt_tokens": 42, "completion_tokens": 9},
    }
    def event(family, body):
        return json.dumps({
            "family": family,
            "context": {"task_id": "sample-oak-task"},
            "payload": {
                "request_id": "sample-request",
                "role": "planner",
                "status": "http_200",
                "__content_b64": base64.b64encode(
                    json.dumps(body).encode("utf-8")
                ).decode("ascii"),
            },
        })
    (raw_dir / "family.jsonl").write_text(
        event("llm.request.raw", request) + "\n"
        + event("llm.attempt.raw", response) + "\n"
    )
    evidence = research / (
        "method-workloads/a/paper_agent/lifetime-a/task-a/"
        "invocation-a/evidence/results/result.json"
    )
    evidence.parent.mkdir(parents=True)
    evidence.write_text(json.dumps({
        "status": "succeeded",
        "events": [
            {"kind": "node:recall", "payload": {
                "items": [{"record_id": "memory-a", "kind": "experience"}],
            }},
            {"kind": "model.invocation", "payload": {
                "request_id": "sample-request",
                "dispatch_queue_seconds": 1.0,
                "dispatch_service_seconds": 2.0,
            }},
            {"kind": "node:plan", "payload": '{"action":{"action_type":"collect_block"}}'},
            {"kind": "node:record_action", "payload": {
                "success": True,
                "goal_satisfied": True,
                "state": {"last_outcome": {"code": "BLOCK_COLLECTED"}},
            }},
        ],
    }))
    raw = inspector._raw_model_records(research, "sample-oak", True)
    assert raw["sample-request"]["actual_request"] == request
    assert raw["sample-request"]["actual_response"] == response["choices"][0]["message"]["content"]
    assert raw["sample-request"]["thinking_enabled"] is False
    episodes = inspector._events(research, raw, "sample-oak", True, 1)
    assert len(episodes) == 1
    timeline = episodes[0]["timeline"]
    assert [row["event"] for row in timeline] == [
        "node:recall", "model.invocation", "node:plan", "node:record_action",
    ]
    assert timeline[0]["records"][0]["record_id"] == "memory-a"
    assert timeline[1]["queue_seconds"] == 1.0
    assert timeline[-1]["last_outcome"]["code"] == "BLOCK_COLLECTED"
    assert inspector._events(research, {}, "other-task", False, 1) == []
