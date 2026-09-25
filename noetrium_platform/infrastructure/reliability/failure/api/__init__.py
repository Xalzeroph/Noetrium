from .contracts import FailureEnvelope, RecoveryAction, RiskLevel
from .catalog import FailureCatalog, FailureSpec
from .default_catalog import DEFAULT_FAILURE_CATALOG
from .classification import ClassifiedOperationFailure, PartialOperationFailureClassifier
from .references import OperationFailureReferenceProjection, OperationFailureReferenceProjector
from .codec import failure_from_dict
from .factory import build_failure, build_failure_from_spec

__all__ = [
    "ClassifiedOperationFailure",
    "DEFAULT_FAILURE_CATALOG",
    "FailureCatalog",
    "FailureEnvelope",
    "FailureCorrelationSource",
    "FailureSpec",
    "OperationFailureReferenceProjection",
    "OperationFailureReferenceProjector",
    "PartialOperationFailureClassifier",
    "RecoveryAction",
    "RiskLevel",
    "build_failure",
    "exception_correlation_refs",
    "build_failure_from_spec",
    "failure_from_dict",
]

from .ports import FailureLedgerPort
__all__ = tuple(__all__) + ("FailureLedgerPort",)

from .exception_refs import FailureCorrelationSource, exception_correlation_refs
from .fingerprint import FailureFingerprint, fingerprint_failure
__all__ = tuple(__all__) + ("FailureFingerprint", "fingerprint_failure")
