from __future__ import annotations

import hashlib
from pathlib import Path
from threading import RLock

from noetrium_platform.foundation.kernel.kernel.errors import describe_exception

from .segment_writer import RawSegmentWriter


def _identity_component(prefix: str, value: str) -> str:
    if not value:
        raise ValueError(f"raw observation {prefix} identity must be non-empty")
    digest = hashlib.sha256(value.encode("utf-8", "surrogatepass")).hexdigest()
    return f"{prefix}-{digest}"


class RawSegmentPool:
    """Short-lock registry for actor-owned raw segment writers."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self._lock = RLock()
        self._writers: dict[tuple[str, str], RawSegmentWriter] = {}
        self._closed = False

    @staticmethod
    def target(root: Path, run_id: str, family: str) -> Path:
        base = Path(root).resolve()
        run_component = _identity_component("run", run_id)
        family_component = _identity_component("family", family)
        target = base / run_component / f"{family_component}.jsonl"
        if base not in target.parents:
            raise ValueError("raw observation segment escaped persistence root")
        return target

    def get(self, run_id: str, family: str, schema_version: str) -> RawSegmentWriter:
        key = (run_id, family)
        with self._lock:
            if self._closed:
                raise RuntimeError("raw segment pool is closed")
            existing = self._writers.get(key)
            if existing is not None:
                if existing.schema_version != schema_version:
                    raise ValueError(
                        f"raw segment schema drift for {key}: "
                        f"{existing.schema_version} != {schema_version}"
                    )
                return existing

        candidate = RawSegmentWriter(
            self.target(self.root, run_id, family),
            family,
            schema_version,
            run_id,
        )
        discard: RawSegmentWriter | None = None
        primary: BaseException | None = None
        try:
            with self._lock:
                if self._closed:
                    discard = candidate
                    raise RuntimeError("raw segment pool is closed")
                existing = self._writers.get(key)
                if existing is None:
                    self._writers[key] = candidate
                    return candidate
                if existing.schema_version != schema_version:
                    discard = candidate
                    raise ValueError(
                        f"raw segment schema drift for {key}: "
                        f"{existing.schema_version} != {schema_version}"
                    )
                discard = candidate
                return existing
        except BaseException as exc:
            primary = exc
            raise
        finally:
            if discard is not None:
                try:
                    discard.close()
                except BaseException as close_exc:
                    if primary is None:
                        raise
                    descriptor = describe_exception(close_exc)
                    primary.add_note(
                        "raw segment candidate cleanup failed: "
                        f"{descriptor.error_type}; error_digest={descriptor.error_digest}"
                    )

    def seal(self) -> tuple[tuple[tuple[str, str], RawSegmentWriter], ...]:
        with self._lock:
            if self._closed:
                return ()
            self._closed = True
            return tuple(self._writers.items())
