from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ControlAction(StrEnum):
    VERIFY_RELEASE="verify_release"
    VERIFY_PROMPTS="verify_prompts"
    INVENTORY_HOST="inventory_host"
    VERIFY_MODEL_CERTIFICATES="verify_model_certificates"
    START_MODEL_SERVICES="start_model_services"
    WAIT_MODEL_READY="wait_model_ready"
    VERIFY_RUNTIME_QUALIFICATION="verify_runtime_qualification"
    VERIFY_METHOD_ENV_ABI="verify_method_env_abi"
    START_STUDY="start_study"
    STATUS="status"


@dataclass(frozen=True, slots=True)
class ControlStep:
    action: ControlAction
    mutating: bool
    success_evidence: tuple[str,...]


@dataclass(frozen=True, slots=True)
class ServerStartupPlan:
    steps: tuple[ControlStep,...]


def exact_server_startup_plan()->ServerStartupPlan:
    return ServerStartupPlan((
        ControlStep(ControlAction.VERIFY_RELEASE,False,("release manifest verified",)),
        ControlStep(ControlAction.VERIFY_PROMPTS,False,("prompt generation verified",)),
        ControlStep(ControlAction.INVENTORY_HOST,False,("host inventory fingerprint",)),
        ControlStep(ControlAction.VERIFY_MODEL_CERTIFICATES,False,("qualified deployment certificates",)),
        ControlStep(ControlAction.START_MODEL_SERVICES,True,("process identities","service generation")),
        ControlStep(ControlAction.WAIT_MODEL_READY,False,("READY evidence",)),
        ControlStep(ControlAction.VERIFY_RUNTIME_QUALIFICATION,False,("exact live runtime qualification receipt",)),
        ControlStep(ControlAction.VERIFY_METHOD_ENV_ABI,False,("method/environment identity",)),
        ControlStep(ControlAction.START_STUDY,True,("study supervisor lifetime","checkpoint root")),
        ControlStep(ControlAction.STATUS,False,("joined platform status",)),
    ))
