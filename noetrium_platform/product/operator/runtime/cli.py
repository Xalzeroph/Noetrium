from __future__ import annotations

import json
import sys

from noetrium_platform.product.operator.api import OperatorHandlerPort
from noetrium_platform.foundation.kernel.kernel.errors import describe_exception

from noetrium_platform.product.operator.api.json_rendering import render_json
from .parser import build_parser

_EXPECTED_OPERATOR_ERRORS = (KeyError, ValueError, FileNotFoundError, json.JSONDecodeError)



def _emit(value, *, stream=None):
    print(render_json(value), file=stream or sys.stdout)


def run_operator_cli(handler: OperatorHandlerPort, argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = handler.handle(args)
    except _EXPECTED_OPERATOR_ERRORS as exc:
        descriptor = describe_exception(exc)
        _emit(
            {
                "ok": False,
                "command": args.command,
                "error_type": descriptor.error_type,
                "error": descriptor.safe_message,
                "error_digest": descriptor.error_digest,
            },
            stream=sys.stderr,
        )
        return 2
    if isinstance(result, int):
        return result
    _emit({"ok": True, "command": args.command, "result": result})
    return 0


__all__ = ["run_operator_cli"]
