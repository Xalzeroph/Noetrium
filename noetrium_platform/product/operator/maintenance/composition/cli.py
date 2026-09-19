from __future__ import annotations

from noetrium_platform.product.operator.maintenance.runtime.management_cli import main as _management_main


def main(argv: list[str] | None = None) -> int:
    return _management_main(argv)


__all__ = ["main"]
