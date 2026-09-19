from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ACTIONS = ("run", "inspect", "stop", "resume", "reconcile", "evidence")
_MARKER = "CONTAINER_PRODUCT_SMOKE="
_WHEEL_LABEL = "org.opencontainers.image.noetrium.wheel.sha256"
_DISTRIBUTION_LABEL = (
    "org.opencontainers.image.noetrium.distribution-evidence.sha256"
)


@dataclass(frozen=True, slots=True)
class CommandReceipt:
    argv: tuple[str, ...]
    returncode: int
    stdout_sha256: str
    stderr_sha256: str
    stdout_tail: str
    stderr_tail: str

@dataclass(frozen=True, slots=True)
class ContainerVerificationReceipt:
    schema: str
    qualification_scope: str
    npe_verified: bool
    operator_smoke_actions: tuple[str, ...]
    image: str
    image_id: str
    source_sha: str
    wheel_sha256: str
    distribution_evidence_sha256: str
    repo_digests: tuple[str, ...]
    container_user: str
    effective_uid: int
    effective_gid: int
    record_verified_files: int
    python_version: str
    package_version: str
    module_file: str
    actions: tuple[str, ...]
    commands: tuple[CommandReceipt, ...]


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _receipt(argv: list[str], completed: subprocess.CompletedProcess[str]) -> CommandReceipt:
    return CommandReceipt(
        argv=tuple(argv), returncode=completed.returncode,
        stdout_sha256=_digest(completed.stdout), stderr_sha256=_digest(completed.stderr),
        stdout_tail=completed.stdout[-4000:], stderr_tail=completed.stderr[-4000:],
    )

def _run(argv: list[str]) -> tuple[CommandReceipt, str]:
    completed = subprocess.run(
        argv, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        check=False,
    )
    receipt = _receipt(argv, completed)
    if completed.returncode != 0:
        raise RuntimeError(
            "container verification command failed: " + " ".join(argv)
            + f"\nstdout={completed.stdout[-4000:]}\nstderr={completed.stderr[-4000:]}"
        )
    return receipt, completed.stdout


def _product_smoke_script(expected_wheel_sha256: str) -> str:
    template = r'''set -eu
work="$(mktemp -d)"
python - "$work" "__EXPECTED_WHEEL__" <<'PY'
import base64
import csv
import hashlib
import importlib.metadata
import io
import json
import os
from pathlib import Path
import sys
import zipfile

root = Path(sys.argv[1])
expected_wheel = sys.argv[2]
wheel = Path(os.environ["PLATFORM_EMBEDDED_WHEEL"])
actual_wheel = hashlib.sha256(wheel.read_bytes()).hexdigest()
if actual_wheel != expected_wheel:
    raise SystemExit("embedded wheel digest mismatch")
uid = os.geteuid()
gid = os.getegid()
if uid == 0 or gid == 0:
    raise SystemExit("container effective uid/gid must both be non-root")
dist = importlib.metadata.distribution("noetrium")
site_root = Path(dist.locate_file("")).resolve()
verified_files = 0
with zipfile.ZipFile(wheel) as archive:
    record_names = [name for name in archive.namelist() if name.endswith(".dist-info/RECORD")]
    if len(record_names) != 1:
        raise SystemExit("wheel must contain exactly one RECORD")
    with archive.open(record_names[0]) as handle:
        rows = csv.reader(io.TextIOWrapper(handle, encoding="utf-8", newline=""))
        for relative, encoded_hash, size in rows:
            if not encoded_hash:
                continue
            algorithm, separator, encoded = encoded_hash.partition("=")
            if algorithm != "sha256" or not separator:
                raise SystemExit(f"unsupported RECORD digest for {relative}")
            target = (site_root / relative).resolve()
            if target != site_root and site_root not in target.parents:
                raise SystemExit(f"RECORD path escaped site-packages: {relative}")
            if not target.is_file():
                raise SystemExit(f"installed RECORD file missing: {relative}")
            padding = "=" * (-len(encoded) % 4)
            expected = base64.urlsafe_b64decode(encoded + padding)
            observed = hashlib.sha256(target.read_bytes()).digest()
            if observed != expected:
                raise SystemExit(f"installed RECORD digest mismatch: {relative}")
            if size and target.stat().st_size != int(size):
                raise SystemExit(f"installed RECORD size mismatch: {relative}")
            verified_files += 1
if verified_files < 1:
    raise SystemExit("wheel RECORD did not verify any installed files")
(root / "provenance.json").write_text(json.dumps({
    "wheel_sha256": actual_wheel,
    "record_verified_files": verified_files,
    "effective_uid": uid,
    "effective_gid": gid,
}, sort_keys=True), encoding="utf-8")
PY
noetrium --help >/dev/null
python - "$work" <<'PY'
import json
import sys
from pathlib import Path
root = Path(sys.argv[1])
(root / "reference.json").write_text(
    json.dumps({"state_root": str(root / "state")}), encoding="utf-8"
)
PY
for action in run inspect stop resume reconcile evidence; do
  noetrium --application noetrium_platform.product.operator.reference:build_reference_application \
    --application-config "$work/reference.json" "$action" container-reference > "$work/$action.json"
done
python - "$work" <<'PY'
import importlib.metadata
import json
import sys
from pathlib import Path
import noetrium
root = Path(sys.argv[1])
provenance = json.loads((root / "provenance.json").read_text(encoding="utf-8"))
actions = ("run", "inspect", "stop", "resume", "reconcile", "evidence")
for action in actions:
    payload = json.loads((root / f"{action}.json").read_text(encoding="utf-8"))
    if payload.get("ok") is not True or payload.get("command") != action:
        raise SystemExit(f"invalid container lifecycle receipt: {action}")
print("CONTAINER_PRODUCT_SMOKE=" + json.dumps({
    "actions": actions,
    "module_file": noetrium.__file__,
    "package_version": importlib.metadata.version("noetrium"),
    "python_version": sys.version.split()[0],
    **provenance,
}, sort_keys=True))
PY
'''
    return template.replace("__EXPECTED_WHEEL__", expected_wheel_sha256)


def _parse_smoke(stdout: str) -> dict[str, object]:
    lines = [line for line in stdout.splitlines() if line.startswith(_MARKER)]
    if len(lines) != 1:
        raise RuntimeError("container smoke output must contain exactly one product marker")
    payload = json.loads(lines[0][len(_MARKER):])
    if not isinstance(payload, dict):
        raise RuntimeError("container smoke marker must contain a JSON object")
    return payload

def verify_container_image(
    image: str,
    *,
    expected_source_sha: str,
    expected_wheel_sha256: str,
    expected_distribution_evidence_sha256: str,
) -> ContainerVerificationReceipt:
    source_sha = expected_source_sha.strip().lower()
    wheel_sha256 = expected_wheel_sha256.strip().lower()
    distribution_sha256 = expected_distribution_evidence_sha256.strip().lower()
    if not _SHA40_RE.fullmatch(source_sha):
        raise ValueError("expected source SHA must be a lowercase 40-character Git SHA")
    if not _SHA256_RE.fullmatch(wheel_sha256):
        raise ValueError("expected wheel SHA256 must be lowercase hexadecimal")
    if not _SHA256_RE.fullmatch(distribution_sha256):
        raise ValueError("expected distribution evidence SHA256 must be lowercase hexadecimal")
    if not image.strip():
        raise ValueError("container image must not be blank")

    receipts: list[CommandReceipt] = []
    inspect_receipt, inspect_stdout = _run(["docker", "image", "inspect", image])
    receipts.append(inspect_receipt)
    document = json.loads(inspect_stdout)
    if not isinstance(document, list) or len(document) != 1 or not isinstance(document[0], dict):
        raise RuntimeError("docker image inspect returned an invalid document")
    metadata = document[0]
    config = metadata.get("Config")
    if not isinstance(config, dict):
        raise RuntimeError("container Config field is invalid")
    labels = config.get("Labels") or {}
    if not isinstance(labels, dict):
        raise RuntimeError("container image labels are invalid")
    if labels.get("org.opencontainers.image.revision") != source_sha:
        raise RuntimeError("container source revision label does not match expected SHA")
    if labels.get(_WHEEL_LABEL) != wheel_sha256:
        raise RuntimeError("container wheel digest label does not match expected artifact")
    if labels.get(_DISTRIBUTION_LABEL) != distribution_sha256:
        raise RuntimeError("container distribution evidence label does not match expected receipt")
    image_id = metadata.get("Id")
    if not isinstance(image_id, str) or not image_id.startswith("sha256:"):
        raise RuntimeError("container image ID is missing or invalid")
    repo_digests = metadata.get("RepoDigests") or []
    if not isinstance(repo_digests, list) or not all(isinstance(value, str) for value in repo_digests):
        raise RuntimeError("container RepoDigests field is invalid")
    container_user = config.get("User")
    if not isinstance(container_user, str) or not container_user.strip():
        raise RuntimeError("container image must declare a non-root user")
    principal = container_user.strip().split(":", 1)[0].lower()
    if principal in {"0", "root"}:
        raise RuntimeError("container image must not declare root runtime user")

    doctor_receipt, _ = _run(["docker", "run", "--rm", "--network=none", image, "doctor"])
    receipts.append(doctor_receipt)
    smoke_receipt, smoke_stdout = _run([
        "docker", "run", "--rm", "--network=none", image,
        "shell", "/bin/sh", "-lc", _product_smoke_script(wheel_sha256),
    ])
    receipts.append(smoke_receipt)
    smoke = _parse_smoke(smoke_stdout)
    actions = smoke.get("actions")
    if actions != list(_ACTIONS):
        raise RuntimeError("container smoke did not exercise the full lifecycle")
    module_file = smoke.get("module_file")
    if not isinstance(module_file, str) or "/site-packages/" not in module_file.replace("\\", "/"):
        raise RuntimeError("container product import did not come from installed site-packages")
    package_version = smoke.get("package_version")
    python_version = smoke.get("python_version")
    if not isinstance(package_version, str) or not package_version:
        raise RuntimeError("container package version missing")
    if not isinstance(python_version, str) or not python_version.startswith("3.12."):
        raise RuntimeError("container Python runtime is not Python 3.12")
    if smoke.get("wheel_sha256") != wheel_sha256:
        raise RuntimeError("container embedded wheel bytes do not match expected artifact")
    effective_uid = smoke.get("effective_uid")
    effective_gid = smoke.get("effective_gid")
    if type(effective_uid) is not int or type(effective_gid) is not int:
        raise RuntimeError("container smoke did not attest effective uid/gid")
    if effective_uid == 0 or effective_gid == 0:
        raise RuntimeError("container effective uid/gid must both be non-root")
    record_verified_files = smoke.get("record_verified_files")
    if type(record_verified_files) is not int or record_verified_files < 1:
        raise RuntimeError("container installed wheel RECORD was not verified")

    return ContainerVerificationReceipt(
        schema="noetrium.container-verification.v3",
        qualification_scope="operator-smoke-only",
        npe_verified=False,
        operator_smoke_actions=tuple(_ACTIONS),
        image=image,
        image_id=image_id,
        source_sha=source_sha,
        wheel_sha256=wheel_sha256,
        distribution_evidence_sha256=distribution_sha256,
        repo_digests=tuple(repo_digests),
        container_user=container_user.strip(),
        effective_uid=effective_uid,
        effective_gid=effective_gid,
        record_verified_files=record_verified_files,
        python_version=python_version,
        package_version=package_version,
        module_file=module_file,
        actions=tuple(actions),
        commands=tuple(receipts),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("image")
    parser.add_argument("--expected-source-sha", required=True)
    parser.add_argument("--expected-wheel-sha256", required=True)
    parser.add_argument("--expected-distribution-evidence-sha256", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        receipt = verify_container_image(
            args.image,
            expected_source_sha=args.expected_source_sha,
            expected_wheel_sha256=args.expected_wheel_sha256,
            expected_distribution_evidence_sha256=args.expected_distribution_evidence_sha256,
        )
    except Exception as exc:
        print(f"CONTAINER_VERIFY_FAIL {type(exc).__qualname__}: {exc}", file=sys.stderr)
        return 1
    document = json.dumps(asdict(receipt), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(document, encoding="utf-8", newline="\n")
    print(document, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
