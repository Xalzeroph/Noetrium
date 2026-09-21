from __future__ import annotations

import argparse
import ast
import hashlib
import json
from dataclasses import dataclass, asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPRO_ROOT = ROOT / "research" / "reproductions"
BENCH_ROOT = ROOT / "research" / "benchmarks"
CATALOG = ROOT / "research" / "catalog" / "reproduction_catalog.json"
PRESSURE = ROOT / "research" / "catalog" / "pressure_status.json"


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _has_main(path: Path) -> bool:
    if not path.is_file():
        return False
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "main" for node in tree.body)


def _benchmark_manifest(benchmark_id: str) -> dict | None:
    path = BENCH_ROOT / benchmark_id.replace("-", "_") / "manifest.json"
    if not path.is_file():
        # exact manifest benchmark_id wins over directory spelling.
        for candidate in BENCH_ROOT.glob("*/manifest.json"):
            try:
                value = _json(candidate)
            except Exception:
                continue
            if value.get("benchmark", {}).get("benchmark_id") == benchmark_id:
                return value
        return None
    return _json(path)


def _benchmark_package(benchmark_id: str) -> Path | None:
    direct = BENCH_ROOT / benchmark_id.replace("-", "_")
    if direct.is_dir():
        return direct
    for candidate in BENCH_ROOT.iterdir():
        manifest = candidate / "manifest.json"
        if manifest.is_file():
            try:
                if _json(manifest).get("benchmark", {}).get("benchmark_id") == benchmark_id:
                    return candidate
            except Exception:
                pass
    return None


@dataclass(frozen=True)
class Lane:
    method_id: str
    package: str
    lifecycle: str
    benchmark_ids: tuple[str, ...]
    environment_kinds: tuple[str, ...]
    modalities: tuple[str, ...]
    has_program: bool
    has_study: bool
    has_runtime: bool
    runtime_has_main: bool
    benchmark_materializers: tuple[str, ...]
    pressure_ready: bool | None
    pressure_claim_ready: bool | None
    state: str
    blockers: tuple[str, ...]


def build_plan() -> dict:
    methods = _json(CATALOG)["methods"]
    pressure_rows = _json(PRESSURE).get("lanes", [])
    pressure_by_package = {}
    for row in pressure_rows:
        package = row.get("reproduction_package") or row.get("package")
        if package:
            pressure_by_package.setdefault(package, []).append(row)

    lanes: list[Lane] = []
    for method in methods:
        for package_row in method.get("reproduction_packages", []):
            lifecycle = package_row.get("lifecycle")
            if lifecycle != "protocol_bound":
                continue
            package = package_row["package"]
            root = REPRO_ROOT / package
            benchmark_ids = tuple(method.get("benchmark_ids", ()))
            envs: set[str] = set()
            modalities: set[str] = set()
            materializers: list[str] = []
            blockers: list[str] = []
            for bid in benchmark_ids:
                manifest = _benchmark_manifest(bid)
                if manifest is None:
                    blockers.append(f"benchmark_manifest_missing:{bid}")
                else:
                    bench = manifest.get("benchmark", {})
                    envs.update(str(x) for x in bench.get("environment_kinds", ()))
                    modalities.update(str(x) for x in bench.get("modalities", ()))
                bp = _benchmark_package(bid)
                if bp is None:
                    blockers.append(f"benchmark_package_missing:{bid}")
                elif (bp / "materializer.py").is_file():
                    materializers.append(bid)
            runtime = root / "runtime.py"
            has_program = (root / "program.py").is_file()
            has_study = (root / "study.py").is_file()
            has_runtime = runtime.is_file()
            runtime_main = _has_main(runtime)
            if not has_program:
                blockers.append("method_program_missing")
            if not has_study:
                blockers.append("study_missing")
            if not has_runtime:
                blockers.append("runtime_binding_missing")
            elif not runtime_main:
                blockers.append("runtime_entrypoint_missing")
            for bid in benchmark_ids:
                if bid not in materializers:
                    blockers.append(f"benchmark_materializer_missing:{bid}")
            prs = pressure_by_package.get(package, [])
            p_ready = None if not prs else all(bool(x.get("ready")) for x in prs)
            p_claim = None if not prs else all(bool(x.get("claim_ready")) for x in prs)
            # Only direct-main lanes are auto-launchable today. Everything else is
            # admitted into the fleet but fails closed with explicit missing seams.
            state = "runnable" if not blockers else "blocked"
            lanes.append(Lane(
                method_id=method["method_id"], package=package, lifecycle=lifecycle,
                benchmark_ids=benchmark_ids, environment_kinds=tuple(sorted(envs)),
                modalities=tuple(sorted(modalities)), has_program=has_program,
                has_study=has_study, has_runtime=has_runtime,
                runtime_has_main=runtime_main,
                benchmark_materializers=tuple(sorted(materializers)),
                pressure_ready=p_ready, pressure_claim_ready=p_claim,
                state=state, blockers=tuple(sorted(set(blockers))),
            ))
    lanes.sort(key=lambda x: (x.state != "runnable", x.method_id, x.package))
    payload = {
        "schema": "noetrium.reproduction-fleet-plan.v1",
        "protocol_bound_count": len(lanes),
        "runnable_count": sum(x.state == "runnable" for x in lanes),
        "blocked_count": sum(x.state == "blocked" for x in lanes),
        "lanes": [asdict(x) for x in lanes],
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["plan_digest"] = hashlib.sha256(raw).hexdigest()
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the fail-closed reproduction fleet admission plan.")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = build_plan()
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(json.dumps({k: payload[k] for k in ("protocol_bound_count", "runnable_count", "blocked_count", "plan_digest")}, sort_keys=True))
    for row in payload["lanes"]:
        if row["state"] == "runnable":
            print("RUNNABLE", row["method_id"], row["package"], ",".join(row["benchmark_ids"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
