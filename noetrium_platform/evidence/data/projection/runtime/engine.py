from __future__ import annotations

from noetrium_platform.evidence.data.projection.api import ProjectionCheckpoint, ProjectionTail


class ProjectionSourceDrift(RuntimeError):
    pass


class IncrementalProjectionRuntime:
    """Generic verified-watermark + tail-replay engine.

    The source suffix is represented by one ``ProjectionTail`` contract so the
    starting watermark, ending watermark, and item count cannot disagree at the
    call boundary. Projector/source changes require an explicit rebuild.
    """

    def advance(self, *, reducer, store, tail: ProjectionTail):
        current = store.load(reducer.projector_id)
        if current is None:
            if tail.from_cursor.position != 0:
                raise ProjectionSourceDrift("initial projection tail must start at position zero")
            state = reducer.initial()
        else:
            if current.projector_version != reducer.projector_version:
                raise ProjectionSourceDrift("projector version changed; rebuild required")
            if current.cursor.source_id != tail.to_cursor.source_id:
                raise ProjectionSourceDrift("projection source identity changed; rebuild required")
            if tail.from_cursor != current.cursor:
                raise ProjectionSourceDrift("projection tail does not extend the current verified watermark")
            state = current.payload

        for item in tail.items:
            state = reducer.apply(state, item)

        checkpoint = ProjectionCheckpoint(
            reducer.projector_id,
            reducer.projector_version,
            tail.to_cursor,
            state,
            reducer.digest(state),
        )
        store.save(checkpoint)
        return checkpoint


__all__ = ["IncrementalProjectionRuntime", "ProjectionSourceDrift"]
