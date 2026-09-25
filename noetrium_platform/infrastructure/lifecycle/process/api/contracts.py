from __future__ import annotations

from dataclasses import dataclass


class CaptureIntegrityError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ByteSegment:
    index:int
    filename:str
    start_offset:int
    end_offset:int
    size:int
    sha256:str


@dataclass(frozen=True, slots=True)
class CaptureManifest:
    schema_version:int
    stream:str
    total_bytes:int
    segments:tuple[ByteSegment,...]
    sealed:bool
    manifest_sha256:str


@dataclass(frozen=True, slots=True)
class CaptureWriterState:
    index:int
    total_bytes:int
    since_sync:int
    sealed:bool
    active_size:int


@dataclass(frozen=True, slots=True)
class CaptureRotationReceipt:
    from_index:int
    to_index:int
    total_bytes:int


@dataclass(frozen=True, slots=True)
class CaptureSyncReceipt:
    stream:str
    segment_index:int
    total_bytes:int
    synced_bytes:int
    tail_sha256:str
