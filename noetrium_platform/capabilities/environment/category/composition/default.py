from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.substrate.api import component_catalog, system_catalog

from ..api.contracts import (
    EnvironmentCategoryDescriptor,
    EnvironmentCategoryId,
    EnvironmentImplementationDescriptor,
)
from ..runtime.catalog import (
    canonical_environment_categories,
    canonical_environment_implementations,
)


def _validate_registered_environment_families() -> None:
    """Fail closed against the declared topology shape of every environment family."""

    rows = []
    for descriptor in system_catalog():
        if descriptor.parent_key == "environment":
            rows.append(
                (
                    descriptor.identity.key,
                    descriptor.package_prefix,
                    descriptor.provides,
                    descriptor.shape,
                )
            )
    for component in component_catalog():
        if component.parent == "environment":
            rows.append(
                (
                    component.key,
                    component.package_prefix,
                    component.provides,
                    component.shape,
                )
            )

    for key, package_prefix, provides, shape in rows:
        contract_capabilities = tuple(
            capability
            for capability in provides
            if capability.startswith("environment.") and capability.endswith(".contract")
        )
        if not contract_capabilities:
            continue
        try:
            import_module(package_prefix + ".api")
            if "composition" in shape:
                import_module(package_prefix + ".composition")
        except ImportError as exc:
            raise RuntimeError(
                f"environment family declared plane is not importable: {key}"
            ) from exc


@dataclass(frozen=True, slots=True)
class DefaultEnvironmentCategoryCatalog:
    _categories: tuple[EnvironmentCategoryDescriptor, ...]
    _implementations: tuple[EnvironmentImplementationDescriptor, ...]

    def __post_init__(self) -> None:
        _validate_registered_environment_families()
        category_ids = {item.category_id for item in self._categories}
        if len(category_ids) != len(self._categories):
            raise ValueError("environment category ids must be unique")
        implementation_ids = [item.implementation_id for item in self._implementations]
        if len(set(implementation_ids)) != len(implementation_ids):
            raise ValueError("environment implementation ids must be unique")
        declared = {
            implementation_id
            for category in self._categories
            for implementation_id in category.implementation_ids + category.planned_implementation_ids
        }
        if set(implementation_ids) != declared:
            raise ValueError("environment catalog has dangling category or implementation declarations")

    def categories(self) -> tuple[EnvironmentCategoryDescriptor, ...]:
        return self._categories

    def category(self, category_id: EnvironmentCategoryId) -> EnvironmentCategoryDescriptor:
        for item in self._categories:
            if item.category_id == category_id:
                return item
        raise KeyError(category_id.value)

    def implementations(
        self, category_id: EnvironmentCategoryId
    ) -> tuple[EnvironmentImplementationDescriptor, ...]:
        return tuple(item for item in self._implementations if item.category_id == category_id)

    def implementation(self, implementation_id: str) -> EnvironmentImplementationDescriptor:
        for item in self._implementations:
            if item.implementation_id == implementation_id:
                return item
        raise KeyError(implementation_id)

    @property
    def catalog_digest(self) -> str:
        return canonical_digest({
            "categories": [item.record() for item in self._categories],
            "implementations": [item.record() for item in self._implementations],
        })


def default_environment_category_catalog():
    return DefaultEnvironmentCategoryCatalog(
        canonical_environment_categories(),
        canonical_environment_implementations(),
    )


__all__ = ["DefaultEnvironmentCategoryCatalog", "default_environment_category_catalog"]
