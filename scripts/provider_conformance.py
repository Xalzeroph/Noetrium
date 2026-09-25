from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "tests" / "PROVIDER_CONFORMANCE.json"
REQUIRED = {"durable", "environment", "model", "effect", "checkpoint"}


def load_conformance_catalog(path: Path = CATALOG) -> dict[str, tuple[str, ...]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError("unsupported provider conformance schema")
    required = set(data.get("required_classes", ()))
    classes = data.get("classes")
    if required != REQUIRED or not isinstance(classes, dict) or set(classes) != REQUIRED:
        raise ValueError("provider conformance classes must match required set exactly")
    result: dict[str, tuple[str, ...]] = {}
    for class_id in sorted(REQUIRED):
        paths = tuple(classes[class_id])
        if not paths or len(set(paths)) != len(paths):
            raise ValueError(f"invalid provider conformance suite: {class_id}")
        for relative in paths:
            path = ROOT / relative
            if path.parent != ROOT / "tests" or not path.is_file() or not path.name.startswith("test_"):
                raise ValueError(f"invalid provider conformance test path: {relative}")
        result[class_id] = paths
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("check", "run"))
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    try:
        suites = load_conformance_catalog()
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"PROVIDER_CONFORMANCE_FAIL {exc}", file=sys.stderr)
        return 2
    paths = tuple(dict.fromkeys(path for rows in suites.values() for path in rows))
    if args.command == "run":
        local_root = ROOT / ".local"
        local_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="provider-conformance-", dir=local_root) as temp_dir:
            return subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "--basetemp", temp_dir, *paths],
                cwd=ROOT,
                check=False,
            ).returncode
    payload = {"classes": {key: list(value) for key, value in suites.items()}, "test_files": len(paths)}
    if args.as_json:
        print(json.dumps(payload, sort_keys=True, indent=2))
    else:
        print(
            "PROVIDER_CONFORMANCE_CHECK_PASS "
            f"classes={len(suites)} test_files={len(paths)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
