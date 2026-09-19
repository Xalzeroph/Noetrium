"""nsh command line and SDK facade for canonical program compilation.

nsh is a compiler/verifier surface. Research Run lifecycle belongs to the
journal-backed RunProgram/RunControl authority and is intentionally not exposed
through a second generic run command ABI.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from noetrium_platform.foundation.kernel.kernel import (
    NshCompiler,
    ProgramSource,
    strict_json_loads,
)


def _read_object(path: Path) -> dict[str, object]:
    value = strict_json_loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def compile_file(
    source_path: str | Path,
    output_path: str | Path,
    *,
    interpreter_id: str = "noetrium.machine",
    interpreter_version: str = "1",
) -> dict[str, object]:
    compiler = NshCompiler(
        interpreter_id=interpreter_id,
        interpreter_version=interpreter_version,
    )
    compiled = compiler.compile(
        ProgramSource.from_mapping(_read_object(Path(source_path)))
    )
    manifest = compiled.manifest()
    from noetrium_platform.foundation.kernel.kernel import canonical_bytes
    Path(output_path).write_bytes(canonical_bytes(manifest, indent=2))
    return manifest


def verify_file(
    manifest_path: str | Path,
    *,
    interpreter_id: str = "noetrium.machine",
    interpreter_version: str = "1",
) -> str:
    compiler = NshCompiler(
        interpreter_id=interpreter_id,
        interpreter_version=interpreter_version,
    )
    program = compiler.verify_manifest(_read_object(Path(manifest_path)))
    return program.program_digest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nsh")
    sub = parser.add_subparsers(dest="command", required=True)

    compile_parser = sub.add_parser(
        "compile",
        help="compile a canonical nsh source into a frozen program manifest",
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
            interpreter_id=args.interpreter_id,
            interpreter_version=args.interpreter_version,
        )
        print(manifest["program_digest"])
        return 0
    if args.command == "verify":
        print(
            verify_file(
                args.manifest,
                interpreter_id=args.interpreter_id,
                interpreter_version=args.interpreter_version,
            )
        )
        return 0
    raise AssertionError(f"unreachable nsh command: {args.command}")


__all__ = ["build_parser", "compile_file", "main", "verify_file"]
