from __future__ import annotations

import json

from noetrium_platform.infrastructure.reliability.failure.api import FailureFingerprint
from noetrium_platform.infrastructure.reliability.forensics.providers.incident_codec import decode_strings, encode_strings


class IncidentProjectionWriter:
    """Owns exact/family recurrence mutations inside one caller-owned SQLite transaction."""

    @staticmethod
    def _updated_examples(old:tuple[str,...],failure_id:str,max_examples:int)->tuple[str,...]:
        return tuple(dict.fromkeys((*old,failure_id)))[-max_examples:]

    def project(
        self,db,fp:FailureFingerprint,failure_id:str,*,timestamp:float,max_examples:int=8,
    )->bool:
        if db.execute("SELECT 1 FROM seen_failures WHERE failure_id=?",(failure_id,)).fetchone():
            return False
        db.execute("INSERT INTO seen_failures VALUES(?,?,?)",(failure_id,fp.fingerprint,fp.family_fingerprint))
        row=db.execute(
            "SELECT count,examples_json FROM patterns WHERE fingerprint=?",(fp.fingerprint,),
        ).fetchone()
        if row is None:
            examples=(failure_id,)
            db.execute(
                "INSERT INTO patterns VALUES(?,?,?,?,?,?,?)",
                (fp.fingerprint,fp.family_fingerprint,1,timestamp,timestamp,encode_strings(examples),encode_strings(fp.signature)),
            )
        else:
            examples=self._updated_examples(decode_strings(row[1]),failure_id,max_examples)
            db.execute(
                "UPDATE patterns SET count=count+1,last_seen=?,examples_json=? WHERE fingerprint=?",
                (timestamp,encode_strings(examples),fp.fingerprint),
            )
        family=db.execute(
            "SELECT count,examples_json FROM families WHERE family_fingerprint=?",(fp.family_fingerprint,),
        ).fetchone()
        if family is None:
            family_examples=(failure_id,)
            db.execute(
                "INSERT INTO families VALUES(?,?,?,?,?)",
                (fp.family_fingerprint,1,timestamp,timestamp,encode_strings(family_examples)),
            )
        else:
            family_examples=self._updated_examples(decode_strings(family[1]),failure_id,max_examples)
            db.execute(
                "UPDATE families SET count=count+1,last_seen=?,examples_json=? WHERE family_fingerprint=?",
                (timestamp,encode_strings(family_examples),fp.family_fingerprint),
            )
        return True
