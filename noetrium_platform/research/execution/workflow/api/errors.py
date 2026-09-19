class WorkflowParticipantRequirementError(RuntimeError):
    """A workflow cannot bind because one or more required participant roles are absent."""


__all__ = ["WorkflowParticipantRequirementError"]
