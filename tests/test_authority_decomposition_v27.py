from pathlib import Path
import tempfile
import unittest

from noetrium_platform.infrastructure.reliability.forensics.providers.index import ForensicIndex
from tests._concurrency_support import forensic_index
from noetrium_platform.infrastructure.reliability.forensics.providers.index_reader import ForensicIndexReader
from noetrium_platform.infrastructure.reliability.forensics.providers.index_writer import ForensicIndexWriter
from noetrium_platform.capabilities.model.request.prompt.runtime.active_pointer import ActivePromptPointer
from noetrium_platform.capabilities.model.request.prompt.runtime.generation_store import PromptGenerationStore
from noetrium_platform.capabilities.model.request.prompt.runtime.promotion_record_store import PromotionRecordStore
from noetrium_platform.capabilities.model.request.prompt.runtime.promotion_store import PromptPromotionStore


class AuthorityDecompositionV27Tests(unittest.TestCase):
    def test_prompt_storage_and_promotion_have_distinct_state_authority(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); lock=root/'.publication.lock'
            generations=PromptGenerationStore(root/"generations",lock_path=lock)
            promotion=PromptPromotionStore(
                generation_store=generations,
                records=PromotionRecordStore(root/"promotions"),
                pointer=ActivePromptPointer(root/"ACTIVE"),
                lock_path=lock,
            )
            self.assertFalse(hasattr(generations,'active'))
            self.assertTrue(hasattr(promotion,'pointer'))
            self.assertFalse(hasattr(promotion,'stage'))

    def test_read_only_index_has_no_writer(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'index.sqlite3'
            forensic_index(path).close()
            read=ForensicIndex(path,read_only=True)
            self.assertIsInstance(read.reader,ForensicIndexReader)
            self.assertIsNone(read.writer)
            with self.assertRaises(PermissionError): read.set_freshness('events',0,'0'*64)

    def test_writer_refuses_read_only_db(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'index.sqlite3'; writable=forensic_index(path)
            ro=writable.db.__class__(path,read_only=True)
            with self.assertRaises(PermissionError): ForensicIndexWriter(ro)

if __name__=='__main__': unittest.main()
