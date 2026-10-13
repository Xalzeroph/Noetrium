from __future__ import annotations

import json


def encode_strings(values: tuple[str,...]) -> str:
    return json.dumps(values,ensure_ascii=False,separators=(",",":"))


def decode_strings(raw: str) -> tuple[str,...]:
    value=json.loads(raw)
    if not isinstance(value,list) or not all(isinstance(x,str) for x in value):
        raise ValueError("incident index string tuple payload is invalid")
    return tuple(value)
