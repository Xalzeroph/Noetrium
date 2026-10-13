"""Data-only barriers retain the first-create metadata and crash contract."""
from pathlib import Path
import os

import pytest

from noetrium_platform.foundation.kernel.kernel.durability import PersistentAppendFile
import noetrium_platform.foundation.kernel.kernel.durability.durable_append as durability


def test_new_append_file_first_fsyncs_metadata_then_fdatasyncs_data(tmp_path,monkeypatch):
    seen=[]
    original_fsync=durability.flush_file_descriptor
    original_fdatasync=os.fdatasync if hasattr(os,'fdatasync') else None
    def fsync(fd):
        seen.append('metadata')
        return original_fsync(fd)
    def fdatasync(fd):
        seen.append('data')
        return original_fdatasync(fd)
    monkeypatch.setattr(durability,'flush_file_descriptor',fsync)
    if original_fdatasync is not None:
        monkeypatch.setattr(os,'fdatasync',fdatasync)
    file=PersistentAppendFile(tmp_path/'append.bin')
    file.open()
    file.write_all(b'first\n'); file.sync()
    file.write_all(b'second\n'); file.sync()
    file.close()
    assert seen==(['metadata','data'] if original_fdatasync is not None and os.name!='nt' else ['metadata','metadata'])
    assert (tmp_path/'append.bin').read_bytes()==b'first\nsecond\n'


def test_existing_append_file_data_sync_failure_fails_closed_to_caller(tmp_path,monkeypatch):
    p=tmp_path/'prior.bin';p.write_bytes(b'existing\n')
    file=PersistentAppendFile(p)
    file.open()
    file.write_all(b'next\n')
    if os.name!='nt' and hasattr(os,'fdatasync'):
        def fail(_fd):
            raise OSError('injected data barrier failure')
        monkeypatch.setattr(os,'fdatasync',fail)
        with pytest.raises(OSError,match='data barrier failure'):
            file.sync()
    file.close()


def test_one_shot_append_first_metadata_then_existing_data_barrier(tmp_path,monkeypatch):
    from noetrium_platform.foundation.kernel.kernel.durability import append_bytes,AppendDurability
    markers=[]
    original=durability._sync_append_descriptor
    def check(fd,*,metadata):
        markers.append(metadata)
        return original(fd,metadata=metadata)
    monkeypatch.setattr(durability,'_sync_append_descriptor',check)
    path=tmp_path/'one-shot.bin'
    append_bytes(path,b'A',durability=AppendDurability.DURABLE)
    append_bytes(path,b'B',durability=AppendDurability.DURABLE)
    assert markers==[True,False]
    assert path.read_bytes()==b'AB'
