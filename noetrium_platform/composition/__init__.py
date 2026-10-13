"""Composition package boundary.

Concrete composition modules are imported explicitly. Importing the package
itself must not construct or import managed runtime, model, resource, or
observability systems as a side effect.
"""

__all__: tuple[str, ...] = ()
