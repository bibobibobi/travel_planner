import os
import sys
from pathlib import Path

import pytest

pytest.importorskip('fcntl')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deploy' / 'server'))
import receive_artifact as receiver


def test_reuse_keeps_lock_held_against_another_process(tmp_path, monkeypatch):
    lock = tmp_path / 'lock'
    lock.touch()
    monkeypatch.setattr(receiver, 'LOCK', lock)
    monkeypatch.setattr(receiver, 'trusted', lambda path: None)
    fd = receiver.take_lock()
    try:
        receiver.reuse_lock(fd)
        pid = os.fork()
        if pid == 0:
            os.close(fd)
            try:
                receiver.take_lock(timeout=0.1)
            except receiver.Rejected:
                os._exit(0)
            os._exit(1)
        _, status = os.waitpid(pid, 0)
        assert os.waitstatus_to_exitcode(status) == 0
    finally:
        os.close(fd)


def test_reuse_rejects_another_file(tmp_path, monkeypatch):
    lock, wrong = tmp_path / 'lock', tmp_path / 'wrong'
    lock.touch()
    wrong.touch()
    monkeypatch.setattr(receiver, 'LOCK', lock)
    monkeypatch.setattr(receiver, 'trusted', lambda path: None)
    fd = os.open(wrong, os.O_RDONLY)
    try:
        with pytest.raises(receiver.Rejected, match='invalid lifecycle'):
            receiver.reuse_lock(fd)
    finally:
        os.close(fd)
