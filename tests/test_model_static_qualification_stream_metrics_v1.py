
from __future__ import annotations

import asyncio
import json

from noetrium_platform.capabilities.model.serving.endpoint.api import (
    RawServerSentEvent,
    SseHttpResponse,
)
from noetrium_platform.composition.model_runtime_bootstrap import (
    _stream_qualification_exchange,
    _throughput_qualification_payloads,
)


class _Clock:
    def __init__(self, values):
        self._values=iter(values)
    def __call__(self):
        return next(self._values)


class _SseTransport:
    async def post_sse(
        self,
        url,
        body,
        *,
        timeout_s,
        idle_timeout_s,
        on_event,
        headers=(),
    ):
        del url, timeout_s, idle_timeout_s, headers
        for payload in (
            {"choices":[{"delta":{"content":"1 "},"finish_reason":None}]},
            {"choices":[{"delta":{"content":"2"},"finish_reason":"stop"}]},
            {"choices":[],"usage":{"prompt_tokens":20,"completion_tokens":2}},
        ):
            on_event(RawServerSentEvent(None,json.dumps(payload).encode()))
        on_event(RawServerSentEvent(None,b"[DONE]"))
        return SseHttpResponse(
            200,
            (("content-type","text/event-stream"),),
            body,
            b"",
            4,
        )


def test_streaming_static_qualification_measures_real_ttft_and_tpot():
    exchange=asyncio.run(
        _stream_qualification_exchange(
            completion_url="http://local/v1/chat/completions",
            payload=b"{}",
            http_transport=_SseTransport(),
            timeout_s=10.0,
            clock=_Clock((0.0,0.1,0.3,0.31,0.32,0.4)),
        )
    )
    assert exchange.text == "1 2"
    assert exchange.prompt_tokens == 20
    assert exchange.output_tokens == 2
    assert exchange.ttft_seconds == 0.1
    assert abs(exchange.tpot_seconds - 0.2) < 1e-9


def test_throughput_qualification_payloads_mix_decode_and_prefill():
    payloads=_throughput_qualification_payloads(
        "qwen",
        context_length=32768,
        observed_prompt_tokens=32,
    )
    assert len(payloads) == 2
    rows=tuple(json.loads(value) for value in payloads)
    assert all(row["stream"] is True for row in rows)
    assert all(row["stream_options"]["include_usage"] is True for row in rows)
    short=rows[0]["messages"][0]["content"]
    long=rows[1]["messages"][0]["content"]
    assert len(long) > len(short)
    assert rows[0]["max_tokens"] == rows[1]["max_tokens"] == 64
