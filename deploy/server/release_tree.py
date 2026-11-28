"""Copy a quiescent build tree into a private directory, without executing it.

This is a building block, not a release controller. The caller must first prove
that all writers have stopped, and keep the source and destination parents
under trusted control for the duration of this operation.
"""
import os
import re
import stat

MAX_BYTES = 600 * 1024 * 1024
MAX_FILES = 100000
MAX_DEPTH = 32
CHUNK = 65536
PYTHON_LINK = re.compile(r'python(?:3(?:\.[0-9]+)?)?\Z')


class UnsafeTree(ValueError):
    """Build output cannot be copied across the release boundary."""


def allowed_python_link(parts, target):
    # CPython venv creates this compatibility link on 64-bit Linux.
    if parts == ('venv', 'lib64'):
        return target == 'lib'
    if len(parts) != 3 or parts[:2] != ('venv', 'bin') or not PYTHON_LINK.fullmatch(parts[2]):
        return False
    return bool(PYTHON_LINK.fullmatch(target) or target in ('/usr/bin/python3', '/usr/bin/python3.10'))


def copy_tree(source_fd, destination_fd, *, max_bytes=MAX_BYTES, max_files=MAX_FILES):
    """Copy by directory descriptors; never follow source symlinks.

    The destination must be a new empty directory inaccessible to untrusted
    users. A failed copy leaves partial output for its caller to clean up.
    """
    root_info = os.fstat(source_fd)
    dest_info = os.fstat(destination_fd)
    if not stat.S_ISDIR(root_info.st_mode) or not stat.S_ISDIR(dest_info.st_mode):
        raise UnsafeTree('source and destination must be directories')
    if os.listdir(destination_fd):
        raise UnsafeTree('destination must be empty')
    total = 0
    entries = 0

    def visit(src, dst, parts):
        nonlocal total, entries
        if len(parts) > MAX_DEPTH:
            raise UnsafeTree('directory depth exceeded')
        for name in sorted(os.listdir(src)):
            entries += 1
            if entries > max_files:
                raise UnsafeTree('entry count exceeded')
            metadata = os.stat(name, dir_fd=src, follow_symlinks=False)
            relative = (*parts, name)
            if metadata.st_dev != root_info.st_dev:
                raise UnsafeTree('filesystem boundary rejected')
            if stat.S_ISLNK(metadata.st_mode):
                target = os.readlink(name, dir_fd=src)
                if not allowed_python_link(relative, target):
                    raise UnsafeTree('unexpected symbolic link')
                os.symlink(target, name, dir_fd=dst)
            elif stat.S_ISDIR(metadata.st_mode):
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=src)
                try:
                    opened = os.fstat(child)
                    if (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino):
                        raise UnsafeTree('directory changed while opening')
                    os.mkdir(name, 0o700, dir_fd=dst)
                    target_fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=dst)
                    try:
                        visit(child, target_fd, relative)
                        os.fchmod(target_fd, 0o555)
                    finally:
                        os.close(target_fd)
                finally:
                    os.close(child)
            elif stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1:
                source = os.open(name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=src)
                try:
                    opened = os.fstat(source)
                    if (not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1 or
                            (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino)):
                        raise UnsafeTree('file changed while opening')
                    out = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                  0o600, dir_fd=dst)
                    try:
                        while True:
                            data = os.read(source, min(CHUNK, max_bytes - total + 1))
                            if not data:
                                break
                            total += len(data)
                            if total > max_bytes:
                                raise UnsafeTree('copy byte limit exceeded')
                            view = memoryview(data)
                            while view:
                                view = view[os.write(out, view):]
                        after = os.fstat(source)
                        if (after.st_size, after.st_mtime_ns, after.st_ctime_ns, after.st_nlink) != (
                                opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns, 1):
                            raise UnsafeTree('file changed while copying')
                        # Extracted build artifacts are often 0700/0600; any
                        # executable must remain runnable by the service user.
                        os.fchmod(out, 0o555 if opened.st_mode & 0o111 else 0o444)
                    finally:
                        os.close(out)
                finally:
                    os.close(source)
            else:
                raise UnsafeTree('hardlink or special file rejected')

    visit(source_fd, destination_fd, ())
    return total
