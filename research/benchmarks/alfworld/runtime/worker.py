from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import json
import os
from pathlib import Path
import sys
from typing import Any


def _emit(kind: str, request_id: str | None, **payload: Any) -> None:
    row = {"type": kind, "request_id": request_id, **payload}
    sys.stdout.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _error(request_id: str | None, code: str, exc: BaseException) -> None:
    _emit("error", request_id, code=code, error_type=type(exc).__name__, message=str(exc)[:1000])


class AlfworldWorker:
    def __init__(self, *, data_root: Path, config_path: Path, split: str) -> None:
        self.data_root = data_root.resolve(strict=True)
        self.config_path = config_path.resolve(strict=True)
        self.split = split
        os.environ["ALFWORLD_DATA"] = str(self.data_root)
        with redirect_stdout(sys.stderr):
            import yaml
            from alfworld.agents.environment.alfred_tw_env import AlfredTWEnv

            with self.config_path.open("r", encoding="utf-8") as handle:
                self.config = yaml.safe_load(handle)
            self.provider = AlfredTWEnv(self.config, train_eval=split)
        self.provider_order = tuple(str(Path(path).resolve()) for path in self.provider.game_files)
        self._allowed = set(self.provider_order)
        self._env = None
        self._current_gamefile: str | None = None

    def close(self) -> None:
        env, self._env = self._env, None
        self._current_gamefile = None
        if env is not None:
            with redirect_stdout(sys.stderr):
                env.close()

    def provider_order_payload(self) -> dict[str, Any]:
        return {
            "split": self.split,
            "count": len(self.provider_order),
            "game_files": list(self.provider_order),
        }

    def reset(self, gamefile: str) -> dict[str, Any]:
        candidate = Path(gamefile)
        if not candidate.is_absolute():
            candidate = self.data_root / "json_2.1.1" / "valid_unseen" / candidate
        resolved = str(candidate.resolve(strict=True))
        if resolved not in self._allowed:
            raise ValueError("requested gamefile is outside the audited provider order")
        self.close()
        original = self.provider.game_files
        try:
            self.provider.game_files = [resolved]
            with redirect_stdout(sys.stderr):
                self._env = self.provider.init_env(batch_size=1)
                observation, info = self._env.reset()
        finally:
            self.provider.game_files = original
        self._current_gamefile = resolved
        return self._state_payload(observation[0], False, info)

    def step(self, action: str) -> dict[str, Any]:
        if self._env is None or self._current_gamefile is None:
            raise RuntimeError("worker must be reset before step")
        if not isinstance(action, str) or not action.strip():
            raise ValueError("ALFWorld action must be non-empty text")
        with redirect_stdout(sys.stderr):
            observation, _score, done, info = self._env.step([action])
        return self._state_payload(observation[0], bool(done[0]), info)

    def _state_payload(self, observation: str, done: bool, info: dict[str, Any]) -> dict[str, Any]:
        won_raw = info.get("won", [False])
        won = bool(won_raw[0]) if isinstance(won_raw, (tuple, list)) else bool(won_raw)
        commands_raw = info.get("admissible_commands", [[]])
        commands = commands_raw[0] if isinstance(commands_raw, (tuple, list)) and commands_raw else []
        if not isinstance(commands, (tuple, list)):
            commands = []
        relative = Path(self._current_gamefile).resolve().relative_to(
            (self.data_root / "json_2.1.1" / "valid_unseen").resolve()
        ).as_posix()
        return {
            "observation": str(observation),
            "done": bool(done),
            "won": won,
            "gamefile": relative,
            "admissible_commands": [str(item) for item in commands],
        }


def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--split", default="eval_out_of_distribution")
    parser.add_argument("--dump-provider-order", action="store_true")
    args = parser.parse_args()
    worker = AlfworldWorker(
        data_root=Path(args.data_root),
        config_path=Path(args.config),
        split=args.split,
    )
    if args.dump_provider_order:
        _emit("provider_order", None, **worker.provider_order_payload())
        worker.close()
        return 0
    try:
        for raw in sys.stdin:
            raw = raw.strip()
            if not raw:
                continue
            request_id = None
            try:
                request = json.loads(raw)
                if not isinstance(request, dict):
                    raise TypeError("request must be a JSON object")
                request_id = None if request.get("request_id") is None else str(request["request_id"])
                cmd = str(request.get("cmd", ""))
                if cmd == "provider_order":
                    _emit("provider_order", request_id, **worker.provider_order_payload())
                elif cmd == "reset":
                    _emit("reset", request_id, **worker.reset(str(request.get("gamefile", ""))))
                elif cmd == "step":
                    _emit("step", request_id, **worker.step(str(request.get("action", ""))))
                elif cmd == "close":
                    worker.close()
                    _emit("closed", request_id)
                    return 0
                else:
                    raise ValueError(f"unsupported command: {cmd}")
            except BaseException as exc:
                _error(request_id, "ALFWORLD_WORKER_REQUEST_FAILED", exc)
    finally:
        worker.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
