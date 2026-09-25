#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]

_FORBIDDEN_PATHS = (
    "noetrium_platform/foundation/governance/architecture/gating/quality/degradation_contracts.py",
    "noetrium/contracts/agent.py",
    "noetrium/contracts/environment.py",
    "noetrium/contracts/model.py",
    "noetrium/contracts/participant.py",
    "noetrium/contracts/project.py",
    "noetrium/contracts/research.py",
    "noetrium/contracts/server.py",
    "noetrium/contracts/session.py",
    "tests/test_thread_pool_child_research_machine_batch_v1.py",
)

_FORBIDDEN_TEXT = {
    "noetrium_platform/research/execution/machines/child_machine_batch.py": (
        "ThreadPoolChildResearchBatchMechanics",
        "ThreadPoolExecutor",
    ),
    "noetrium_platform/foundation/governance/release/runtime/regression_state.py": (
        "legacy_parallel_bool",
        "schema_version == 1",
        "schema_version in {2, 3",
    ),
    "noetrium_platform/foundation/governance/analysis/algorithm/providers/filesystem.py": (
        '"algorithm-snapshot.v2"',
        'source_authority = "legacy"',
    ),
    "noetrium_platform/foundation/governance/analysis/concurrency/providers/filesystem.py": (
        'source_authority="legacy"',
        "blocker_fingerprints',()))",
    ),
    "noetrium_platform/foundation/governance/analysis/performance/providers/filesystem.py": (
        'source_authority="legacy"',
        'data.get("blocker_fingerprints"',
    ),
    "noetrium_platform/research/execution/workflow/providers/method_checkpoint.py": (
        "unsupported platform fallback",
    ),
    "noetrium_platform/infrastructure/reliability/forensics/providers/directory_change_signal.py": (
        "portability fallback",
        'return "stat"',
    ),
    "noetrium_platform/capabilities/model/serving/runtime/placement_policy.py": (
        "preserve legacy behavior",
        "setdefault(key, link.bandwidth_gbps)",
    ),
    "noetrium/contracts/__init__.py": (
        "_old_alias",
        "_new_alias",
    ),
}

_ACTIVE_CONVENIENCE_RE = re.compile(
    r"(?m)^_CONVENIENCE_(?:FACADES|CANONICAL_OWNERS|EXTRA_PLANES|EXCLUDED_NAMES)\b"
)


def validate(root: Path = ROOT) -> tuple[str, ...]:
    errors: list[str] = []
    for relative in _FORBIDDEN_PATHS:
        if (root / relative).exists():
            errors.append(f"{relative}: retired compatibility surface exists")

    for relative, needles in _FORBIDDEN_TEXT.items():
        path = root / relative
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for needle in needles:
            if needle in text:
                errors.append(
                    f"{relative}: forbidden compatibility token {needle!r}"
                )

    generator = root / "scripts/generate_downstream_contracts.py"
    if generator.is_file():
        text = generator.read_text(encoding="utf-8")
        if _ACTIVE_CONVENIENCE_RE.search(text):
            errors.append(
                "scripts/generate_downstream_contracts.py: retired convenience facade generator exists"
            )
        if "_old_alias" in text or "_new_alias" in text:
            errors.append(
                "scripts/generate_downstream_contracts.py: collision alias generation exists"
            )
    return tuple(errors)


def main() -> int:
    errors = validate()
    if errors:
        for error in errors:
            print(error)
        return 1
    print("no compatibility surface: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
