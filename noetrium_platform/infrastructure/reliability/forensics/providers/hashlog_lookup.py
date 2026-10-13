from __future__ import annotations

import json
from pathlib import Path


def find_payload_in_hashlog(
    path:Path,
    field:str,
    value:object,
)->dict[str,object]|None:
    if not path.exists():
        return None
    with path.open("r",encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            payload=json.loads(line)["payload"]
            if payload.get(field)==value:
                return payload
    return None
