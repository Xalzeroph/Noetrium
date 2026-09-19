"""Canonical capability identities used by explicit composition roots.

These constants name public composition seams only.  They are deliberately
separate from runtime ports: a capability key identifies a bindable contract,
while a port is the narrow object injected after the binding plan is frozen.
"""

from .capability_composition import CapabilityKey


HOST_OPERATING_SYSTEM_ROUTE_V1 = CapabilityKey(
    "runtime.host", "operating-system-route", 1
)
SERVER_CONNECTION_FACTORY_V1 = CapabilityKey(
    "runtime.server", "connection-factory", 1
)
SERVER_FILE_TRANSFER_FACTORY_V1 = CapabilityKey(
    "runtime.server", "file-transfer-factory", 1
)
LOG_SINK_V1 = CapabilityKey("observability.logging", "sink", 1)
LOG_QUERY_V1 = CapabilityKey("observability.logging", "query", 1)
EXCEPTION_DESCRIPTOR_V1 = CapabilityKey(
    "observability.logging", "exception-descriptor", 1
)
LOGGING_SYSTEM_V1 = CapabilityKey("observability.logging", "system", 1)
METHOD_COMPOSITION_PORTS_V1 = CapabilityKey(
    "participant.method", "composition-ports", 1
)


__all__ = [
    "EXCEPTION_DESCRIPTOR_V1",
    "HOST_OPERATING_SYSTEM_ROUTE_V1",
    "LOG_QUERY_V1",
    "LOG_SINK_V1",
    "LOGGING_SYSTEM_V1",
    "METHOD_COMPOSITION_PORTS_V1",
    "SERVER_CONNECTION_FACTORY_V1",
    "SERVER_FILE_TRANSFER_FACTORY_V1",
]
