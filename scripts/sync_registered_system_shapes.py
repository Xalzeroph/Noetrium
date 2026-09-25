from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
_MARKER = "AUTO-GENERATED registered-system plane stub"


def _catalog(root: Path) -> dict[str, dict[str, object]]:
    path = root / "noetrium_platform/foundation/governance/system_registry/catalog.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not value:
        raise RuntimeError("canonical system registry must be a non-empty object")
    return value


def _stub(system_key: str, plane: str) -> str:
    return (
        f'""" {_MARKER}.\n\n'
        f'System: {system_key}\nPlane: {plane}\n'
        'This file exists because the canonical registry declares the standard system plane.\n'
        '"""\n\n'
        '__all__: tuple[str, ...] = ()\n'
    )


def sync_registered_system_shapes(root: Path, *, check: bool = False) -> tuple[str, ...]:
    root = Path(root).resolve()
    catalog = _catalog(root)
    expected: dict[Path, tuple[str, str]] = {}
    findings: list[str] = []
    for system_key, descriptor in catalog.items():
        package_prefix = descriptor.get("package_prefix")
        shape = descriptor.get("shape")
        if not isinstance(package_prefix, str) or not package_prefix.strip():
            raise RuntimeError(f"invalid package_prefix for {system_key!r}")
        if not isinstance(shape, list) or not all(isinstance(x, str) and x for x in shape):
            raise RuntimeError(f"invalid shape for {system_key!r}")
        package = root.joinpath(*package_prefix.split("."))
        if not (package / "__init__.py").is_file():
            findings.append(f"registered package missing: {system_key}: {package_prefix}")
            continue
        legacy_api = package / "api.py"
        if "api" in shape and legacy_api.is_file():
            findings.append(
                f"legacy api.py conflicts with standard api package: {system_key}: "
                f"{legacy_api.relative_to(root)}"
            )
        for plane in shape:
            target = package / plane / "__init__.py"
            expected[target] = (system_key, plane)
            if target.is_file():
                continue
            if check:
                findings.append(
                    f"registered plane missing: {system_key}: {target.relative_to(root)}"
                )
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(_stub(system_key, plane), encoding="utf-8")

    # Only marker-owned obsolete stubs are safe to delete automatically.
    for target in sorted(root.rglob("__init__.py")):
        if target in expected:
            continue
        try:
            text = target.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        if _MARKER not in text:
            continue
        if check:
            findings.append(f"obsolete generated plane stub: {target.relative_to(root)}")
        else:
            target.unlink()
            try:
                target.parent.rmdir()
            except OSError:
                pass
    return tuple(findings)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Synchronize standard registered-system plane packages.")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    findings = sync_registered_system_shapes(args.root, check=args.check)
    for finding in findings:
        print(finding, file=sys.stderr)
    print(json.dumps({"schema": "registered-system-shape-sync.v1", "clean": not findings, "finding_count": len(findings)}, sort_keys=True))
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
