#!/usr/bin/env python3
"""Persistent asynchronous KDE Connect adapter; private JSON-lines stdin/stdout.

Owned by the shell-wide Service.qml, not monitor-local panels or popups. Closing a panel never stops it.
No persistent message/contact database. Notification mutations require explicit UI commands and fresh capability checks.
"""
import json
import os
from pathlib import Path
import re
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
import contacts
import sms
import mms_media
from media_remote import RemoteMedia, IFACE as MPRIS_REMOTE
from notification_text import plain_conversation_text

import gi
gi.require_version('Gio', '2.0')
from gi.repository import Gio, GLib
from messaging import Store, bounded_text, json_line_size, utf8_size
from identity import PLUGIN_ID
from telephony import CallEvents
from notification_removal_store import NotificationRemovalStore, notification_fingerprint

BUS = 'org.kde.kdeconnect'
ROOT = '/modules/kdeconnect'
DEVICE = BUS + '.device'
CONVERSATIONS = DEVICE + '.conversations'
NOTIFICATIONS = DEVICE + '.notifications'
PROPERTIES = 'org.freedesktop.DBus.Properties'
ID = re.compile(r'^[A-Za-z0-9_]+$')
MAX_NOTIFICATION_ID_BYTES = 1024
MAX_NOTIFICATION_EVENT_BYTES = 32 * 1024
MAX_NOTIFICATION_IDENTITIES = 4096
MAX_RECIPIENTS = 16
MAX_RECIPIENT_BYTES = 256
MAX_DEVICE_NAME_BYTES = 256
MAX_DEVICE_PLUGINS = 128
MAX_DEVICE_PLUGIN_ID_BYTES = 128
MAX_DEVICE_EVENT_BYTES = 614400
DEVICE_PLUGIN_ID_PATTERN = re.compile(r'^[A-Za-z0-9_.-]+$')


def exact_identifier(value):
    """Keep opaque KDE Connect tokens exact, or return empty to disable actions."""
    if not isinstance(value, str) or not value:
        return ''
    if utf8_size(value) > MAX_NOTIFICATION_ID_BYTES or any(0xd800 <= ord(char) <= 0xdfff for char in value):
        return ''
    return value


def normalize_recipient_scope(value):
    """Return the exact ordered scope represented by a reply composer."""
    if not isinstance(value, (list, tuple)) or not value or len(value) > MAX_RECIPIENTS:
        raise ValueError('Recipient list is missing or incomplete. Refresh history before replying.')
    result = []
    for address in value:
        if not isinstance(address, str) or not address or utf8_size(address) > MAX_RECIPIENT_BYTES:
            raise ValueError('Recipient list is missing or incomplete. Refresh history before replying.')
        result.append(address)
    return tuple(result)


def notification_size(record):
    return json_line_size({'event': 'notification', 'notification': record,
                           'notification_epoch': '0' * 32})


def fit_notification(record):
    """Fit display text to the complete event budget without changing tokens."""
    for field in ('body', 'title', 'app', 'icon_path'):
        original = record[field]
        if notification_size(record) <= MAX_NOTIFICATION_EVENT_BYTES:
            return True
        low, high = 0, utf8_size(original)
        while low < high:
            middle = (low + high + 1) // 2
            record[field] = bounded_text(original, middle)
            if notification_size(record) <= MAX_NOTIFICATION_EVENT_BYTES:
                low = middle
            else:
                high = middle - 1
        record[field] = bounded_text(original, low)
    return notification_size(record) <= MAX_NOTIFICATION_EVENT_BYTES


def device_path(device):
    if not isinstance(device, str) or len(device) > 256 or not ID.fullmatch(device):
        raise ValueError('Invalid device identifier')
    return ROOT + '/devices/' + device


def valid_device_name(value):
    return (isinstance(value, str) and bool(value) and
            utf8_size(value) <= MAX_DEVICE_NAME_BYTES and
            not any(0xd800 <= ord(char) <= 0xdfff for char in value) and
            not any(ord(char) < 32 or ord(char) == 127 for char in value))


def normalize_device_plugins(value, error=False):
    """Keep exact, bounded plugin IDs; malformed lists disable capabilities."""
    if error or not isinstance(value, (list, tuple)) or len(value) > MAX_DEVICE_PLUGINS:
        return [], False
    result = []
    for plugin in value:
        if (not isinstance(plugin, str) or not plugin or len(plugin) > MAX_DEVICE_PLUGIN_ID_BYTES or
                len(plugin.encode('utf-8', 'surrogatepass')) > MAX_DEVICE_PLUGIN_ID_BYTES or
                any(0xd800 <= ord(char) <= 0xdfff for char in plugin) or
                not DEVICE_PLUGIN_ID_PATTERN.fullmatch(plugin)):
            return [], False
        if plugin not in result:
            result.append(plugin)
    return result, True


class Transport:
    def __init__(self):
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)

    def call(self, path, interface, method, signature, args, callback):
        def done(bus, result, _):
            try:
                value = bus.call_finish(result).unpack()
            except GLib.Error:
                callback(None, 'KDE Connect could not complete the operation')
            else:
                callback(value, None)
        self.bus.call(BUS, path, interface, method,
                      GLib.Variant(signature, args) if signature else None,
                      None, Gio.DBusCallFlags.NONE, 5000, None, done, None)


class Service:
    def __init__(self, transport, emit, clock=time.monotonic, notification_state=None):
        self.transport, self.emit, self.clock = transport, emit, clock
        self.store = Store(emit, clock)
        self.calls = CallEvents(emit, clock)
        self.devices = {}
        self.notifications = {}
        self.notification_state = notification_state or NotificationRemovalStore(persistent=False)
        self.notification_epoch = uuid.uuid4().hex
        self.note_versions = {}
        self.note_sequence = 0
        # One monotone observation fence survives per-ID payload eviction. A
        # bounded snapshot may retire state only if no notification observation
        # arrived after that snapshot was requested.
        self.notification_observation_revision = 0
        self.notification_event_revision = 0
        self.note_reads = {}
        self.note_dirty = set()
        self.attachments = {}
        self.attachment_owners = {}  # Retained across reconnects: never rebind a filename.
        self.downloads = {}          # Bounded ephemeral references to KDE's cache only.
        self.notification_actions = {}
        self.epoch = 0
        self.scan_active = False
        self.scan_again = False
        self.refresh_due = None
        self.scan_retries = 0
        self.stopped = False
        self.local_pool = None
        self.contact_jobs = set()
        self.sms_actions = {}
        self.picker = None
        self.media = RemoteMedia(self)

    def call(self, path, interface, method, signature=None, args=(), callback=None):
        epoch = self.epoch
        def completed(value, error):
            if not self.stopped and epoch == self.epoch and callback:
                callback(value, error)
        self.transport.call(path, interface, method, signature, args, completed)

    def failure(self, request, text):
        self.emit({'event': 'error', 'request_id': request, 'error': text})

    def schedule_refresh(self):
        self.refresh_due = self.clock() + .2

    def emit_device(self, current):
        event = {'event': 'device', 'device': current}
        if json_line_size(event) > MAX_DEVICE_EVENT_BYTES:
            current = {'id': current.get('id', ''), 'name': 'Phone', 'name_valid': False,
                       'online': bool(current.get('online')), 'plugins': [],
                       'capabilities': 'unavailable', 'generation': current.get('generation', 0)}
            self.devices[current['id']] = current
            event = {'event': 'device', 'device': current}
        self.emit(event)

    def refresh(self):
        if self.scan_active:
            self.scan_again = True
            return
        self.scan_active = True
        def listed(value, error):
            if error:
                self.scan_active = False
                self.failure(None, 'KDE Connect is unavailable')
                self.scan_retries += 1
                if self.scan_retries <= 2:
                    self.refresh_due = self.clock() + 2 ** self.scan_retries
                return
            self.scan_retries = 0
            if not isinstance(value, (tuple, list)) or not value or not isinstance(value[0], (tuple, list)):
                self.scan_active = False
                self.failure(None, 'KDE Connect returned invalid device metadata')
                return
            if len(value[0]) > 64:
                self.scan_active = False
                self.failure(None, 'KDE Connect returned too many devices')
                return
            ids = set(sorted(d for d in value[0] if isinstance(d, str) and len(d) <= 256 and ID.fullmatch(d))[:16])
            for device in set(self.devices) - ids:
                self.disconnect(device)
                self.devices.pop(device, None)
            remaining = set(ids)
            if not remaining:
                self.end_scan()
            for device in ids:
                def props(value, error, device=device):
                    data = value[0] if not error and isinstance(value, (tuple, list)) and value and isinstance(value[0], dict) else {}
                    name_valid = valid_device_name(data.get('name'))
                    name = data.get('name') if name_valid else 'Phone'
                    online = data.get('isReachable') is True and data.get('isPaired') is True
                    previous = self.devices.get(device, {})
                    if not online:
                        self.disconnect(device)
                    current = {'id': device, 'name': name, 'name_valid': name_valid, 'online': online,
                               'plugins': None, 'capabilities': 'pending' if online else 'offline',
                               'generation': previous.get('generation', 0) + (0 if previous.get('online') else 1)}
                    self.devices[device] = current
                    self.emit_device(current)
                    if online:
                        generation = current['generation']
                        def plugins(value, error):
                            if not self.current(device, generation):
                                return
                            raw_plugins = value[0] if not error and isinstance(value, (tuple, list)) and value else None
                            available, plugins_valid = normalize_device_plugins(raw_plugins, error)
                            current['plugins'] = available
                            current['capabilities'] = 'available' if plugins_valid else 'unavailable'
                            self.emit_device(current)
                            if 'kdeconnect_notifications' in available:
                                self.refresh_notifications(device)
                            if 'kdeconnect_sms' in available:
                                self.refresh_threads(device)
                            if 'kdeconnect_mprisremote' in available:
                                self.media.refresh(device)
                        self.call(device_path(device), DEVICE, 'loadedPlugins', callback=plugins)
                    remaining.discard(device)
                    if not remaining:
                        self.end_scan()
                self.call(device_path(device), PROPERTIES, 'GetAll', '(s)', (DEVICE,), props)
        self.call(ROOT, BUS + '.daemon', 'devices', '(bb)', (False, True), listed)

    def end_scan(self):
        self.scan_active = False
        if self.scan_again:
            self.scan_again = False
            self.schedule_refresh()

    def current(self, device, generation):
        current = self.devices.get(device, {})
        valid = current.get('online') and current.get('generation') == generation
        return valid

    def disconnect(self, device):
        self.media.clear(device)
        previous = self.devices.get(device, {})
        previous.update(online=False, generation=previous.get('generation', 0) + 1)
        self.devices[device] = previous
        self.store.reset_device(device)
        self.downloads = {k: v for k, v in self.downloads.items() if k[0] != device}
        self.calls.clear_device(device)
        if device in self.sms_actions:
            op = self.sms_actions[device]
            self.finish_sms(device, op, False, 'Connection changed. Check the phone before trying again.' if op['submitted'] else 'Phone is offline. Your draft is saved.')
        for key, op in list(self.notification_actions.items()):
            if key[0] == device:
                self.finish_notification_action(key, op, False,
                    'Connection changed. Check the phone before trying again.' if op['submitted'] else 'Reply no longer available')
        for key in list(self.notifications):
            if key[0] == device:
                self.remove_notification(*key)
        for key, op in list(self.attachments.items()):
            if key[0] == device:
                self.failure(op['request_id'], 'Phone is offline')
                del self.attachments[key]
        self.emit({'event': 'device_offline', 'device': device})

    def owner_changed(self):
        self.epoch += 1
        self.note_reads.clear()
        self.note_dirty.clear()
        self.scan_active = self.scan_again = False
        self.scan_retries = 0
        for device in list(self.devices):
            self.disconnect(device)
        self.schedule_refresh()

    def refresh_threads(self, device):
        generation = self.devices[device]['generation']
        def heads(value, error):
            if not self.current(device, generation):
                return
            if error:
                self.emit({'event': 'threads_error', 'device': device, 'error': 'Conversation summaries are unavailable. Try refreshing.'})
                self.failure(None, 'Conversation summaries are unavailable')
                return
            for wire in value[0]:
                self.ingest(device, wire)
            self.emit({'event': 'threads_refreshed', 'device': device, 'exhaustive': False})
        self.call(device_path(device), CONVERSATIONS, 'activeConversations', callback=heads)
        self.call(device_path(device), CONVERSATIONS, 'requestAllConversationThreads')

    def ingest(self, device, wire, history=False):
        try:
            return self.store.ingest(device, wire, history)
        except (ValueError, TypeError, IndexError):
            self.failure(None, 'Unsupported KDE Connect message record; messaging needs review')

    def refresh_notifications(self, device):
        generation = self.devices[device]['generation']
        revision = dict(self.note_versions)
        observation_revision = self.notification_observation_revision
        def listed(value, error):
            if error or not self.current(device, generation):
                return
            if (not isinstance(value, (tuple, list)) or len(value) != 1 or
                    not isinstance(value[0], (tuple, list))):
                self.failure(None, 'Could not refresh notifications because KDE Connect returned invalid data')
                return
            listed_ids = value[0]
            membership_complete = len(listed_ids) <= MAX_NOTIFICATION_IDENTITIES
            valid_id = lambda n: isinstance(n, str) and len(n) <= 256 and ID.fullmatch(n)
            # Keep authoritative membership separate from the property-read cap.
            # Oversized or malformed lists may still supply a bounded read sample,
            # but they never prove that an omitted identity has closed.
            if membership_complete:
                validated = {n for n in listed_ids if valid_id(n)}
                membership_complete = all(valid_id(n) for n in listed_ids)
                if not membership_complete:
                    self.failure(None, 'Could not refresh notifications because KDE Connect returned invalid data')
                active = set(sorted(validated)[:128])
            else:
                validated = set()
                active = set()
                for note_id in listed_ids:
                    if valid_id(note_id):
                        active.add(note_id)
                        if len(active) == 128:
                            break
            known = set(self.notifications) | set(self.note_versions)
            # A list can be complete yet stale. This scalar fence is independent
            # of note_versions and survives transient property failures that
            # evict their per-ID payload and version records.
            snapshot_is_current = observation_revision == self.notification_observation_revision
            if membership_complete and snapshot_is_current:
                for key in known:
                    if key[0] == device and key[1] not in validated and self.note_versions.get(key) == revision.get(key):
                        self.remove_notification(*key, authoritative=True)
                for saved in self.notification_state.entries_for_device(device):
                    if saved['id'] not in validated and (device, saved['id']) not in known:
                        self.remove_notification(device, saved['id'], authoritative=True)
            for note in active:
                key = (device, note)
                if self.note_versions.get(key) == revision.get(key):
                    self.read_notification(device, note)
        self.call(device_path(device) + '/notifications', NOTIFICATIONS,
                  'activeNotifications', callback=listed)

    def remove_notification(self, device, note, authoritative=False):
        key = (device, note)
        self.notification_observation_revision += 1
        current = self.notifications.get(key)
        saved = self.notification_state.current(device, note)
        occurrence = current.get('occurrence_id', '') if current else (saved.get('occurrence_id', '') if saved else '')
        revision = self.next_notification_event_revision()
        retired = self.notification_state.retire(device, note, occurrence) if authoritative and occurrence else True
        authoritative = bool(authoritative and retired)
        self.note_versions.pop(key, None)
        self.note_reads.pop(key, None)
        self.note_dirty.discard(key)
        self.notifications.pop(key, None)
        self.calls.remove_notification(device, note)
        self.emit({'event': 'notification_removed', 'device': device, 'id': note, 'occurrence_id': occurrence, 'authoritative': bool(authoritative), 'revision': revision, 'notification_epoch': self.notification_epoch})

    def next_notification_event_revision(self):
        self.notification_event_revision += 1
        return self.notification_event_revision

    def read_notification(self, device, note):
        if not isinstance(note, str) or len(note) > 256 or not ID.fullmatch(note):
            return
        # Count the observation before coalescing, property reads, or failure
        # paths can erase its per-ID bookkeeping.
        self.notification_observation_revision += 1
        key = (device, note)
        if key in self.note_reads:
            self.note_dirty.add(key)
            return
        if len(self.note_reads) >= 128:
            return
        if key not in self.note_versions and len(self.note_versions) >= 128:
            self.remove_notification(*next(iter(self.note_versions)))
        self.note_sequence += 1
        version = self.note_versions[key] = self.note_sequence
        self.note_reads[key] = version
        generation = self.devices.get(device, {}).get('generation')
        def loaded(value, error):
            self.note_reads.pop(key, None)
            if key in self.note_dirty:
                self.note_dirty.discard(key)
                self.read_notification(device, note)
                return
            if not self.current(device, generation) or self.note_versions.get(key) != version:
                return
            if error:
                self.remove_notification(device, note)
                return
            data = value[0]
            if not isinstance(data, dict):
                self.remove_notification(device, note)
                return
            # A membership request may be in flight while this property read
            # is pending. Once the current, validated result is accepted, a
            # later-arriving membership response cannot prove absence relative
            # to this observation. Obsolete callbacks returned above and do
            # not advance the fence.
            self.notification_observation_revision += 1
            app = bounded_text(data.get('appName'), 1024)
            title = bounded_text(data.get('title'), 4096)
            body = bounded_text(plain_conversation_text(bounded_text(data.get('text'), 16384), data.get('isConversation') is True), 16384)
            internal_id = exact_identifier(data.get('internalId'))
            # Both reply and dismiss validation depend on the internal token.
            # Hide reply capability as well when that token is malformed or oversized.
            reply_id = exact_identifier(data.get('replyId')) if internal_id else ''
            icon_path = bounded_text(data.get('iconPath'), 4096)
            record = {'device': bounded_text(device, 256), 'id': bounded_text(note, 256), 'revision': self.next_notification_event_revision(),
                      'internal_id': internal_id, 'app': app, 'title': title,
                      'body': body, 'dismissable': bool(data.get('dismissable')) and bool(internal_id),
                      'reply_id': reply_id, 'icon_path': icon_path,
                      'icon_kind': 'notification_icon'}
            occurrence = self.notification_state.occurrence(device, note, notification_fingerprint(record))
            if not occurrence:
                self.emit({'event': 'notification_state_capacity', 'device': device,
                           'error': self.notification_state.error or
                           'Local notification state capacity reached. Close older notifications on the phone, then refresh.'})
                return
            record['occurrence_id'] = occurrence
            if not fit_notification(record):
                self.remove_notification(device, note)
                return
            self.notifications[key] = record
            self.calls.notification(record)
            self.emit({'event': 'notification', 'notification': record, 'notification_epoch': self.notification_epoch})
        self.call(device_path(device) + '/notifications/' + note, PROPERTIES, 'GetAll',
                  '(s)', (NOTIFICATIONS + '.notification',), loaded)

    def finish_notification_action(self, key, op, accepted, error=''):
        if self.notification_actions.get(key) is not op:
            return
        self.notification_actions.pop(key)
        self.emit({'event': 'notification_action_result', 'request_id': op['request_id'],
                   'device': key[0], 'id': key[1], 'action': op['action'],
                   'accepted': accepted, 'delivery_confirmed': None,
                   'uncertain': bool(op['submitted'] and not accepted), 'error': error})

    def notification_action(self, command):
        device, note = command['device'], command['id']
        action = command['op']
        self.require_online(device, 'kdeconnect_notifications')
        if not isinstance(note, str) or not ID.fullmatch(note):
            raise ValueError('Invalid notification')
        expected_occurrence = command.get('occurrence_id')
        expected_epoch = command.get('notification_epoch')
        if (not isinstance(expected_occurrence, str) or not expected_occurrence or
                len(expected_occurrence) > 128 or
                not isinstance(expected_epoch, str) or expected_epoch != self.notification_epoch):
            raise ValueError('Notification action is no longer available')
        key = (device, note)
        if key in self.notification_actions:
            raise ValueError('Notification action is already pending')
        record = self.notifications.get(key)
        expected_reply = command.get('reply_id', '')
        expected_internal = command.get('internal_id', '')
        text = command.get('text', '')
        if action == 'notification_reply' and (not isinstance(text, str) or not text.strip() or len(text) > 16384):
            raise ValueError('Enter a reply of at most 16384 characters')
        if not isinstance(expected_internal, str) or not exact_identifier(expected_internal):
            raise ValueError('Notification action is no longer available')
        if action == 'notification_reply' and (not isinstance(expected_reply, str) or not exact_identifier(expected_reply)):
            raise ValueError('Reply is no longer available')
        op = {'request_id': command.get('request_id'), 'action': action,
              'submitted': False, 'deadline': self.clock() + 12}
        self.notification_actions[key] = op
        def valid(data):
            if data.get('internalId', '') != expected_internal:
                return False
            if action == 'notification_reply':
                return bool(expected_reply and data.get('replyId') == expected_reply)
            return bool(data.get('dismissable'))
        if not record or record.get('occurrence_id') != expected_occurrence or record['internal_id'] != expected_internal or (
            action == 'notification_reply' and (not expected_reply or record['reply_id'] != expected_reply)):
            self.finish_notification_action(key, op, False, 'Reply no longer available' if action == 'notification_reply' else 'Notification no longer available')
            return
        version = self.note_versions.get(key)
        generation = self.devices[device]['generation']
        def still_authorized():
            return (self.notification_actions.get(key) is op and
                    self.notification_epoch == expected_epoch and
                    self.current(device, generation) and
                    self.note_versions.get(key) == version and
                    self.notifications.get(key) is record and
                    record.get('occurrence_id') == expected_occurrence)
        def checked(value, error):
            if self.notification_actions.get(key) is not op:
                return
            if error or not still_authorized() or not isinstance(value, (tuple, list)) or not value or not isinstance(value[0], dict) or not valid(value[0]):
                self.finish_notification_action(key, op, False, 'Reply no longer available' if action == 'notification_reply' else 'Dismiss no longer available')
                return
            # Recheck the exact occurrence immediately before dispatch.
            if not still_authorized():
                self.finish_notification_action(key, op, False, 'Reply no longer available' if action == 'notification_reply' else 'Dismiss no longer available')
                return
            op['submitted'] = True
            def completed(value, error):
                self.finish_notification_action(key, op, not error,
                    'Could not confirm the action. Check the phone before trying again.' if error else '')
            if action == 'notification_reply':
                # Send the exact validated token, never the possibly replaced object's
                # current token, and never route a failure to SMS/MMS. Never retry.
                self.call(device_path(device) + '/notifications', NOTIFICATIONS,
                          'sendReply', '(ss)', (expected_reply, text), completed)
            else:
                self.call(device_path(device) + '/notifications/' + note,
                          NOTIFICATIONS + '.notification', 'dismiss', callback=completed)
        self.call(device_path(device) + '/notifications/' + note, PROPERTIES,
                  'GetAll', '(s)', (NOTIFICATIONS + '.notification',), checked)

    def local_job(self, work, complete):
        if self.local_pool is None:
            self.local_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='pocket-local')
        future = self.local_pool.submit(work)
        def completed(future):
            try:
                value, error = future.result(), None
            except (OSError, ValueError) as exc:
                value, error = None, str(exc)
            def deliver():
                if not self.stopped: complete(value, error)
                return False
            GLib.idle_add(deliver)
        future.add_done_callback(completed)

    def get_contacts(self, device, request=None):
        device_path(device)
        if len(self.contact_jobs) >= 16: raise ValueError('Contacts are busy; try again shortly')
        if device in self.contact_jobs: return
        self.contact_jobs.add(device)
        def completed(value, error):
            self.contact_jobs.discard(device)
            if value:
                self.calls.resolve_contacts(device, value['contacts'])
            self.emit({'event': 'contacts', 'device': device, 'request_id': request,
                       **(value or {'contacts': [], 'available': False}),
                       'error': 'Contacts are unavailable; enter a number manually' if error else ''})
        self.local_job(lambda: contacts.read_contacts(device), completed)

    def pick_files(self, device, request):
        device_path(device)
        if self.picker: raise ValueError('File chooser is already open')
        try:
            process = Gio.Subprocess.new(['omarchy-file-select', '--title', 'Attach files to SMS/MMS', '--multiple'],
                                         Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE)
        except GLib.Error:
            raise ValueError('System file chooser is unavailable') from None
        self.picker = process
        def timeout():
            if self.picker is process: process.force_exit()
            return False
        timer = GLib.timeout_add_seconds(610, timeout)
        def finished(proc, result, _):
            self.picker = None
            GLib.source_remove(timer)
            try:
                _, output, _ = proc.communicate_utf8_finish(result)
                code = proc.get_exit_status() if proc.get_if_exited() else 2
            except GLib.Error:
                code, output = 2, ''
            def validated(value, error):
                if error: self.failure(request, error)
                else: self.emit({'event': 'files_selected', 'device': device, 'request_id': request, **value})
            self.local_job(lambda: sms.picker_result(code, output), validated)
        process.communicate_utf8_async(None, None, finished, None)

    def finish_sms(self, device, op, accepted, error=''):
        if self.sms_actions.get(device) is not op: return
        self.sms_actions.pop(device)
        self.emit({'event': 'sms_result', 'device': device, 'request_id': op['request_id'],
                   'accepted': accepted, 'delivery_confirmed': None,
                   'uncertain': bool(op['submitted'] and not accepted), 'error': error})

    def send_sms(self, command):
        device = command['device']
        self.require_online(device)
        if device in self.sms_actions: raise ValueError('A message is already sending')
        thread = str(command['thread']) if command.get('op') == 'sms_reply' else None
        requested_scope = None
        if thread is not None:
            if command.get('conversation_token') != self.store.token(device, thread):
                raise ValueError('Conversation changed. Your draft is saved; review a new reply before sending.')
            # Recipient authorization is retained independently from message
            # payloads. A bounded-history eviction must not disable a reply
            # while this conversation object, session token and singleton
            # evidence remain current.
            if (device, thread) not in self.store.threads:
                raise ValueError('Conversation is unavailable. Refresh before replying.')
            requested_scope = normalize_recipient_scope(command.get('recipient_scope'))
            status = self.store.reply_status(device, thread)
            if status == 'group':
                raise ValueError('Group replies are unavailable for recipient safety.')
            if status != 'individual':
                raise ValueError('Recipient scope is incomplete or uncertain. Refresh history before replying.')
            current_scope = self.recipient_scope(device, thread)
            if current_scope is None:
                raise ValueError('Recipient list is incomplete. Refresh history before replying.')
            if requested_scope != current_scope:
                raise ValueError('Recipient list changed. Your draft is saved; review a new reply before sending.')
            if not -(2**63) <= int(thread) < 2**63:
                raise ValueError('Invalid thread identifier')
        number = sms.recipient(command['recipient']) if thread is None else None
        body = command.get('text', '')
        paths = command.get('files', [])
        if not isinstance(body, str) or len(body) > 65536 or (not body.strip() and not paths):
            raise ValueError('Enter a message or attach a file')
        op = {'request_id': command.get('request_id'), 'submitted': False, 'deadline': self.clock() + 20}
        self.sms_actions[device] = op
        generation = self.devices[device]['generation']
        def validated(selected, error):
            if self.sms_actions.get(device) is not op: return
            if error:
                self.finish_sms(device, op, False, error); return
            def ready(value, error):
                if self.sms_actions.get(device) is not op: return
                props = value[0] if not error else {}
                if error or not self.current(device, generation) or not props.get('isReachable') or not props.get('isPaired'):
                    self.finish_sms(device, op, False, 'Phone is offline. Your draft is saved.'); return
                if thread is not None and not self.store.threads.get((device, thread)):
                    self.finish_sms(device, op, False, 'Conversation is no longer available. Your draft is saved.'); return
                if thread is not None and command.get('conversation_token') != self.store.token(device, thread):
                    self.finish_sms(device, op, False, 'Conversation changed. Your draft is saved.'); return
                if thread is not None:
                    status = self.store.reply_status(device, thread)
                    if status == 'group':
                        self.finish_sms(device, op, False, 'Group replies are unavailable for recipient safety.'); return
                    if status != 'individual':
                        self.finish_sms(device, op, False, 'Recipient scope is incomplete or uncertain. Your draft is saved; refresh history before replying.'); return
                    current_scope = self.recipient_scope(device, thread)
                    if current_scope is None:
                        self.finish_sms(device, op, False, 'Recipient list is incomplete. Your draft is saved; refresh history before replying.'); return
                    if current_scope != requested_scope:
                        self.finish_sms(device, op, False, 'Recipient list changed. Your draft is saved; review a new reply before sending.'); return
                op['submitted'] = True
                # KDE's av addresses contain variants of (s), not raw strings.
                # Its attachmentUrls parameter actually expects local file paths.
                args = ([GLib.Variant('(s)', (number,))] if number is not None else [], body,
                        [GLib.Variant('s', f['path']) for f in selected])
                def sent(value, error):
                    self.finish_sms(device, op, not error,
                        'Could not confirm sending. Check the phone before trying again.' if error else '')
                if thread is not None:
                    # KDE Connect selects the cached conversation's full address list and SIM.
                    self.call(device_path(device), CONVERSATIONS, 'replyToConversation', '(xsav)',
                              (int(thread), body, args[2]), sent)
                else:
                    self.call(device_path(device), CONVERSATIONS, 'sendWithoutConversation', '(avsav)', args, sent)
            self.call(device_path(device), PROPERTIES, 'GetAll', '(s)', (DEVICE,), ready)
        self.local_job(lambda: sms.files(paths), validated)

    def recipient_scope(self, device, thread):
        if self.store.reply_status(device, thread) != 'individual':
            return None
        evidence = self.store.reply_scopes.get((device, str(thread)))
        return evidence[0] if evidence else None

    def recipient_count(self, device, thread):
        conversation = self.store.threads.get((device, str(thread)))
        if not conversation or not conversation.messages:
            return 0
        head = max(conversation.messages.values(),
                   key=lambda message: (message.timestamp, len(message.message_id), message.message_id))
        return max(len(message.addresses) for message in conversation.messages.values())

    def require_online(self, device, plugin='kdeconnect_sms'):
        device_path(device)
        state = self.devices.get(device, {})
        if not state.get('online'):
            raise ValueError('Phone is offline')
        if state.get('plugins') is None:
            raise ValueError('KDE Connect capabilities are still loading. Try again when the phone status is ready.')
        if plugin not in state.get('plugins', []):
            raise ValueError('This KDE Connect capability is unavailable')

    def request_page(self, page):
        key = (page.device, page.thread)
        def requested(value, error):
            if error and self.store.pages.get(key) is page:
                self.store.finish_page(key, 'error')
                self.failure(page.request_id, error)
        self.call(device_path(page.device), CONVERSATIONS, 'requestConversation', '(xii)',
                  (int(page.thread), page.start, page.start + page.size), requested)

    def request_attachment(self, request, device, thread, message_id, part_id, identifier):
        self.require_online(device)
        identity = (device, str(thread), str(message_id), str(part_id), identifier)
        self.attachment_descriptor(identity)
        mms_media.filename(identifier)
        if not 0 <= int(part_id) < 2**63: raise ValueError('Unsupported attachment part')
        if self.devices[device].get('name_valid') is False:
            raise ValueError('Phone name is unavailable; cannot safely resolve the attachment cache')
        name = self.devices[device].get('name', 'Phone')
        mms_media.filename(name)
        if any(d != device and s.get('name') == name for d, s in self.devices.items()):
            raise ValueError('Ambiguous KDE attachment cache: devices share a name')
        # KDE caches by device name + identifier, and signals only that identifier.
        owner_key = (name, identifier)
        owner = self.attachment_owners.get(owner_key)
        if owner is not None and owner != identity:
            raise ValueError('Attachment filename is ambiguous; cannot retrieve safely')
        if owner is None and len(self.attachment_owners) >= 2048:
            raise ValueError('Attachment session limit reached')
        key = (device, identifier)
        if key in self.attachments:
            raise ValueError('This attachment is already loading')
        if len(self.attachments) >= 8: raise ValueError('Too many attachments loading; try again shortly')
        self.attachment_owners[owner_key] = identity
        op = {'request_id': request, 'part_id': str(part_id), 'deadline': self.clock() + 30,
              'attempts': 1, 'identity': identity, 'name': name, 'name_valid': self.devices[device].get('name_valid') is not False,
              'generation': self.devices[device]['generation']}
        self.attachments[key] = op
        self.emit({'event': 'attachment_loading', 'request_id': request, 'device': device,
                   'thread': str(thread), 'message_id': str(message_id), 'part_id': str(part_id), 'identifier': identifier})
        self.fetch_attachment(key, op)

    def attachment_descriptor(self, identity):
        device, thread, message_id, part_id, identifier = identity
        if self.devices.get(device, {}).get('name_valid') is False:
            raise ValueError('Phone name is unavailable; cannot safely resolve the attachment cache')
        name = self.devices.get(device, {}).get('name', 'Phone')
        if any(d != device and s.get('name') == name for d, s in self.devices.items()):
            raise ValueError('Ambiguous KDE attachment cache: devices share a name')
        conversation = self.store.threads.get((device, thread))
        message = conversation.messages.get(message_id) if conversation else None
        if not message or not any(a.part_id == part_id and a.identifier == identifier for a in message.attachments):
            raise ValueError('Attachment is no longer available in this conversation')
        for c in self.store.threads.values():
            if c.device_id == device:
                for other in c.messages.values():
                    for a in other.attachments:
                        if a.identifier == identifier and (device, c.thread_id, other.message_id, a.part_id, a.identifier) != identity:
                            raise ValueError('Attachment filename is ambiguous; cannot retrieve safely')
        return message

    def fetch_attachment(self, key, op):
        device, identifier = key
        try:
            if (not self.current(device, op['generation']) or
                    self.devices[device].get('name_valid') is False or
                    self.devices[device].get('name', 'Phone') != op['name']):
                raise ValueError('Attachment connection changed')
            self.attachment_descriptor(op['identity'])
        except ValueError as error:
            self.attachments.pop(key, None)
            self.failure(op['request_id'], str(error))
            return
        def requested(value, error):
            if error and self.attachments.get(key) is op:
                self.attachments.pop(key)
                self.failure(op['request_id'], error)
        self.call(device_path(device), CONVERSATIONS, 'requestAttachmentFile', '(xs)',
                  (int(op['part_id']), identifier), requested)

    def attachment_received(self, device, path, filename):
        key = (device, filename)
        op = self.attachments.pop(key, None)
        if not op:
            return  # Another KDE client may have requested this file.
        try:
            if (not self.current(device, op['generation']) or self.devices[device].get('name_valid') is False or
                    self.devices[device].get('name', 'Phone') != op['name']):
                raise ValueError('Attachment connection changed')
            self.attachment_descriptor(op['identity'])
            local, fingerprint = mms_media.local_file(path, filename, op['name'])
        except (ValueError, TypeError):
            self.failure(op['request_id'], 'Downloaded attachment is unavailable or stale'); return
        self.downloads[op['identity']] = (local, fingerprint, op['name'], op['generation'])
        while len(self.downloads) > 300: self.downloads.pop(next(iter(self.downloads)))
        self.emit({'event': 'attachment_ready', 'request_id': op['request_id'],
                   'device': device, 'thread': op['identity'][1], 'message_id': op['identity'][2],
                   'part_id': op['part_id'], 'identifier': filename, 'local_path': local,
                   'kind': 'mms_download'})

    def open_attachment(self, command):
        identity = (command['device'], str(command['thread']), str(command['message_id']), str(command['part_id']), command['identifier'])
        self.attachment_descriptor(identity)
        download = self.downloads.get(identity)
        if not download: raise ValueError('Download this MMS attachment first')
        path, fingerprint, name, generation = download
        if not self.current(identity[0], generation) or self.devices[identity[0]].get('name', 'Phone') != name:
            raise ValueError('Attachment connection changed; retrieve again')
        local, current = mms_media.local_file(path, identity[4], name)
        if current != fingerprint:
            self.downloads.pop(identity, None)
            raise ValueError('Cached attachment changed; retrieve again')
        # Only this explicit command opens a file. No shell and no supplied URI.
        request = command.get('request_id')
        def opened(source, result, _):
            try:
                Gio.AppInfo.launch_default_for_uri_finish(result)
                self.emit({'event': 'attachment_opened', 'request_id': request})
            except GLib.Error:
                self.failure(request, 'No default application could open this attachment')
        Gio.AppInfo.launch_default_for_uri_async(Path(local).as_uri(), None, None, opened, None)

    def signal(self, path, interface, member, args):
        if path == ROOT and interface == BUS + '.daemon':
            if member in ('deviceAdded', 'deviceRemoved', 'deviceListChanged'):
                self.schedule_refresh()
            return
        match = re.fullmatch(re.escape(ROOT) + r'/devices/([A-Za-z0-9_]+)(?:/(.*))?', path)
        if not match:
            return
        device, tail = match.groups()
        if interface == DEVICE and member in ('reachableChanged', 'pairStateChanged', 'pluginsChanged'):
            if device in self.devices and member == 'reachableChanged' and args and not args[0]:
                self.disconnect(device)
            self.schedule_refresh()
            return
        if not self.devices.get(device, {}).get('online'):
            return
        if tail == 'mprisremote' and ((interface == MPRIS_REMOTE and member == 'propertiesChanged') or
                (interface == PROPERTIES and member == 'PropertiesChanged' and args and args[0] == MPRIS_REMOTE)):
            self.media.refresh(device)
            return
        if interface == DEVICE + '.telephony' and tail == 'telephony' and member == 'callReceived':
            if len(args) == 3 and self.calls.receive(device, *args):
                self.get_contacts(device)
        elif interface == CONVERSATIONS:
            if member in ('conversationCreated', 'conversationUpdated'):
                self.ingest(device, args[0], True)
            elif member == 'conversationLoaded':
                self.store.conversation(device, str(args[0])).daemon_cached_count = args[1]
            elif member == 'conversationRemoved':
                key = (device, str(args[0]))
                if key in self.store.pages:
                    self.store.finish_page(key, 'removed')
                self.store.remove_conversation(*key)
                self.emit({'event': 'thread_removed', 'device': device, 'thread': str(args[0])})
            elif member == 'attachmentReceived':
                self.attachment_received(device, *args)
        elif interface == DEVICE + '.contacts' and member == 'localCacheSynchronized':
            self.get_contacts(device)
        elif interface == NOTIFICATIONS:
            if member in ('notificationPosted', 'notificationUpdated'):
                self.read_notification(device, args[0])
            elif member == 'notificationRemoved':
                self.remove_notification(device, args[0], authoritative=True)
            elif member == 'allNotificationsRemoved':
                known = set(self.notifications) | set(self.note_versions)
                known.update((row['device'], row['id']) for row in self.notification_state.entries_for_device(device))
                for d, note in known:
                    if d == device:
                        self.remove_notification(d, note, authoritative=True)
        elif interface == NOTIFICATIONS + '.notification' and member == 'ready' and tail:
            self.read_notification(device, tail.rsplit('/', 1)[-1])

    def tick(self):
        now = self.clock()
        self.calls.expire()
        if self.refresh_due is not None and now >= self.refresh_due:
            self.refresh_due = None
            self.refresh()
        for key, op in list(self.notification_actions.items()):
            if now >= op['deadline']:
                self.finish_notification_action(key, op, False,
                    'Could not confirm the action. Check the phone before trying again.' if op['submitted'] else 'Notification action timed out')
        for device, op in list(self.sms_actions.items()):
            if now >= op['deadline']:
                self.finish_sms(device, op, False, 'Could not confirm sending. Check the phone before trying again.' if op['submitted'] else 'Sending timed out. Your draft is saved.')
        for key, page in list(self.store.pages.items()):
            if now < page.deadline:
                continue
            if not page.seen and page.attempts < 2:
                page.attempts += 1
                page.deadline = now + 15
                self.request_page(page)
            else:
                self.store.finish_page(key, 'partial' if page.seen else 'timeout')
        for key, op in list(self.attachments.items()):
            if now >= op['deadline']:
                if op['attempts'] < 2:
                    op.update(attempts=2, deadline=now + 30)
                    self.fetch_attachment(key, op)
                else:
                    self.attachments.pop(key)
                    self.failure(op['request_id'], 'Attachment download timed out. Try again.')
        return True

    def command(self, command):
        request = command.get('request_id')
        try:
            operation = command['op']
            if operation in ('notification_reply', 'notification_dismiss'):
                self.notification_action(command)
            elif operation == 'notification_local_remove':
                result = self.notification_state.mark_removed(command.get('entries', []))
                if result['removed']:
                    self.emit({'event': 'notification_local_remove', 'request_id': request,
                               'entries': result['removed'], 'notification_epoch': self.notification_epoch})
                elif result['error']:
                    self.emit({'event': 'notification_local_remove_failed', 'request_id': request,
                               'error': result['error'], 'notification_epoch': self.notification_epoch})
                elif result['capacity']:
                    self.emit({'event': 'notification_local_remove_capacity', 'request_id': request,
                               'error': 'Local notification state capacity reached. Close older notifications on the phone, then refresh.', 'notification_epoch': self.notification_epoch})
                else:
                    self.emit({'event': 'notification_local_remove_result', 'request_id': request,
                               'entries': [], 'pending': result['pending'], 'notification_epoch': self.notification_epoch})
            elif operation == 'contacts':
                self.get_contacts(command['device'], request)
            elif operation == 'pick_files':
                self.pick_files(command['device'], request)
            elif operation in ('sms_send', 'sms_reply'):
                self.send_sms(command)
            elif operation == 'media_volume':
                self.media.set_volume(command)
            elif operation == 'refresh':
                self.schedule_refresh()
            elif operation == 'history':
                device, thread = command['device'], str(command['thread'])
                self.require_online(device)
                if not -(2**63) <= int(thread) < 2**63:
                    raise ValueError('Invalid thread identifier')
                if (device, thread) not in self.store.threads:
                    raise ValueError('Refresh conversation summaries first')
                page = self.store.begin_page(request, device, thread, int(command.get('size', 25)))
                self.request_page(page)
            elif operation == 'attachment':
                self.request_attachment(request, command['device'], str(command['thread']),
                                        str(command['message_id']), str(command['part_id']), command['identifier'])
            elif operation == 'attachment_open':
                self.open_attachment(command)
            elif operation == 'state':
                self.emit({'event': 'state', 'request_id': request, 'devices': list(self.devices.values()),
                           'notifications': list(self.notifications.values()),
                           'calls': list(self.calls.records.values()),
                           'messages': [m.json() for c in self.store.threads.values() for m in c.ordered()],
                           'history_exhaustive': False})
            else:
                raise ValueError('Unsupported operation')
        except ValueError as error:
            self.failure(request, str(error))
        except (KeyError, TypeError, OverflowError):
            self.failure(request, 'Invalid or unavailable operation')


def main():
    # stdout is private IPC, never a journal: it contains notification/message data.
    def emit(event):
        try:
            print(json.dumps(event, ensure_ascii=False), flush=True)
        except BrokenPipeError:
            loop.quit()
    loop = GLib.MainLoop()
    try:
        transport = Transport()
    except GLib.Error:
        emit({'event': 'error', 'error': 'Session D-Bus is unavailable'})
        return 1
    try:
        removal_state = NotificationRemovalStore()
    except (OSError, ValueError) as error:
        removal_state = NotificationRemovalStore(persistent=False, disabled=True)
        removal_state.error = 'Local notification state unavailable: ' + str(error)
    service = Service(transport, emit, notification_state=removal_state)
    bus = transport.bus
    subscriptions = [bus.signal_subscribe(BUS, None, None, None, None, Gio.DBusSignalFlags.NONE,
        lambda b, sender, path, interface, member, params: service.signal(path, interface, member, params.unpack()))]
    subscriptions.append(bus.signal_subscribe('org.freedesktop.DBus', 'org.freedesktop.DBus',
        'NameOwnerChanged', '/org/freedesktop/DBus', BUS, Gio.DBusSignalFlags.NONE,
        lambda *args: service.owner_changed()))
    os.set_blocking(sys.stdin.fileno(), False)
    buffer = bytearray()
    def input_ready(fd, condition):
        if condition & (GLib.IO_ERR | GLib.IO_NVAL):
            loop.quit()
            return False
        try:
            data = os.read(fd, 65536)
        except BlockingIOError:
            return True
        if not data:
            loop.quit()
            return False
        buffer.extend(data)
        if len(buffer) > 1024 * 1024:
            service.failure(None, 'Command is too large')
            loop.quit()
            return False
        while b'\n' in buffer:
            line, _, rest = buffer.partition(b'\n')
            buffer[:] = rest
            try:
                command = json.loads(line)
                if not isinstance(command, dict):
                    raise ValueError()
                service.command(command)
            except (ValueError, UnicodeError):
                service.failure(None, 'Invalid command')
        return True
    GLib.io_add_watch(sys.stdin.fileno(), GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR, input_ready)
    GLib.timeout_add(250, service.tick)
    emit({'event': 'ready', 'protocol': 1, 'plugin_id': PLUGIN_ID, 'notification_epoch': service.notification_epoch, 'notification_revision': service.notification_event_revision, 'notification_removals': service.notification_state.suppressed(), 'notification_occurrences': service.notification_state.snapshot(), 'notification_state_error': service.notification_state.error})
    service.refresh()
    try:
        loop.run()
    finally:
        service.stopped = True
        if service.picker: service.picker.force_exit()
        if service.local_pool: service.local_pool.shutdown(wait=False, cancel_futures=True)
        for subscription in subscriptions:
            bus.signal_unsubscribe(subscription)
    return 0


if __name__ == '__main__':
    sys.exit(main())
