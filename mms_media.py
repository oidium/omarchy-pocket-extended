"""Validation for KDE-owned MMS files. No copies or persistent media index."""
import os
import stat
from pathlib import Path


def filename(value):
    if not isinstance(value, str) or not value or value in ('.', '..') or '/' in value or '\\' in value or any(ord(c) < 32 for c in value):
        raise ValueError('Unsupported attachment identifier')
    return value


def local_file(path, identifier, device_name):
    filename(identifier)
    filename(device_name)
    root = Path(os.environ.get('XDG_CACHE_HOME', str(Path.home() / '.cache'))) / 'kdeconnect.daemon'
    expected = root / device_name / identifier
    file = Path(path)
    if not file.is_absolute() or file != expected or root.is_symlink() or expected.parent.is_symlink() or file.is_symlink():
        raise ValueError('Downloaded attachment is unavailable')
    try:
        if not file.resolve(strict=True).is_relative_to(root.resolve(strict=True)):
            raise ValueError('Downloaded attachment is unavailable')
        fd = os.open(file, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode): raise ValueError('Downloaded attachment is unavailable')
            os.read(fd, 1)
        finally:
            os.close(fd)
    except OSError:
        raise ValueError('Downloaded attachment is missing or unreadable') from None
    return str(file), (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
