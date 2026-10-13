"""nsh command line and SDK facade for canonical Unit compilation.

nsh is a compiler/verifier surface. Research execution lifecycle belongs to the
canonical Research execution control authority and is intentionally not exposed through
a second generic run command ABI.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from noetrium_platform.foundation.kernel.kernel import (
    UnitCompiler,
    UnitSource,
    strict_json_loads,
)
from noetrium_platform.foundation.kernel.kernel.durability import atomic_replace_bytes


def _read_object(path: Path) -> dict[str, object]:
    value = strict_json_loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def compile_file(
    source_path: str | Path,
    output_path: str | Path,
    *,
    unit_machine_id: str = "noetrium.machine",
    unit_machine_version: str = "1",
) -> dict[str, object]:
    compiler = UnitCompiler(
        unit_machine_id=unit_machine_id,
        unit_machine_version=unit_machine_version,
    )
    compiled = compiler.compile(
        UnitSource.from_mapping(_read_object(Path(source_path)))
    )
    manifest = compiled.manifest()
    from noetrium_platform.foundation.kernel.kernel import canonical_bytes
    atomic_replace_bytes(Path(output_path), canonical_bytes(manifest, indent=2))
    return manifest


def verify_file(
    manifest_path: str | Path,
    *,
    unit_machine_id: str = "noetrium.machine",
    unit_machine_version: str = "1",
) -> str:
    compiler = UnitCompiler(
        unit_machine_id=unit_machine_id,
        unit_machine_version=unit_machine_version,
    )
    unit = compiler.verify_manifest(_read_object(Path(manifest_path)))
    return unit.unit_digest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nsh")
    sub = parser.add_subparsers(dest="command", required=True)

    compile_parser = sub.add_parser(
        "compile",
        help="compile a canonical nsh source into a frozen Unit manifest",
    )
    compile_parser.add_argument("source")
    compile_parser.add_argument("-o", "--output", required=True)
    compile_parser.add_argument(
        "--interpreter-id",
        default="noetrium.machine",
    )
    compile_parser.add_argument(
        "--interpreter-version",
        default="1",
    )

    verify_parser = sub.add_parser(
        "verify",
        help="verify a frozen canonical program manifest",
    )
    verify_parser.add_argument("manifest")
    verify_parser.add_argument(
        "--interpreter-id",
        default="noetrium.machine",
    )
    verify_parser.add_argument(
        "--interpreter-version",
        default="1",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "compile":
        manifest = compile_file(
            args.source,
            args.output,
            unit_machine_id=args.unit_machine_id,
            unit_machine_version=args.unit_machine_version,
        )
        print(manifest["unit_digest"])
        return 0
    if args.command == "verify":
        print(
            verify_file(
                args.manifest,
                unit_machine_id=args.unit_machine_id,
                unit_machine_version=args.unit_machine_version,
            )
        )
        return 0
    raise AssertionError(f"unreachable nsh command: {args.command}")


__all__ = ["build_parser", "compile_file", "main", "verify_file"]
