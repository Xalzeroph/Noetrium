from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.experimentation.lifecycle.api import BenchmarkSourceResolution
from noetrium_platform.research.experimentation.lifecycle.study.api import (
    BenchmarkResolutionRegistration,
)

from .authority import (
    ALFWORLD_RELEASE_AUTHORITY_DIGEST,
    ALFWORLD_RELEASE_COMMIT,
    ALFWORLD_RELEASE_PROVIDER,
    ALFWORLD_RELEASE_VERSION,
)
from .cut import (
    ALFWORLD_PAPER_EVAL_DATASET_PATH,
    ALFWORLD_PAPER_EVAL_EXPECTED_TASK_COUNT,
    AlfworldTaskRecord,
    bind_alfworld_paper_eval_cut,
)

_RAW_FAMILY_TO_CANONICAL = {
    "pick_and_place_simple": "pick_and_place",
    "pick_clean_then_place_in_recep": "pick_clean_then_place",
    "pick_heat_then_place_in_recep": "pick_heat_then_place",
    "pick_cool_then_place_in_recep": "pick_cool_then_place",
    "look_at_obj_in_light": "look_at_obj",
    "pick_two_obj_and_place": "pick_two_obj",
}
_REQUIRED_TASK_FILES = ("game.tw-pddl", "traj_data.json", "initial_state.pddl")
_REQUIRED_LOGIC_FILES = ("alfred.pddl", "alfred.twl2")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_within(path: Path, root: Path, field: str) -> Path:
    resolved = path.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{field} escapes frozen ALFWorld dataset root") from exc
    return resolved


def _provider_game_files(provider: object) -> tuple[str, ...]:
    raw = getattr(provider, "game_files", None)
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        raise TypeError("ALFWorld provider game_files must be a sequence")
    rows = tuple(raw)
    if any(type(row) is not str or not row.strip() for row in rows):
        raise TypeError("ALFWorld provider game_files must contain non-empty paths")
    if len(rows) != ALFWORLD_PAPER_EVAL_EXPECTED_TASK_COUNT:
        raise ValueError(
            "ALFWorld provider order requires exactly "
            f"{ALFWORLD_PAPER_EVAL_EXPECTED_TASK_COUNT} paper-eval games"
        )
    return rows


@dataclass(frozen=True, slots=True)
class AlfworldMaterialization:
    records: tuple[AlfworldTaskRecord, ...]
    source_digest: str
    resolution: BenchmarkSourceResolution
    provider_order_digest: str


def register_alfworld_materialization(
    materialization: AlfworldMaterialization,
) -> BenchmarkResolutionRegistration:
    """Freeze one verified ALFWorld materialization into Benchmark authority."""

    if type(materialization) is not AlfworldMaterialization:
        raise TypeError(
            "ALFWorld benchmark registration requires AlfworldMaterialization"
        )
    proof_digest = canonical_digest(
        {
            "schema": "alfworld.paper-eval.benchmark-authority-proof.v1",
            "release_authority_digest": ALFWORLD_RELEASE_AUTHORITY_DIGEST,
            "source_digest": materialization.source_digest,
            "provider_order_digest": materialization.provider_order_digest,
            "resolution_digest": materialization.resolution.resolution_digest,
        }
    )
    return BenchmarkResolutionRegistration(
        materialization.resolution,
        proof_digest,
    )


def materialize_alfworld_paper_eval(
    provider: object,
    *,
    data_root: str | Path,
    installed_source_commit: str,
    installed_version: str,
) -> AlfworldMaterialization:
    """Freeze the official ALFWorld provider's eval reset order into task authority.

    The provider is authoritative for game discovery/order. This function does not
    reimplement ALFWorld's os.walk/filtering rules; it only validates and hashes the
    exact games already admitted by the audited provider.
    """

    if installed_source_commit != ALFWORLD_RELEASE_COMMIT:
        raise ValueError("installed ALFWorld source commit does not match audited release")
    if installed_version != ALFWORLD_RELEASE_VERSION:
        raise ValueError("installed ALFWorld version does not match audited release")

    root = Path(data_root).resolve(strict=True)
    eval_root = (root / ALFWORLD_PAPER_EVAL_DATASET_PATH).resolve(strict=True)
    try:
        eval_root.relative_to(root)
    except ValueError as exc:
        raise ValueError("ALFWorld eval root escapes data root") from exc
    logic_root = (root / "logic").resolve(strict=True)
    logic_digests: dict[str, str] = {}
    for name in _REQUIRED_LOGIC_FILES:
        path = _require_within(logic_root / name, root, f"ALFWorld logic file {name}")
        if not path.is_file():
            raise FileNotFoundError(path)
        logic_digests[name] = _sha256(path)

    records: list[AlfworldTaskRecord] = []
    provider_rows: list[dict[str, object]] = []
    seen: set[str] = set()
    for ordinal, raw_gamefile in enumerate(_provider_game_files(provider)):
        gamefile = _require_within(Path(raw_gamefile), eval_root, "ALFWorld provider gamefile")
        if gamefile.name != "game.tw-pddl" or not gamefile.is_file():
            raise ValueError("ALFWorld provider gamefile must identify game.tw-pddl")
        relative = gamefile.relative_to(eval_root).as_posix()
        if relative in seen:
            raise ValueError("ALFWorld provider gamefile order contains duplicates")
        seen.add(relative)

        task_dir = gamefile.parent
        component_digests: dict[str, str] = {}
        for name in _REQUIRED_TASK_FILES:
            path = _require_within(task_dir / name, eval_root, f"ALFWorld task file {name}")
            if not path.is_file():
                raise FileNotFoundError(path)
            component_digests[name] = _sha256(path)

        trajectory = json.loads((task_dir / "traj_data.json").read_text(encoding="utf-8"))
        raw_family = trajectory.get("task_type") if isinstance(trajectory, dict) else None
        if type(raw_family) is not str or raw_family not in _RAW_FAMILY_TO_CANONICAL:
            raise ValueError(f"unsupported ALFWorld task_type: {raw_family!r}")
        family = _RAW_FAMILY_TO_CANONICAL[raw_family]
        content_digest = canonical_digest(
            {
                "authority_digest": ALFWORLD_RELEASE_AUTHORITY_DIGEST,
                "provider": ALFWORLD_RELEASE_PROVIDER,
                "gamefile": relative,
                "family": family,
                "components": component_digests,
            }
        )
        records.append(AlfworldTaskRecord(relative, family, content_digest))
        provider_rows.append(
            {
                "ordinal": ordinal,
                "gamefile": relative,
                "family": family,
                "content_digest": content_digest,
            }
        )

    provider_order_digest = canonical_digest(tuple(provider_rows))
    source_digest = canonical_digest(
        {
            "schema": "alfworld.paper-eval.materialization.v1",
            "authority_digest": ALFWORLD_RELEASE_AUTHORITY_DIGEST,
            "dataset_path": ALFWORLD_PAPER_EVAL_DATASET_PATH,
            "provider_order_digest": provider_order_digest,
            "logic_digests": logic_digests,
            "task_count": len(records),
        }
    )
    frozen = tuple(records)
    resolution = bind_alfworld_paper_eval_cut(
        frozen,
        locator=str(eval_root),
        source_digest=source_digest,
    )
    return AlfworldMaterialization(
        records=frozen,
        source_digest=source_digest,
        resolution=resolution,
        provider_order_digest=provider_order_digest,
    )


__all__ = [
    "AlfworldMaterialization",
    "materialize_alfworld_paper_eval",
    "register_alfworld_materialization",
]
