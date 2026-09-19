from __future__ import annotations

from collections.abc import Mapping
import re

from noetrium_platform.capabilities.environment.api import (
    ActionRequest,
    ActionResult,
)
from noetrium_platform.capabilities.environment.software.api import (
    SoftwareActionKind,
    SoftwareWorldPort,
)
from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    JsonObject,
    JsonValue,
    canonical_digest,
    require_sha256,
    thaw_json,
)
from noetrium_platform.infrastructure.lifecycle.process.api import (
    LocalCommandTimeoutError,
)

from .environment import (
    ChatDevV1EnvironmentApplication,
    ChatDevV1EnvironmentApplyRequest,
    ChatDevV1EnvironmentPreparation,
    ChatDevV1EnvironmentPrepareRequest,
    ChatDevV1PhaseDisposition,
)
from .fidelity import CHATDEV_V1_AUDITED_COMMIT


_SUCCESS_REPORT = "The software run successfully without errors."
_CODE_PHASES = {
    "Coding",
    "CodeComplete",
    "CodeReviewModification",
    "TestModification",
}
_GUI_PROMPT = (
    "The software should be equipped with graphical user interface (GUI) so "
    "that user can visually and graphically use it; so you must choose a GUI "
    "framework (e.g., in Python, you can implement GUI via tkinter, Pygame, "
    "Flexx, PyGUI, etc,)."
)


def _text(value: object, field: str) -> str:
    if type(value) is not str:
        raise TypeError(f"{field} must be text")
    return value


def _mapping(value: object) -> dict[str, JsonValue]:
    decoded = thaw_json(value)
    if not isinstance(decoded, dict):
        raise TypeError("ChatDev v1 state projection must be an object")
    return decoded


def _phase_result(row: Mapping[str, object]) -> dict[str, JsonValue]:
    value = thaw_json(row.get("phase_result", {}))
    return value if isinstance(value, dict) else {}


def _projection(row: Mapping[str, object]) -> dict[str, JsonValue]:
    value = thaw_json(row.get("environment_state_projection", {}))
    return value if isinstance(value, dict) else {}


def _history_state(
    rows: tuple[JsonObject, ...],
) -> dict[str, JsonValue]:
    state: dict[str, JsonValue] = {
        "modality": "",
        "ideas": "",
        "language": "",
        "review_comments": "",
        "error_summary": "",
        "test_reports": "",
    }
    for row in rows:
        if isinstance(row, Mapping):
            state.update(_projection(row))
    return state


def _filename_from_header(header: str) -> str:
    filename = ""
    for match in re.finditer(r"(\w+\.\w+)", header, re.DOTALL):
        filename = match.group().lower()
    return filename


def _filename_from_code(code: str) -> str:
    filename = ""
    for match in re.finditer(r"class (\S+?):\n", code, re.DOTALL):
        filename = match.group(1)
    if filename:
        return filename.lower().split("(")[0] + ".py"
    return ""


def _format_code(code: str) -> str:
    return "\n".join(
        line for line in code.split("\n") if line.strip()
    )


def parse_chatdev_v1_codes(generated_content: str) -> dict[str, str]:
    """Reproduce v1.0.0 Codes parsing without importing the historical project."""

    values: dict[str, str] = {}
    for match in re.finditer(
        r"(.+?)\n```.*?\n(.*?)```",
        generated_content,
        re.DOTALL,
    ):
        code = match.group(2)
        if "CODE" in code:
            continue
        filename = _filename_from_header(match.group(1))
        if "__main__" in code:
            filename = "main.py"
        if not filename:
            filename = _filename_from_code(code)
        if filename and code:
            values[filename] = _format_code(code)
    return values


def parse_chatdev_v1_requirements(generated_content: str) -> str | None:
    values = [
        match.group(1)
        for match in re.finditer(
            r"```\n(.*?)```",
            generated_content,
            re.DOTALL,
        )
    ]
    return None if not values else values[-1]


class ChatDevV1RepositoryWorkspace:
    """ChatDev v1 workspace semantics over the generic software-world port."""

    def __init__(
        self,
        *,
        workspace: SoftwareWorldPort,
        workspace_identity_digest: str,
        context: ExecutionContext,
        python_test_argv: tuple[str, ...] = ("python3", "main.py"),
        pip_install_argv: tuple[str, ...] = ("pip", "install"),
        test_timeout_seconds: float = 3.0,
    ) -> None:
        if not isinstance(workspace, SoftwareWorldPort):
            raise TypeError(
                "ChatDev v1 repository workspace requires SoftwareWorldPort"
            )
        if not isinstance(context, ExecutionContext):
            raise TypeError(
                "ChatDev v1 repository workspace requires ExecutionContext"
            )
        for name, argv in (
            ("python_test_argv", python_test_argv),
            ("pip_install_argv", pip_install_argv),
        ):
            if type(argv) is not tuple or not argv or any(
                type(value) is not str or not value or "\x00" in value
                for value in argv
            ):
                raise ValueError(f"ChatDev v1 {name} must be a safe argv tuple")
        if float(test_timeout_seconds) <= 0:
            raise ValueError("ChatDev v1 test timeout must be positive")
        self._workspace = workspace
        self._workspace_identity_digest = require_sha256(
            workspace_identity_digest,
            "ChatDev v1 workspace identity_digest",
        )
        self._context = context
        self._python_test_argv = python_test_argv
        self._pip_install_argv = pip_install_argv
        self._test_timeout_seconds = float(test_timeout_seconds)

    @property
    def identity_digest(self) -> str:
        return canonical_digest({
            "adapter": "chatdev-v1-repository-workspace",
            "source_commit": CHATDEV_V1_AUDITED_COMMIT,
            "workspace_identity_digest": self._workspace_identity_digest,
            "run_id": self._context.run_id,
            "task_id": self._context.task_id,
            "python_test_argv": self._python_test_argv,
            "pip_install_argv": self._pip_install_argv,
            "test_timeout_seconds": self._test_timeout_seconds,
        })

    def prepare(
        self,
        request: ChatDevV1EnvironmentPrepareRequest,
    ) -> ChatDevV1EnvironmentPreparation:
        if not isinstance(request, ChatDevV1EnvironmentPrepareRequest):
            raise TypeError("ChatDev v1 workspace prepare request is invalid")
        state = _history_state(request.prior_phase_results)
        phase = request.phase_name
        placeholders: dict[str, JsonValue] = {}
        disposition = ChatDevV1PhaseDisposition.EXECUTE
        reason_code = None
        direct_conclusion = None
        receipts: list[JsonValue] = []

        if phase == "DemandAnalysis":
            pass
        elif phase == "LanguageChoose":
            placeholders.update({
                "task": request.task_prompt,
                "modality": state["modality"],
                "ideas": state["ideas"],
            })
        elif phase == "Coding":
            placeholders.update({
                "task": request.task_prompt,
                "modality": state["modality"],
                "ideas": state["ideas"],
                "language": state["language"],
                "gui": _GUI_PROMPT,
            })
        elif phase == "CodeComplete":
            codes = self._codes(request.prior_phase_results)
            files = self._python_files(
                phase=phase,
                cycle_index=request.cycle_index,
            )
            attempts = self._code_complete_attempts(
                request.prior_phase_results
            )
            unimplemented = ""
            for filename in files:
                content = self._read(
                    filename,
                    phase=phase,
                    cycle_index=request.cycle_index,
                )
                if (
                    any(
                        line.strip() == "pass"
                        for line in content.split("\n")
                    )
                    and attempts.get(filename, 0) < 5
                ):
                    unimplemented = filename
                    break
            placeholders.update({
                "task": request.task_prompt,
                "modality": state["modality"],
                "ideas": state["ideas"],
                "language": state["language"],
                "codes": codes,
                "unimplemented_file": unimplemented,
                "pyfiles": files,
                "num_tried": attempts,
                "max_num_implement": 5,
            })
            if not unimplemented:
                disposition = ChatDevV1PhaseDisposition.SKIP
                reason_code = "unimplemented_file_is_empty"
        elif phase == "CodeReviewComment":
            placeholders.update({
                "task": request.task_prompt,
                "modality": state["modality"],
                "ideas": state["ideas"],
                "language": state["language"],
                "codes": self._codes(request.prior_phase_results),
                "images": "",
            })
        elif phase == "CodeReviewModification":
            placeholders.update({
                "task": request.task_prompt,
                "modality": state["modality"],
                "ideas": state["ideas"],
                "language": state["language"],
                "codes": self._codes(request.prior_phase_results),
                "comments": state["review_comments"],
            })
        elif phase == "TestErrorSummary":
            exist_bugs, report, test_receipt = self._test(
                phase=phase,
                cycle_index=request.cycle_index,
            )
            if test_receipt is not None:
                receipts.append(test_receipt)
            placeholders.update({
                "task": request.task_prompt,
                "modality": state["modality"],
                "ideas": state["ideas"],
                "language": state["language"],
                "codes": self._codes(request.prior_phase_results),
                "test_reports": report,
                "exist_bugs_flag": exist_bugs,
            })
            if not exist_bugs:
                disposition = ChatDevV1PhaseDisposition.SKIP
                reason_code = "exist_bugs_flag_is_false"
            elif "ModuleNotFoundError" in report:
                install_receipts = self._repair_missing_modules(
                    report,
                    phase=phase,
                    cycle_index=request.cycle_index,
                )
                receipts.extend(install_receipts)
                disposition = ChatDevV1PhaseDisposition.DIRECT
                reason_code = "module_not_found_repaired"
                direct_conclusion = "nothing need to do"
        elif phase == "TestModification":
            placeholders.update({
                "task": request.task_prompt,
                "modality": state["modality"],
                "ideas": state["ideas"],
                "language": state["language"],
                "codes": self._codes(request.prior_phase_results),
                "test_reports": state["test_reports"],
                "error_summary": state["error_summary"],
            })
        elif phase == "EnvironmentDoc":
            placeholders.update({
                "task": request.task_prompt,
                "modality": state["modality"],
                "ideas": state["ideas"],
                "language": state["language"],
                "codes": self._codes(request.prior_phase_results),
            })
        elif phase == "Manual":
            placeholders.update({
                "task": request.task_prompt,
                "modality": state["modality"],
                "ideas": state["ideas"],
                "language": state["language"],
                "codes": self._codes(request.prior_phase_results),
                "requirements": self._requirements(
                    phase=phase,
                    cycle_index=request.cycle_index,
                ),
            })
        else:
            raise KeyError(f"unsupported ChatDev v1 phase: {phase}")

        return ChatDevV1EnvironmentPreparation(
            phase_name=phase,
            cycle_index=request.cycle_index,
            placeholders=placeholders,
            disposition=disposition,
            reason_code=reason_code,
            direct_conclusion=direct_conclusion,
            environment_digest=self._environment_digest(),
            provider_receipt={
                "workspace_identity_digest": self._workspace_identity_digest,
                "action_receipts": tuple(receipts),
            },
        )

    def apply(
        self,
        request: ChatDevV1EnvironmentApplyRequest,
    ) -> ChatDevV1EnvironmentApplication:
        if not isinstance(request, ChatDevV1EnvironmentApplyRequest):
            raise TypeError("ChatDev v1 workspace apply request is invalid")
        phase = request.phase_name
        projection: dict[str, JsonValue] = {}
        receipts: list[JsonValue] = []

        if phase == "DemandAnalysis":
            projection["modality"] = (
                request.conclusion.split("<INFO>")[-1]
                .lower()
                .replace(".", "")
                .strip()
            )
        elif phase == "LanguageChoose":
            conclusion = request.conclusion
            projection["language"] = (
                conclusion.split("<INFO>")[-1].lower().replace(".", "").strip()
                if "<INFO>" in conclusion
                else conclusion if conclusion else "Python"
            )
        elif phase in _CODE_PHASES:
            if phase in {"Coding", "CodeComplete"} or "```" in request.conclusion:
                receipts.extend(
                    self._write_codes(
                        request.conclusion,
                        phase=phase,
                        cycle_index=request.cycle_index,
                    )
                )
            if phase == "CodeComplete":
                placeholders = _mapping(
                    request.preparation_result.get("placeholders", {})
                )
                projection["unimplemented_file"] = str(
                    placeholders.get("unimplemented_file", "")
                )
            elif phase == "CodeReviewModification":
                projection["modification_conclusion"] = request.conclusion
        elif phase == "CodeReviewComment":
            projection["review_comments"] = request.conclusion
        elif phase == "TestErrorSummary":
            placeholders = _mapping(
                request.preparation_result.get("placeholders", {})
            )
            projection["test_reports"] = str(
                placeholders.get("test_reports", "")
            )
            projection["exist_bugs_flag"] = bool(
                placeholders.get("exist_bugs_flag", False)
            )
            projection["error_summary"] = request.conclusion
        elif phase == "EnvironmentDoc":
            requirements = parse_chatdev_v1_requirements(
                request.conclusion
            )
            if requirements is not None:
                receipts.append(
                    self._edit(
                        "requirements.txt",
                        requirements,
                        phase=phase,
                        cycle_index=request.cycle_index,
                    )
                )
        elif phase == "Manual":
            receipts.append(
                self._edit(
                    "manual.md",
                    request.conclusion,
                    phase=phase,
                    cycle_index=request.cycle_index,
                )
            )
        else:
            raise KeyError(f"unsupported ChatDev v1 phase: {phase}")

        return ChatDevV1EnvironmentApplication(
            phase_name=phase,
            cycle_index=request.cycle_index,
            environment_digest=self._environment_digest(),
            state_projection=projection,
            provider_receipt={
                "workspace_identity_digest": self._workspace_identity_digest,
                "action_receipts": tuple(receipts),
            },
        )

    def _action(
        self,
        kind: SoftwareActionKind,
        payload: JsonObject,
        *,
        phase: str,
        cycle_index: int,
        tag: str,
    ) -> ActionResult:
        generation = self._environment_digest()
        action_id = (
            "chatdev-v1:"
            + canonical_digest({
                "source_commit": CHATDEV_V1_AUDITED_COMMIT,
                "phase": phase,
                "cycle_index": cycle_index,
                "tag": tag,
                "kind": kind.value,
                "payload": payload,
                "workspace_generation": generation,
            })[:32]
        )
        result = self._workspace.act(
            ActionRequest(
                action_id=action_id,
                action_type=kind.value,
                payload=payload,
                context=self._context.child(
                    span_id=f"chatdev:{phase}:{cycle_index}:{tag}",
                    operation_id=action_id,
                    component_id="chatdev-v1-software-workspace",
                ),
            )
        )
        if not isinstance(result, ActionResult):
            raise TypeError("software workspace returned invalid ActionResult")
        return result

    def _environment_digest(self) -> str:
        observation = self._workspace.observe(self._context)
        return require_sha256(
            observation.generation,
            "ChatDev v1 workspace generation",
        )

    def _python_files(
        self,
        *,
        phase: str,
        cycle_index: int,
    ) -> tuple[str, ...]:
        result = self._action(
            SoftwareActionKind.LIST,
            {"suffix": ".py"},
            phase=phase,
            cycle_index=cycle_index,
            tag="list-python",
        )
        if result.observation is None:
            return ()
        payload = _mapping(result.observation.payload)
        values = payload.get("files", ())
        if not isinstance(values, (tuple, list)):
            raise TypeError("software list files must be a sequence")
        return tuple(str(value) for value in values)

    def _read(
        self,
        path: str,
        *,
        phase: str,
        cycle_index: int,
    ) -> str:
        result = self._action(
            SoftwareActionKind.READ,
            {"path": path},
            phase=phase,
            cycle_index=cycle_index,
            tag=f"read:{path}",
        )
        if result.observation is None:
            raise RuntimeError(f"software read returned no observation: {path}")
        payload = _mapping(result.observation.payload)
        return _text(payload.get("content"), f"workspace file {path}")

    def _edit(
        self,
        path: str,
        content: str,
        *,
        phase: str,
        cycle_index: int,
    ) -> JsonValue:
        result = self._action(
            SoftwareActionKind.EDIT,
            {"path": path, "content": content},
            phase=phase,
            cycle_index=cycle_index,
            tag=f"edit:{path}",
        )
        return self._action_receipt(result)

    def _write_codes(
        self,
        conclusion: str,
        *,
        phase: str,
        cycle_index: int,
    ) -> tuple[JsonValue, ...]:
        codes = parse_chatdev_v1_codes(conclusion)
        if phase in {"Coding", "CodeComplete"} and not codes:
            raise ValueError("No Valid Codes.")
        receipts = []
        for filename, content in codes.items():
            receipts.append(
                self._edit(
                    filename,
                    content,
                    phase=phase,
                    cycle_index=cycle_index,
                )
            )
        return tuple(receipts)

    def _codes(self, rows: tuple[JsonObject, ...]) -> str:
        codebook: dict[str, str] = {}
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            if row.get("phase_name") not in _CODE_PHASES:
                continue
            conclusion = _phase_result(row).get("conclusion")
            if type(conclusion) is str:
                codebook.update(parse_chatdev_v1_codes(conclusion))
        output = ""
        for filename in codebook:
            try:
                content = self._read(
                    filename,
                    phase="Context",
                    cycle_index=0,
                )
            except FileNotFoundError:
                continue
            language = (
                "python"
                if filename.endswith(".py")
                else filename.rsplit(".", 1)[-1]
            )
            output += (
                f"{filename}\n```{language}\n{content}\n```\n\n"
            )
        return output

    @staticmethod
    def _code_complete_attempts(
        rows: tuple[JsonObject, ...],
    ) -> dict[str, int]:
        attempts: dict[str, int] = {}
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            if row.get("phase_name") != "CodeComplete":
                continue
            filename = _projection(row).get("unimplemented_file")
            if type(filename) is str and filename:
                attempts[filename] = attempts.get(filename, 0) + 1
        return attempts

    def _requirements(
        self,
        *,
        phase: str,
        cycle_index: int,
    ) -> str:
        try:
            content = self._read(
                "requirements.txt",
                phase=phase,
                cycle_index=cycle_index,
            )
        except FileNotFoundError:
            return ""
        return f"requirements.txt\n```\n{content}\n```\n\n"

    def _test(
        self,
        *,
        phase: str,
        cycle_index: int,
    ) -> tuple[bool, str, JsonValue | None]:
        try:
            result = self._action(
                SoftwareActionKind.TEST,
                {
                    "argv": self._python_test_argv,
                    "timeout_seconds": self._test_timeout_seconds,
                },
                phase=phase,
                cycle_index=cycle_index,
                tag="run-main",
            )
        except LocalCommandTimeoutError:
            # v1.0.0 kills a still-running program after roughly three seconds
            # and treats the no-traceback path as success.
            return False, _SUCCESS_REPORT, {
                "timed_out": True,
                "source_semantics": "kill_after_three_seconds",
            }
        if result.observation is None:
            raise RuntimeError("ChatDev v1 test action returned no observation")
        payload = _mapping(result.observation.payload)
        returncode = payload.get("returncode")
        stderr = str(payload.get("stderr", ""))
        if returncode == 0:
            return False, _SUCCESS_REPORT, self._action_receipt(result)
        if stderr and "traceback" in stderr.lower():
            root = self._workspace.spec.workspace_root.rstrip("/\\")
            report = stderr.replace(root + "/", "").replace(root + "\\", "")
            return True, report, self._action_receipt(result)
        return False, _SUCCESS_REPORT, self._action_receipt(result)

    def _repair_missing_modules(
        self,
        report: str,
        *,
        phase: str,
        cycle_index: int,
    ) -> tuple[JsonValue, ...]:
        receipts = []
        for index, match in enumerate(
            re.finditer(r"No module named '(\S+)'", report, re.DOTALL)
        ):
            module = match.group(1)
            result = self._action(
                SoftwareActionKind.EXECUTE,
                {
                    "argv": (*self._pip_install_argv, module),
                },
                phase=phase,
                cycle_index=cycle_index,
                tag=f"pip-install:{index}:{module}",
            )
            receipts.append(self._action_receipt(result))
        return tuple(receipts)

    @staticmethod
    def _action_receipt(result: ActionResult) -> JsonValue:
        effect = result.effect
        return {
            "action_id": result.action_id,
            "effect": (
                None
                if effect is None
                else {
                    "effect_id": effect.effect_id,
                    "request_digest": effect.request_digest,
                    "effect_class": effect.effect_class.value,
                    "certainty": effect.certainty.value,
                    "provider_instance_id": effect.provider_instance_id,
                    "verification_required": effect.verification_required,
                    "before_artifact": effect.before_artifact,
                    "after_artifact": effect.after_artifact,
                    "provider_receipt": effect.provider_receipt,
                }
            ),
        }


__all__ = [
    "ChatDevV1RepositoryWorkspace",
    "parse_chatdev_v1_codes",
    "parse_chatdev_v1_requirements",
]
