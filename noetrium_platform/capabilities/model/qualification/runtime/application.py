"""Deterministic application of one persisted qualification plan."""

from __future__ import annotations

from noetrium_platform.capabilities.model.qualification.api import (
    DeploymentQualificationApplicationPort,
    DeploymentQualificationApplicationReceipt,
    DeploymentQualificationApplicationRequest,
    DeploymentQualificationApplicationStorePort,
    DeploymentQualificationEvidenceStorePort,
    QualificationMaterializationStatus,
    QualificationPackageInstallerPort,
)


class DeploymentQualificationPlanApplier(DeploymentQualificationApplicationPort):
    """Consume only a stored plan; never re-probe or choose a fallback backend."""

    def __init__(
        self,
        evidence: DeploymentQualificationEvidenceStorePort,
        installer: QualificationPackageInstallerPort,
        receipts: DeploymentQualificationApplicationStorePort,
    ) -> None:
        self._evidence = evidence
        self._installer = installer
        self._receipts = receipts

    def apply(
        self,
        request: DeploymentQualificationApplicationRequest,
    ) -> DeploymentQualificationApplicationReceipt:
        evidence = self._evidence.get(request.plan_digest)
        plan = evidence.plan
        if plan.selected_backend is None:
            receipt = DeploymentQualificationApplicationReceipt(
                plan_digest=plan.plan_digest,
                environment_id=request.environment_id,
                backend=None,
                packages=(),
                install_commands=(),
                check_command=None,
                status=QualificationMaterializationStatus.REJECTED,
                reasons=("qualification plan has no accepted backend",),
            )
            return self._receipts.publish(receipt)

        candidate = next(
            item for item in plan.candidates if item.backend == plan.selected_backend
        )
        try:
            install_commands = self._installer.install(
                request.environment_id,
                candidate.packages,
            )
        except Exception as exc:
            receipt = self._failed_receipt(
                request,
                candidate.backend,
                candidate.packages,
                reason=f"package installer raised {type(exc).__name__}",
            )
            self._receipts.publish(receipt)
            raise
        try:
            check_command = self._installer.check(request.environment_id)
        except Exception as exc:
            receipt = self._failed_receipt(
                request,
                candidate.backend,
                candidate.packages,
                install_commands=install_commands,
                reason=f"pip check raised {type(exc).__name__}",
            )
            self._receipts.publish(receipt)
            raise
        reasons = tuple(
            [
                f"package installation command returned {item.return_code}"
                for item in install_commands
                if item.return_code != 0
            ]
            + ([f"pip check returned {check_command.return_code}"] if check_command.return_code != 0 else [])
        )
        status = (
            QualificationMaterializationStatus.SUCCEEDED
            if not reasons and install_commands and check_command.return_code == 0
            else QualificationMaterializationStatus.FAILED
        )
        receipt = DeploymentQualificationApplicationReceipt(
            plan_digest=plan.plan_digest,
            environment_id=request.environment_id,
            backend=candidate.backend,
            packages=candidate.packages,
            install_commands=install_commands,
            check_command=check_command,
            status=status,
            reasons=reasons,
        )
        return self._receipts.publish(receipt)

    def _failed_receipt(
        self,
        request: DeploymentQualificationApplicationRequest,
        backend: str,
        packages,
        *,
        install_commands=(),
        reason: str,
    ) -> DeploymentQualificationApplicationReceipt:
        return DeploymentQualificationApplicationReceipt(
            plan_digest=request.plan_digest,
            environment_id=request.environment_id,
            backend=backend,
            packages=tuple(packages),
            install_commands=tuple(install_commands),
            check_command=None,
            status=QualificationMaterializationStatus.FAILED,
            reasons=(reason,),
        )


__all__ = ["DeploymentQualificationPlanApplier"]
