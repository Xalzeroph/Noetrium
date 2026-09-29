from __future__ import annotations

import json

from noetrium_platform.capabilities.model.serving.endpoint.api import (
    ModelStreamEventKind,
    RawServerSentEvent,
    ServerSentEventDecoder,
)
from noetrium_platform.capabilities.model.serving.provider import (
    AnthropicStreamDecoder,
    GeminiStreamDecoder,
    OpenAIChatStreamDecoder,
    OpenAIResponsesStreamDecoder,
)


def test_sse_decoder_handles_split_chunks_and_preserves_raw_bytes():
    decoder=ServerSentEventDecoder()
    first=decoder.feed(b"event: response.output_text.delta\ndata: {\"delta\":\"O\"")
    assert first == ()
    second=decoder.feed(b"}\n\nevent: response.completed\ndata: {\"response\":{\"usage\":{")
    assert len(second)==1
    assert second[0].event=="response.output_text.delta"
    assert second[0].data==b'{"delta":"O"}'
    assert b"event: response.output_text.delta" in second[0].raw_bytes
    third=decoder.feed(b"\"input_tokens\":1,\"output_tokens\":2}}}\n\n")
    assert len(third)==1
    assert third[0].event=="response.completed"


def test_responses_stream_maps_text_reasoning_tool_usage_and_terminal():
    decoder=OpenAIResponsesStreamDecoder(provider_id="vllm")
    text=decoder.decode(RawServerSentEvent(
        "response.output_text.delta",
        b'{"type":"response.output_text.delta","delta":"hi"}',
    ))
    reasoning=decoder.decode(RawServerSentEvent(
        "response.reasoning_summary_text.delta",
        b'{"type":"response.reasoning_summary_text.delta","delta":"think"}',
    ))
    tool=decoder.decode(RawServerSentEvent(
        "response.function_call_arguments.delta",
        json.dumps({'type':'response.function_call_arguments.delta','item_id':'fc1','delta':'{\"x\":'}).encode(),
    ))
    completed=decoder.decode(RawServerSentEvent(
        "response.completed",
        b'{"type":"response.completed","response":{"usage":{"input_tokens":3,"output_tokens":4,"total_tokens":7}}}',
    ))
    assert text[0].kind is ModelStreamEventKind.TEXT_DELTA
    assert text[0].text_delta=="hi"
    assert reasoning[0].kind is ModelStreamEventKind.REASONING_DELTA
    assert reasoning[0].reasoning_delta=="think"
    assert tool[0].kind is ModelStreamEventKind.TOOL_CALL_DELTA
    assert tool[0].tool_call_id=="fc1"
    assert tool[0].tool_arguments_delta=='{"x":'
    assert completed[0].kind is ModelStreamEventKind.USAGE
    assert completed[0].usage["prompt_tokens"]==3
    assert completed[-1].kind is ModelStreamEventKind.COMPLETED
    assert completed[-1].terminal is True
    assert [row.sequence for row in (*text,*reasoning,*tool,*completed)] == [1,2,3,4,5]


def test_openai_chat_stream_maps_reasoning_tool_and_finish():
    decoder=OpenAIChatStreamDecoder(provider_id="vllm")
    rows=decoder.decode(RawServerSentEvent(
        None,
        json.dumps({'choices':[{'delta':{'content':'a','reasoning_content':'r','tool_calls':[{'id':'c1','function':{'name':'act','arguments':'{\"x\":'}}]},'finish_reason':'tool_calls'}]}).encode(),
    ))
    assert [row.kind for row in rows] == [
        ModelStreamEventKind.TEXT_DELTA,
        ModelStreamEventKind.REASONING_DELTA,
        ModelStreamEventKind.TOOL_CALL_DELTA,
        ModelStreamEventKind.COMPLETED,
    ]


def test_anthropic_stream_tracks_tool_identity_across_delta_events():
    decoder=AnthropicStreamDecoder(provider_id="anthropic")
    decoder.decode(RawServerSentEvent(
        "content_block_start",
        b'{"type":"content_block_start","index":2,"content_block":{"type":"tool_use","id":"tool1","name":"lookup","input":{}}}',
    ))
    rows=decoder.decode(RawServerSentEvent(
        "content_block_delta",
        json.dumps({'type':'content_block_delta','index':2,'delta':{'type':'input_json_delta','partial_json':'{\"q\":'}}).encode(),
    ))
    assert rows[0].kind is ModelStreamEventKind.TOOL_CALL_DELTA
    assert rows[0].tool_call_id=="tool1"
    assert rows[0].tool_name=="lookup"


def test_gemini_stream_preserves_thought_and_usage():
    decoder=GeminiStreamDecoder(provider_id="gemini")
    rows=decoder.decode(RawServerSentEvent(
        None,
        b'{"candidates":[{"content":{"parts":[{"thought":true,"text":"r","thoughtSignature":"sig"},{"text":"a"}]},"finishReason":"STOP"}],"usageMetadata":{"promptTokenCount":2,"candidatesTokenCount":3,"totalTokenCount":5}}',
    ))
    assert rows[0].kind is ModelStreamEventKind.REASONING_DELTA
    assert rows[0].content["thoughtSignature"]=="sig"
    assert rows[1].kind is ModelStreamEventKind.TEXT_DELTA
    assert any(row.kind is ModelStreamEventKind.USAGE for row in rows)
    assert any(row.kind is ModelStreamEventKind.COMPLETED for row in rows)
