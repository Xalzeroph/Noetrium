from __future__ import annotations

from noetrium_platform.product.operator.runtime import run_operator_cli

from .runtime import build_operator_handler


def main(argv: list[str] | None = None) -> int:
    return run_operator_cli(build_operator_handler(), argv)


__all__ = ["main"]
