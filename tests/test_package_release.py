import io
import os
import subprocess
import tarfile
from unittest.mock import patch

import pytest

from scripts import package_release as release

SHA = 'a' * 40


@pytest.fixture
def stage(tmp_path):
    for name in release.FILES - {'REVISION'}:
        (tmp_path / name).write_bytes(b'content')
    (tmp_path / 'REVISION').write_bytes((SHA + '\n').encode())
    (tmp_path / 'dist').mkdir()
    (tmp_path / 'dist' / 'index.html').write_text('index')
    (tmp_path / 'dist' / 'app.js').write_text('javascript')
    return tmp_path


def test_valid_archive(stage):
    expected = release.scan_stage(stage, SHA)
    archive = stage.parent / 'valid.tar.gz'
    with tarfile.open(archive, 'w:gz') as tar:
        for name in expected:
            tar.add(stage / name, arcname=name)
    release.validate_archive(archive, expected)


@pytest.mark.parametrize('name', ['app.py', 'dist/index.html', 'dist/app.js'])
def test_missing_required(stage, name):
    (stage / name).unlink()
    with pytest.raises(ValueError):
        release.scan_stage(stage, SHA)


def test_wrong_revision_and_forbidden_file(stage):
    (stage / 'REVISION').write_text('wrong')
    with pytest.raises(ValueError):
        release.scan_stage(stage, SHA)
    (stage / 'REVISION').write_bytes((SHA + '\n').encode())
    (stage / '.env').write_text('dummy')
    with pytest.raises(ValueError):
        release.scan_stage(stage, SHA)


def test_hard_link_rejected(stage):
    os.link(stage / 'app.py', stage / 'dist' / 'linked.js')
    with pytest.raises(ValueError):
        release.scan_stage(stage, SHA)


def test_symlink_rejected(stage):
    try:
        (stage / 'dist' / 'link.js').symlink_to(stage / 'app.py')
    except OSError:
        pytest.skip('Creating symbolic links is not permitted')
    with pytest.raises(ValueError):
        release.scan_stage(stage, SHA)


@pytest.mark.skipif(not hasattr(os, 'mkfifo'), reason='FIFO unavailable')
def test_special_file_rejected(stage):
    os.mkfifo(stage / 'dist' / 'pipe')
    with pytest.raises(ValueError):
        release.scan_stage(stage, SHA)


@pytest.mark.parametrize('names', [['/app.py'], ['../app.py'], ['app.py', 'app.py'],
                                   ['dist/../../app.py']])
def test_unsafe_archive_names(stage, names, tmp_path):
    expected = release.scan_stage(stage, SHA)
    archive = tmp_path / 'unsafe.tar.gz'
    with tarfile.open(archive, 'w:gz') as tar:
        for name in names:
            member = tarfile.TarInfo(name)
            member.size = 1
            tar.addfile(member, io.BytesIO(b'x'))
    with pytest.raises(ValueError):
        release.validate_archive(archive, expected)


@pytest.mark.parametrize('kind', [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE])
def test_archive_links_and_special_rejected(stage, kind, tmp_path):
    archive = tmp_path.parent / 'unsafe-links.tar.gz'
    with tarfile.open(archive, 'w:gz') as tar:
        member = tarfile.TarInfo('app.py')
        member.type = kind
        member.linkname = 'elsewhere'
        tar.addfile(member)
    with pytest.raises(ValueError):
        release.validate_archive(archive, release.scan_stage(stage, SHA))


def test_existing_output_not_overwritten(tmp_path):
    target = tmp_path / f'travel-app-{SHA}.tar.gz'
    target.write_bytes(b'old')
    with patch.object(release, 'resolve_ref', return_value=SHA), pytest.raises(FileExistsError):
        release.package('HEAD', tmp_path)
    assert target.read_bytes() == b'old'


def test_command_failure_stops_and_cleans(tmp_path):
    with (patch.object(release, 'resolve_ref', return_value=SHA),
          patch.object(release, 'git', side_effect=subprocess.CalledProcessError(1, 'git')),
          pytest.raises(subprocess.CalledProcessError)):
        release.package('HEAD', tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_npm_failure_stops_before_build_and_cleans(stage, tmp_path):
    def archive_source(*args, stdout, **kwargs):
        with tarfile.open(fileobj=stdout, mode='w') as tar:
            tar.add(stage / 'app.py', arcname='frontend/placeholder')
    out = tmp_path / 'out'
    with (patch.object(release, 'resolve_ref', return_value=SHA),
          patch.object(release, 'git', side_effect=archive_source),
          patch.object(release.shutil, 'which', return_value='npm'),
          patch.object(release, 'command', side_effect=subprocess.CalledProcessError(1, 'npm')) as run,
          pytest.raises(subprocess.CalledProcessError)):
        release.package('HEAD', out)
    assert run.call_count == 1
    assert run.call_args.kwargs['env']['VITE_API_URL'] == ''
    assert list(out.iterdir()) == []


def test_archive_content_mismatch(stage, tmp_path):
    expected = release.scan_stage(stage, SHA)
    archive = tmp_path.parent / 'mismatch.tar.gz'
    with tarfile.open(archive, 'w:gz') as tar:
        for name in expected:
            data = b'changed' if name == 'app.py' else expected[name]
            member = tarfile.TarInfo(name)
            member.size = len(data)
            tar.addfile(member, io.BytesIO(data))
    with pytest.raises(ValueError, match='content mismatch'):
        release.validate_archive(archive, expected)


def test_checksum_and_publication(stage, tmp_path):
    # Exercise publication with isolated source and a simulated npm build.
    def archive_source(*args, stdout, **kwargs):
        with tarfile.open(fileobj=stdout, mode='w') as tar:
            for name in release.FILES - {'REVISION'}:
                tar.add(stage / name, arcname=name)
            for path in (stage / 'dist').rglob('*'):
                tar.add(path, arcname='frontend/' + path.relative_to(stage).as_posix())
    out = tmp_path / 'out'
    with (patch.object(release, 'resolve_ref', return_value=SHA),
          patch.object(release, 'git', side_effect=archive_source),
          patch.object(release.shutil, 'which', return_value='npm'),
          patch.object(release, 'command')):
        artifact, digest = release.package('HEAD', out)
    assert len(digest) == 64 and digest == release.hashlib.sha256(artifact.read_bytes()).hexdigest()
    assert (out / (artifact.name + '.sha256')).read_text() == f'{digest}  {artifact.name}\n'
    assert sorted(p.name for p in out.iterdir()) == sorted([artifact.name, artifact.name + '.sha256'])


def test_second_publication_failure_removes_first(stage, tmp_path):
    def archive_source(*args, stdout, **kwargs):
        with tarfile.open(fileobj=stdout, mode='w') as tar:
            for name in release.FILES - {'REVISION'}:
                tar.add(stage / name, arcname=name)
            for path in (stage / 'dist').rglob('*'):
                tar.add(path, arcname='frontend/' + path.relative_to(stage).as_posix())
    real_link = os.link
    def fail_second(src, dst):
        if str(dst).endswith('.sha256'):
            raise OSError('simulated failure')
        real_link(src, dst)
    out = tmp_path / 'out'
    with (patch.object(release, 'resolve_ref', return_value=SHA),
          patch.object(release, 'git', side_effect=archive_source),
          patch.object(release.shutil, 'which', return_value='npm'),
          patch.object(release, 'command'), patch.object(release.os, 'link', side_effect=fail_second),
          pytest.raises(OSError)):
        release.package('HEAD', out)
    assert list(out.iterdir()) == []
