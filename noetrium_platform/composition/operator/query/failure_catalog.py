from __future__ import annotations

from dataclasses import asdict

from noetrium_platform.infrastructure.reliability.failure.api import DEFAULT_FAILURE_CATALOG, FailureCatalog


class FailureCatalogView:
    """Read-only operator projection of the stable failure taxonomy."""

    def __init__(self, catalog: FailureCatalog = DEFAULT_FAILURE_CATALOG) -> None:
        self.catalog = catalog

    def query(
        self,
        *,
        domain: str | None = None,
        code: str | None = None,
    ) -> dict[str, object]:
        if domain is not None:
            domain = domain.upper()
        if code is not None:
            code = code.upper()
        rows = self.catalog.find(domain=domain, code=code)
        return {
            "domain": domain,
            "code": code,
            "count": len(rows),
            "specs": [
                {
                    **asdict(spec),
                    "default_recovery": spec.default_recovery.value,
                    "data_integrity_risk": spec.data_integrity_risk.value,
                    "comparability_risk": spec.comparability_risk.value,
                    "scientific_validity_risk": spec.scientific_validity_risk.value,
                }
                for spec in rows
            ],
        }
