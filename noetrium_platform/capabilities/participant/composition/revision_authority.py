from __future__ import annotations

from pathlib import Path

from noetrium_platform.capabilities.participant.api import ParticipantRevisionAuthorityPort
from noetrium_platform.capabilities.participant.providers import SQLiteParticipantRevisionAuthority


def sqlite_revision_authority(path: str | Path) -> ParticipantRevisionAuthorityPort:
    """Compose one durable local participant revision lineage authority."""
    return SQLiteParticipantRevisionAuthority(path)


__all__ = ["sqlite_revision_authority"]
