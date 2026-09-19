from __future__ import annotations

from pathlib import Path

from .catalog_contract_invariants import audit_catalog_contract_consistency
from .composition_invariants import audit_composition_invariants
from .concurrency_boundary_invariants import audit_concurrency_boundary_invariants
from .diagnostics_invariants import audit_diagnostics_invariants
from .document_integrity_invariants import audit_document_integrity_invariants
from .error_invariants import audit_error_invariants
from .participant_invariants import audit_participant_invariants
from .model_invariants import audit_model_invariants
from .prompt_invariants import audit_prompt_invariants
from .quality_invariants import audit_quality_invariants
from .process_invariants import audit_process_invariants
from .dependency_invariants import audit_dependency_invariants
from .runtime_invariants import audit_runtime_invariants
from .recovery_invariants import audit_recovery_invariants
from .release_invariants import audit_release_invariants
from .server_session_invariants import audit_server_session_invariants
from .service_invariants import audit_service_invariants
from .source_scan import SourceInvariantViolation
from .study_invariants import audit_study_invariants
from .telemetry_invariants import audit_telemetry_invariants
from .status_invariants import audit_status_invariants
from .workflow_invariants import audit_workflow_invariants
from .harness_pattern_invariants import audit_harness_pattern_invariants
from .system_dependency_invariants import audit_system_dependency_invariants
from .system_topology_invariants import audit_system_topology_completeness
from .public_api_invariants import audit_registered_public_facades
from .extensions import discover_architecture_extensions


def audit_source_invariants(root: Path) -> tuple[SourceInvariantViolation, ...]:
    root = Path(root).resolve()
    core = (
        audit_catalog_contract_consistency(root)
        + audit_diagnostics_invariants(root)
        + audit_error_invariants(root)
        + audit_document_integrity_invariants(root)
        + audit_study_invariants(root)
        + audit_workflow_invariants(root)
        + audit_dependency_invariants(root)
        + audit_composition_invariants(root)
        + audit_concurrency_boundary_invariants(root)
        + audit_participant_invariants(root)
        + audit_model_invariants(root)
        + audit_prompt_invariants(root)
        + audit_quality_invariants(root)
        + audit_process_invariants(root)
        + audit_runtime_invariants(root)
        + audit_server_session_invariants(root)
        + audit_service_invariants(root)
        + audit_status_invariants(root)
        + audit_telemetry_invariants(root)
        + audit_recovery_invariants(root)
        + audit_release_invariants(root)
        + audit_harness_pattern_invariants(root)
        + audit_system_dependency_invariants(root)
        + audit_system_topology_completeness(root)
        + audit_registered_public_facades(root)
    )
    extension_rows = []
    for extension in discover_architecture_extensions(root):
        auditor = getattr(extension, "audit_source_invariants", None)
        if auditor is not None:
            extension_rows.extend(auditor(root))
    return tuple(core + extension_rows)
