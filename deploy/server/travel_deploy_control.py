#!/usr/bin/env python3
"""Root-owned controller for the travel_plan release lifecycle.

Install this file mode 0755, owner root:root.  It never evaluates code from an
artifact.  The only program it starts as root besides standard OS utilities is
this root-owned file.  ``travel-build`` performs extraction and pip work in a
directory which cannot reach /opt/travel-app/shared.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

try:  # The controller is Linux-only; this keeps mock tests importable on Windows.
    import fcntl
except ModuleNotFoundError:  # pragma: no cover - exercised only by Windows test hosts
    fcntl = None

try:
    import pwd
except ModuleNotFoundError:  # pragma: no cover - exercised only by Windows test hosts
    pwd = None

ROOT = Path("/opt/travel-app")
INCOMING = ROOT / "incoming"
BUILD_INPUTS = ROOT / "build-inputs"
PREPARE = ROOT / "prepare"
RELEASES = ROOT / "releases"
CURRENT = ROOT / "current"
LOCK = ROOT / ".lifecycle.lock"  # Backup V6 must flock this exact file too.
ALLOWLIST = Path("/etc/travel-deploy/allowed-revisions")
BUILD_USER = "travel-build"
SHA = re.compile(r"[0-9a-f]{40}")
DIGEST = re.compile(r"[0-9a-f]{64}")
MAX_TREE_BYTES = 600 * 1024 * 1024
MIN_FREE_BYTES = 800 * 1024 * 1024
HEALTH_URLS = ("http://127.0.0.1:5001/api/health", "http://127.0.0.1:5001/api/ready",
               "https://bobo-travel-planner.duckdns.org/api/health")


class DeployError(RuntimeError):
    pass


def checked(value: str, pattern: re.Pattern[str], name: str) -> str:
    if not pattern.fullmatch(value):
        raise DeployError(f"invalid {name}")
    return value


def run(args: list[str], *, timeout: int = 300, user: str | None = None) -> None:
    command = args if user is None else ["/usr/sbin/runuser", "-u", user, "--", *args]
    subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, check=True, timeout=timeout)


@contextmanager
def lifecycle_lock():
    if fcntl is None:
        raise DeployError("Linux flock is required")
    LOCK.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    with LOCK.open("a", encoding="ascii") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def require_root_owned(path: Path) -> os.stat_result:
    info = path.lstat()
    if path.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1:
        raise DeployError("trusted control input has unsafe metadata")
    return info


def allowed_revision(revision: str) -> None:
    require_root_owned(ALLOWLIST)
    entries = {line.strip() for line in ALLOWLIST.read_text(encoding="ascii").splitlines()
               if line and not line.startswith("#")}
    if revision not in entries:
        raise DeployError("revision is not authorized for production")


def safe_copy(source: Path, target: Path) -> None:
    """Copy a non-linked regular file, refusing symlink and replacement races."""
    before = source.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise DeployError("untrusted build output is not a private regular file")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    fd = os.open(source, flags)
    try:
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino, opened.st_nlink) != (before.st_dev, before.st_ino, 1):
            raise DeployError("untrusted build output changed while opening")
        out = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o444)
        try:
            with os.fdopen(fd, "rb", closefd=False) as input_file, os.fdopen(out, "wb") as output:
                shutil.copyfileobj(input_file, output, 1024 * 1024)
            after = source.lstat()
            if (after.st_dev, after.st_ino, after.st_nlink) != (before.st_dev, before.st_ino, 1):
                raise DeployError("untrusted build output changed while copying")
        except BaseException:
            target.unlink(missing_ok=True)
            raise
    finally:
        os.close(fd)


def copy_tree(source: Path, destination: Path) -> int:
    """Copy only a private regular-file tree; destination is root-owned/read-only."""
    total = 0
    for directory, dirs, files in os.walk(source, followlinks=False):
        relative = Path(directory).relative_to(source)
        target_dir = destination / relative
        if relative != Path("."):
            target_dir.mkdir(mode=0o555, exist_ok=False)
        info = Path(directory).lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid == 0:
            raise DeployError("untrusted build directory is unsafe")
        for name in sorted(dirs.copy()):
            if name.startswith("."):
                raise DeployError("untrusted build tree contains hidden directory")
            candidate = Path(directory) / name
            if candidate.is_symlink():
                # The builder may create only these two non-secret shared links.
                if (relative, name, os.readlink(candidate)) not in {
                    (Path("."), "uploads", "/opt/travel-app/shared/uploads"),
                }:
                    raise DeployError("untrusted build tree contains unsafe link")
                os.symlink(os.readlink(candidate), target_dir / name)
                dirs.remove(name)
        for name in sorted(files):
            src, dst = Path(directory) / name, target_dir / name
            if src.is_symlink():
                if (relative, name, os.readlink(src)) != (
                    Path("."), ".env", "/opt/travel-app/shared/.env"
                ):
                    raise DeployError("untrusted build tree contains unsafe link")
                os.symlink(os.readlink(src), dst)
                continue
            if name.startswith("."):
                raise DeployError("untrusted build tree contains hidden file")
            size = src.lstat().st_size
            total += size
            if total > MAX_TREE_BYTES:
                raise DeployError("release exceeds size limit")
            safe_copy(src, dst)
    return total


def freeze_tree(root: Path) -> None:
    """Make a completed release immutable to both service and build accounts."""
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in [*dirs, *files]:
            path = Path(directory) / name
            if path.is_symlink():
                continue
            os.chown(path, 0, 0)
            mode = path.stat().st_mode
            os.chmod(path, 0o555 if path.is_dir() else 0o444 | (mode & 0o111))
    os.chown(root, 0, 0)
    os.chmod(root, 0o555)


def current_revision() -> str | None:
    if not CURRENT.is_symlink():
        return None
    target = CURRENT.resolve(strict=True)
    if target.parent != RELEASES or not SHA.fullmatch(target.name):
        raise DeployError("current link is unsafe")
    return target.name


def switch_current(revision: str) -> None:
    target = RELEASES / revision
    if not target.is_dir() or target.is_symlink():
        raise DeployError("release does not exist")
    temporary = ROOT / ".current.new"
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(Path("releases") / revision)
    os.replace(temporary, CURRENT)  # atomic replacement within /opt/travel-app


def healthy() -> bool:
    for url in HEALTH_URLS:
        for _ in range(3):
            try:
                run(["/usr/bin/curl", "--fail", "--silent", "--show-error", "--max-time", "5", url], timeout=8)
                break
            except (subprocess.SubprocessError, OSError):
                time.sleep(2)
        else:
            return False
    return True


def restart_and_check() -> bool:
    try:
        run(["/bin/systemctl", "restart", "travel.service"], timeout=45)
    except (subprocess.SubprocessError, OSError):
        return False
    return healthy()


def build_release(revision: str, digest: str) -> None:
    """Prepare as travel-build, then cross the boundary by verified copies."""
    artifact = INCOMING / f"{revision}.tar.gz"
    # Root verifies source metadata only; trusted validator is run without privilege.
    info = artifact.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or artifact.is_symlink():
        raise DeployError("incoming artifact is unsafe")
    if (RELEASES / revision).exists():
        raise DeployError("release already exists")
    if shutil.disk_usage(ROOT).free < MIN_FREE_BYTES:
        raise DeployError("insufficient free disk space")
    BUILD_INPUTS.mkdir(mode=0o700, exist_ok=True)
    PREPARE.mkdir(mode=0o700, exist_ok=True)
    source = BUILD_INPUTS / f"{revision}.tar.gz"
    source.unlink(missing_ok=True)
    safe_copy(artifact, source)
    if pwd is None:
        raise DeployError("Linux user lookup is required")
    os.chown(source, pwd.getpwnam(BUILD_USER).pw_uid, -1)
    work = PREPARE / revision
    if work.exists():
        raise DeployError("prepare directory already exists")
    # This root-owned helper invokes validator/extractor as travel-build.
    run(["/usr/local/lib/travel-deploy/build-release", "prepare", revision, digest],
        timeout=300, user=BUILD_USER)
    try:
        with tempfile.TemporaryDirectory(prefix=".release-", dir=RELEASES) as temporary:
            root = Path(temporary)
            copy_tree(work, root)
            os.rename(root, RELEASES / revision)  # target was checked absent while locked
        release = RELEASES / revision
        venv = release / "venv"
        venv.mkdir(mode=0o700)
        os.chown(venv, pwd.getpwnam(BUILD_USER).pw_uid, -1)
        # Creating the venv at its final absolute path avoids broken shebangs.
        run(["/usr/local/lib/travel-deploy/build-release", "install-venv", str(release)],
            timeout=600, user=BUILD_USER)
        freeze_tree(release)
    except BaseException:
        shutil.rmtree(RELEASES / revision, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(work, ignore_errors=True)


def deploy(revision: str, digest: str) -> None:
    old = current_revision()
    build_release(revision, digest)
    switch_current(revision)
    if restart_and_check():
        return
    if old is None:
        raise DeployError("deployment failed and no previous release exists")
    switch_current(old)
    if not restart_and_check():
        raise DeployError("deployment and rollback both failed")
    raise DeployError("deployment failed; previous release was restored")


def rollback(revision: str) -> None:
    old = current_revision()
    if revision == old:
        raise DeployError("release is already current")
    switch_current(revision)
    if restart_and_check():
        return
    if old is not None:
        switch_current(old)
        restart_and_check()
    raise DeployError("rollback target failed health checks")


def cleanup(dry_run: bool) -> list[str]:
    current = current_revision()
    keep = {current} if current else set()
    candidates = sorted(path.name for path in RELEASES.iterdir()
                        if path.is_dir() and SHA.fullmatch(path.name) and path.name not in keep)
    if not dry_run:
        raise DeployError("cleanup is deliberately dry-run only")
    return candidates


def main(argv: list[str] | None = None) -> int:
    # Fail closed until the publication boundary and SSH integration have been
    # implemented and verified on Linux. Do not enable this in production.
    print("deployment controller disabled: security review incomplete", file=sys.stderr)
    return 1


def _unfinished_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    actions = parser.add_subparsers(dest="action", required=True)
    deploy_parser = actions.add_parser("deploy-artifact")
    deploy_parser.add_argument("revision")
    deploy_parser.add_argument("sha256")
    rollback_parser = actions.add_parser("rollback")
    rollback_parser.add_argument("revision")
    actions.add_parser("status")
    cleanup_parser = actions.add_parser("cleanup")
    cleanup_parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        if os.geteuid() != 0:
            raise DeployError("controller must run as root")
        with lifecycle_lock():
            if args.action == "deploy-artifact":
                revision, digest = checked(args.revision, SHA, "revision"), checked(args.sha256, DIGEST, "sha256")
                allowed_revision(revision)
                deploy(revision, digest)
            elif args.action == "rollback":
                rollback(checked(args.revision, SHA, "revision"))
            elif args.action == "status":
                print(current_revision() or "none")
            else:
                print("\n".join(cleanup(args.dry_run)))
    except (DeployError, OSError, subprocess.SubprocessError):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
