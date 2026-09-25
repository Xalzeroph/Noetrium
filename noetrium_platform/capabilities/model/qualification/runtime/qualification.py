"""Pure deployment-plan interpretation over captured capability facts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from noetrium_platform.capabilities.model.qualification.api import (
    BackendCandidatePlan,
    CandidateDecision,
    DeploymentCapabilityFacts,
    DeploymentQualificationPlan,
    DeploymentQualificationRequest,
    InstallPackage,
    PackageIndexFacts,
    native_cuda_runtime_package_names,
)
from noetrium_platform.capabilities.model.qualification.api.qualification import DEFAULT_PACKAGE_INDEX_URL


PYPI_SIMPLE = DEFAULT_PACKAGE_INDEX_URL


@dataclass(frozen=True, slots=True)
class _QualificationFactView:
    facts: DeploymentCapabilityFacts
    facts_digest: str
    by_package: Mapping[str, tuple[PackageIndexFacts, ...]]
    by_identity: Mapping[tuple[str, str], PackageIndexFacts]

    @classmethod
    def build(cls, facts: DeploymentCapabilityFacts) -> "_QualificationFactView":
        grouped: dict[str, list[PackageIndexFacts]] = {}
        identities: dict[tuple[str, str], PackageIndexFacts] = {}
        for item in facts.package_indexes:
            grouped.setdefault(item.package, []).append(item)
            identities[(item.package, item.index_url)] = item
        return cls(
            facts=facts,
            facts_digest=facts.digest(),
            by_package=MappingProxyType({key: tuple(rows) for key, rows in grouped.items()}),
            by_identity=MappingProxyType(dict(identities)),
        )

    def first_compatible(self, package: str) -> PackageIndexFacts | None:
        rows = self.by_package.get(package, ())
        return next((item for item in rows if item.selected_version), rows[0] if rows else None)

    def package_index(self, package: str, index_url: str) -> PackageIndexFacts | None:
        return self.by_identity.get((package, index_url))


class DeploymentQualificationResolver:
    """Turn immutable facts into an explainable, installable candidate plan.

    This implementation intentionally does not install packages or start a
    process.  It selects at most one *plan candidate* for this composition
    request; runtime fallback is not part of this module.
    """

    def resolve(
        self,
        request: DeploymentQualificationRequest,
        facts: DeploymentCapabilityFacts,
    ) -> DeploymentQualificationPlan:
        view = _QualificationFactView.build(facts)
        candidates = tuple(self._candidate(backend, request, view) for backend in request.backends)
        selected = next(
            (item.backend for item in candidates if item.decision is CandidateDecision.ACCEPTED),
            None,
        )
        return DeploymentQualificationPlan(
            request_digest=request.digest(),
            facts_digest=facts.digest(),
            candidates=candidates,
            selected_backend=selected,
        )

    def _candidate(
        self,
        backend: str,
        request: DeploymentQualificationRequest,
        view: _QualificationFactView,
    ) -> BackendCandidatePlan:
        facts = view.facts
        normalized = backend.strip().lower()
        reasons: list[str] = []
        evidence: list[str] = [f"facts:{view.facts_digest}"]
        packages: list[InstallPackage] = []

        if not facts.gpus:
            reasons.append("no NVIDIA GPU was observed")
        elif len(facts.gpus) < request.tensor_parallel:
            reasons.append(
                f"tensor_parallel={request.tensor_parallel} requires at least that many GPUs; "
                f"only {len(facts.gpus)} were observed"
            )
        if facts.host.logical_cpu_count < 1:
            reasons.append("host logical CPU capacity was not observed")
        if facts.host.physical_memory_bytes is None:
            reasons.append("host physical memory capacity was not observed")
        if not facts.storage.readable:
            reasons.append("model path readability was not observed")
        if request.tensor_parallel > 1:
            if not facts.fabric.topology:
                reasons.append("multi-GPU topology was not observed for tensor parallel deployment")
        if facts.model.error or not facts.model.config_present:
            reasons.append("model config.json was not captured; model identity is incomplete")
        if facts.python.errors:
            reasons.append(
                "target Python capability facts are incomplete: " + "; ".join(facts.python.errors)
            )
        if not facts.python.pip_version:
            reasons.append("selected Python interpreter has no usable pip")
        if not facts.python.ensurepip_available:
            reasons.append(
                "selected Python interpreter cannot bootstrap ensurepip; "
                "environment creation must use a managed interpreter with venv support"
            )

        if normalized not in {"sglang", "vllm"}:
            reasons.append(f"no compatibility rule is registered for backend {backend!r}")
            return BackendCandidatePlan(
                backend=backend,
                decision=CandidateDecision.REJECTED,
                version=None,
                packages=(),
                reasons=tuple(reasons),
                evidence_refs=tuple(evidence),
            )

        framework_item = view.first_compatible(normalized)
        framework = framework_item.selected_version if framework_item is not None else None
        if framework is None:
            detail = framework_item.compatibility_error if framework_item is not None else None
            reasons.append(
                f"package index has no compatible binary {normalized} release"
                + (f": {detail}" if detail else "")
            )
        else:
            packages.append(InstallPackage(normalized, framework, framework_item.index_url))
            evidence.append(f"package-index:{normalized}:{framework_item.index_url}:{framework}")
            self._append_artifact_evidence(framework_item, evidence)
            self._check_dependency_closure(framework_item, reasons, evidence)
            self._append_dependency_packages(framework_item, packages, reasons, evidence)

        self._append_native_cuda_runtime(
            view,
            packages,
            reasons,
            evidence,
        )

        if normalized == "sglang":
            kernel = self._latest_kernel(view)
            if kernel is None:
                reasons.append(
                    "no CUDA-specific sglang-kernel package was found in the official channel set"
                )
            else:
                kernel_version, kernel_index = kernel
                packages.append(InstallPackage("sglang-kernel", kernel_version, kernel_index))
                evidence.append(f"package-index:sglang-kernel:{kernel_index}:{kernel_version}")
                self._append_artifact_evidence(
                    view.package_index("sglang-kernel", kernel_index), evidence
                )
                self._check_dependency_closure(
                    view.package_index("sglang-kernel", kernel_index), reasons, evidence
                )
                self._append_dependency_packages(
                    view.package_index("sglang-kernel", kernel_index),
                    packages,
                    reasons,
                    evidence,
                )
                self._check_observed_kernel_architecture(facts, reasons, evidence)

        if request.tensor_parallel > 1 and not facts.fabric.nccl_version and not facts.fabric.nccl_library:
            planned_nccl = next(
                (
                    item
                    for item in packages
                    if item.name.lower().replace("_", "-").startswith("nvidia-nccl")
                ),
                None,
            )
            if planned_nccl is None:
                reasons.append("NCCL runtime evidence was not observed for tensor parallel deployment")
            else:
                evidence.append(
                    f"nccl-runtime:planned:{planned_nccl.name}:{planned_nccl.version}"
                )

        if facts.cuda.driver_version is None:
            reasons.append("NVIDIA driver version was not observed")
        if facts.cuda.driver_cuda_version is None and facts.cuda.toolkit_version is None:
            reasons.append("neither driver CUDA API nor toolkit version was observed")

        decision = CandidateDecision.REJECTED if reasons else CandidateDecision.ACCEPTED
        return BackendCandidatePlan(
            backend=backend,
            decision=decision,
            version=packages[0].version if packages else None,
            packages=tuple(packages),
            reasons=tuple(reasons),
            evidence_refs=tuple(evidence),
        )

    @staticmethod
    def _latest_kernel(
        view: _QualificationFactView,
    ) -> tuple[str, str] | None:
        rows = [
            item
            for item in view.by_package.get("sglang-kernel", ())
            if item.selected_version is not None
        ]
        if not rows:
            return None
        # Probe order is the CUDA-channel compatibility order; the first index
        # exposing a compatible binary wheel is the exact source in the plan.
        item = rows[0]
        return item.selected_version or "", item.index_url

    @staticmethod
    def _append_native_cuda_runtime(
        view: _QualificationFactView,
        packages: list[InstallPackage],
        reasons: list[str],
        evidence: list[str],
    ) -> None:
        """Close the native CUDA runtime seam for an isolated Python environment."""

        facts = view.facts
        raw = facts.python.torch_cuda_version or facts.cuda.driver_cuda_version or facts.cuda.toolkit_version
        if not raw:
            return
        major = raw.split(".", 1)[0].strip()
        if major not in {"11", "12", "13"}:
            return
        library_prefix = f"libcudart.so.{major}"
        target_has_library = any(
            name == library_prefix or name.startswith(library_prefix + ".")
            for name in facts.python.native_library_names
        )
        system_has_library = any(
            str(version).split(".", 1)[0] == major
            for version in facts.cuda.runtime_library_versions
        )
        if target_has_library or system_has_library:
            evidence.append(f"native-cuda-runtime:{library_prefix}:observed")
            return
        provider_names = native_cuda_runtime_package_names(raw)
        item = next(
            (
                candidate
                for package_name in provider_names
                if (candidate := view.first_compatible(package_name))
                and candidate.selected_version
            ),
            None,
        )
        package_name = item.package if item is not None else ", ".join(provider_names)
        if item is None or not item.selected_version:
            reasons.append(
                f"required native CUDA runtime {library_prefix} was not observed and "
                f"no compatible provider ({package_name}) was qualified"
            )
            evidence.append(f"native-cuda-runtime:{library_prefix}:missing")
            return
        if not any(
            artifact.kind == "wheel"
            and any(str(tag).lower() != "any" for tag in artifact.platform_tags)
            for artifact in item.artifacts
        ):
            reasons.append(
                f"{package_name} does not provide a platform-specific binary artifact "
                f"that proves it contains {library_prefix}"
            )
            evidence.append(
                f"native-cuda-runtime:{library_prefix}:unproven:artifact-not-platform-specific"
            )
            return
        # The dependency closure can already contain a package with the same
        # normalized name but an older/non-runtime-bearing build.  Appending a
        # second version would produce an impossible pip request (and was the
        # reason the vLLM materialization receipt failed on the server).  The
        # native-library probe is the stronger fact for this seam, so make its
        # provider the single package authority in the plan.
        normalized_provider = package_name.lower().replace("_", "-")
        packages[:] = [
            package
            for package in packages
            if package.name.lower().replace("_", "-") != normalized_provider
        ]
        packages.append(InstallPackage(package_name, item.selected_version, item.index_url))
        evidence.append(f"native-cuda-runtime:{library_prefix}:single-provider:{package_name}")
        evidence.append(
            f"native-cuda-runtime:{library_prefix}:planned:{item.index_url}:{item.selected_version}"
        )
        DeploymentQualificationResolver._append_artifact_evidence(item, evidence)
        DeploymentQualificationResolver._check_dependency_closure(item, reasons, evidence)
        DeploymentQualificationResolver._append_dependency_packages(item, packages, reasons, evidence)

    @staticmethod
    def _append_artifact_evidence(item, evidence: list[str] | None) -> None:
        if item is None or evidence is None:
            return
        if item.selected_version:
            evidence.append(
                f"binary-artifact:{item.package}:{item.selected_version}:"
                f"{len(item.artifacts)}-compatible-wheel(s)"
            )
        elif item.compatibility_error:
            evidence.append(f"binary-artifact-error:{item.package}:{item.compatibility_error}")

    @staticmethod
    def _check_dependency_closure(item, reasons: list[str], evidence: list[str]) -> None:
        if item is None:
            return
        if item.dependency_closure_complete:
            evidence.append(f"dependency-closure:{item.package}:{len(item.dependency_nodes)}-node(s)")
            return
        detail = item.dependency_closure_error or "dependency closure was not observed"
        evidence.append(f"dependency-closure-error:{item.package}:{detail}")
        reasons.append(f"{item.package} dependency closure is incomplete: {detail}")

    @staticmethod
    def _append_dependency_packages(
        item,
        packages: list[InstallPackage],
        reasons: list[str],
        evidence: list[str],
    ) -> None:
        """Freeze every observed closure node into the materialization plan.

        The probe and resolver jointly own compatibility interpretation. Once
        the closure is complete, the installer must not ask pip to discover a
        different transitive graph. Package identity is deduplicated globally
        across the backend and any backend-specific kernel package, while
        incompatible duplicate versions reject the candidate.
        """

        if item is None or not item.dependency_closure_complete:
            return
        planned = {package.name.lower().replace("_", "-"): package for package in packages}
        additions = 0
        rows = [
            (item.package, item.selected_version, item.index_url),
            *(
                (node.package, node.version, node.index_url)
                for node in item.dependency_nodes
            ),
        ]
        for name, version, index_url in rows:
            if not version:
                continue
            normalized = str(name).lower().replace("_", "-")
            previous = planned.get(normalized)
            if previous is not None:
                if previous.version != str(version):
                    reasons.append(
                        "materialization dependency closure requires conflicting versions for "
                        + normalized
                    )
                continue
            package = InstallPackage(str(name), str(version), str(index_url))
            packages.append(package)
            planned[normalized] = package
            additions += 1
        evidence.append(f"dependency-package-plan:{item.package}:{additions}-package(s)")

    @staticmethod
    def _check_observed_kernel_architecture(
        facts: DeploymentCapabilityFacts,
        reasons: list[str],
        evidence: list[str],
    ) -> None:
        observed = facts.python.kernel_architectures
        if not observed:
            evidence.append("sglang-kernel-architecture:not-observed")
            reasons.append(
                "architecture-specific sglang-kernel support is not observable yet; "
                "wheel/import qualification is required before materialization"
            )
            return
        evidence.append("sglang-kernel-architecture:" + ",".join(observed))
        required = {
            f"sm{gpu.compute_capability.replace('.', '')}"
            for gpu in facts.gpus
            if gpu.compute_capability
        }
        if required and not required.issubset(set(observed)):
            reasons.append(
                "observed sglang-kernel architectures "
                f"{','.join(observed)} do not cover required GPU architectures "
                f"{','.join(sorted(required))}"
            )


__all__ = ["DeploymentQualificationResolver", "PYPI_SIMPLE"]
