import os
import stat
import sys

import pytest

from deploy.server import release_tree

pytestmark = pytest.mark.skipif(not sys.platform.startswith('linux'), reason='Linux dir_fd required')


def copy(source, destination, **kwargs):
    src = os.open(source, os.O_RDONLY | os.O_DIRECTORY)
    dst = os.open(destination, os.O_RDONLY | os.O_DIRECTORY)
    try:
        return release_tree.copy_tree(src, dst, **kwargs)
    finally:
        os.close(src)
        os.close(dst)


def test_copy_preserves_execute_without_write_or_setid(tmp_path):
    src, dst = tmp_path / 'src', tmp_path / 'dst'
    src.mkdir()
    dst.mkdir()
    (src / 'run').write_bytes(b'hello')
    (src / 'run').chmod(0o6755)
    assert copy(src, dst) == 5
    assert stat.S_IMODE((dst / 'run').stat().st_mode) == 0o555
    assert (dst / 'run').read_bytes() == b'hello'


@pytest.mark.parametrize('kind', ['symlink', 'hardlink', 'fifo', 'oversize'])
def test_rejects_unsafe_build_output(tmp_path, kind):
    src, dst = tmp_path / 'src', tmp_path / 'dst'
    src.mkdir()
    dst.mkdir()
    if kind == 'symlink':
        (src / 'bad').symlink_to('/etc/passwd')
    elif kind == 'fifo':
        os.mkfifo(src / 'bad')
    else:
        (src / 'file').write_bytes(b'hello')
        if kind == 'hardlink':
            os.link(src / 'file', src / 'bad')
    with pytest.raises(release_tree.UnsafeTree):
        copy(src, dst, max_bytes=1 if kind == 'oversize' else 100)


def test_accepts_expected_venv_python_link(tmp_path):
    src, dst = tmp_path / 'src', tmp_path / 'dst'
    (src / 'venv' / 'bin').mkdir(parents=True)
    dst.mkdir()
    (src / 'venv' / 'bin' / 'python').symlink_to('python3')
    (src / 'venv' / 'lib').mkdir()
    (src / 'venv' / 'lib64').symlink_to('lib', target_is_directory=True)
    copy(src, dst)
    assert os.readlink(dst / 'venv' / 'bin' / 'python') == 'python3'
    assert os.readlink(dst / 'venv' / 'lib64') == 'lib'
