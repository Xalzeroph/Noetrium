from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib, json
from pathlib import Path

ZERO_HASH="0"*64


def hash_payload(prev:str,payload:dict[str,object])->str:
    raw=json.dumps(payload,sort_keys=True,ensure_ascii=False,separators=(",",":")).encode("utf-8")
    return hashlib.sha256(prev.encode("ascii")+b"\0"+raw).hexdigest()

def encode_row(prev:str,payload:dict[str,object])->tuple[bytes,str]:
    row_hash=hash_payload(prev,payload)
    row={"prev_hash":prev,"row_hash":row_hash,"payload":payload}
    encoded=(json.dumps(row,sort_keys=True,ensure_ascii=False,separators=(",",":"))+"\n").encode("utf-8")
    return encoded,row_hash

@dataclass(frozen=True, slots=True)
class WriterTail:
    initialized: bool=False
    count: int=0
    tail_hash: str=ZERO_HASH
    signature: tuple[int,int,int,int]|None=None
    since_sync: int=0

    def verified(self,count:int,tail_hash:str,signature:tuple[int,int,int,int]|None)->"WriterTail":
        return WriterTail(True,count,tail_hash,signature,0)
    def appended(self,row_hash:str,signature:tuple[int,int,int,int]|None,*,synced:bool)->"WriterTail":
        return WriterTail(True,self.count+1,row_hash,signature,0 if synced else self.since_sync+1)


def stat_signature(path:Path)->tuple[int,int,int,int]|None:
    try: st=path.stat()
    except FileNotFoundError: return None
    return int(st.st_dev),int(st.st_ino),int(st.st_size),int(st.st_mtime_ns)
