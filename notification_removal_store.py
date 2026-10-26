"""Private, bounded durable local-notification suppression state.

Only active notification occurrences are stored. Authoritative closure retires an
entry; the next occurrence for a reused KDE Connect id gets a fresh UUID.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import threading
import uuid

SCHEMA = 1
MAX_ENTRIES = 128
MAX_BYTES = 256 * 1024
TOKEN = re.compile(r'^[a-f0-9]{32}$')
FINGERPRINT = re.compile(r'^[a-f0-9]{64}$')


def notification_fingerprint(record):
    """Stable while a KDE notification occurrence is updated in place."""
    internal = record.get('internal_id', '')
    reply = record.get('reply_id', '')
    if internal:
        identity = [internal, reply]
    else:
        # Without an opaque capability token, presentation text cannot safely
        # distinguish a new occurrence from a delayed update. Keep the same
        # active device/id occurrence until authoritative closure retires it.
        identity = ['non-actionable', record.get('device', ''), record.get('id', '')]
    payload = json.dumps(identity, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(payload).hexdigest()


class NotificationRemovalStore:
    def __init__(self, path=None, persistent=True, disabled=False):
        self.disabled = disabled
        self.write_disabled = False
        self.persistent = persistent
        self._lock = threading.RLock()
        self.path = (Path(path) if path is not None else self.default_path()) if persistent else None
        self.entries = {}
        self.error = ''
        if persistent:
            self._ensure_directory()
            self._load()

    @staticmethod
    def default_path():
        state_home = os.environ.get('XDG_STATE_HOME') or str(Path.home() / '.local' / 'state')
        base = Path(state_home)
        if not base.is_absolute():
            raise ValueError('XDG_STATE_HOME must be an absolute path')
        return base / 'omarchy-pocket-extended' / 'notification-removals-v1.json'

    @staticmethod
    def key(device, note_id):
        return json.dumps([device, note_id], ensure_ascii=False, separators=(',', ':'))

    def _ensure_directory(self):
        directory = self.path.parent
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = os.lstat(directory)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise OSError('notification state directory is not a user-owned directory')
        if stat.S_IMODE(info.st_mode) != 0o700:
            os.chmod(directory, 0o700)

    def _load(self):
        try:
            fd = os.open(self.path, os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK | getattr(os, 'O_NOFOLLOW', 0))
        except FileNotFoundError:
            return
        except OSError as error:
            self.error = 'Local notification state is unavailable: ' + str(error)
            # Never acknowledge removals when an unsafe existing file cannot be read.
            self.write_disabled = True
            return
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
                    info.st_size > MAX_BYTES):
                raise ValueError('unsafe or oversized state file')
            if stat.S_IMODE(info.st_mode) != 0o600:
                os.fchmod(fd, 0o600)
            chunks = []
            remaining = MAX_BYTES + 1
            while remaining:
                block = os.read(fd, min(65536, remaining))
                if not block:
                    break
                chunks.append(block); remaining -= len(block)
            raw = b''.join(chunks)
            if len(raw) > MAX_BYTES:
                raise ValueError('oversized state file')
            value = json.loads(raw.decode('utf-8'))
            if not isinstance(value, dict) or value.get('schema') != SCHEMA or not isinstance(value.get('entries'), list):
                raise ValueError('unsupported local notification state schema')
            if len(value['entries']) > MAX_ENTRIES:
                raise ValueError('local notification state exceeds its bound')
            parsed = {}
            for row in value['entries']:
                if not isinstance(row, dict):
                    raise ValueError('invalid local notification state entry')
                device, note_id = row.get('device'), row.get('id')
                occurrence, fingerprint = row.get('occurrence_id'), row.get('fingerprint')
                if (not isinstance(device, str) or not 1 <= len(device) <= 256 or
                        not isinstance(note_id, str) or not 1 <= len(note_id) <= 256 or
                        not isinstance(occurrence, str) or not TOKEN.fullmatch(occurrence) or
                        not isinstance(fingerprint, str) or not FINGERPRINT.fullmatch(fingerprint) or
                        type(row.get('removed')) is not bool):
                    raise ValueError('invalid local notification state fields')
                key = self.key(device, note_id)
                if key in parsed:
                    raise ValueError('duplicate local notification state key')
                parsed[key] = {'device': device, 'id': note_id, 'occurrence_id': occurrence,
                               'fingerprint': fingerprint, 'removed': row['removed']}
            self.entries = parsed
        except (OSError, UnicodeError, ValueError, TypeError) as error:
            # Never truncate or silently replace corrupt state. Cleanup remains
            # unavailable until the user or a later version can recover it.
            self.error = 'Local notification state could not be read safely: ' + str(error)
            self.write_disabled = True
        finally:
            os.close(fd)

    def _save(self, entries):
        if self.disabled or self.write_disabled:
            raise OSError(self.error or 'persistent local notification state is disabled')
        if not self.persistent:
            return
        rows = sorted(entries.values(), key=lambda row: (row['device'], row['id']))
        payload = json.dumps({'schema': SCHEMA, 'entries': rows}, ensure_ascii=False,
                             sort_keys=True, separators=(',', ':')).encode('utf-8') + b'\n'
        if len(payload) > MAX_BYTES or len(rows) > MAX_ENTRIES:
            raise OSError('local notification state capacity reached')
        fd, temporary = tempfile.mkstemp(prefix='.notification-removals-', dir=self.path.parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, 'wb', closefd=True) as stream:
                stream.write(payload); stream.flush(); os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            directory_fd = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except Exception:
            try: os.unlink(temporary)
            except FileNotFoundError: pass
            raise

    def current(self, device, note_id):
        """Return the saved generation, including before a worker has read it."""
        with self._lock:
            row = self.entries.get(self.key(device, note_id))
            return dict(row) if row else None

    def occurrence(self, device, note_id, fingerprint):
        """Return the current occurrence UUID, persisting new generations first."""
        with self._lock:
            key = self.key(device, note_id)
            current = self.entries.get(key)
            if current and current['fingerprint'] == fingerprint:
                return current['occurrence_id']
            next_entries = dict(self.entries)
            if not current and len(next_entries) >= MAX_ENTRIES:
                return ''
            next_entries[key] = {'device': device, 'id': note_id,
                                 'occurrence_id': uuid.uuid4().hex,
                                 'fingerprint': fingerprint, 'removed': False}
            try:
                self._save(next_entries)
            except OSError as error:
                self.error = 'Local notification state could not be saved safely: ' + str(error)
                self.entries = next_entries
                return next_entries[key]['occurrence_id']
            self.entries = next_entries
            if not self.write_disabled:self.error = ''
            return next_entries[key]['occurrence_id']

    def mark_removed(self, entries):
        """Atomically persist the accepted active occurrence removals."""
        with self._lock:
            if not isinstance(entries, list) or len(entries) > MAX_ENTRIES:
                return {'removed': [], 'pending': 0, 'capacity': True, 'error': ''}
            next_entries = dict(self.entries); removed = []; pending = 0
            invalid = False
            for item in entries:
                if not isinstance(item, dict):
                    invalid = True
                    continue
                device, note_id, occurrence = item.get('device'), item.get('id'), item.get('occurrence_id')
                key = self.key(device, note_id) if isinstance(device, str) and isinstance(note_id, str) else ''
                current = next_entries.get(key)
                if not current or current['occurrence_id'] != occurrence:
                    invalid = True
                    continue
                if current['removed']:
                    removed.append({'device': device, 'id': note_id, 'occurrence_id': occurrence})
                    continue
                current = dict(current); current['removed'] = True; next_entries[key] = current
                removed.append({'device': device, 'id': note_id, 'occurrence_id': occurrence})
            if invalid:
                return {'removed': [], 'pending': pending, 'capacity': False,
                        'error': 'One or more notification occurrences changed. Refresh and review the list.'}
            if not removed:
                return {'removed': [], 'pending': pending, 'capacity': False, 'error': self.error}
            try:
                self._save(next_entries)
            except OSError as error:
                self.error = 'Local notification state could not be saved safely: ' + str(error)
                return {'removed': [], 'pending': pending, 'capacity': False, 'error': self.error}
            self.entries = next_entries; self.error = ''
            return {'removed': removed, 'pending': pending, 'capacity': False, 'error': ''}

    def retire(self, device, note_id, occurrence_id):
        """Retire only the exact occurrence after authoritative phone closure."""
        with self._lock:
            key = self.key(device, note_id); current = self.entries.get(key)
            if not current or current['occurrence_id'] != occurrence_id:
                return True
            next_entries = dict(self.entries); next_entries.pop(key, None)
            try:
                self._save(next_entries)
            except OSError as error:
                self.error = 'Could not retire closed notification state: ' + str(error)
                return False
            self.entries = next_entries; self.error = ''
            return True

    def is_removed(self, device, note_id, occurrence_id):
        key = self.key(device, note_id); current = self.entries.get(key)
        return bool(current and current['occurrence_id'] == occurrence_id and current['removed'])

    def suppressed(self):
        return [{'device': row['device'], 'id': row['id'], 'occurrence_id': row['occurrence_id']}
                for row in self.entries.values() if row['removed']]

    def snapshot(self):
        return [{'device': row['device'], 'id': row['id'], 'occurrence_id': row['occurrence_id'],
                 'removed': row['removed']} for row in self.entries.values()]

    def entries_for_device(self, device):
        return [dict(row) for row in self.entries.values() if row['device'] == device]
