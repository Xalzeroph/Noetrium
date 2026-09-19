def management_main(argv=None):
    """Invoke the management CLI without importing its module eagerly."""

    from .management_cli import main

    return main(argv)

__all__ = ["management_main"]
