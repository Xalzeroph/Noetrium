"""Cross-domain failure/recovery primitives that remain reliability semantics."""

from .crash import CrashClass, CrashDiagnosis, CrashEvidence, classify_crash
from .runtime_faults import *

__all__ = ["CrashClass", "CrashDiagnosis", "CrashEvidence", "classify_crash"]
