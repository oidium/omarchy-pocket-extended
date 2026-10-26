"""Local SMS composer helpers; device communication remains in Service."""
import mimetypes
import os
from pathlib import Path
import re
import stat


def recipient(value):
    if not isinstance(value, str) or len(value) > 100 or not re.fullmatch(r'[+0-9*#().\s-]+', value):
        raise ValueError('Enter a phone number')
    number = re.sub(r'[().\s-]', '', value)
    if not re.fullmatch(r'\+?[0-9*#]{1,32}', number): raise ValueError('Enter a phone number')
    return number


def files(paths):
    if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
        raise ValueError('Invalid attachment selection')
    if len(paths)>32: raise ValueError('Select at most 32 attachments per message')
    result = []
    for value in dict.fromkeys(paths):
        path = Path(value)
        if not path.is_absolute(): raise ValueError('Attachments must be local files')
        try:
            path = path.resolve(strict=True)
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode): raise ValueError('Select a regular file')
                os.read(fd, 1)
            finally: os.close(fd)
        except OSError:
            raise ValueError('An attachment is missing or unreadable') from None
        result.append({'path': str(path), 'name': path.name, 'size': info.st_size,
                       'mime_type': mimetypes.guess_type(path.name)[0] or 'application/octet-stream'})
    return result


def picker_result(code, output):
    if code == 1 or (code == 0 and not output.strip()): return {'cancelled': True, 'files': []}
    if code != 0: raise ValueError('Could not open the file chooser')
    return {'cancelled': False, 'files': files(output.rstrip('\n').split('\n'))}
