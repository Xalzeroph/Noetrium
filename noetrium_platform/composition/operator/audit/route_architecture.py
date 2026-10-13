from __future__ import annotations

from noetrium_platform.foundation.governance.architecture.gate import main as architecture_gate_main
from noetrium_platform.foundation.governance.architecture.report import build_architecture_report


def route_architecture(args: object):
    command = getattr(args, "command", None)
    if command == "architecture-gate":
        return architecture_gate_main()
    if command == "architecture-report":
        return build_architecture_report(args.source_root)
    return None


__all__ = ["route_architecture"]
