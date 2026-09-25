from __future__ import annotations

import json
import unittest

from noetrium_platform.infrastructure.reliability.failure.api import exception_correlation_refs
from noetrium_platform.foundation.kernel.kernel.durability.checksummed_document import (
    ChecksummedDocumentError,
    ChecksummedDocumentFailureCode,
    decode_checksummed_document,
    encode_checksummed_document,
)


class ChecksummedDocumentFailureCodesV181Tests(unittest.TestCase):
    def test_checksum_failure_has_stable_code_and_correlation_ref(self):
        raw=json.loads(encode_checksummed_document("x.v1", {"secret":"VALUE"}).decode())
        raw["payload_sha256"]="0"*64
        with self.assertRaises(ChecksummedDocumentError) as caught:
            decode_checksummed_document(json.dumps(raw).encode(), expected_schema="x.v1")
        self.assertIs(caught.exception.code, ChecksummedDocumentFailureCode.CHECKSUM_MISMATCH)
        self.assertEqual(exception_correlation_refs(caught.exception), ("document-integrity:checksum_mismatch",))
        self.assertNotIn("VALUE", str(caught.exception))

    def test_unsupported_schema_does_not_echo_actual_schema(self):
        raw=encode_checksummed_document("secret-schema-name", {})
        with self.assertRaises(ChecksummedDocumentError) as caught:
            decode_checksummed_document(raw, expected_schema="x.v1")
        self.assertIs(caught.exception.code, ChecksummedDocumentFailureCode.UNSUPPORTED_SCHEMA)
        self.assertNotIn("secret-schema-name", str(caught.exception))


if __name__=="__main__": unittest.main()
