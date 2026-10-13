"""Concrete operator composition exposes the single public entry lazily."""


def main(argv=None):
    from .wiring.entrypoint import main as operator_main
    return operator_main(argv)


__all__ = ["main"]
