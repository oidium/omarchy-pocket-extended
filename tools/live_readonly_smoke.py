#!/usr/bin/env python3
"""Opt-in live check. Reads two history pages; never sends/dismisses/opens anything.
Only anonymous counts are printed. Message contents remain in process memory.
"""
import collections
import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import tempfile
import time


def isolated_worker_environment(state_home, inherited=None):
    """Keep diagnostic worker persistence separate from the installed service."""
    environment = dict(os.environ if inherited is None else inherited)
    environment['XDG_STATE_HOME'] = str(state_home)
    return environment


def main():
    state_home = tempfile.TemporaryDirectory(prefix='pocket-smoke-state-')
    process = subprocess.Popen([sys.executable, str(Path(__file__).resolve().parents[1] / 'messaging_service.py')],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0,
                               env=isolated_worker_environment(state_home.name))
    selector = selectors.DefaultSelector(); selector.register(process.stdout, selectors.EVENT_READ)
    counts = collections.Counter(); messages = {}; notes = {}; pages = []; target = None; pending = False
    buffer = bytearray()
    def request():
        process.stdin.write((json.dumps({'op': 'history', 'request_id': str(len(pages)),
                            'device': target[0], 'thread': target[1], 'size': 25}) + '\n').encode())
    try:
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline and len(pages) < 2:
            for key, _ in selector.select(.5):
                data = key.fileobj.read(65536)
                if not data: raise RuntimeError('Worker stopped unexpectedly')
                buffer.extend(data)
                while b'\n' in buffer:
                    line, _, rest = buffer.partition(b'\n'); buffer[:] = rest
                    event = json.loads(line); counts[event['event']] += 1
                    if event['event'] == 'message':
                        m = event['message']; messages[(m['device_id'], m['thread_id'], m['message_id'])] = m
                    elif event['event'] == 'notification':
                        n = event['notification']; notes[(n['device'], n['id'])] = n
                    elif event['event'] == 'threads_refreshed' and messages and not pending:
                        m = max(messages.values(), key=lambda m: m['timestamp'])
                        target = (m['device_id'], m['thread_id']); pending = True; request()
                    elif event['event'] == 'history_result':
                        pages.append({k: event[k] for k in ('received', 'reason', 'next_offset', 'exhaustive', 'complete')})
                        if len(pages) < 2: request()
        print(json.dumps({'events': dict(counts), 'unique_messages': len(messages), 'pages': pages,
                          'reply_capable_notifications': sum(bool(n['reply_id']) for n in notes.values()),
                          'notification_icons': sum(bool(n['icon_path']) for n in notes.values())}))
        return 0 if len(pages) == 2 and not counts['error'] else 1
    finally:
        process.stdin.close()
        try: process.wait(timeout=3)
        except subprocess.TimeoutExpired: process.terminate(); process.wait(timeout=3)
        errors = process.stderr.read()
        print(json.dumps({'worker_exit': process.returncode, 'stderr_bytes': len(errors)}))
        selector.close()
        state_home.cleanup()

if __name__ == '__main__': sys.exit(main())
