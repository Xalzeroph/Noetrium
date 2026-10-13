from __future__ import annotations

from ..api.contracts import RuntimeStage


class RuntimeStageAudit:
    def __init__(self, stages: tuple[RuntimeStage, ...], declared_events: set[str]) -> None:
        self.stages = stages
        self.declared_events = declared_events

    def run(self) -> tuple[str, ...]:
        errors: list[str] = []
        seen: set[str] = set()
        for stage in self.stages:
            if stage.stage_id in seen:
                errors.append(f"duplicate stage: {stage.stage_id}")
            seen.add(stage.stage_id)
            for name in (stage.start_event, stage.success_event, stage.failure_event):
                if name not in self.declared_events:
                    errors.append(f"stage {stage.stage_id} references unknown event {name}")
        return tuple(errors)


__all__ = ["RuntimeStageAudit"]
