"""Read-only reconstruction of Agent decisions from persisted research evidence.

Usage:
  python scripts/inspect_agent_causal_execution.py /path/to/research --task sticks
  python scripts/inspect_agent_causal_execution.py /path/to/research --task sticks --full

This is a forensic reader, never an execution path or evidence authority.
"""
from __future__ import annotations

import argparse
import base64
from collections import Counter
import json
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("rb") as fh:
            value = json.load(fh)
        return value if isinstance(value, dict) else None
    except (OSError, ValueError, UnicodeError):
        return None


def _prompt_sections(request: dict[str, Any]) -> list[dict[str, Any]]:
    sections = []
    for message in request.get("messages", ()):
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if not isinstance(content, str):
            continue
        role = message.get("role")
        if role != "user" or not content.startswith("## "):
            sections.append({"heading": role, "characters": len(content)})
            continue
        for part in content.split("\n\n## "):
            name, _, text = part.removeprefix("## ").partition("\n")
            sections.append({"heading": name, "characters": len(text)})
    return sections


def _raw_model_records(root: Path, needle: str, full: bool) -> dict[str, dict[str, Any]]:
    raw: dict[str, dict[str, Any]] = {}
    for path in (root / "platform-runtime/state/observability/raw").glob("run-*/*.jsonl"):
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                    family = row["family"]
                    if family not in {"llm.request.raw", "llm.attempt.raw"}:
                        continue
                    payload = row["payload"]
                    request_id = payload["request_id"]
                    task = str(row.get("context", {}).get("task_id") or "")
                    if needle and needle not in task and request_id not in raw:
                        # A response need not repeat the full task metadata;
                        # never consume another task's content opportunistically.
                        continue
                    content = json.loads(base64.b64decode(payload["__content_b64"]))
                except (ValueError, KeyError, TypeError, UnicodeError):
                    continue
                target = raw.setdefault(request_id, {"task_id": task})
                target.update({
                    "role": payload.get("role"),
                    "status": payload.get("status"),
                })
                if family == "llm.request.raw":
                    target["sections"] = _prompt_sections(content)
                    target["thinking_enabled"] = (
                        content.get("chat_template_kwargs", {}).get("enable_thinking")
                    )
                    if full:
                        target["actual_request"] = content
                else:
                    choices = content.get("choices") or ()
                    if choices and isinstance(choices[0], dict):
                        message = choices[0].get("message", {})
                        target["actual_response"] = message.get("content")
                        target["finish_reason"] = choices[0].get("finish_reason")
                    target["usage"] = content.get("usage", {})
    return raw


def _events(root: Path, raw: dict[str, dict[str, Any]], needle: str, full: bool, max_episodes: int):
    results = []
    for file in (root / "method-workloads").glob(
        "*/paper_agent/lifetime-*/task-*/invocation-*/evidence/results/*.json"
    ):
        document = _read_json(file)
        if document is None:
            continue
        events = document.get("events")
        if not isinstance(events, list):
            continue
        request_ids = [
            e.get("payload", {}).get("request_id")
            for e in events
            if isinstance(e, dict)
            and e.get("kind") == "model.invocation"
            and isinstance(e.get("payload"), dict)
        ]
        matched = [rid for rid in request_ids if rid in raw]
        if needle and not matched:
            continue
        timeline: list[dict[str, Any]] = []
        for index, event in enumerate(events):
            if not isinstance(event, dict):
                continue
            kind = event.get("kind")
            payload = event.get("payload")
            if kind == "model.invocation" and isinstance(payload, dict):
                rid = payload.get("request_id")
                item = {
                    "event_index": index, "event": kind, "request_id": rid,
                    "queue_seconds": payload.get("dispatch_queue_seconds"),
                    "service_seconds": payload.get("dispatch_service_seconds"),
                    "provider_stages_ns": payload.get("provider_stage_timings_ns"),
                    "model_request": raw.get(rid, {}),
                }
            elif kind == "node:recall" and isinstance(payload, dict):
                items = payload.get("items") or ()
                item = {
                    "event_index": index, "event": kind,
                    "retrieved_count": len(items),
                    "records": items if full else [
                        {"record_id": e.get("record_id"), "kind": e.get("kind")}
                        for e in items if isinstance(e, dict)
                    ],
                }
            elif kind in {"node:plan", "node:prepare_action", "node:parse_meta", "node:apply_evolution"}:
                if kind == "node:plan" and isinstance(payload, str):
                    try:
                        payload = json.loads(payload)
                    except ValueError:
                        pass
                if kind == "node:apply_evolution" and isinstance(payload, dict) and not full:
                    payload = {
                        "accepted": payload.get("accepted"),
                        "adopted_count": payload.get("adopted_count"),
                        "active_node_count": payload.get("active_node_count"),
                    }
                item = {"event_index": index, "event": kind, "value": payload}
            elif kind in {"node:environment", "node:record_action"} and isinstance(payload, dict):
                state = payload.get("state")
                if not isinstance(state, dict):
                    state = ((payload.get("observation") or {}).get("payload") or {}).get("state") or {}
                item = {
                    "event_index": index, "event": kind,
                    "accepted": payload.get("accepted"),
                    "goal_satisfied": payload.get("goal_satisfied"),
                    "success": payload.get("success"),
                    "last_outcome": state.get("last_outcome"),
                }
            elif kind in {"node:complete", "node:finalize"}:
                item = {
                    "event_index": index, "event": kind,
                    "complete": kind == "node:complete",
                }
            else:
                continue
            timeline.append(item)
        results.append({
            "source_file": str(file),
            "status": document.get("status"),
            "matched_task_ids": sorted({
                raw[r]["task_id"] for r in matched if raw[r].get("task_id")
            }),
            "event_kinds": dict(Counter(e.get("kind") for e in events if isinstance(e, dict))),
            "timeline": timeline,
        })
        if len(results) >= max_episodes:
            break
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("research", type=Path)
    parser.add_argument("--task", default="", help="Match actual raw model task_id")
    parser.add_argument("--max-episodes", type=int, default=1)
    parser.add_argument("--full", action="store_true", help="Include exact model input and memory records")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.max_episodes < 1:
        parser.error("--max-episodes must be positive")
    root = args.research.resolve()
    if not (root / "method-workloads").is_dir():
        parser.error("research root lacks method-workloads")
    indexed = _raw_model_records(root, args.task, args.full)
    result = {
        "schema": "noetrium.agent-causal-inspection.v1",
        "research_root": str(root),
        "raw_model_requests": len(indexed),
        "episodes": _events(root, indexed, args.task, args.full, args.max_episodes),
    }
    output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(output + "\n", encoding="utf-8")
        print(args.output)
    else:
        print(output)


if __name__ == "__main__":
    main()
