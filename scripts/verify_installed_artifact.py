from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


@dataclass(frozen=True, slots=True)
class CommandReceipt:
    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True, slots=True)
class InstalledArtifactReceipt:
    schema: str
    qualification_scope: str
    npe_verified: bool
    operator_smoke_actions: tuple[str, ...]
    artifact_name: str
    artifact_sha256: str
    artifact_size: int
    python_version: str
    installed_version: str
    module_file: str
    commands: tuple[CommandReceipt, ...]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(argv: list[str], *, cwd: Path, env: dict[str, str]) -> CommandReceipt:
    completed = subprocess.run(
        argv,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    receipt = CommandReceipt(
        tuple(argv),
        completed.returncode,
        completed.stdout,
        completed.stderr,
    )
    if receipt.returncode != 0:
        raise RuntimeError(
            "installed-artifact command failed: "
            + " ".join(argv)
            + f"\nstdout={receipt.stdout}\nstderr={receipt.stderr}"
        )
    return receipt


def _venv_python(root: Path) -> Path:
    return root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _noetrium_executable(root: Path) -> Path:
    return root / ("Scripts/noetrium.exe" if os.name == "nt" else "bin/noetrium")


def _create_venv(root: Path) -> None:
    try:
        import venv
    except ModuleNotFoundError as exc:
        raise RuntimeError("Python venv module is unavailable") from exc
    venv.EnvBuilder(with_pip=True, clear=True).create(root)


def verify_installed_artifact(artifact: Path) -> InstalledArtifactReceipt:
    artifact = Path(artifact).resolve()
    if not artifact.is_file():
        raise FileNotFoundError(artifact)
    commands: list[CommandReceipt] = []
    with tempfile.TemporaryDirectory(prefix="noetrium-installed-") as td:
        root = Path(td)
        venv_root = root / "venv"
        work = root / "work"
        work.mkdir()
        _create_venv(venv_root)
        python = _venv_python(venv_root)
        noetrium = _noetrium_executable(venv_root)
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        env["PYTHONNOUSERSITE"] = "1"

        commands.append(
            _run(
                [
                    str(python),
                    "-m",
                    "pip",
                    "install",
                    "--disable-pip-version-check",
                    "--no-input",
                    "--no-deps",
                    str(artifact),
                ],
                cwd=work,
                env=env,
            )
        )
        commands.append(_run([str(noetrium), "--help"], cwd=work, env=env))
        metadata_code = (
            "import importlib.metadata,json,noetrium;"
            "print(json.dumps({'version':importlib.metadata.version('noetrium'),"
            "'module_file':noetrium.__file__}))"
        )
        metadata_receipt = _run(
            [str(python), "-I", "-c", metadata_code],
            cwd=work,
            env=env,
        )
        commands.append(metadata_receipt)
        metadata = json.loads(metadata_receipt.stdout)
        module_file = Path(metadata["module_file"]).resolve()
        if venv_root.resolve() not in module_file.parents:
            raise RuntimeError(
                f"installed import escaped verification venv: {module_file}"
            )

        reference_config = work / "reference.json"
        reference_config.write_text(
            json.dumps({"state_root": str(work / "reference-state")}),
            encoding="utf-8",
        )
        prefix = [
            str(noetrium),
            "--application",
            "noetrium_platform.product.operator.reference:build_reference_application",
            "--application-config",
            str(reference_config),
        ]
        for command in ("run", "inspect", "stop", "resume", "reconcile", "evidence"):
            receipt = _run([*prefix, command, "installed-reference"], cwd=work, env=env)
            payload = json.loads(receipt.stdout)
            if payload.get("ok") is not True or payload.get("command") != command:
                raise RuntimeError(f"installed noetrium {command} returned invalid receipt")
            commands.append(receipt)

        return InstalledArtifactReceipt(
            schema="noetrium.installed-artifact-verification.v2",
            qualification_scope="operator-smoke-only",
            npe_verified=False,
            operator_smoke_actions=("run", "inspect", "stop", "resume", "reconcile", "evidence"),
            artifact_name=artifact.name,
            artifact_sha256=_sha256(artifact),
            artifact_size=artifact.stat().st_size,
            python_version=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            installed_version=str(metadata["version"]),
            module_file=str(module_file),
            commands=tuple(commands),
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        receipt = verify_installed_artifact(args.artifact)
    except Exception as exc:
        print(f"INSTALLED_ARTIFACT_VERIFY_FAIL {type(exc).__qualname__}: {exc}", file=sys.stderr)
        return 1
    document = json.dumps(asdict(receipt), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(document, encoding="utf-8")
    print(document, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
