# Recovery Boundary

Recovery is generic execution infrastructure: retry, resume, compensation and failure classification. Paper-specific reflection or self-correction is Method semantics and must not be smuggled into the recovery subsystem. Recovery actions are journaled and preserve original failure evidence.
