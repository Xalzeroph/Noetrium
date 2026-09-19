from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path

from noetrium_platform.foundation.kernel.kernel.durability.durable_file import atomic_replace_bytes

from noetrium_platform.infrastructure.lifecycle.process.api import (
    ByteSegment,
    CaptureIntegrityError,
    CaptureManifest,
    CaptureWriterState,
)


class CaptureStorage:
    """Pure filesystem projection for segmented process capture."""

    def __init__(self,root:Path,stream:str)->None:
        self.root=root; self.stream=stream; root.mkdir(parents=True,exist_ok=True)
        self.manifest_path=root/f"{stream}.manifest.json"
        self.resume_path=root/f"{stream}.resume.json"

    def path(self,index:int)->Path:
        return self.root/f"{self.stream}.{index:06d}.bin"

    def files(self)->tuple[Path,...]:
        return tuple(sorted(self.root.glob(f"{self.stream}.[0-9][0-9][0-9][0-9][0-9][0-9].bin")))

    def sized_files(self) -> tuple[tuple[Path, int], ...]:
        """Freeze one ordered segment-name/size snapshot with one directory scan."""
        return tuple((path, path.stat().st_size) for path in self.files())

    @staticmethod
    def _resume_digest(payload: dict[str, object]) -> str:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        return hashlib.sha256(raw).hexdigest()

    def write_resume_state(self, state: CaptureWriterState) -> None:
        """Publish a rebuildable O(1)-reopen checkpoint after durable writer state."""
        payload: dict[str, object] = {
            "schema_version": 1,
            "stream": self.stream,
            "index": state.index,
            "total_bytes": state.total_bytes,
            "active_size": state.active_size,
            "sealed": state.sealed,
        }
        document = {**payload, "resume_sha256": self._resume_digest(payload)}
        atomic_replace_bytes(
            self.resume_path,
            json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(),
        )

    def _read_resume_state(self) -> CaptureWriterState | None:
        if not self.resume_path.exists():
            return None
        try:
            document = json.loads(self.resume_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise CaptureIntegrityError("capture resume checkpoint is unreadable") from exc
        if not isinstance(document, dict):
            raise CaptureIntegrityError("capture resume checkpoint must be an object")
        expected = {
            "schema_version", "stream", "index", "total_bytes", "active_size", "sealed", "resume_sha256"
        }
        if set(document) != expected:
            raise CaptureIntegrityError("capture resume checkpoint fields are not exact")
        payload = {key: document[key] for key in expected if key != "resume_sha256"}
        if document.get("resume_sha256") != self._resume_digest(payload):
            raise CaptureIntegrityError("capture resume checkpoint digest mismatch")
        if document.get("schema_version") != 1 or document.get("stream") != self.stream:
            raise CaptureIntegrityError("capture resume checkpoint identity mismatch")
        index = document.get("index")
        total = document.get("total_bytes")
        active = document.get("active_size")
        sealed = document.get("sealed")
        if type(index) is not int or type(total) is not int or type(active) is not int or type(sealed) is not bool:
            raise CaptureIntegrityError("capture resume checkpoint types are invalid")
        if index < 0 or total < 0 or active < 0 or active > total:
            raise CaptureIntegrityError("capture resume checkpoint counters are invalid")
        return CaptureWriterState(index, total, 0, sealed, active)

    def _resume_matches_disk(self, state: CaptureWriterState) -> bool:
        if state.sealed != self.manifest_path.exists():
            return False
        current = self.path(state.index)
        if state.total_bytes == 0:
            if current.exists() and current.stat().st_size != 0:
                return False
        elif not current.exists() or current.stat().st_size != state.active_size:
            return False
        if self.path(state.index + 1).exists():
            return False
        if state.index > 0 and not self.path(state.index - 1).exists():
            return False
        return True

    def _scan_resume_state(self) -> CaptureWriterState:
        sized = self.sized_files()
        total = 0
        active_size = 0
        for index, (path, size) in enumerate(sized):
            if path.name != self.path(index).name:
                raise CaptureIntegrityError(f"segment sequence gap at {index}")
            total += size
            active_size = size
        last_index = len(sized) - 1 if sized else 0
        return CaptureWriterState(last_index, total, 0, self.manifest_path.exists(), active_size)

    def resume_state(self) -> CaptureWriterState:
        """Load the fast checkpoint or explicitly rebuild stale/missing state from disk."""
        state = self._read_resume_state()
        if state is not None and self._resume_matches_disk(state):
            return state
        rebuilt = self._scan_resume_state()
        self.write_resume_state(rebuilt)
        return rebuilt

    def load_tail_from_state(self, state: CaptureWriterState, limit: int) -> bytes:
        """Read only the bounded suffix, independent of total historical segment count."""
        remaining = min(state.total_bytes, limit)
        if remaining <= 0:
            return b""
        parts: list[bytes] = []
        index = state.index
        while remaining > 0 and index >= 0:
            path = self.path(index)
            if not path.exists():
                raise CaptureIntegrityError(f"capture tail segment missing: {index}")
            size = path.stat().st_size
            wanted = min(remaining, size)
            with path.open("rb") as handle:
                handle.seek(size - wanted)
                chunk = handle.read(wanted)
            if len(chunk) != wanted:
                raise CaptureIntegrityError(f"capture tail segment truncated: {index}")
            parts.append(chunk)
            remaining -= wanted
            index -= 1
        if remaining:
            raise CaptureIntegrityError("capture resume total exceeds available segment bytes")
        return b"".join(reversed(parts))

    def scan_segments(self)->tuple[ByteSegment,...]:
        out=[]; offset=0
        for i,p in enumerate(self.files()):
            if p.name!=self.path(i).name:
                raise CaptureIntegrityError(f"segment sequence gap at {i}")
            h=hashlib.sha256(); size=0
            with p.open("rb",buffering=1024*1024) as fh:
                while chunk:=fh.read(1024*1024):
                    h.update(chunk); size+=len(chunk)
            out.append(ByteSegment(i,p.name,offset,offset+size,size,h.hexdigest()))
            offset+=size
        return tuple(out)

    def build_manifest(self,segments:tuple[ByteSegment,...],sealed:bool)->CaptureManifest:
        total=sum(x.size for x in segments)
        base={
            "schema_version":1,
            "stream":self.stream,
            "total_bytes":total,
            "segments":[asdict(x) for x in segments],
            "sealed":sealed,
        }
        digest=hashlib.sha256(
            json.dumps(base,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
        ).hexdigest()
        return CaptureManifest(1,self.stream,total,segments,sealed,digest)

    def write_manifest(self,manifest:CaptureManifest)->None:
        raw=json.dumps(asdict(manifest),sort_keys=True,ensure_ascii=False,indent=2).encode()
        atomic_replace_bytes(self.manifest_path, raw)

    def verify_manifest(self)->CaptureManifest:
        segments=self.scan_segments()
        actual=self.build_manifest(segments,self.manifest_path.exists())
        if not self.manifest_path.exists():
            return actual
        stored=json.loads(self.manifest_path.read_text(encoding="utf-8"))
        expected=tuple(ByteSegment(**x) for x in stored["segments"])
        if expected!=segments or stored["total_bytes"]!=actual.total_bytes or not stored.get("sealed"):
            raise CaptureIntegrityError("sealed capture segment digest/size mismatch")
        if actual.manifest_sha256!=stored.get("manifest_sha256"):
            raise CaptureIntegrityError("capture manifest digest mismatch")
        return actual

    def total_size(self)->int:
        return sum(p.stat().st_size for p in self.files())

    def active_size(self)->int:
        files=self.files()
        return files[-1].stat().st_size if files else 0

    def read_range_unverified(self,offset:int,length:int)->bytes:
        """Read a bounded byte range without manifest verification.

        Algorithm-Complexity: O(N)
        Algorithm-Rationale: N is segment metadata visited plus requested bytes consumed; inner readinto calls partition the requested range and therefore sum rather than multiply across segments.
        """
        if offset < 0 or length < 0:
            raise ValueError("offset and length must be non-negative")
        if length == 0:
            return b""

        # Snapshot segment sizes once so the output buffer is exactly bounded by
        # available capture data.  This avoids the old list-of-chunks + join
        # double residency while also avoiding an attacker-sized allocation when
        # ``length`` extends past EOF.
        segments: list[tuple[Path, int, int, int]] = []
        cursor = 0
        for path in self.files():
            size = path.stat().st_size
            segments.append((path, size, cursor, cursor + size))
            cursor += size
        available = max(0, min(length, cursor - offset))
        if available == 0:
            return b""

        target_end = offset + available
        buffer = bytearray(available)
        written = 0
        for path, _size, seg_start, seg_end in segments:
            if seg_end <= offset or seg_start >= target_end:
                continue
            local_start = max(offset, seg_start) - seg_start
            local_end = min(target_end, seg_end) - seg_start
            wanted = local_end - local_start
            with path.open("rb", buffering=1024 * 1024) as handle:
                handle.seek(local_start)
                view = memoryview(buffer)[written : written + wanted]
                consumed = 0
                while consumed < wanted:
                    count = handle.readinto(view[consumed:])
                    if not count:
                        break
                    consumed += count
                written += consumed
                if consumed != wanted:
                    # The unverified API permits concurrent files, but it must not
                    # expose zero-filled bytes when a segment is truncated mid-read.
                    return bytes(buffer[:written])
        return bytes(buffer[:written])

    def load_tail(self,total:int,limit:int)->bytes:
        remaining=min(total,limit)
        return self.read_range_unverified(total-remaining,remaining) if remaining else b""
