from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from noetrium_platform.foundation.governance.release.runtime.manifest import build_release_manifest


@dataclass(frozen=True, slots=True)
class GateCommandReceipt:
    name: str
    argv: tuple[str, ...]
    returncode: int
    stdout_sha256: str
    stderr_sha256: str
    stdout_tail: str
    stderr_tail: str


@dataclass(frozen=True, slots=True)
class ProductAssuranceReceipt:
    schema: str
    generated_at_utc: str
    repository: str
    branch: str
    source_sha: str
    source_tree_sha256: str
    source_clean: bool
    closing_branch: str | None
    closing_source_sha: str | None
    closing_source_tree_sha256: str | None
    closing_source_clean: bool | None
    source_identity_rechecked: bool
    source_identity_consistent: bool
    passed: bool
    commands: tuple[GateCommandReceipt, ...]


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _tail(value: str, limit: int = 4000) -> str:
    return value[-limit:]


def _git(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "git command failed")
    return completed.stdout.strip()


def _source_identity() -> tuple[str, str, str, bool]:
    sha = _git("rev-parse", "HEAD")
    branch = _git("branch", "--show-current")
    clean = not bool(
        _git("status", "--porcelain=v1", "--untracked-files=all")
    )
    source_tree_sha256 = build_release_manifest(ROOT).source_tree_sha256
    return sha, branch, source_tree_sha256, clean


def _isolated_python_argv(argv: list[str]) -> list[str]:
    if not argv or Path(argv[0]).resolve() != Path(sys.executable).resolve():
        return argv
    target = argv[1:]
    if target[:1] == ["-m"] and len(target) >= 2:
        launcher = (
            "import runpy,sys; "
            "root,module,*args=sys.argv[1:]; "
            "sys.path.insert(0,root); "
            "sys.argv=[module,*args]; "
            "runpy.run_module(module,run_name='__main__')"
        )
        return [argv[0], "-c", launcher, str(ROOT), target[1], *target[2:]]
    if target:
        launcher = (
            "import runpy,sys; "
            "root,script,*args=sys.argv[1:]; "
            "sys.path.insert(0,root); "
            "sys.argv=[script,*args]; "
            "runpy.run_path(script,run_name='__main__')"
        )
        return [argv[0], "-c", launcher, str(ROOT), *target]
    return argv


def _run(name: str, argv: list[str]) -> GateCommandReceipt:
    child_env = os.environ.copy()
    existing_pythonpath = child_env.get("PYTHONPATH", "")
    child_env["PYTHONPATH"] = os.pathsep.join(
        item for item in (str(ROOT), existing_pythonpath) if item
    )
    completed = subprocess.run(
        _isolated_python_argv(argv),
        cwd=ROOT,
        env=child_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return GateCommandReceipt(
        name=name,
        argv=tuple(argv),
        returncode=completed.returncode,
        stdout_sha256=_digest(completed.stdout),
        stderr_sha256=_digest(completed.stderr),
        stdout_tail=_tail(completed.stdout),
        stderr_tail=_tail(completed.stderr),
    )


def evaluate(*, full: bool, include_architecture: bool = True) -> ProductAssuranceReceipt:
    source_sha, branch, source_tree_sha256, source_clean = _source_identity()
    if full and not source_clean:
        return ProductAssuranceReceipt(
            schema="noetrium.product-assurance-gate.v3",
            generated_at_utc=datetime.now(timezone.utc).isoformat(),
            repository="agent-noetrium-system",
            branch=branch,
            source_sha=source_sha,
            source_tree_sha256=source_tree_sha256,
            source_clean=False,
            closing_branch=None,
            closing_source_sha=None,
            closing_source_tree_sha256=None,
            closing_source_clean=None,
            source_identity_rechecked=False,
            source_identity_consistent=False,
            passed=False,
            commands=(),
        )
    commands = [
        ("test-taxonomy", [sys.executable, "scripts/test_system.py", "check"]),
        (
            "provider-conformance",
            [sys.executable, "scripts/provider_conformance.py", "run"],
        ),
    ]
    if include_architecture:
        commands.append(
            (
                "architecture",
                [sys.executable, "-m", "noetrium_platform.foundation.governance.architecture.gate"],
            )
        )
    if full:
        commands.append(
            (
                "full-regression",
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-q",
                    "--basetemp",
                    str(
                        Path(
                            os.environ.get(
                                "RUNNER_TEMP",
                                tempfile.gettempdir(),
                            )
                        )
                        / "noetrium-product-assurance-full"
                    ),
                ],
            )
        )
    receipts: list[GateCommandReceipt] = []
    for name, argv in commands:
        receipt = _run(name, argv)
        receipts.append(receipt)
        if receipt.returncode != 0:
            break
    closing_sha, closing_branch, closing_tree_sha256, closing_clean = _source_identity()
    identity_consistent = (
        closing_sha == source_sha
        and closing_branch == branch
        and closing_tree_sha256 == source_tree_sha256
        and closing_clean == source_clean
    )
    passed = (
        bool(receipts)
        and all(row.returncode == 0 for row in receipts)
        and len(receipts) == len(commands)
        and identity_consistent
    )
    return ProductAssuranceReceipt(
        schema="noetrium.product-assurance-gate.v3",
        generated_at_utc=datetime.now(timezone.utc).isoformat(),
        repository="agent-noetrium-system",
        branch=branch,
        source_sha=source_sha,
        source_tree_sha256=source_tree_sha256,
        source_clean=source_clean,
        closing_branch=closing_branch,
        closing_source_sha=closing_sha,
        closing_source_tree_sha256=closing_tree_sha256,
        closing_source_clean=closing_clean,
        source_identity_rechecked=True,
        source_identity_consistent=identity_consistent,
        passed=passed,
        commands=tuple(receipts),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true")
    parser.add_argument(
        "--skip-architecture",
        action="store_true",
        help="omit the architecture governance gate",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    receipt = evaluate(full=args.full, include_architecture=not args.skip_architecture)
    document = (
        json.dumps(asdict(receipt), ensure_ascii=False, sort_keys=True, indent=2)
        + "\n"
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(document, encoding="utf-8")
    print(document, end="")
    return 0 if receipt.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
