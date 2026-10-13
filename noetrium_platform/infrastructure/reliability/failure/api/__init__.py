from .contracts import RecoveryAction, RiskLevel
from .catalog import FailureCatalog, FailureSpec
from .default_catalog import DEFAULT_FAILURE_CATALOG
from .classification import ClassifiedOperationFailure, PartialOperationFailureClassifier
from .codec import failure_from_dict
from .factory import build_failure, build_failure_from_spec
from .failure_units import failure_document, failure_field, failure_record, is_failure_record, replace_failure

__all__ = [
    "ClassifiedOperationFailure",
    "DEFAULT_FAILURE_CATALOG",
    "FailureCatalog",
    "FailureCorrelationSource",
    "FailureSpec",
    "PartialOperationFailureClassifier",
    "RecoveryAction",
    "RiskLevel",
    "build_failure",
    "exception_correlation_refs",
    "build_failure_from_spec",
    "failure_from_dict",
    "failure_document",
    "failure_field",
    "failure_record",
    "is_failure_record",
    "replace_failure",
]

from .ports import FailureLedgerPort, FailureMaterializationPort
__all__ = tuple(__all__) + ("FailureLedgerPort", "FailureMaterializationPort")

from .exception_refs import FailureCorrelationSource, exception_correlation_refs, exception_failure_id
from .fingerprint import FailureFingerprint, fingerprint_failure
__all__ = tuple(__all__) + ("FailureFingerprint", "fingerprint_failure", "exception_failure_id")

from .reference import FailureReference, failure_reference
__all__ = tuple(__all__) + ("FailureReference", "failure_reference")
