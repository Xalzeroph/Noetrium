from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
from typing import Any

MATRIX_PATH = Path("docs/release/PHYSICAL_CRASH_ASSURANCE_MATRIX.json")
SCHEMA = "noetrium.physical-crash-assurance-matrix.v1"
ALLOWED_L3_STATUS = {"unverified_remote", "passed"}
REQUIRED_L3 = {
    "host_reboot",
    "docker_daemon_restart",
    "sigkill_runtime",
    "gpu_process_orphan",
    "container_survives_owner",
    "external_port_occupied",
    "model_process_survives_durable_state_loss",
    "startup_takeover",
    "repeated_reconcile_crash",
}


def _test_node_exists(root: Path, nodeid: str) -> str | None:
    path_text, separator, test_name = nodeid.partition("::")
    if not separator or not path_text or not test_name:
        return f"invalid pytest node id: {nodeid!r}"
    path = root / path_text
    if not path.is_file():
        return f"missing test file for node id: {nodeid}"
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:
        return f"cannot parse referenced test file {path_text}: {exc}"
    names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    if test_name not in names:
        return f"missing referenced test function: {nodeid}"
    return None


def validate_matrix(root: Path, *, require_l3: bool = False) -> dict[str, Any]:
    root = root.resolve()
    payload = json.loads((root / MATRIX_PATH).read_text(encoding="utf-8"))
    errors: list[str] = []

    if payload.get("schema") != SCHEMA:
        errors.append(f"unexpected schema: {payload.get('schema')!r}")
    cases = payload.get("cases")
    if not isinstance(cases, list):
        errors.append("cases must be a list")
        cases = []
    if payload.get("case_count") != 40 or len(cases) != 40:
        errors.append(
            f"physical crash assurance requires exactly 40 cells; "
            f"declared={payload.get('case_count')!r} actual={len(cases)}"
        )

    expected_ids = [f"C{index:02d}" for index in range(1, 41)]
    actual_ids = [case.get("id") for case in cases if isinstance(case, dict)]
    if actual_ids != expected_ids:
        errors.append(
            "case ids must be exactly C01..C40 in canonical order; "
            f"actual={actual_ids!r}"
        )

    keys: set[str] = set()
    seen_l3: set[str] = set()
    for case in cases:
        if not isinstance(case, dict):
            errors.append(f"non-object crash-matrix cell: {case!r}")
            continue
        case_id = str(case.get("id", "<missing>"))
        key = case.get("key")
        if not isinstance(key, str) or not key.strip():
            errors.append(f"{case_id}: key must be non-empty")
        elif key in keys:
            errors.append(f"{case_id}: duplicate key {key!r}")
        else:
            keys.add(key)

        if not isinstance(case.get("scenario"), str) or not case["scenario"].strip():
            errors.append(f"{case_id}: scenario must be non-empty")
        if case.get("invariant") != payload.get("invariant"):
            errors.append(f"{case_id}: invariant drifted from matrix authority")

        for level, expected_kind in (("L1", "deterministic"), ("L2", "local_integration")):
            proof = case.get(level)
            if not isinstance(proof, dict):
                errors.append(f"{case_id}: {level} proof must be an object")
                continue
            if proof.get("kind") != expected_kind:
                errors.append(f"{case_id}: {level} kind must be {expected_kind!r}")
            nodeid = proof.get("nodeid")
            if not isinstance(nodeid, str):
                errors.append(f"{case_id}: {level} nodeid must be text")
            else:
                missing = _test_node_exists(root, nodeid)
                if missing is not None:
                    errors.append(f"{case_id}: {missing}")

        l3 = case.get("L3")
        if not isinstance(l3, dict):
            errors.append(f"{case_id}: L3 proof must be an object")
            continue
        if l3.get("kind") != "server_integration":
            errors.append(f"{case_id}: L3 kind must be 'server_integration'")
        qualification_case = l3.get("qualification_case")
        if not isinstance(qualification_case, str) or not qualification_case:
            errors.append(f"{case_id}: L3 qualification_case must be non-empty")
        else:
            seen_l3.add(qualification_case)
        if not isinstance(l3.get("fault"), str) or not l3["fault"].strip():
            errors.append(f"{case_id}: L3 fault injection must be explicit")
        assertions = l3.get("assertions")
        if (
            not isinstance(assertions, list)
            or len(assertions) < 2
            or any(not isinstance(value, str) or not value.strip() for value in assertions)
        ):
            errors.append(f"{case_id}: L3 assertions must contain at least two checks")
        if l3.get("environment") != ["linux", "docker", "nvidia"]:
            errors.append(f"{case_id}: L3 environment must be Linux + Docker + NVIDIA")
        status = l3.get("status")
        if status not in ALLOWED_L3_STATUS:
            errors.append(f"{case_id}: unsupported L3 status {status!r}")
        receipt_text = l3.get("receipt_path")
        if not isinstance(receipt_text, str) or not receipt_text.strip():
            errors.append(f"{case_id}: L3 receipt_path must be non-empty")
            continue

        if require_l3:
            if status != "passed":
                errors.append(f"{case_id}: L3 is not passed (status={status!r})")
                continue
            receipt_path = root / receipt_text
            if not receipt_path.is_file():
                errors.append(f"{case_id}: missing L3 receipt {receipt_text}")
                continue
            try:
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                errors.append(f"{case_id}: unreadable L3 receipt: {exc}")
                continue
            if receipt.get("case_id") != case_id or receipt.get("passed") is not True:
                errors.append(f"{case_id}: L3 receipt does not prove this case")
            head_sha = receipt.get("head_sha")
            if (
                not isinstance(head_sha, str)
                or len(head_sha) != 40
                or any(ch not in "0123456789abcdef" for ch in head_sha)
            ):
                errors.append(f"{case_id}: L3 receipt requires exact lowercase HEAD SHA")

    declared_required = set(payload.get("required_l3_qualification_cases", []))
    if declared_required != REQUIRED_L3:
        errors.append(
            "required L3 qualification set drifted: "
            f"declared={sorted(declared_required)!r}"
        )
    missing_required = REQUIRED_L3 - seen_l3
    if missing_required:
        errors.append(
            "40-cell matrix is missing mandatory server faults: "
            + ", ".join(sorted(missing_required))
        )

    if errors:
        raise ValueError(
            "physical crash assurance matrix is invalid:\n- "
            + "\n- ".join(errors)
        )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify Noetrium's canonical 40-cell physical crash matrix."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root",
    )
    parser.add_argument(
        "--require-l3",
        action="store_true",
        help="require every server-integration cell to have a passing receipt",
    )
    args = parser.parse_args()
    payload = validate_matrix(args.root, require_l3=args.require_l3)
    passed = sum(1 for case in payload["cases"] if case["L3"]["status"] == "passed")
    print(
        f"physical-crash-assurance: 40/40 structured; "
        f"L3 passed={passed}/40; strict={args.require_l3}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
