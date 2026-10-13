from __future__ import annotations

import asyncio
import json

from noetrium_platform.capabilities.model.serving.endpoint.providers import (
    PooledModelHttpTransport,
)


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


class _LocalHttpServer:
    def __init__(self) -> None:
        self.server = None
        self.port = None
        self.connections = 0
        self.max_open_connections = 0
        self.open_connections = 0
        self.requests: list[tuple[str, dict[str, str], bytes]] = []
        self.target_hits = 0

    async def start(self) -> None:
        self.server = await asyncio.start_server(
            self._handle,
            "127.0.0.1",
            0,
        )
        sockets = self.server.sockets
        assert sockets
        self.port = sockets[0].getsockname()[1]

    async def close(self) -> None:
        assert self.server is not None
        self.server.close()
        await self.server.wait_closed()

    async def _read_request(self, reader):
        line = await reader.readline()
        if not line:
            return None
        parts = line.decode("ascii").rstrip("\r\n").split(" ")
        assert len(parts) == 3
        _method, target, _version = parts
        headers: dict[str, str] = {}
        while True:
            row = await reader.readline()
            if row in {b"", b"\r\n", b"\n"}:
                break
            name, value = row.decode("iso-8859-1").split(":", 1)
            headers[name.strip().lower()] = value.strip()
        length = int(headers.get("content-length", "0"))
        body = await reader.readexactly(length) if length else b""
        return target, headers, body

    async def _send(
        self,
        writer,
        *,
        status: int = 200,
        content_type: str = "application/json",
        body: bytes,
        extra_headers: tuple[tuple[str, str], ...] = (),
    ) -> None:
        reason = {
            200: "OK",
            307: "Temporary Redirect",
        }[status]
        headers = (
            ("Content-Type", content_type),
            ("Content-Length", str(len(body))),
            ("Connection", "keep-alive"),
            *extra_headers,
        )
        raw = (
            f"HTTP/1.1 {status} {reason}\r\n"
            + "".join(f"{name}: {value}\r\n" for name, value in headers)
            + "\r\n"
        ).encode("iso-8859-1") + body
        writer.write(raw)
        await writer.drain()

    async def _handle(self, reader, writer) -> None:
        self.connections += 1
        self.open_connections += 1
        self.max_open_connections = max(
            self.max_open_connections,
            self.open_connections,
        )
        try:
            while True:
                request = await self._read_request(reader)
                if request is None:
                    return
                target, headers, body = request
                self.requests.append((target, headers, body))
                if target == "/slow":
                    await asyncio.sleep(0.03)
                    await self._send(
                        writer,
                        body=b'{"ok":true}',
                    )
                elif target == "/cookie":
                    await self._send(
                        writer,
                        body=b'{"ok":true}',
                        extra_headers=(("Set-Cookie", "secret=leak; Path=/"),),
                    )
                elif target == "/echo":
                    payload = json.dumps(
                        {"cookie": headers.get("cookie")},
                        separators=(",", ":"),
                    ).encode("utf-8")
                    await self._send(writer, body=payload)
                elif target == "/redirect":
                    await self._send(
                        writer,
                        status=307,
                        body=b'{"redirect":true}',
                        extra_headers=(("Location", "/target"),),
                    )
                elif target == "/target":
                    self.target_hits += 1
                    await self._send(
                        writer,
                        body=b'{"target":true}',
                    )
                elif target == "/sse":
                    stream = (
                        b"event: response.output_text.delta\n"
                        b'data: {"type":"response.output_text.delta","delta":"OK"}\n\n'
                        b"event: response.completed\n"
                        b'data: {"type":"response.completed","response":{"status":"completed"}}\n\n'
                    )
                    await self._send(
                        writer,
                        content_type="text/event-stream",
                        body=stream,
                    )
                else:
                    await self._send(
                        writer,
                        body=b'{"ok":true}',
                    )
        finally:
            self.open_connections -= 1
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass


def test_pooled_transport_reuses_connection_and_has_no_cookie_or_redirect_state():
    async def scenario():
        server = _LocalHttpServer()
        await server.start()
        transport = PooledModelHttpTransport(
            max_connections=4,
            max_keepalive_connections=4,
            keepalive_expiry_s=30,
        )
        base = f"http://127.0.0.1:{server.port}"
        try:
            one = await transport.post_json(
                base + "/json",
                _json_bytes({"n": 1}),
                timeout_s=3,
            )
            two = await transport.post_json(
                base + "/json",
                _json_bytes({"n": 2}),
                timeout_s=3,
            )
            assert one.status_code == two.status_code == 200
            assert one.http_version == two.http_version == "HTTP/1.1"
            assert one.request_body == b'{"n":1}'
            assert two.request_body == b'{"n":2}'
            assert server.connections == 1

            await transport.post_json(
                base + "/cookie",
                _json_bytes({"x": 1}),
                timeout_s=3,
            )
            echo = await transport.post_json(
                base + "/echo",
                _json_bytes({"x": 2}),
                timeout_s=3,
            )
            assert echo.body["cookie"] is None

            redirect = await transport.post_json(
                base + "/redirect",
                _json_bytes({"x": 3}),
                timeout_s=3,
            )
            assert redirect.status_code == 307
            assert server.target_hits == 0

            raw_events = []
            stream = await transport.post_sse(
                base + "/sse",
                _json_bytes({"stream": True}),
                timeout_s=3,
                idle_timeout_s=1,
                on_event=raw_events.append,
            )
            assert stream.status_code == 200
            assert stream.http_version == "HTTP/1.1"
            assert stream.event_count == 2
            assert len(raw_events) == 2
            assert raw_events[0].event == "response.output_text.delta"
            assert server.connections == 1

            snap = transport.snapshot()
            assert snap.requests_completed == 5
            assert snap.streams_completed == 1
            assert snap.requests_failed == 0
            assert snap.streams_failed == 0
            assert snap.http1_responses == 6
            assert snap.http2_responses == 0
        finally:
            await transport.aclose()
            await server.close()

    asyncio.run(scenario())


def test_pooled_transport_bounds_concurrent_http1_connections():
    async def scenario():
        server = _LocalHttpServer()
        await server.start()
        transport = PooledModelHttpTransport(
            max_connections=4,
            max_keepalive_connections=4,
            keepalive_expiry_s=30,
        )
        base = f"http://127.0.0.1:{server.port}"
        try:
            responses = await asyncio.gather(
                *(
                    transport.post_json(
                        base + "/slow",
                        _json_bytes({"index": index}),
                        timeout_s=5,
                    )
                    for index in range(20)
                )
            )
            assert len(responses) == 20
            assert all(row.status_code == 200 for row in responses)
            assert 1 <= server.connections <= 4
            assert server.max_open_connections <= 4
            snap = transport.snapshot()
            assert snap.requests_started == 20
            assert snap.requests_completed == 20
            assert snap.requests_failed == 0
        finally:
            await transport.aclose()
            await server.close()

    asyncio.run(scenario())


def test_pooled_transport_close_is_idempotent_and_terminal():
    async def scenario():
        transport = PooledModelHttpTransport(
            max_connections=1,
            max_keepalive_connections=1,
        )
        await transport.aclose()
        await transport.aclose()
        try:
            await transport.post_json(
                "http://127.0.0.1:1/nope",
                {},
                timeout_s=1,
            )
        except Exception as exc:
            assert "closed" in str(exc)
        else:
            raise AssertionError("closed transport accepted new request")

    asyncio.run(scenario())
