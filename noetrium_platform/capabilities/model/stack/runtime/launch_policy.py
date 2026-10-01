from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.capabilities.model.stack.api import ModelStackSpec


_PLATFORM_OWNED_VLLM_FLAGS = frozenset({
    "--enable-reasoning",
    "--reasoning-parser",
    "--enable-auto-tool-choice",
    "--tool-call-parser",
    "--kv-cache-dtype",
    "--scheduling-policy",
    "--enable-prefix-caching",
    "--no-enable-prefix-caching",
    "--prefix-caching-hash-algo",
    "--enable-chunked-prefill",
    "--no-enable-chunked-prefill",
    "--max-num-batched-tokens",
    "--max-model-len",
    "--dtype",
    "--quantization",
})


def _contains_flag(args: tuple[str, ...], flag: str) -> bool:
    return any(item == flag or item.startswith(flag + "=") for item in args)


@dataclass(frozen=True, slots=True)
class ModelStackLaunchSettings:
    engine_args: tuple[str, ...]
    environment: tuple[tuple[str, str], ...] = ()


def model_stack_launch_settings(
    stack: ModelStackSpec,
) -> ModelStackLaunchSettings:
    """Render one frozen stack into exact engine process settings.

    Typed ModelStackSpec fields are authoritative. Engine-specific free-form
    arguments remain available only for semantics that do not already have a
    typed platform owner.
    """

    if not isinstance(stack, ModelStackSpec):
        raise TypeError("model stack launch settings require ModelStackSpec")
    if type(stack.engine_args) is not tuple or any(
        type(item) is not str or not item
        for item in stack.engine_args
    ):
        raise TypeError("model stack engine_args must be non-empty strings")

    engine = stack.identity.engine.strip().lower()
    if engine == "vllm":
        collisions = tuple(
            sorted(
                flag
                for flag in _PLATFORM_OWNED_VLLM_FLAGS
                if _contains_flag(stack.engine_args, flag)
            )
        )
        if collisions:
            raise ValueError(
                "vLLM engine_args duplicate platform-owned typed stack fields: "
                + ", ".join(collisions)
            )

        args: list[str] = [
            "--max-model-len",
            str(stack.identity.context_length),
            "--dtype",
            stack.identity.dtype,
        ]
        if stack.identity.quantization is not None:
            args.extend(("--quantization", stack.identity.quantization))
        if stack.reasoning_parser is not None:
            args.extend((
                "--enable-reasoning",
                "--reasoning-parser",
                stack.reasoning_parser,
            ))
        if stack.tool_call_parser is not None:
            args.extend((
                "--enable-auto-tool-choice",
                "--tool-call-parser",
                stack.tool_call_parser,
            ))
        if stack.kv_cache_dtype is not None:
            args.extend(("--kv-cache-dtype", stack.kv_cache_dtype))

        scheduler = stack.scheduler_policy.strip().lower()
        if scheduler == "default":
            pass
        elif scheduler in {"fcfs", "priority"}:
            args.extend(("--scheduling-policy", scheduler))
        else:
            raise ValueError(
                "vLLM scheduler_policy must be default, fcfs, or priority"
            )

        policy = stack.serving_policy
        if policy.prefix_caching is True:
            args.append("--enable-prefix-caching")
            if policy.prefix_cache_hash_algorithm is not None:
                args.extend((
                    "--prefix-caching-hash-algo",
                    policy.prefix_cache_hash_algorithm,
                ))
        elif policy.prefix_caching is False:
            args.append("--no-enable-prefix-caching")

        if policy.chunked_prefill is True:
            args.append("--enable-chunked-prefill")
        elif policy.chunked_prefill is False:
            args.append("--no-enable-chunked-prefill")

        if policy.max_batch_tokens is not None:
            args.extend((
                "--max-num-batched-tokens",
                str(policy.max_batch_tokens),
            ))

        environment: list[tuple[str, str]] = []
        if stack.attention_backend is not None:
            environment.append((
                "VLLM_ATTENTION_BACKEND",
                stack.attention_backend,
            ))

        return ModelStackLaunchSettings(
            engine_args=tuple((*args, *stack.engine_args)),
            environment=tuple(sorted(environment)),
        )

    if engine == "sglang":
        # SGLang launch semantics are intentionally fail-closed until a typed
        # engine renderer proves the exact mapping. Never silently freeze a
        # stack field that the physical process ignores.
        unsupported = tuple(
            name
            for name, value in (
                ("reasoning_parser", stack.reasoning_parser),
                ("tool_call_parser", stack.tool_call_parser),
                ("kv_cache_dtype", stack.kv_cache_dtype),
                ("attention_backend", stack.attention_backend),
            )
            if value is not None
        )
        scheduler = stack.scheduler_policy.strip().lower()
        if scheduler not in {"default", "fcfs"}:
            unsupported = (*unsupported, "scheduler_policy")
        policy = stack.serving_policy
        if any((
            policy.prefix_caching is not None,
            policy.prefix_cache_hash_algorithm is not None,
            policy.chunked_prefill is not None,
            policy.max_batch_tokens is not None,
        )):
            unsupported = (*unsupported, "serving_policy")
        if unsupported:
            raise ValueError(
                "SGLang stack contains typed launch semantics without a "
                "qualified physical renderer: "
                + ", ".join(unsupported)
            )
        return ModelStackLaunchSettings(engine_args=stack.engine_args)

    raise ValueError(f"unsupported model stack engine: {stack.identity.engine!r}")


__all__ = ["ModelStackLaunchSettings", "model_stack_launch_settings"]
