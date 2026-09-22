from __future__ import annotations

from pathlib import Path

from noetrium_platform.capabilities.model.qualification.api import DEFAULT_DEPLOYMENT_PROBE_TIMEOUT_SECONDS

GROUP = "deployment"


def register(groups) -> None:
    parser = groups.add_parser(GROUP)
    sub = parser.add_subparsers(dest="action", required=True)
    put_json = sub.add_parser("put-json")
    put_json.add_argument("path", type=Path)
    listing = sub.add_parser("list")
    for target in (listing,):
        target.add_argument("--tag", action="append", default=[])
        target.add_argument("--model")
        target.add_argument("--engine")
        target.add_argument("--env")
    desire = sub.add_parser("desire")
    desire.add_argument("deployment_id")
    desire.add_argument("state", choices=("running", "stopped"))
    desire_all = sub.add_parser("desire-all")
    desire_all.add_argument("state", choices=("running", "stopped"))
    desire_all.add_argument("--tag", action="append", default=[])
    desire_all.add_argument("--model")
    desire_all.add_argument("--engine")
    desire_all.add_argument("--env")
    for action in ("start", "stop", "restart", "status", "remove"):
        command = sub.add_parser(action)
        command.add_argument("deployment_id")
    set_gpus = sub.add_parser("set-gpus")
    set_gpus.add_argument("deployment_id")
    set_gpus.add_argument("gpu_devices", nargs="*")
    set_env = sub.add_parser("set-env")
    set_env.add_argument("deployment_id")
    set_env.add_argument("environment_id", nargs="?")
    for action in ("status-all", "reconcile", "start-all", "stop-all", "gpu", "gpu-conflicts", "gpu-runtime", "env-usage", "gpu-processes"):
        sub.add_parser(action)
    candidates = sub.add_parser("gpu-candidates")
    candidates.add_argument("--count", type=int, default=1)
    candidates.add_argument("--min-free-mb", type=int, default=0)
    candidates.add_argument("--max-utilization", type=int, default=100)
    logs = sub.add_parser("logs")
    logs.add_argument("deployment_id")
    tail = sub.add_parser("tail")
    tail.add_argument("deployment_id")
    tail.add_argument("--stream", choices=("stdout", "stderr"), default="stderr")
    tail.add_argument("--max-bytes", type=int, default=8192)
    qualify = sub.add_parser("qualify")
    qualify.add_argument("--model-id", required=True)
    qualify.add_argument("--model-path", required=True, type=Path)
    qualify.add_argument(
        "--environment-id",
        help="resolve the target interpreter from the platform Python-environment registry",
    )
    qualify.add_argument(
        "--python",
        type=Path,
        help="direct interpreter path for an environment not registered with the platform",
    )
    qualify.add_argument("--backend", action="append", dest="backends", default=[])
    qualify.add_argument("--tensor-parallel", type=int, default=1)
    qualify.add_argument("--index-url", action="append", dest="index_urls", default=[])
    qualify.add_argument(
        "--summary",
        action="store_true",
        help="return a compact candidate/reason/evidence summary instead of the full package plan",
    )
    qualify.add_argument(
        "--timeout-seconds",
        type=float,
        default=DEFAULT_DEPLOYMENT_PROBE_TIMEOUT_SECONDS,
        help="bounded host/index observation budget (default: 90 seconds)",
    )
    qualification = sub.add_parser("qualification")
    qualification.add_argument("plan_digest")
    apply_qualification = sub.add_parser("apply-qualification")
    apply_qualification.add_argument("plan_digest")
    apply_qualification.add_argument("--environment-id", required=True)
    runtime_qualification = sub.add_parser("runtime-qualify")
    runtime_qualification.add_argument("application_digest")


__all__ = ["GROUP", "register"]
