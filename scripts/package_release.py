"""Build and validate a deployment archive from an immutable Git commit."""

import argparse
import hashlib
import os
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
FILES = {'app.py', 'websocket_worker.py', 'requirements.txt', 'requirements-prod.txt', 'REVISION'}


def command(args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def git(*args, **kwargs):
    return command(['git', '-c', f'safe.directory={ROOT.as_posix()}', '-C', str(ROOT), *args], **kwargs)


def resolve_ref(ref):
    result = git('rev-parse', '--verify', '--end-of-options', ref + '^{commit}',
                 stdout=subprocess.PIPE, text=True)
    sha = result.stdout.strip()
    if not re.fullmatch(r'[0-9a-f]{40,64}', sha):
        raise ValueError('Git returned an invalid commit ID')
    return sha


def valid_path(name):
    path = PurePosixPath(name)
    return (bool(name) and not name.startswith('/') and '\\' not in name
            and all(part not in ('', '.', '..') for part in name.split('/'))
            and str(path) == name and not re.match(r'^[A-Za-z]:', name))


def allowed(name):
    return name in FILES or name.startswith('dist/')


def check_build_tree(directory):
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError('Invalid build directory')
    for entry in os.scandir(directory):
        info = Path(entry.path).stat(follow_symlinks=False)
        if stat.S_ISDIR(info.st_mode):
            check_build_tree(Path(entry.path))
        elif not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError('Forbidden build entry')


def scan_stage(stage, sha):
    """Reject links and non-regular files before reading any file content."""
    contents = {}
    def visit(directory):
        for entry in os.scandir(directory):
            path = Path(entry.path)
            name = path.relative_to(stage).as_posix()
            info = path.stat(follow_symlinks=False)
            if not valid_path(name):
                raise ValueError('Invalid staging path')
            if stat.S_ISDIR(info.st_mode):
                if name != 'dist' and not name.startswith('dist/'):
                    raise ValueError('Unexpected staging directory')
                visit(path)
            elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and allowed(name):
                contents[name] = path.read_bytes()
            else:
                raise ValueError('Forbidden staging entry')
    visit(stage)
    required = FILES | {'dist/index.html'}
    if not required <= contents.keys() or any(not contents[n] for n in required):
        raise ValueError('Missing or empty required file')
    if contents['REVISION'] != sha.encode('ascii') + b'\n':
        raise ValueError('Revision mismatch')
    if not any(n.endswith('.js') and data for n, data in contents.items() if n.startswith('dist/')):
        raise ValueError('Missing JavaScript build output')
    return contents


def validate_archive(archive, expected):
    seen = set()
    with tarfile.open(archive, 'r:gz') as tar:
        for member in tar:
            name = member.name
            if (not valid_path(name) or name in seen or not member.isfile()
                    or not allowed(name) or name not in expected):
                raise ValueError('Forbidden or duplicate archive member')
            seen.add(name)
            source = tar.extractfile(member)
            if source is None or source.read() != expected[name]:
                raise ValueError('Archive content mismatch')
    if seen != expected.keys():
        raise ValueError('Archive contents incomplete')


def extract_git_archive(archive, destination):
    """Extract only regular files and directories, without following links."""
    seen = set()
    with tarfile.open(archive, 'r:') as tar:
        for member in tar:
            name = member.name.rstrip('/') if member.isdir() else member.name
            if not valid_path(name) or name in seen or not (member.isfile() or member.isdir()):
                raise ValueError('Unsafe Git archive member')
            seen.add(name)
            target = destination.joinpath(*name.split('/'))
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                source = tar.extractfile(member)
                if source is None:
                    raise ValueError('Missing Git archive data')
                with target.open('xb') as output:
                    shutil.copyfileobj(source, output)


def package(ref, output_dir):
    sha = resolve_ref(ref)
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    name = f'travel-app-{sha}.tar.gz'
    final = output_dir / name
    checksum = output_dir / (name + '.sha256')
    if final.exists() or checksum.exists():
        raise FileExistsError('Release output already exists')
    with tempfile.TemporaryDirectory(prefix='travel-release-') as work_name, \
            tempfile.TemporaryDirectory(prefix='.travel-release-', dir=output_dir) as out_name:
        work, out = Path(work_name), Path(out_name)
        exported = work / 'export'
        exported.mkdir()
        git_archive = work / 'source.tar'
        with git_archive.open('wb') as stream:
            git('archive', '--format=tar', sha, stdout=stream)
        extract_git_archive(git_archive, exported)
        env = os.environ.copy()
        env['VITE_API_URL'] = ''
        npm = shutil.which('npm.cmd' if os.name == 'nt' else 'npm')
        if not npm:
            raise FileNotFoundError('npm executable not found')
        command([npm, 'ci'], cwd=exported / 'frontend', env=env)
        command([npm, 'run', 'build'], cwd=exported / 'frontend', env=env)
        stage = work / 'stage'
        stage.mkdir()
        for filename in FILES - {'REVISION'}:
            shutil.copyfile(exported / filename, stage / filename, follow_symlinks=False)
        (stage / 'REVISION').write_bytes(sha.encode('ascii') + b'\n')
        check_build_tree(exported / 'frontend' / 'dist')
        shutil.copytree(exported / 'frontend' / 'dist', stage / 'dist', symlinks=True)
        expected = scan_stage(stage, sha)
        archive = out / name
        with tarfile.open(archive, 'w:gz', format=tarfile.PAX_FORMAT) as tar:
            for filename in sorted(expected):
                tar.add(stage / filename, arcname=filename, recursive=False)
        validate_archive(archive, expected)
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        check_temp = out / checksum.name
        check_temp.write_text(f'{digest}  {name}\n', encoding='ascii', newline='\n')
        # Hard-link creation is atomic and fails if the destination exists.
        # The pair cannot be published atomically; remove our first link if the
        # second publication fails. A crash between links can leave one file.
        os.link(archive, final)
        try:
            os.link(check_temp, checksum)
        except BaseException:
            final.unlink()
            raise
    return final, digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ref', default='HEAD')
    parser.add_argument('--output-dir', default='artifacts')
    args = parser.parse_args()
    try:
        artifact, digest = package(args.ref, args.output_dir)
    except (OSError, ValueError, subprocess.CalledProcessError, tarfile.TarError) as error:
        parser.exit(1, f'Packaging failed: {error}\n')
    print(f'{artifact.name}\nSHA256: {digest}')


if __name__ == '__main__':
    main()
