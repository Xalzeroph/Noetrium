"""Research implementation schemas over the universal NoetriumUnit.

There is no implementation dataclass carrier. Python, Method and native executable Unit
implementations are immutable implementation Units; import/materialization are
pure projections that fail closed on source or graph drift.
"""
from __future__ import annotations


from noetrium_platform.research.experimentation.api import (
    PARTICIPANT_IMPLEMENTATION_TRAIT,
    require_participant_implementation,
    participant_implementation_id,
    participant_implementation_schema,
    participant_implementation_version,
)

from collections.abc import Callable, Mapping
import hashlib
import inspect

from noetrium_platform.foundation.kernel.structure import (
    implementation_digest,
    implementation_field,
    implementation_unit,
    callable_implementation_unit,
    import_symbol,
    require_implementation,
    resolve_callable,
)
from noetrium_platform.foundation.kernel.kernel import (
    JsonInput,
    JsonValue,
    canonical_digest,
    freeze_json,
    require_sha256,
    thaw_json,
)
from noetrium_platform.foundation.kernel.structure import NoetriumUnit
from noetrium_platform.foundation.kernel.unit import unit_token
from noetrium_platform.foundation.kernel.kernel.universal import (
    unit_operation_name,
    executable_unit_domain,
    executable_unit_nodes,
    validate_executable_unit,
)
from noetrium_platform.research.experimentation.api import (
    method_program_artifact_kinds,
    method_program_configuration,
    method_program_entrypoint,
    method_program_evidence_obligations,
    method_program_execution_class,
    method_program_identity,
    method_program_input_schema,
    method_program_metric_names,
    method_program_output_schema,
    method_program_state_schema,
    validate_method_program,
)


PYTHON_IMPLEMENTATION_TYPE = "python.callable"
METHOD_IMPLEMENTATION_TYPE = "research.method"
EXECUTABLE_UNIT_IMPLEMENTATION_TYPE = "research.executable-unit"


def _clean_text(value: str, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field} must be non-empty")
    return value.strip()


def _importable_coordinates(module: str, qualname: str) -> tuple[str, str]:
    module = _clean_text(module, "implementation module")
    qualname = _clean_text(qualname, "implementation qualname")
    if module == "__main__":
        raise ValueError("implementation must live in an importable module")
    if "<locals>" in qualname or "<lambda>" in qualname:
        raise ValueError(
            "implementation must be a module-resolvable named symbol"
        )
    return module, qualname


def _inspect_source_digest(value: Callable[..., object]) -> str:
    try:
        source = inspect.getsource(value)
    except (OSError, TypeError) as exc:
        raise ValueError("implementation callable source cannot be resolved") from exc
    normalized = source.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def python_implementation(
    implementation_id: str,
    module: str,
    qualname: str,
    source_digest: str,
) -> NoetriumUnit:
    implementation_id = unit_token(
        implementation_id, "research implementation_id"
    )
    module, qualname = _importable_coordinates(module, qualname)
    require_sha256(source_digest, "research implementation source_digest")
    identity = {
        "module": module,
        "qualname": qualname,
        "source_digest": source_digest,
    }
    return implementation_unit(
        implementation_id,
        implementation_type=PYTHON_IMPLEMENTATION_TYPE,
        fields=identity,
        identity_fields=identity,
    )


def python_implementation_from_callable(
    implementation_id: str,
    implementation: Callable[..., object],
) -> NoetriumUnit:
    return callable_implementation_unit(
        implementation_id,
        implementation,
        implementation_type=PYTHON_IMPLEMENTATION_TYPE,
    )


def resolve_python_implementation(
    implementation: NoetriumUnit,
) -> Callable[..., object]:
    require_implementation(implementation, PYTHON_IMPLEMENTATION_TYPE)
    return resolve_callable(
        implementation,
        observed_source_digest=_inspect_source_digest,
    )


def _materialize_method(
    *,
    method_id: str,
    configurer: Callable[..., object],
    entrypoint: str,
    version: str,
    semantic_contract: str,
    method_configuration: JsonValue,
    execution: str,
    evidence: tuple[str, ...],
    metrics: tuple[str, ...],
    artifacts: tuple[str, ...],
    state_schema: str,
    input_schema: str,
    output_schema: str,
    args: tuple[JsonValue, ...],
    kwargs: JsonValue,
) -> NoetriumUnit:
    """Resolve one method implementation directly to its immutable Method Unit."""

    result = configurer(
        *(thaw_json(row) for row in args),
        **dict(thaw_json(kwargs)),
    )
    if type(result) is not NoetriumUnit:
        raise TypeError(
            "research method configurer must return a research.method NoetriumUnit"
        )
    # Full structural validation is intentionally single-pass here.  Public
    # MethodProgram accessors remain fail-close and validate independently, but
    # re-entering them after this exact immutable Unit has just been validated
    # would rescan the same graph once per projected field (formerly ~12x).
    validate_method_program(result)
    params = result.parameters
    implementations = tuple(
        child
        for child in result.members
        if child.has_trait(PARTICIPANT_IMPLEMENTATION_TRAIT)
    )
    if len(implementations) != 1:
        # Defensive invariant: validate_method_program already proves this.
        raise RuntimeError(
            "validated research method lost its unique participant implementation"
        )
    implementation = require_participant_implementation(implementations[0])
    expected_configuration = freeze_json(thaw_json(method_configuration))
    checks = (
        ("method_id", participant_implementation_id(implementation), method_id),
        ("version", participant_implementation_version(implementation), version),
        ("semantic_contract", participant_implementation_schema(implementation), semantic_contract),
        ("entrypoint", str(params["entrypoint"]), entrypoint),
        ("state_schema", str(params["state_schema"]), state_schema),
        ("input_schema", str(params["input_schema"]), input_schema),
        ("output_schema", str(params["output_schema"]), output_schema),
        ("execution", str(params["execution_class"]), execution),
        ("evidence", tuple(params.get("evidence_obligations", ())), evidence),
        ("metrics", tuple(params.get("metric_names", ())), metrics),
        ("artifacts", tuple(params.get("artifact_kinds", ())), artifacts),
    )
    for field, observed, expected in checks:
        if observed != expected:
            raise ValueError(
                f"research method {field} drifted: "
                f"expected={expected!r}, observed={observed!r}"
            )
    observed_configuration = params.get("configuration", {})
    if not isinstance(observed_configuration, Mapping):
        # Defensive invariant: validate_method_program already proves this.
        raise RuntimeError("validated research method configuration is not an object")
    if freeze_json(observed_configuration) != expected_configuration:
        raise ValueError("research method configuration drifted")
    return result


def method_implementation(
    implementation_id: str,
    method_id: str,
    module: str,
    qualname: str,
    source_digest: str,
    method_digest: str,
    entrypoint: str,
    version: str = "1",
    semantic_contract: str = "research.method.v1",
    method_configuration: JsonValue = None,
    execution: str = "effect_recorded",
    evidence: tuple[str, ...] = (),
    metrics: tuple[str, ...] = (),
    artifacts: tuple[str, ...] = (),
    state_schema: str = "json",
    input_schema: str = "json",
    output_schema: str = "json",
    configurer_args: tuple[JsonValue, ...] = (),
    configurer_kwargs: JsonValue = None,
) -> NoetriumUnit:
    implementation_id = unit_token(
        implementation_id, "research method implementation_id"
    )
    method_id = unit_token(method_id, "research method method_id")
    module, qualname = _importable_coordinates(module, qualname)
    require_sha256(source_digest, "research method source_digest")
    require_sha256(method_digest, "research method unit digest")
    entrypoint = _clean_text(entrypoint, "research method entrypoint")
    version = _clean_text(version, "research method version")
    semantic_contract = _clean_text(
        semantic_contract, "research method semantic_contract"
    )
    execution = _clean_text(execution, "research method execution")
    state_schema = _clean_text(state_schema, "research method state_schema")
    input_schema = _clean_text(input_schema, "research method input_schema")
    output_schema = _clean_text(output_schema, "research method output_schema")
    configuration = freeze_json(
        {} if method_configuration is None else method_configuration
    )
    args = freeze_json(configurer_args)
    kwargs = freeze_json(
        {} if configurer_kwargs is None else configurer_kwargs
    )
    if not isinstance(configuration, Mapping):
        raise TypeError("research method configuration must be an object")
    if type(args) is not tuple:
        raise TypeError("research method configurer_args must remain tuple")
    if not isinstance(kwargs, Mapping):
        raise TypeError("research method configurer_kwargs must be an object")
    for field_name, values in (
        ("evidence", evidence),
        ("metrics", metrics),
        ("artifacts", artifacts),
    ):
        if type(values) is not tuple or any(
            type(row) is not str or not row.strip() for row in values
        ):
            raise TypeError(
                f"research method {field_name} must be a text tuple"
            )

    fields = {
        "method_id": method_id,
        "module": module,
        "qualname": qualname,
        "source_digest": source_digest,
        "method_digest": method_digest,
        "entrypoint": entrypoint,
        "version": version,
        "semantic_contract": semantic_contract,
        "method_configuration": configuration,
        "execution": execution,
        "evidence": evidence,
        "metrics": metrics,
        "artifacts": artifacts,
        "state_schema": state_schema,
        "input_schema": input_schema,
        "output_schema": output_schema,
        "configurer_args": args,
        "configurer_kwargs": kwargs,
    }
    return implementation_unit(
        implementation_id,
        implementation_type=METHOD_IMPLEMENTATION_TYPE,
        fields=fields,
        identity_fields=fields,
    )


def method_implementation_from_configurer(
    implementation_id: str,
    configurer: Callable[..., object],
    *,
    method_id: str | None = None,
    entrypoint: str,
    version: str = "1",
    semantic_contract: str = "research.method.v1",
    method_configuration: JsonInput = None,
    execution: str = "effect_recorded",
    evidence: tuple[str, ...] = (),
    metrics: tuple[str, ...] = (),
    artifacts: tuple[str, ...] = (),
    state_schema: str = "json",
    input_schema: str = "json",
    output_schema: str = "json",
    args: tuple[JsonValue, ...] = (),
    kwargs: JsonInput = None,
) -> NoetriumUnit:
    resolved_method_id = implementation_id if method_id is None else method_id
    return callable_implementation_unit(
        implementation_id,
        configurer,
        implementation_type=METHOD_IMPLEMENTATION_TYPE,
        fields={
            "method_id": unit_token(resolved_method_id, "research method method_id"),
            "entrypoint": _clean_text(entrypoint, "research method entrypoint"),
            "version": _clean_text(version, "research method version"),
            "semantic_contract": _clean_text(semantic_contract, "research method semantic_contract"),
            "method_configuration": freeze_json({} if method_configuration is None else method_configuration),
            "execution": _clean_text(execution, "research method execution"),
            "evidence": evidence,
            "metrics": metrics,
            "artifacts": artifacts,
            "state_schema": _clean_text(state_schema, "research method state_schema"),
            "input_schema": _clean_text(input_schema, "research method input_schema"),
            "output_schema": _clean_text(output_schema, "research method output_schema"),
            "configurer_args": freeze_json(args),
            "configurer_kwargs": freeze_json({} if kwargs is None else kwargs),
        },
    )


def resolve_method_implementation(
    implementation: NoetriumUnit,
) -> NoetriumUnit:
    require_implementation(implementation, METHOD_IMPLEMENTATION_TYPE)
    configurer = resolve_callable(
        implementation,
        observed_source_digest=_inspect_source_digest,
    )
    method = _materialize_method(
        method_id=str(implementation_field(implementation, "method_id")),
        configurer=configurer,
        entrypoint=str(implementation_field(implementation, "entrypoint")),
        version=str(implementation_field(implementation, "version")),
        semantic_contract=str(
            implementation_field(implementation, "semantic_contract")
        ),
        method_configuration=implementation_field(
            implementation, "method_configuration"
        ),
        execution=str(implementation_field(implementation, "execution")),
        evidence=tuple(implementation_field(implementation, "evidence", ())),
        metrics=tuple(implementation_field(implementation, "metrics", ())),
        artifacts=tuple(implementation_field(implementation, "artifacts", ())),
        state_schema=str(
            implementation_field(implementation, "state_schema")
        ),
        input_schema=str(
            implementation_field(implementation, "input_schema")
        ),
        output_schema=str(
            implementation_field(implementation, "output_schema")
        ),
        args=tuple(
            implementation_field(implementation, "configurer_args", ())
        ),
        kwargs=implementation_field(
            implementation, "configurer_kwargs", {}
        ),
    )
    return method


def executable_unit_implementation(
    implementation_id: str,
    program_module: str,
    program_qualname: str,
    operations_module: str,
    operations_qualname: str,
    program_digest: str,
    domain: str,
    operations_digest: str,
    operation_identities: tuple[tuple[str, str], ...],
) -> NoetriumUnit:
    implementation_id = unit_token(
        implementation_id, "executable Unit implementation_id"
    )
    program_module, program_qualname = _importable_coordinates(
        program_module, program_qualname
    )
    operations_module, operations_qualname = _importable_coordinates(
        operations_module, operations_qualname
    )
    domain = _clean_text(domain, "executable Unit domain")
    require_sha256(program_digest, "executable Unit program_digest")
    require_sha256(operations_digest, "executable Unit operations_digest")
    if type(operation_identities) is not tuple or any(
        type(row) is not tuple
        or len(row) != 2
        or type(row[0]) is not str
        or not row[0].strip()
        or type(row[1]) is not str
        for row in operation_identities
    ):
        raise TypeError(
            "executable Unit operation identities must be text pairs"
        )
    identities = tuple(
        sorted((name.strip(), digest) for name, digest in operation_identities)
    )
    if len({name for name, _ in identities}) != len(identities):
        raise ValueError("executable Unit operation names must be unique")
    for _name, digest in identities:
        require_sha256(
            digest, "executable Unit operation implementation_digest"
        )
    if canonical_digest(identities) != operations_digest:
        raise ValueError("executable Unit operations digest drifted")
    fields = {
        "program_module": program_module,
        "program_qualname": program_qualname,
        "operations_module": operations_module,
        "operations_qualname": operations_qualname,
        "program_digest": program_digest,
        "domain": domain,
        "operations_digest": operations_digest,
        "operation_identities": identities,
    }
    return implementation_unit(
        implementation_id,
        implementation_type=EXECUTABLE_UNIT_IMPLEMENTATION_TYPE,
        fields=fields,
        identity_fields=fields,
    )


def executable_unit_implementation_from_symbols(
    implementation_id: str,
    *,
    program_module: str,
    program_qualname: str,
    operations_module: str,
    operations_qualname: str,
) -> NoetriumUnit:
    program = import_symbol(program_module, program_qualname)
    if type(program) is not NoetriumUnit:
        raise TypeError(
            "executable Unit binding must resolve to NoetriumUnit"
        )
    validate_executable_unit(program)
    domain = executable_unit_domain(program)

    factory = import_symbol(operations_module, operations_qualname)
    if not callable(factory):
        raise TypeError(
            "executable Unit operations binding must be callable"
        )
    try:
        operations = factory()
    except Exception as exc:
        raise ValueError(
            "executable Unit operation factory failed to materialize"
        ) from exc
    if type(operations) is not tuple:
        raise TypeError(
            "executable Unit operation factory must return a tuple"
        )
    identities: list[tuple[str, str]] = []
    for operation in operations:
        name = getattr(operation, "operation", None)
        digest = getattr(operation, "implementation_digest", None)
        if type(name) is not str or not name.strip() or type(digest) is not str:
            raise TypeError(
                "executable Unit operation set contains invalid entries"
            )
        require_sha256(
            digest, "executable Unit operation implementation_digest"
        )
        identities.append((name.strip(), digest))
    normalized = tuple(sorted(identities))
    if len({name for name, _ in normalized}) != len(normalized):
        raise ValueError("executable Unit operation names must be unique")

    required_operations = tuple(
        sorted(
            {
                unit_operation_name(node)
                for node in executable_unit_nodes(program)
                if not unit_operation_name(node).startswith("core.")
            }
        )
    )
    actual_operations = tuple(name for name, _ in normalized)
    if actual_operations != required_operations:
        raise ValueError(
            "executable Unit operation closure is not exact: "
            f"required={required_operations}, actual={actual_operations}"
        )
    return executable_unit_implementation(
        implementation_id,
        program_module,
        program_qualname,
        operations_module,
        operations_qualname,
        program.unit_digest,
        domain,
        canonical_digest(normalized),
        normalized,
    )


def resolve_executable_unit_implementation(
    implementation: NoetriumUnit,
) -> tuple[NoetriumUnit, tuple[object, ...]]:
    require_implementation(
        implementation, EXECUTABLE_UNIT_IMPLEMENTATION_TYPE
    )
    program = import_symbol(
        str(implementation_field(implementation, "program_module")),
        str(implementation_field(implementation, "program_qualname")),
    )
    if type(program) is not NoetriumUnit:
        raise TypeError(
            "executable Unit implementation no longer resolves to Unit"
        )
    validate_executable_unit(program)
    expected_program = implementation_field(
        implementation, "program_digest"
    )
    require_sha256(expected_program, "executable Unit expected program digest")
    if program.unit_digest != expected_program:
        raise ValueError("research machine program drifted")

    factory = import_symbol(
        str(implementation_field(implementation, "operations_module")),
        str(implementation_field(implementation, "operations_qualname")),
    )
    if not callable(factory):
        raise TypeError(
            "executable Unit operation binding no longer callable"
        )
    operations = factory()
    if type(operations) is not tuple:
        raise TypeError(
            "executable Unit operation factory must return tuple"
        )
    identities = tuple(
        sorted(
            (
                getattr(row, "operation"),
                getattr(row, "implementation_digest"),
            )
            for row in operations
        )
    )
    expected_identities = tuple(
        implementation_field(
            implementation, "operation_identities", ()
        )
    )
    if identities != expected_identities:
        raise ValueError(
            "executable Unit operation identity set drifted"
        )
    expected_operations = implementation_field(
        implementation, "operations_digest"
    )
    require_sha256(
        expected_operations, "executable Unit operations_digest"
    )
    if canonical_digest(identities) != expected_operations:
        raise ValueError("executable Unit operation digest drifted")
    expected_domain = str(
        implementation_field(implementation, "domain")
    )
    if executable_unit_domain(program) != expected_domain:
        raise ValueError("executable Unit domain drifted")
    return program, operations


__all__ = [
    "EXECUTABLE_UNIT_IMPLEMENTATION_TYPE",
    "METHOD_IMPLEMENTATION_TYPE",
    "PYTHON_IMPLEMENTATION_TYPE",
    "executable_unit_implementation",
    "executable_unit_implementation_from_symbols",
    "method_implementation",
    "method_implementation_from_configurer",
    "python_implementation",
    "python_implementation_from_callable",
    "resolve_executable_unit_implementation",
    "resolve_method_implementation",
    "resolve_python_implementation",
]
