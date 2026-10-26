import unittest
import tempfile
from pathlib import Path
import contacts
import sms
import tempfile
from pathlib import Path
from unittest.mock import patch
from messaging import Attachment, Message, Store, json_line_size
from messaging_service import Service, CONVERSATIONS, NOTIFICATIONS, device_path, notification_size, fit_notification, MAX_NOTIFICATION_EVENT_BYTES


def wire(uid=1, thread=9, kind=1, attachments=(), addresses=None, body='Hi 👋'):
    return (1, body, addresses if addresses is not None else [('5550100',)], 100, kind, 0, thread, uid, -1, attachments)


def oversized_record(addresses):
    # Astra's rejected-record fixture: escaped text and metadata plus valid,
    # bounded thumbnail strings push the complete serialized record over cap.
    attachments = [(i, '\x01' * 256,
                    'A' * (196608 if i < 2 else 110000 if i == 2 else 0),
                    '\x01' * 512) for i in range(16)]
    return wire(uid=2, addresses=addresses, body='\x01' * Message.MAX_BODY_BYTES,
                attachments=attachments)


def oversized_singleton_event_replacement(store, address='5550199'):
    """Return a decodable same-UID replacement whose complete event is 614401 bytes."""
    from messaging import json_line_size
    attachments = [(i, '\x01' * 256,
                    'A' * (196608 if i < 2 else 110000 if i == 2 else 0),
                    '\x01' * 512) for i in range(16)]
    raw = list(wire(uid=1, addresses=[(address,)], body='', attachments=attachments))
    raw[3] = 50

    def event_for(value):
        message = Message.decode('phone', value)
        return {'event': 'message', 'message': message.json(),
                'conversation_token': store.session + ':' + str(store.sequence + 1),
                'source': 'summary', 'reply_status': 'incomplete', 'reply_risk': 'ordering',
                'delivery_confirmed': None, 'read_receipt': None}

    target = Message.MAX_SERIALIZED_BYTES + 1
    delta = target - json_line_size(event_for(raw))
    if delta < 0:
        raise AssertionError('base event already exceeds the complete event limit')
    raw[1] = '\x01' * (delta // 6) + 'x' * (delta % 6)
    assert json_line_size(event_for(raw)) == target
    assert Message.decode('phone', raw).serialized_size() <= Message.MAX_SERIALIZED_BYTES
    return raw


class FakeTransport:
    def __init__(self): self.calls = []
    def call(self, *args): self.calls.append(args)
    def respond(self, index=-1, value=(), error=None): self.calls[index][-1](value, error)


class MessagingTests(unittest.TestCase):
    def setUp(self):
        self.events = []; self.now = 0; self.transport = FakeTransport()
        self.service = Service(self.transport, self.events.append, lambda: self.now)
        self.service.devices['phone'] = {'id': 'phone', 'online': True, 'generation': 1,
            'plugins': ['kdeconnect_sms', 'kdeconnect_notifications']}
        self.store = self.service.store

    def test_record_preserves_unicode_large_ids_and_attachment(self):
        m = Message.decode('phone', wire(thread=2**60, kind=5, attachments=[(7, 'image/jpeg', 'encoded', 'photo')]))
        self.assertEqual(m.thread_id, str(2**60)); self.assertEqual(m.body, 'Hi 👋')
        self.assertEqual(m.state, 'failed'); self.assertEqual(m.android_read, 0)
        self.assertEqual(m.attachments[0].identifier, 'photo')

    def test_oversized_message_text_is_utf8_truncated_before_retention(self):
        data = list(wire()); data[1] = '🙂' * 10000
        message = Message.decode('phone', data)
        self.assertLessEqual(len(message.body.encode('utf-8')), Message.MAX_BODY_BYTES)
        self.assertEqual(message.body.encode('utf-8').decode('utf-8'), message.body)
        self.store.ingest('phone', data)
        self.assertLessEqual(len(self.events[-1]['message']['body'].encode('utf-8')), Message.MAX_BODY_BYTES)

    def test_multimegabyte_text_is_bounded_without_large_retained_copy(self):
        data = list(wire()); data[1] = '🙂' * 2_000_000
        message = Message.decode('phone', data)
        self.assertLessEqual(len(message.body.encode('utf-8')), Message.MAX_BODY_BYTES)
        self.assertLess(len(message.body), 20_000)

    def test_serialized_message_event_is_bounded_with_escaped_fields(self):
        addresses = [('\x01' * 256,) for _ in range(16)]
        attachments = [(i, '\x01' * 256, 'QUJD', '\x01' * 512) for i in range(16)]
        message = Message.decode('phone', wire(body='\x01' * Message.MAX_BODY_BYTES,
                                               addresses=addresses, attachments=attachments))
        self.store.ingest('phone', wire(body='\x01' * Message.MAX_BODY_BYTES,
                                        addresses=addresses, attachments=attachments))
        self.assertLessEqual(json_line_size(self.events[-1]), Message.MAX_SERIALIZED_BYTES)
        self.assertEqual(message.attachments[0].thumbnail_base64, 'QUJD')

    def test_malformed_thumbnail_is_dropped_but_message_is_retained(self):
        malformed = Message.decode('phone', wire(attachments=[(1, 'image/jpeg', 'not base64!', 'photo')]))
        self.assertEqual(malformed.attachments[0].thumbnail_base64, '')
        self.store.ingest('phone', wire(attachments=[(1, 'image/jpeg', 'not base64!', 'photo')]))
        self.assertEqual(self.events[-1]['event'], 'message')

    def test_exact_thumbnail_boundary_is_validated_and_retained(self):
        thumbnail = 'QUJD' * (Attachment.MAX_THUMBNAIL_BYTES // 4)
        message = Message.decode('phone', wire(attachments=[(1, 'image/jpeg', thumbnail, 'photo')]))
        self.assertEqual(len(message.attachments[0].thumbnail_base64.encode('ascii')), Attachment.MAX_THUMBNAIL_BYTES)

    def test_aggregate_message_budget_tracks_replacements_and_evictions(self):
        self.store.MAX_RETAINED_BYTES = 700
        for uid in range(1, 10):
            self.store.ingest('phone', wire(uid=uid))
        self.assertLessEqual(self.store.retained_bytes, self.store.MAX_RETAINED_BYTES)
        self.assertNotIn('1', self.store.conversation('phone', '9').messages)
        retained = sum(m.serialized_size() for c in self.store.threads.values() for m in c.messages.values())
        self.assertEqual(self.store.retained_bytes, retained)
        self.store.MAX_RETAINED_BYTES = 1 << 20
        self.store.ingest('phone', wire(uid=100, body='short'))
        before = self.store.retained_bytes
        self.store.ingest('phone', wire(uid=100, body='replacement' * 100))
        self.assertNotEqual(self.store.retained_bytes, before)
        self.assertEqual(len(self.store.conversation('phone', '9').messages), 3)
        self.service.disconnect('phone')
        self.assertEqual(self.store.retained_bytes, 0)

    def test_conversation_removal_releases_retained_bytes(self):
        self.store.ingest('phone', wire(uid=1))
        self.assertGreater(self.store.retained_bytes, 0)
        self.service.signal(device_path('phone'), CONVERSATIONS, 'conversationRemoved', (9,))
        self.assertEqual(self.store.retained_bytes, 0)
        self.assertNotIn(('phone', '9'), self.store.threads)

    def test_oversized_and_aggregate_thumbnails_are_rejected_and_count_is_capped(self):
        huge = 'A' * (Attachment.MAX_THUMBNAIL_BYTES + 1)
        entries = [(i, 'image/jpeg', huge if i == 0 else 'QUJD', 'photo') for i in range(24)]
        message = Message.decode('phone', wire(attachments=entries))
        self.assertEqual(len(message.attachments), Message.MAX_ATTACHMENTS)
        self.assertEqual(message.attachments[0].thumbnail_base64, '')
        self.assertLessEqual(sum(len(a.thumbnail_base64.encode('utf-8')) for a in message.attachments), Message.MAX_ATTACHMENT_BYTES)
        self.assertTrue(all(a.thumbnail_base64 in ('', 'QUJD') for a in message.attachments))
        aggregate = Message.decode('phone', wire(attachments=[(i, 'image/jpeg', 'A' * Attachment.MAX_THUMBNAIL_BYTES, 'photo') for i in range(4)]))
        self.assertLessEqual(sum(len(a.thumbnail_base64.encode('utf-8')) for a in aggregate.attachments), Message.MAX_ATTACHMENT_BYTES)
        self.assertEqual(aggregate.attachments[-1].thumbnail_base64, '')

    def test_group_recipient_scope_is_explicit_and_replies_fail_closed(self):
        full = [('555%04d' % i,) for i in range(17)]
        message = Message.decode('phone', wire(addresses=full))
        self.assertFalse(message.addresses_complete)
        self.store.ingest('phone', wire(addresses=full))
        with self.assertRaises(ValueError):
            self.service.send_sms({'op': 'sms_reply', 'device': 'phone', 'thread': '9',
                                   'conversation_token': self.store.token('phone', '9'),
                                   'recipient_scope': full,
                                   'text': 'reply', 'files': [], 'request_id': 'group'})
        self.assertFalse(any(call[2] == 'replyToConversation' for call in self.transport.calls))

    def test_oversized_recipient_identifier_is_incomplete_not_truncated(self):
        value = 'x' * 257
        message = Message.decode('phone', wire(addresses=[(value,)]))
        self.assertFalse(message.addresses_complete)
        self.store.ingest('phone', wire(addresses=[(value,)]))
        self.assertEqual(self.store.reply_status('phone', '9'), 'incomplete')
        with self.assertRaises(ValueError):
            self.service.send_sms({'op': 'sms_reply', 'device': 'phone', 'thread': '9',
                                   'conversation_token': self.store.token('phone', '9'),
                                   'recipient_scope': [value], 'text': 'reply', 'files': [], 'request_id': 'long-id'})
        self.assertFalse(any(call[2] == 'replyToConversation' for call in self.transport.calls))

    def test_incomplete_scope_remains_blocked_after_later_single_recipient_record(self):
        self.store.ingest('phone', wire(addresses=[('',)]))
        self.assertEqual(self.store.reply_status('phone', '9'), 'incomplete')
        self.store.ingest('phone', wire(uid=2, addresses=[('5550100',)]))
        self.assertEqual(self.store.reply_status('phone', '9'), 'incomplete')
        with self.assertRaises(ValueError):
            self.service.send_sms({'op': 'sms_reply', 'device': 'phone', 'thread': '9',
                                   'conversation_token': self.store.token('phone', '9'),
                                   'recipient_scope': ['5550100'], 'text': 'reply', 'files': [], 'request_id': 'incomplete-sticky'})

    def test_group_risk_survives_replacement_message_eviction_reconnect_and_removal(self):
        group = [('5550100',), ('5550101',)]
        self.store.ingest('phone', wire(addresses=group))
        self.store.ingest('phone', wire(uid=1, addresses=[('5550100',)]))
        self.assertEqual(self.store.reply_status('phone', '9'), 'group')
        self.store.MAX_MESSAGES = 1
        self.store.ingest('phone', wire(uid=2, addresses=[('5550100',)]))
        self.assertEqual(self.store.reply_status('phone', '9'), 'group')
        self.service.disconnect('phone')
        self.store.ingest('phone', wire(uid=3, addresses=[('5550100',)]))
        self.assertEqual(self.store.reply_status('phone', '9'), 'group')
        self.store.remove_conversation('phone', '9')
        self.store.ingest('phone', wire(uid=4, addresses=[('5550100',)]))
        self.assertEqual(self.store.reply_status('phone', '9'), 'group')

    def test_group_risk_survives_conversation_capacity_eviction(self):
        self.store.MAX_THREADS = 1
        self.store.ingest('phone', wire(thread=9, addresses=[('5550100',), ('5550101',)]))
        self.store.ingest('phone', wire(thread=10))
        self.store.ingest('phone', wire(thread=9, uid=2))
        self.assertEqual(self.store.reply_status('phone', '9'), 'group')

    def test_reply_risk_capacity_overflow_fails_closed_for_device(self):
        self.store.MAX_REPLY_RISKS = 0
        self.store.ingest('phone', wire(addresses=[('5550100',), ('5550101',)]))
        self.assertEqual(self.store.reply_status('phone', '9'), 'unknown')
        with self.assertRaises(ValueError):
            self.service.send_sms({'op': 'sms_reply', 'device': 'phone', 'thread': '9',
                                   'conversation_token': self.store.token('phone', '9'),
                                   'recipient_scope': ['5550100'], 'text': 'reply', 'files': [], 'request_id': 'overflow'})
        self.assertIn({'event': 'reply_scope_uncertain', 'device': 'phone'}, self.events)

    def test_uncertainty_tracking_stays_bounded_across_discovery_churn(self):
        transport = FakeTransport(); events = []
        def safety_event(event):
            if event.get('event') == 'reply_scope_uncertain': events.append(event)
        service = Service(transport, safety_event)
        for index in range(4200):
            device = 'device_' + str(index)
            service.refresh()
            transport.respond(value=([device],))
            transport.respond(value=({'isPaired': True, 'isReachable': True},))
            transport.respond(value=([],))
            service.signal('/modules/kdeconnect/devices/' + device,
                           'org.kde.kdeconnect.device.conversations',
                           'conversationUpdated', ((1,),))
            service.refresh()
            transport.respond(value=([],))
        self.assertEqual(service.devices, {})
        self.assertLessEqual(len(service.store.reply_uncertain_devices),
                             service.store.MAX_UNCERTAIN_DEVICES)
        self.assertTrue(service.store.reply_uncertain_all)
        self.assertEqual(events.count({'event': 'reply_scope_uncertain', 'all': True}), 1)

        # A returning device remains uncertain through removal and owner change.
        device = 'device_0'
        service.devices[device] = {'id': device, 'online': True, 'generation': 1,
                                   'plugins': ['kdeconnect_sms']}
        service.store.ingest(device, wire())
        self.assertEqual(service.store.reply_status(device, '9'), 'unknown')
        service.owner_changed()
        service.devices[device] = {'id': device, 'online': True, 'generation': 3,
                                   'plugins': ['kdeconnect_sms']}
        service.store.ingest(device, wire(uid=2))
        self.assertEqual(service.store.reply_status(device, '9'), 'unknown')

        # A fresh Store belongs to a fresh worker session and can establish a
        # new individual authorization from newly received evidence.
        fresh = Store(lambda _event: None)
        fresh.ingest(device, wire())
        self.assertEqual(fresh.reply_status(device, '9'), 'individual')

    def test_message_json_line_exact_boundary_counts_newline(self):
        import json
        base = {'event': 'x', 'value': ''}
        fixed = json_line_size(base)
        event = {'event': 'x', 'value': 'a' * (Message.MAX_SERIALIZED_BYTES - fixed)}
        self.assertEqual(json_line_size(event), Message.MAX_SERIALIZED_BYTES)
        event['value'] += 'a'
        self.assertEqual(json_line_size(event), Message.MAX_SERIALIZED_BYTES + 1)
        self.assertEqual(json_line_size(event), len((json.dumps(event, ensure_ascii=False) + '\n').encode('utf-8')))

    def test_store_event_acceptance_at_limit_minus_one_limit_and_plus_one(self):
        event = {'event': 'message', 'message': Message.decode('phone', wire()).json(),
                 'conversation_token': 'x' * 34, 'source': 'summary', 'reply_status': 'individual',
                 'delivery_confirmed': None, 'read_receipt': None, 'recipient_scope': ['5550100']}
        exact = json_line_size(event)
        for limit, accepted in ((exact - 1, False), (exact, True), (exact + 1, True)):
            with self.subTest(limit=limit):
                store = Store(lambda _event: None)
                with patch.object(Message, 'MAX_SERIALIZED_BYTES', limit):
                    if accepted:
                        store.ingest('phone', wire())
                        self.assertEqual(len(store.threads[('phone', '9')].messages), 1)
                    else:
                        with self.assertRaisesRegex(ValueError, 'event exceeds'):
                            store.ingest('phone', wire())
                        self.assertFalse(store.threads)

    def test_notification_event_limit_includes_newline_and_exact_boundary(self):
        base = {'app': '', 'title': '', 'body': '', 'internal_id': '', 'reply_id': '', 'icon_path': ''}
        fixed = notification_size(base)
        record = dict(base, body='a' * (MAX_NOTIFICATION_EVENT_BYTES - fixed))
        self.assertEqual(notification_size(record), MAX_NOTIFICATION_EVENT_BYTES)
        self.assertTrue(fit_notification(record))
        self.assertEqual(notification_size(record), MAX_NOTIFICATION_EVENT_BYTES)
        record['body'] += 'a'
        self.assertTrue(fit_notification(record))
        self.assertEqual(notification_size(record), MAX_NOTIFICATION_EVENT_BYTES)

    def test_individual_scope_is_submitted_to_kde_connect(self):
        scope = ['5550100']
        self.store.ingest('phone', wire(addresses=[('5550100',)]))
        self.service.local_job = lambda work, complete: complete(work(), None)
        self.service.send_sms({'op': 'sms_reply', 'device': 'phone', 'thread': '9',
                               'conversation_token': self.store.token('phone', '9'),
                               'recipient_scope': scope,
                               'text': 'reply', 'files': [], 'request_id': 'group'})
        self.transport.respond(value=({'isReachable': True, 'isPaired': True},))
        self.assertEqual(self.transport.calls[-1][2], 'replyToConversation')

    def test_two_recipient_group_is_disabled_even_when_complete(self):
        full = [('5550100',), ('5550101',)]
        self.store.ingest('phone', wire(addresses=full))
        with self.assertRaisesRegex(ValueError, 'Group replies'):
            self.service.send_sms({'op': 'sms_reply', 'device': 'phone', 'thread': '9',
                                   'conversation_token': self.store.token('phone', '9'),
                                   'recipient_scope': [a[0] for a in full], 'text': 'reply', 'files': [], 'request_id': 'group2'})
        self.assertFalse(any(call[2] == 'replyToConversation' for call in self.transport.calls))

    def test_direct_group_command_cannot_bypass_policy(self):
        full = [('5550100',), ('5550101',), ('5550102',), ('5550103',)]
        self.store.ingest('phone', wire(addresses=full))
        with self.assertRaisesRegex(ValueError, 'Group replies'):
            self.service.send_sms({'op': 'sms_reply', 'device': 'phone', 'thread': '9',
                                   'conversation_token': self.store.token('phone', '9'),
                                   'recipient_scope': [a[0] for a in full], 'text': 'reply', 'files': [], 'request_id': 'direct'})

    def test_recipient_scope_changes_are_rejected(self):
        base = [('5550100',), ('5550101',), ('5550102',)]
        scope = [address[0] for address in base]
        self.store.ingest('phone', wire(addresses=base))
        token = self.store.token('phone', '9')
        for changed in (base + [('5550103',)], base[:2]):
            self.store.ingest('phone', wire(uid=1, addresses=changed))
            with self.assertRaises(ValueError):
                self.service.send_sms({'op': 'sms_reply', 'device': 'phone', 'thread': '9',
                                       'conversation_token': token, 'recipient_scope': scope,
                                       'text': 'reply', 'files': [], 'request_id': 'changed'})

    def test_complete_to_incomplete_scope_is_rejected(self):
        base = [('5550100',), ('5550101',), ('5550102',)]
        scope = [address[0] for address in base]
        self.store.ingest('phone', wire(addresses=base))
        token = self.store.token('phone', '9')
        incomplete = [('555%04d' % i,) for i in range(17)]
        self.store.ingest('phone', wire(uid=1, addresses=incomplete))
        with self.assertRaises(ValueError):
            self.service.send_sms({'op': 'sms_reply', 'device': 'phone', 'thread': '9',
                                   'conversation_token': token, 'recipient_scope': scope,
                                   'text': 'reply', 'files': [], 'request_id': 'incomplete'})

    def test_recipient_scope_race_is_rechecked_before_submission(self):
        base = [('5550100',)]
        scope = [address[0] for address in base]
        changed = [('5550190',)]
        self.store.ingest('phone', wire(addresses=base))
        token = self.store.token('phone', '9')
        self.service.local_job = lambda work, complete: complete(work(), None)
        self.service.send_sms({'op': 'sms_reply', 'device': 'phone', 'thread': '9',
                               'conversation_token': token, 'recipient_scope': scope,
                               'text': 'reply', 'files': [], 'request_id': 'race'})
        self.store.ingest('phone', wire(uid=1, addresses=changed))
        self.transport.respond(value=({'isReachable': True, 'isPaired': True},))
        self.assertFalse(any(call[2] == 'replyToConversation' for call in self.transport.calls))
        self.assertIn('Conversation changed', self.events[-1]['error'])

    def test_rejected_oversized_group_record_invalidates_reply_before_discard(self):
        self.store.ingest('phone', wire(addresses=[('5550100',)]))
        oversized = list(wire(addresses=[('5550100',), ('5550101',)], body='\x01' * Message.MAX_BODY_BYTES))
        oversized[9] = [(i, '\x01' * 256,
                         'A' * (Attachment.MAX_THUMBNAIL_BYTES if i < 2 else 100_000 if i == 2 else 0),
                         '\x01' * 512) for i in range(16)]
        with self.assertRaisesRegex(ValueError, 'serialized size limit'):
            self.store.ingest('phone', oversized)
        conversation = self.store.threads[('phone', '9')]
        self.assertEqual(self.store.reply_status('phone', '9'), 'group')
        self.assertEqual(len(conversation.messages), 1)
        self.assertEqual(self.events[-1]['event'], 'reply_scope')
        self.assertEqual(self.events[-1]['reply_status'], 'group')
        self.assertEqual(self.events[-1]['conversation_token'], self.store.token('phone', '9'))

    def test_changed_singleton_at_complete_event_guard_invalidates_old_authorization(self):
        self.store.ingest('phone', wire(uid=1, addresses=[('5550100',)]))
        old_token = self.store.token('phone', '9')
        from messaging import json_line_size
        attachments = [(i, '\x01' * 256,
                        'A' * (196608 if i < 2 else 110000 if i == 2 else 0),
                        '\x01' * 512) for i in range(16)]
        candidate = None
        low, high = 0, Message.MAX_BODY_BYTES
        while low < high:
            size = (low + high + 1) // 2
            raw = wire(uid=2, addresses=[('5550199',)], body='\x01' * size, attachments=attachments)
            try:
                decoded = Message.decode('phone', raw)
            except ValueError:
                high = size - 1
                continue
            if decoded.serialized_size() <= Message.MAX_SERIALIZED_BYTES:
                low = size
            else:
                high = size - 1
        for size in range(low, max(-1, low - 128), -1):
            raw = wire(uid=2, addresses=[('5550199',)], body='\x01' * size, attachments=attachments)
            try:
                decoded = Message.decode('phone', raw)
            except ValueError:
                continue
            event = {'event': 'message', 'message': decoded.json(),
                     'conversation_token': old_token, 'source': 'summary',
                     'reply_status': 'individual', 'delivery_confirmed': None,
                     'read_receipt': None}
            if json_line_size(event) > Message.MAX_SERIALIZED_BYTES:
                candidate = raw
                break
        self.assertIsNotNone(candidate, 'expected decoded singleton rejected by complete event framing')
        with self.assertRaisesRegex(ValueError, 'event exceeds'):
            self.store.ingest('phone', candidate)
        self.assertEqual(self.store.reply_status('phone', '9'), 'incomplete')
        self.assertEqual(list(self.store.threads[('phone', '9')].messages), ['1'])
        self.assertNotEqual(self.store.token('phone', '9'), old_token)
        self.assertEqual(self.events[-1]['reply_status'], 'incomplete')
        with self.assertRaises(ValueError):
            self.service.send_sms({'op': 'sms_reply', 'device': 'phone', 'thread': '9',
                                   'conversation_token': old_token, 'recipient_scope': ['5550100'],
                                   'text': 'reply', 'files': [], 'request_id': 'frame-singleton'})

    def test_rejected_oversized_individual_record_preserves_reliable_reply(self):
        self.store.ingest('phone', wire(addresses=[('5550100',)]))
        oversized = list(wire(uid=2, addresses=[('5550100',)], body='\x01' * Message.MAX_BODY_BYTES))
        oversized[9] = [(i, '\x01' * 256,
                         'A' * (Attachment.MAX_THUMBNAIL_BYTES if i < 2 else 100_000 if i == 2 else 0),
                         '\x01' * 512) for i in range(16)]
        with self.assertRaisesRegex(ValueError, 'serialized size limit'):
            self.store.ingest('phone', oversized)
        self.assertEqual(self.store.reply_status('phone', '9'), 'individual')
        self.service.local_job = lambda work, complete: complete(work(), None)
        self.service.send_sms({'op': 'sms_reply', 'device': 'phone', 'thread': '9',
                               'conversation_token': self.store.token('phone', '9'),
                               'recipient_scope': ['5550100'], 'text': 'reply', 'files': [],
                               'request_id': 'rejected-individual'})
        self.transport.respond(value=({'isReachable': True, 'isPaired': True},))
        self.assertEqual(self.transport.calls[-1][2], 'replyToConversation')

    def test_rejected_changed_singleton_invalidates_old_reply_authorization(self):
        self.store.ingest('phone', wire(addresses=[('5550100',)]))
        token = self.store.token('phone', '9')
        rejected = oversized_record([('5550199',)])
        with self.assertRaisesRegex(ValueError, 'serialized size limit'):
            self.store.ingest('phone', rejected)
        self.assertEqual(self.store.reply_status('phone', '9'), 'incomplete')
        self.assertEqual(self.events[-1]['event'], 'reply_scope')
        self.assertEqual(self.events[-1]['reply_status'], 'incomplete')
        self.assertNotEqual(self.events[-1]['conversation_token'], token)
        self.assertEqual(list(self.store.threads[('phone', '9')].messages), ['1'])
        self.assertFalse(any('5550199' in str(message.json())
                             for c in self.store.threads.values()
                             for message in c.messages.values()))
        with self.assertRaises(ValueError):
            self.service.send_sms({'op': 'sms_reply', 'device': 'phone', 'thread': '9',
                                   'conversation_token': token, 'recipient_scope': ['5550100'],
                                   'text': 'reply', 'files': [], 'request_id': 'changed-singleton'})
        self.assertFalse(any(call[2] == 'replyToConversation' for call in self.transport.calls))

    def test_rejected_changed_singleton_is_rechecked_after_file_validation(self):
        self.store.ingest('phone', wire(addresses=[('5550100',)]))
        pending = []
        self.service.local_job = lambda work, complete: pending.append((work, complete))
        self.service.send_sms({'op': 'sms_reply', 'device': 'phone', 'thread': '9',
                               'conversation_token': self.store.token('phone', '9'),
                               'recipient_scope': ['5550100'], 'text': 'reply', 'files': [],
                               'request_id': 'changed-singleton-pending'})
        work, complete = pending.pop()
        self.assertFalse(any(call[2] == 'replyToConversation' for call in self.transport.calls))
        with self.assertRaisesRegex(ValueError, 'serialized size limit'):
            self.store.ingest('phone', oversized_record([('5550199',)]))
        complete(work(), None)
        self.transport.respond(value=({'isReachable': True, 'isPaired': True},))
        self.assertFalse(any(call[2] == 'replyToConversation' for call in self.transport.calls))
        self.assertFalse(self.events[-1]['accepted'])

    def test_rejected_changed_singleton_is_rechecked_after_online_lookup(self):
        self.store.ingest('phone', wire(addresses=[('5550100',)]))
        self.service.local_job = lambda work, complete: complete(work(), None)
        self.service.send_sms({'op': 'sms_reply', 'device': 'phone', 'thread': '9',
                               'conversation_token': self.store.token('phone', '9'),
                               'recipient_scope': ['5550100'], 'text': 'reply', 'files': [],
                               'request_id': 'changed-singleton-online'})
        with self.assertRaisesRegex(ValueError, 'serialized size limit'):
            self.store.ingest('phone', oversized_record([('5550199',)]))
        self.transport.respond(value=({'isReachable': True, 'isPaired': True},))
        self.assertFalse(any(call[2] == 'replyToConversation' for call in self.transport.calls))

    def test_same_uid_earlier_timestamp_conflict_invalidates_all_reply_paths(self):
        for update_kind in ('accepted', 'record-rejected', 'event-rejected'):
            for timing in ('direct', 'file', 'online'):
                with self.subTest(update=update_kind, timing=timing):
                    self.setUp()
                    self.store.ingest('phone', wire(uid=1, addresses=[('5550100',)]))
                    old_token = self.store.token('phone', '9')
                    command = {'op': 'sms_reply', 'device': 'phone', 'thread': '9',
                               'conversation_token': old_token, 'recipient_scope': ['5550100'],
                               'text': 'reply', 'files': [], 'request_id': 'same-uid-rollback'}
                    pending = []
                    if timing == 'file':
                        self.service.local_job = lambda work, complete: pending.append((work, complete))
                    elif timing == 'online':
                        self.service.local_job = lambda work, complete: complete(work(), None)
                    if timing != 'direct':
                        self.service.send_sms(command)

                    if update_kind == 'accepted':
                        replacement = list(wire(uid=1, addresses=[('5550199',)]))
                        replacement[3] = 50
                    elif update_kind == 'record-rejected':
                        replacement = list(oversized_record([('5550199',)]))
                        replacement[3] = 50
                        replacement[7] = 1
                    else:
                        replacement = oversized_singleton_event_replacement(self.store)

                    if update_kind == 'accepted':
                        self.store.ingest('phone', replacement)
                        self.assertEqual(self.store.reply_status('phone', '9'), 'incomplete')
                        self.assertNotIn(('phone', '9'), self.store.reply_scopes)
                    else:
                        with self.assertRaisesRegex(ValueError, 'serialized size limit'):
                            self.store.ingest('phone', replacement)
                        self.assertEqual(self.store.reply_status('phone', '9'), 'incomplete')
                        self.assertTrue(any(event.get('event') == 'reply_scope' and
                                            event.get('reply_status') == 'incomplete'
                                            for event in self.events))
                        self.assertEqual(list(self.store.threads[('phone', '9')].messages), ['1'])

                    self.assertNotEqual(self.store.token('phone', '9'), old_token)
                    if timing == 'direct':
                        with self.assertRaisesRegex(ValueError, 'Conversation changed'):
                            self.service.send_sms(command)
                    elif timing == 'file':
                        work, complete = pending.pop()
                        complete(work(), None)
                    if timing != 'direct':
                        self.transport.respond(value=({'isReachable': True, 'isPaired': True},))
                    self.assertFalse(any(call[2] == 'replyToConversation'
                                         for call in self.transport.calls))
                    if timing != 'direct':
                        self.assertFalse(self.events[-1]['accepted'])

    def test_different_older_history_does_not_supersede_current_proof(self):
        self.store.ingest('phone', wire(uid=1, addresses=[('5550100',)]))
        token = self.store.token('phone', '9')
        older = list(wire(uid=2, addresses=[('5550199',)])); older[3] = 50
        self.store.ingest('phone', older)
        self.assertEqual(self.store.token('phone', '9'), token)
        self.assertEqual(self.store.reply_scopes[('phone', '9')][0], ('5550100',))
        self.service.local_job = lambda work, complete: complete(work(), None)
        self.service.send_sms({'op': 'sms_reply', 'device': 'phone', 'thread': '9',
                               'conversation_token': token, 'recipient_scope': ['5550100'],
                               'text': 'reply', 'files': [], 'request_id': 'older-history-control'})
        self.transport.respond(value=({'isReachable': True, 'isPaired': True},))
        self.assertEqual(self.transport.calls[-1][2], 'replyToConversation')

    def test_superseding_singleton_evidence_survives_message_eviction(self):
        self.store.ingest('phone', wire(uid=1, addresses=[('5550100',)]))
        old_token = self.store.token('phone', '9')
        self.store.MAX_MESSAGES = 1
        self.store.ingest('phone', wire(uid=2, addresses=[('5550199',)]))
        self.assertEqual(self.store.reply_scopes[('phone', '9')][0], ('5550199',))
        self.assertEqual(self.store.reply_status('phone', '9'), 'individual')
        self.assertNotIn('1', self.store.threads[('phone', '9')].messages)
        with self.assertRaisesRegex(ValueError, 'Conversation changed'):
            self.service.send_sms({'op': 'sms_reply', 'device': 'phone', 'thread': '9',
                                   'conversation_token': old_token, 'recipient_scope': ['5550100'],
                                   'text': 'stale', 'files': [], 'request_id': 'stale-after-eviction'})
        self.service.local_job = lambda work, complete: complete(work(), None)
        self.service.send_sms({'op': 'sms_reply', 'device': 'phone', 'thread': '9',
                               'conversation_token': self.store.token('phone', '9'),
                               'recipient_scope': ['5550199'], 'text': 'current', 'files': [],
                               'request_id': 'current-after-eviction'})
        self.transport.respond(value=({'isReachable': True, 'isPaired': True},))
        self.assertEqual(self.transport.calls[-1][2], 'replyToConversation')

    def test_production_thread_limit_cannot_restore_evicted_old_recipient(self):
        self.store.ingest('phone', wire(uid=1, addresses=[('5550100',)]))
        stale_token = self.store.token('phone', '9')
        self.store.ingest('phone', wire(uid=2, addresses=[('5550199',)]))
        current_token = self.store.token('phone', '9')
        # These are 300 older history records, arriving after the latest B
        # record. They evict both first messages at the real per-thread cap.
        for uid in range(3, 303):
            old = list(wire(uid=uid, addresses=[('5550100',)])); old[3] = 50
            self.store.ingest('phone', old)
        self.assertEqual(len(self.store.threads[('phone', '9')].messages), self.store.MAX_MESSAGES)
        self.assertNotIn('2', self.store.threads[('phone', '9')].messages)
        self.assertEqual(self.store.reply_scopes[('phone', '9')][0], ('5550199',))
        self.assertEqual(self.store.token('phone', '9'), current_token)
        with self.assertRaises(ValueError):
            self.service.send_sms({'op': 'sms_reply', 'device': 'phone', 'thread': '9',
                                   'conversation_token': stale_token, 'recipient_scope': ['5550100'],
                                   'text': 'stale', 'files': [], 'request_id': 'production-cap-stale'})
        self.service.local_job = lambda work, complete: complete(work(), None)
        self.service.send_sms({'op': 'sms_reply', 'device': 'phone', 'thread': '9',
                               'conversation_token': current_token, 'recipient_scope': ['5550199'],
                               'text': 'current', 'files': [], 'request_id': 'production-cap-current'})
        self.transport.respond(value=({'isReachable': True, 'isPaired': True},))
        self.assertEqual(self.transport.calls[-1][2], 'replyToConversation')

    def test_production_thread_limit_is_rechecked_during_pending_validation(self):
        self.store.ingest('phone', wire(uid=1, addresses=[('5550100',)]))
        self.store.ingest('phone', wire(uid=2, addresses=[('5550199',)]))
        token = self.store.token('phone', '9')
        pending = []
        self.service.local_job = lambda work, complete: pending.append((work, complete))
        self.service.send_sms({'op': 'sms_reply', 'device': 'phone', 'thread': '9',
                               'conversation_token': token, 'recipient_scope': ['5550199'],
                               'text': 'pending', 'files': [], 'request_id': 'production-cap-pending'})
        for uid in range(3, 303):
            old = list(wire(uid=uid, addresses=[('5550100',)])); old[3] = 50
            self.store.ingest('phone', old)
        work, complete = pending.pop()
        complete(work(), None)
        self.transport.respond(value=({'isReachable': True, 'isPaired': True},))
        self.assertEqual(self.transport.calls[-1][2], 'replyToConversation')
        self.assertEqual(self.store.reply_scopes[('phone', '9')][0], ('5550199',))

    def test_global_retention_rejection_does_not_restore_superseded_scope(self):
        self.store.ingest('phone', wire(uid=1, addresses=[('5550100',)]))
        token = self.store.token('phone', '9')
        self.store.MAX_RETAINED_BYTES = 1
        with self.assertRaisesRegex(ValueError, 'retained memory budget'):
            self.store.ingest('phone', wire(uid=2, addresses=[('5550199',)]))
        self.assertEqual(self.store.reply_status('phone', '9'), 'incomplete')
        self.assertEqual(list(self.store.threads[('phone', '9')].messages), ['1'])
        with self.assertRaises(ValueError):
            self.service.send_sms({'op': 'sms_reply', 'device': 'phone', 'thread': '9',
                                   'conversation_token': token, 'recipient_scope': ['5550100'],
                                   'text': 'reply', 'files': [], 'request_id': 'global-retention'})

    def test_group_replacement_self_eviction_publishes_safety_without_message(self):
        self.store.ingest('phone', wire(uid=1, addresses=[('5550100',)]))
        self.store.ingest('phone', wire(uid=1, thread=10, body='f' * 1000))
        group_wire = wire(uid=1, addresses=[('5550100',), ('5550199',)], body='g' * 800)
        group_size = Message.decode('phone', group_wire).serialized_size()
        filler_size = self.store.threads[('phone', '10')].messages['1'].serialized_size()
        self.store.MAX_RETAINED_BYTES = group_size + filler_size - 1
        self.events.clear()
        self.store.ingest('phone', group_wire)
        self.assertNotIn('1', self.store.threads[('phone', '9')].messages)
        self.assertEqual(self.store.reply_status('phone', '9'), 'group')
        self.assertFalse(any(event.get('event') == 'message' and
                             event.get('message', {}).get('thread_id') == '9' for event in self.events))
        state = next(event for event in self.events if event.get('event') == 'reply_scope')
        self.assertEqual(state['reply_status'], 'group')
        self.assertEqual(state['conversation_token'], self.store.token('phone', '9'))
        with self.assertRaises(ValueError):
            self.service.send_sms({'op': 'sms_reply', 'device': 'phone', 'thread': '9',
                                   'conversation_token': self.store.token('phone', '9'),
                                   'recipient_scope': ['5550100'], 'text': 'reply', 'files': [],
                                   'request_id': 'self-evicted-group'})

    def test_unscoped_rejection_then_individual_does_not_restore_authorization(self):
        self.store.ingest('phone', wire(addresses=[('5550100',)]))
        malformed = list(wire()); malformed[6] = 'unknown-thread'; malformed[1] = 'x' * (Message.MAX_BODY_BYTES + 1)
        with self.assertRaises(ValueError): self.store.ingest('phone', malformed)
        with self.assertRaisesRegex(ValueError, 'serialized size limit'):
            self.store.ingest('phone', oversized_record([('5550100',)]))
        self.assertEqual(self.store.reply_status('phone', '9'), 'unknown')
        self.assertEqual(self.events[-1], {'event': 'reply_scope_uncertain', 'device': 'phone'})
        with self.assertRaises(ValueError):
            self.service.send_sms({'op': 'sms_reply', 'device': 'phone', 'thread': '9',
                                   'conversation_token': self.store.token('phone', '9'),
                                   'recipient_scope': ['5550100'], 'text': 'reply', 'files': [],
                                   'request_id': 'uncertainty-sticky'})

    def test_rejected_group_at_event_guard_publishes_safety_state(self):
        self.store.ingest('phone', wire(addresses=[('5550100',)]))
        from messaging import json_line_size
        attachments = [(i, '\x01' * 256,
                        'A' * (196608 if i < 2 else 110000 if i == 2 else 0),
                        '\x01' * 512) for i in range(16)]
        candidate = None
        low, high = 0, Message.MAX_BODY_BYTES
        while low < high:
            size = (low + high + 1) // 2
            raw = wire(uid=2, addresses=[('5550100',), ('5550199',)],
                       body='\x01' * size, attachments=attachments)
            try:
                decoded = Message.decode('phone', raw)
            except ValueError:
                high = size - 1
                continue
            if decoded.serialized_size() <= Message.MAX_SERIALIZED_BYTES:
                low = size
            else:
                high = size - 1
        # One ASCII control byte adds five JSON-escaped bytes, so the largest
        # decodable body should put the enclosing event over its slightly
        # smaller budget without a costly full-size fixture sweep.
        for size in (low,):
            raw = wire(uid=2, addresses=[('5550100',), ('5550199',)],
                       body='\x01' * size, attachments=attachments)
            decoded = Message.decode('phone', raw)
            event = {'event': 'message', 'message': decoded.json(),
                     'conversation_token': self.store.token('phone', '9'),
                     'source': 'summary', 'reply_status': 'group',
                     'delivery_confirmed': None, 'read_receipt': None}
            if decoded.serialized_size() <= Message.MAX_SERIALIZED_BYTES < json_line_size(event):
                candidate = raw
                break
        self.assertIsNotNone(candidate, 'expected room for a message that exceeds only the event envelope')
        with self.assertRaisesRegex(ValueError, 'event exceeds'):
            self.store.ingest('phone', candidate)
        self.assertEqual(self.store.reply_status('phone', '9'), 'group')
        self.assertEqual(self.events[-1]['event'], 'reply_scope')
        self.assertEqual(self.events[-1]['reply_status'], 'group')
        self.assertEqual(self.events[-1]['conversation_token'], self.store.token('phone', '9'))

    def test_rejected_group_while_reply_validation_pending_is_blocked(self):
        self.store.ingest('phone', wire(addresses=[('5550100',)]))
        pending = []
        self.service.local_job = lambda work, complete: pending.append((work, complete))
        self.service.send_sms({'op': 'sms_reply', 'device': 'phone', 'thread': '9',
                               'conversation_token': self.store.token('phone', '9'),
                               'recipient_scope': ['5550100'], 'text': 'reply', 'files': [],
                               'request_id': 'pending-group'})
        self.assertIn('phone', self.service.sms_actions)
        oversized = list(wire(addresses=[('5550100',), ('5550101',)], body='\x01' * Message.MAX_BODY_BYTES))
        oversized[9] = [(i, '\x01' * 256,
                         'A' * (Attachment.MAX_THUMBNAIL_BYTES if i < 2 else 100_000 if i == 2 else 0),
                         '\x01' * 512) for i in range(16)]
        with self.assertRaises(ValueError):
            self.store.ingest('phone', oversized)
        work, complete = pending.pop()
        complete(work(), None)
        self.transport.respond(value=({'isReachable': True, 'isPaired': True},))
        self.assertFalse(any(call[2] == 'replyToConversation' for call in self.transport.calls))
        self.assertEqual(self.events[-1]['event'], 'sms_result')
        self.assertFalse(self.events[-1]['accepted'])

    def test_rejected_record_without_reliable_scope_marks_device_uncertain(self):
        self.store.ingest('phone', wire(addresses=[('5550100',)]))
        malformed = list(wire()); malformed[6] = 'unknown-thread'; malformed[1] = 'x' * (Message.MAX_BODY_BYTES + 1)
        with self.assertRaises(ValueError):
            self.store.ingest('phone', malformed)
        self.assertEqual(self.store.reply_status('phone', '9'), 'unknown')
        self.assertEqual(self.events[-1], {'event': 'reply_scope_uncertain', 'device': 'phone'})

    def test_rejected_incomplete_recipient_update_blocks_backend_reply(self):
        self.store.ingest('phone', wire(addresses=[('5550100',)]))
        malformed = list(wire(uid=2, addresses=[])); malformed[1] = None
        with self.assertRaisesRegex(ValueError, 'Malformed KDE Connect message'):
            self.store.ingest('phone', malformed)
        self.assertEqual(self.store.reply_status('phone', '9'), 'incomplete')
        with self.assertRaisesRegex(ValueError, 'incomplete or uncertain'):
            self.service.send_sms({'op': 'sms_reply', 'device': 'phone', 'thread': '9',
                                   'conversation_token': self.store.token('phone', '9'),
                                   'recipient_scope': ['5550100'], 'text': 'reply', 'files': [],
                                   'request_id': 'rejected-incomplete'})
        self.assertFalse(any(call[2] == 'replyToConversation' for call in self.transport.calls))

    def test_invalid_timestamp_cannot_leave_superseded_scope_authorized(self):
        self.store.ingest('phone', wire(addresses=[('5550100',)]))
        malformed = list(wire(uid=2, addresses=[('5550199',)])); malformed[3] = 2**100
        with self.assertRaisesRegex(ValueError, 'timestamp'):
            self.store.ingest('phone', malformed)
        self.assertEqual(self.store.reply_status('phone', '9'), 'incomplete')
        with self.assertRaises(ValueError):
            self.service.send_sms({'op': 'sms_reply', 'device': 'phone', 'thread': '9',
                                   'conversation_token': self.store.token('phone', '9'),
                                   'recipient_scope': ['5550100'], 'text': 'reply', 'files': [],
                                   'request_id': 'malformed-time'})

    def test_malformed_message_values_are_rejected_and_malformed_attachments_are_empty(self):
        with self.assertRaises(ValueError): Message.decode('phone', None)
        data = list(wire()); data[3] = 'not-a-timestamp'
        with self.assertRaises(ValueError): Message.decode('phone', data)
        message = Message.decode('phone', wire(attachments=[None, ('bad', None, {}, [])]))
        self.assertEqual([(a.part_id, a.mime_type, a.thumbnail_base64, a.identifier) for a in message.attachments], [('', '', '', ''), ('', '', '', '')])

    def test_malformed_unicode_is_safely_normalized_and_action_ids_are_not_truncated(self):
        message = Message.decode('phone', wire(body='bad\ud800text', addresses=[('555\ud800100',)],
                                               attachments=[(1, 'text/\ud800plain', '', 'I' * 513)]))
        self.assertEqual(message.body, 'bad?text')
        self.assertFalse(message.addresses_complete)
        self.assertEqual(message.addresses, ['555?100'])
        self.assertEqual(message.attachments[0].mime_type, 'text/?plain')
        self.assertEqual(message.attachments[0].identifier, '')

    def test_notification_payload_is_utf8_bounded_before_storage_and_qml_event(self):
        self.service.read_notification('phone', '1')
        self.transport.respond(value=({'appName': 'A' * 10000, 'title': 'T' * 10000,
                                       'text': '🙂' * 10000, 'internalId': 'I' * 5000,
                                       'replyId': 'R' * 5000, 'iconPath': '/P' * 5000},))
        record = self.service.notifications[('phone', '1')]
        sizes = [len(record[k].encode('utf-8')) for k in ('app', 'title', 'body', 'internal_id', 'reply_id', 'icon_path')]
        self.assertLessEqual(sum(sizes), 32768)
        self.assertEqual(self.events[-1]['notification'], record)
        import json
        self.assertLessEqual(len(json.dumps(self.events[-1], ensure_ascii=False).encode('utf-8')), 32768)
        self.assertTrue(all(isinstance(record[k], str) for k in ('app', 'title', 'body', 'internal_id', 'reply_id', 'icon_path')))

    def test_notification_limit_covers_empty_body_and_escaped_metadata(self):
        self.service.read_notification('phone', '1')
        self.transport.respond(value=({'appName': '\x01' * 10000, 'title': '\x01' * 10000,
                                       'text': '', 'internalId': 'internal', 'replyId': 'reply',
                                       'iconPath': '\x01' * 10000},))
        record = self.service.notifications.get(('phone', '1'))
        self.assertIsNotNone(record)
        import json
        self.assertLessEqual(len(json.dumps(self.events[-1], ensure_ascii=False).encode('utf-8')), 32768)
        self.assertEqual(record['body'], '')

    def test_notification_retention_stays_within_global_count_limit(self):
        for index in range(140):
            self.service.read_notification('phone', str(index))
            self.transport.respond(value=({'text': 'ordinary'},))
        self.assertLessEqual(len(self.service.notifications), 128)
        self.assertLessEqual(len(self.service.note_versions), 128)

    def test_malformed_notification_payload_is_discarded(self):
        self.service.read_notification('phone', 'bad')
        self.transport.respond(value=(None,))
        self.assertNotIn(('phone', 'bad'), self.service.notifications)

    def test_duplicate_signal_only_emits_once(self):
        self.store.ingest('phone', wire()); self.store.ingest('phone', wire(), True)
        self.assertEqual(len(self.events), 1)

    def test_same_timestamp_preserves_different_messages(self):
        for uid in (1, 2): self.store.ingest('phone', wire(uid=uid))
        self.assertEqual(len(self.store.conversation('phone', '9').messages), 2)

    def test_exposed_status_update_replaces_record(self):
        self.store.ingest('phone', wire(kind=4)); self.store.ingest('phone', wire(kind=2), True)
        self.assertEqual(len(self.store.conversation('phone', '9').messages), 1)
        self.assertEqual(self.events[-1]['message']['state'], 'sent')
        self.assertFalse(self.events[-1]['delivery_confirmed'])

    def test_page_filters_other_devices_threads_and_duplicates(self):
        page = self.store.begin_page('a', 'phone', '9')
        self.store.ingest('other', wire(), True); self.store.ingest('phone', wire(thread=10), True)
        for _ in range(3): self.store.ingest('phone', wire(), True)
        self.assertEqual(page.seen, {'1'})

    def test_pagination_overlap_and_unknown_completion(self):
        self.store.begin_page('a', 'phone', '9', 5)
        for uid in range(5): self.store.ingest('phone', wire(uid=uid), True)
        self.now = 16; self.service.tick()
        page = self.store.begin_page('b', 'phone', '9', 5)
        self.assertEqual(page.start, 3); self.assertIsNone(self.events[-1]['complete'])
        self.assertFalse(self.events[-1]['exhaustive'])
        with self.assertRaises(ValueError): self.store.begin_page('c', 'phone', '9')

    def test_timeout_retries_only_once(self):
        page = self.store.begin_page('a', 'phone', '9'); self.service.request_page(page)
        for now in (16, 32, 100): self.now = now; self.service.tick()
        self.assertEqual(len(self.transport.calls), 2); self.assertEqual(self.events[-1]['reason'], 'timeout')

    def test_disconnect_cancels_and_resets_pagination(self):
        c = self.store.conversation('phone', '9'); c.next_offset = 50
        self.store.begin_page('a', 'phone', '9'); self.service.disconnect('phone')
        self.assertEqual(c.next_offset, 0); self.assertFalse(self.store.pages)
        self.assertEqual(self.events[0]['reason'], 'disconnected')

    def test_s1_late_empty_snapshot_cannot_retire_suppression_after_property_failure(self):
        from notification_removal_store import NotificationRemovalStore, notification_fingerprint
        store=NotificationRemovalStore(persistent=False)
        record={'internal_id':'internal-z','reply_id':'reply-z','title':'t','app':'a','body':'b','dismissable':True}
        occurrence=store.occurrence('phone','z',notification_fingerprint(record))
        store.mark_removed([{'device':'phone','id':'z','occurrence_id':occurrence}])
        events=[];transport=FakeTransport();service=Service(transport,events.append,notification_state=store)
        service.devices['phone']={'id':'phone','online':True,'generation':1,'plugins':['kdeconnect_notifications']}

        # An old complete snapshot is in flight while a post/re-read establishes
        # the same occurrence, then a transient GetAll failure evicts per-ID data.
        service.refresh_notifications('phone')
        list_index=next(i for i,c in enumerate(transport.calls) if c[2]=='activeNotifications')
        service.read_notification('phone','z')
        read_index=max(i for i,c in enumerate(transport.calls) if c[2]=='GetAll')
        props={'internalId':'internal-z','replyId':'reply-z','title':'t','appName':'a','text':'b','dismissable':True}
        transport.respond(read_index,value=(props,))
        self.assertEqual(service.notifications[('phone','z')]['occurrence_id'],occurrence)
        self.assertTrue(store.entries[store.key('phone','z')]['removed'])
        service.read_notification('phone','z')
        failed_index=max(i for i,c in enumerate(transport.calls) if c[2]=='GetAll')
        transport.respond(failed_index,error=RuntimeError('temporary property failure'))
        self.assertNotIn(('phone','z'),service.note_versions)
        transport.respond(list_index,value=([],))
        saved=store.entries.get(store.key('phone','z'))
        self.assertIsNotNone(saved)
        self.assertEqual(saved['occurrence_id'],occurrence)
        self.assertTrue(saved['removed'])
        self.assertFalse(any(e.get('event')=='notification_removed' and e.get('authoritative') for e in events))

        # Re-reading after that stale list still resolves to the suppressed old
        # occurrence; it cannot be converted into a fresh authorization/display.
        service.read_notification('phone','z')
        last=max(i for i,c in enumerate(transport.calls) if c[2]=='GetAll')
        transport.respond(last,value=(props,))
        emitted=[e for e in events if e.get('event')=='notification'][-1]
        self.assertEqual(emitted['notification']['occurrence_id'],occurrence)
        self.assertTrue(store.entries[store.key('phone','z')]['removed'])

        # A new complete empty snapshot after that observation can retire the
        # persisted occurrence; the ordering fence is conservative, not a leak.
        service.refresh_notifications('phone')
        fresh_list=max(i for i,c in enumerate(transport.calls) if c[2]=='activeNotifications')
        transport.respond(fresh_list,value=([],))
        self.assertIsNone(store.entries.get(store.key('phone','z')))
        self.assertTrue(any(e.get('event')=='notification_removed' and e.get('authoritative') for e in events))

    def test_s1r_accepted_property_completion_fences_overlapping_empty_snapshot(self):
        from notification_removal_store import NotificationRemovalStore, notification_fingerprint
        props={'internalId':'internal-z','replyId':'reply-z','title':'t','appName':'a','text':'b','dismissable':True}

        def run(changed_reply=False, cold=False):
            state_dir=tempfile.TemporaryDirectory() if cold else None
            store=(NotificationRemovalStore(Path(state_dir.name)/'removals.json') if cold
                   else NotificationRemovalStore(persistent=False))
            events=[];transport=FakeTransport()
            service=Service(transport,events.append,notification_state=store)
            service.devices['phone']={'id':'phone','online':True,'generation':1,'plugins':['kdeconnect_notifications']}
            if changed_reply:
                prior=store.occurrence('phone','z',notification_fingerprint({'internal_id':'internal-z','reply_id':'reply-old'}))
                store.mark_removed([{'device':'phone','id':'z','occurrence_id':prior}])
                props['replyId']='reply-new'
            elif cold:
                prior=store.occurrence('phone','z',notification_fingerprint({'internal_id':'internal-z','reply_id':'reply-z'}))
                store.mark_removed([{'device':'phone','id':'z','occurrence_id':prior}])
                # Model a restarted worker hydrating the persisted occurrence.
                store=NotificationRemovalStore(store.path)
                service=Service(transport,events.append,notification_state=store)
                service.devices['phone']={'id':'phone','online':True,'generation':1,'plugins':['kdeconnect_notifications']}
            service.read_notification('phone','z')
            property_index=max(i for i,c in enumerate(transport.calls) if c[2]=='GetAll')
            service.refresh_notifications('phone')
            list_index=max(i for i,c in enumerate(transport.calls) if c[2]=='activeNotifications')
            fence_before=service.notification_observation_revision
            transport.respond(property_index,value=(dict(props),))
            self.assertGreater(service.notification_observation_revision,fence_before)
            row=service.notifications[('phone','z')]
            self.assertEqual(row['reply_id'],'reply-new' if changed_reply else 'reply-z')
            occurrence=row['occurrence_id']
            self.assertTrue(occurrence)
            # This is the actual production command parser/dispatcher boundary.
            service.command({'op':'notification_local_remove','request_id':'panel-clear',
                'entries':[{'device':'phone','id':'z','occurrence_id':occurrence}]})
            transport.respond(list_index,value=([],))
            self.assertTrue(store.is_removed('phone','z',occurrence))
            self.assertFalse(any(e.get('event')=='notification_removed' and e.get('authoritative') for e in events))
            # A newly requested complete empty response is fresh closure evidence.
            service.refresh_notifications('phone')
            fresh=max(i for i,c in enumerate(transport.calls) if c[2]=='activeNotifications')
            transport.respond(fresh,value=([],))
            self.assertIsNone(store.current('phone','z'))
            service.read_notification('phone','z')
            reused=max(i for i,c in enumerate(transport.calls) if c[2]=='GetAll')
            transport.respond(reused,value=(dict(props),))
            self.assertNotEqual(service.notifications[('phone','z')]['occurrence_id'],occurrence)
            if changed_reply:
                props['replyId']='reply-z'
            if state_dir:
                state_dir.cleanup()
            return service,store,transport,events,occurrence

        for changed_reply,cold in ((False,False),(True,False),(False,True)):
            with self.subTest(changed_reply=changed_reply,cold=cold):
                run(changed_reply,cold)

        # A callback for a replaced device generation is rejected before the
        # accepted-observation fence advances.
        events=[];transport=FakeTransport();service=Service(transport,events.append)
        service.devices['phone']={'id':'phone','online':True,'generation':1,'plugins':['kdeconnect_notifications']}
        service.read_notification('phone','obsolete')
        index=max(i for i,c in enumerate(transport.calls) if c[2]=='GetAll')
        fence=service.notification_observation_revision
        service.devices['phone']['generation']=2
        transport.respond(index,value=(dict(props),))
        self.assertEqual(service.notification_observation_revision,fence)
        self.assertNotIn(('phone','obsolete'),service.notifications)
        self.assertFalse(any(e.get('event')=='notification' for e in events))

        # A per-identity version replacement is also rejected before the
        # accepted-observation fence advances.
        events=[];transport=FakeTransport();service=Service(transport,events.append)
        service.devices['phone']={'id':'phone','online':True,'generation':1,'plugins':['kdeconnect_notifications']}
        service.read_notification('phone','replaced')
        index=max(i for i,c in enumerate(transport.calls) if c[2]=='GetAll')
        service.remove_notification('phone','replaced')
        fence=service.notification_observation_revision
        transport.respond(index,value=(dict(props),))
        self.assertEqual(service.notification_observation_revision,fence)
        self.assertNotIn(('phone','replaced'),service.notifications)
        self.assertFalse(any(e.get('event')=='notification' for e in events))

        # A property request already in flight when a list starts fences that
        # list when the current property callback is accepted.
        events=[];transport=FakeTransport();service=Service(transport,events.append)
        service.devices['phone']={'id':'phone','online':True,'generation':1,'plugins':['kdeconnect_notifications']}
        service.read_notification('phone','overlap')
        read_index=max(i for i,c in enumerate(transport.calls) if c[2]=='GetAll')
        service.refresh_notifications('phone')
        list_index=max(i for i,c in enumerate(transport.calls) if c[2]=='activeNotifications')
        transport.respond(read_index,value=(dict(props),))
        observed=service.notification_observation_revision
        transport.respond(list_index,value=([],))
        self.assertGreaterEqual(service.notification_observation_revision,observed)
        self.assertIn(('phone','overlap'),service.notifications)
        self.assertFalse(any(e.get('event')=='notification_removed' and e.get('authoritative') for e in events))

    def test_o1_malformed_outer_list_preserves_suppression_but_valid_empty_closes(self):
        from notification_removal_store import NotificationRemovalStore, notification_fingerprint
        malformed=((),('not-an-array',),([],[]),None)
        for response in malformed:
            with self.subTest(response=response):
                store=NotificationRemovalStore(persistent=False)
                occurrence=store.occurrence('phone','z',notification_fingerprint({'internal_id':'i','reply_id':'r'}))
                store.mark_removed([{'device':'phone','id':'z','occurrence_id':occurrence}])
                events=[];transport=FakeTransport();service=Service(transport,events.append,notification_state=store)
                service.devices['phone']={'id':'phone','online':True,'generation':1,'plugins':['kdeconnect_notifications']}
                service.refresh_notifications('phone')
                index=next(i for i,c in enumerate(transport.calls) if c[2]=='activeNotifications')
                transport.respond(index,value=response)
                current=store.entries.get(store.key('phone','z'))
                self.assertIsNotNone(current)
                self.assertTrue(current['removed'])
                self.assertTrue(any(e.get('event')=='error' and 'invalid data' in e.get('error','') for e in events))
        store=NotificationRemovalStore(persistent=False)
        occurrence=store.occurrence('phone','z',notification_fingerprint({'internal_id':'i','reply_id':'r'}))
        store.mark_removed([{'device':'phone','id':'z','occurrence_id':occurrence}])
        events=[];transport=FakeTransport();service=Service(transport,events.append,notification_state=store)
        service.devices['phone']={'id':'phone','online':True,'generation':1,'plugins':['kdeconnect_notifications']}
        service.refresh_notifications('phone')
        transport.respond(value=([],))
        self.assertIsNone(store.entries.get(store.key('phone','z')))
        self.assertTrue(any(e.get('event')=='notification_removed' and e.get('authoritative') for e in events))

    def test_notification_snapshot_truncation_never_retires_omitted_active_identity(self):
        from notification_removal_store import NotificationRemovalStore, notification_fingerprint
        ids=[f"a{i:03d}" for i in range(128)]+["z"]
        for cold in (False,True):
            with self.subTest(cold=cold):
                store=NotificationRemovalStore(persistent=False)
                occurrence=store.occurrence('phone','z',notification_fingerprint({'internal_id':'internal-z','reply_id':'reply-z'}))
                store.mark_removed([{'device':'phone','id':'z','occurrence_id':occurrence}])
                events=[];transport=FakeTransport();service=Service(transport,events.append,notification_state=store)
                service.devices['phone']={'id':'phone','online':True,'generation':1,'plugins':['kdeconnect_notifications']}
                if not cold:
                    service.note_versions[('phone','z')]=1
                    service.notifications[('phone','z')]={'device':'phone','id':'z','occurrence_id':occurrence}
                service.refresh_notifications('phone')
                index=next(i for i,c in enumerate(transport.calls) if c[2]=='activeNotifications')
                transport.respond(index,value=(ids,))
                current=store.entries.get(store.key('phone','z'))
                self.assertEqual(current['occurrence_id'],occurrence)
                self.assertTrue(current['removed'])
                self.assertFalse(any(e.get('event')=='notification_removed' and e.get('id')=='z' and e.get('authoritative') is True for e in events))

    def test_cold_notification_closure_retires_before_first_property_read(self):
        from notification_removal_store import NotificationRemovalStore, notification_fingerprint
        for member in ('notificationRemoved','allNotificationsRemoved'):
            with self.subTest(member=member):
                store=NotificationRemovalStore(persistent=False)
                old=store.occurrence('phone','1',notification_fingerprint({'internal_id':'i','reply_id':'r'}))
                store.mark_removed([{'device':'phone','id':'1','occurrence_id':old}])
                events=[];transport=FakeTransport();service=Service(transport,events.append,notification_state=store)
                service.devices['phone']={'id':'phone','online':True,'generation':1,'plugins':['kdeconnect_notifications']}
                service.read_notification('phone','1')
                service.signal(device_path('phone')+'/notifications',NOTIFICATIONS,member,('1',) if member=='notificationRemoved' else ())
                self.assertIsNone(store.entries.get(store.key('phone','1')))
                # The obsolete in-flight property read must not restore old data.
                read_index=next(i for i,c in enumerate(transport.calls) if c[2]=='GetAll')
                transport.respond(read_index,value=({'internalId':'i','replyId':'r','text':'delayed'},))
                self.assertFalse(any(e.get('event')=='notification' for e in events))
                service.read_notification('phone','1')
                current_index=max(i for i,c in enumerate(transport.calls) if c[2]=='GetAll')
                transport.respond(current_index,value=({'internalId':'i','replyId':'r','text':'new occurrence'},))
                self.assertEqual(len([e for e in events if e.get('event')=='notification']),1)
                self.assertNotEqual(events[-1]['notification']['occurrence_id'],old)

    def test_removed_notification_ignores_late_read(self):
        self.service.read_notification('phone', '1'); self.service.remove_notification('phone', '1')
        self.transport.respond(value=({'text': 'old', 'replyId': 'token'},))
        self.assertFalse(self.service.notifications)

    def test_replaced_notification_ignores_out_of_order_read(self):
        self.service.read_notification('phone', '1'); self.service.read_notification('phone', '1')
        self.assertEqual(len(self.transport.calls), 1)  # Updates coalesce while a read is pending.
        self.transport.respond(0, ({'text': 'old'},))
        self.assertFalse(self.service.notifications)
        self.transport.respond(1, ({'text': 'new', 'replyId': 'new'},))
        self.assertEqual(self.service.notifications[('phone', '1')]['body'], 'new')

    def test_icon_is_not_attachment(self):
        self.service.read_notification('phone', '1')
        self.transport.respond(value=({'iconPath': '/tmp/icon', 'replyId': 'reply', 'dismissable': True},))
        n = self.events[-1]['notification']; self.assertNotIn('media_attachment', n)
        self.assertEqual(n['icon_kind'], 'notification_icon'); self.assertEqual(n['reply_id'], '')

    def test_notification_tokens_are_exact_and_actions_validate_them(self):
        self.service.read_notification('phone', '1')
        self.transport.respond(value=({'internalId': 'internal-😀', 'replyId': 'reply-😀', 'dismissable': True},))
        note = self.service.notifications[('phone', '1')]
        self.assertEqual(note['internal_id'], 'internal-😀')
        self.assertEqual(note['reply_id'], 'reply-😀')
        self.service.command({'op': 'notification_reply', 'device': 'phone', 'id': '1',
                              'internal_id': note['internal_id'], 'reply_id': note['reply_id'],
                              'text': 'yes', 'request_id': 'reply',
                              'occurrence_id': note['occurrence_id'],
                              'notification_epoch': self.service.notification_epoch})
        self.transport.respond(value=({'internalId': 'internal-😀', 'replyId': 'reply-😀'},))
        self.assertEqual(self.transport.calls[-1][2], 'sendReply')
        self.assertEqual(self.transport.calls[-1][4][0], note['reply_id'])

    def test_oversized_or_malformed_notification_tokens_disable_actions(self):
        for internal, reply in [('I' * 1025, 'reply'), ('I' * 2_000_000, 'reply'), ('internal', ['bad'])]:
            self.service.read_notification('phone', '1')
            self.transport.respond(value=({'internalId': internal, 'replyId': reply, 'dismissable': True},))
            note = self.service.notifications[('phone', '1')]
            if isinstance(internal, str) and len(internal) > 1024:
                self.assertEqual(note['internal_id'], '')
                self.assertEqual(note['reply_id'], '')
                self.assertFalse(note['dismissable'])
            else:
                self.assertEqual(note['internal_id'], internal)
                self.assertEqual(note['reply_id'], '')
            before = len(self.transport.calls)
            self.service.command({'op': 'notification_reply', 'device': 'phone', 'id': '1',
                                  'internal_id': internal, 'reply_id': reply, 'text': 'bad', 'request_id': 'bad'})
            self.assertEqual(len(self.transport.calls), before)

    def test_notification_cannot_be_used_as_mms_descriptor(self):
        self.service.read_notification('phone', '1')
        self.transport.respond(value=({'iconPath': '/tmp/icon', 'text': 'photo'},))
        note = self.events[-1]['notification']
        before = len(self.transport.calls)
        for operation in ('attachment', 'attachment_open'):
            self.service.command(dict(note, op=operation, request_id='bad'))
            self.assertEqual(self.events[-1]['event'], 'error')
        self.assertEqual(len(self.transport.calls), before)
        self.assertFalse(self.service.attachments)
        self.assertFalse(self.service.downloads)

    def test_conversation_normalization_preserves_identity_and_capability(self):
        for body, expected in [('Status', 'Status'), ('Project update<br/><b>Casey Example</b><br/>See you soon', 'Project update\nCasey Example\nSee you soon')]:
            self.service.read_notification('phone', '1')
            self.transport.respond(value=({'text': body, 'isConversation': True, 'internalId': 'same',
                                          'replyId': 'token', 'dismissable': True},))
            note = self.events[-1]['notification']
            self.assertEqual((note['id'], note['internal_id'], note['reply_id'], note['dismissable']),
                             ('1', 'same', 'token', True))
            self.assertEqual(note['body'], expected)

    def test_old_daemon_callbacks_ignored(self):
        self.service.read_notification('phone', '1'); self.service.owner_changed()
        self.transport.respond(value=({'text': 'old'},))
        self.assertFalse(self.service.notifications); self.assertIsNotNone(self.service.refresh_due)

    def test_reconnect_refreshes_both_services(self):
        self.service.disconnect('phone'); self.service.refresh()
        self.transport.respond(value=(['phone'],))
        self.transport.respond(value=({'isReachable': True, 'isPaired': True},))
        self.transport.respond(value=(['kdeconnect_sms', 'kdeconnect_notifications'],))
        methods = [c[2] for c in self.transport.calls]
        for m in ('activeNotifications', 'activeConversations', 'requestAllConversationThreads'): self.assertIn(m, methods)

    def test_attachment_requires_message_descriptor(self):
        with self.assertRaises(ValueError): self.service.request_attachment('a', 'phone', '9', '1', '1', 'avatar')
        self.assertFalse(self.transport.calls)

    def test_attachment_timeout_and_offline(self):
        self.store.ingest('phone', wire(attachments=[(7, 'image/jpeg', '', 'photo')]))
        self.service.request_attachment('a', 'phone', '9', '1', '7', 'photo')
        for now in (31, 62): self.now = now; self.service.tick()
        self.assertEqual(len(self.transport.calls), 2); self.assertFalse(self.service.attachments)
        self.assertIn('timed out', self.events[-1]['error'])
        self.service.disconnect('phone')
        with self.assertRaises(ValueError): self.service.request_attachment('b', 'phone', '9', '1', '7', 'photo')

    def test_unrequested_attachment_ignored(self):
        self.service.attachment_received('phone', '/tmp/file', 'file'); self.assertFalse(self.events)

    def test_unknown_or_malformed_send_commands_cannot_send(self):
        for op in ('send', 'sendSms', 'reply', 'notification_reply'): self.service.command({'op': op})
        self.assertFalse(self.transport.calls); self.assertTrue(all(e['event'] == 'error' for e in self.events))

    def test_sms_capability_pending_is_distinct_from_unavailable(self):
        self.service.devices['phone']['plugins'] = None
        self.service.command({'op':'sms_send','device':'phone','recipient':'5550100','text':'pending','files':[],'request_id':'p'})
        self.assertEqual(self.events[-1]['error'], 'KDE Connect capabilities are still loading. Try again when the phone status is ready.')
        self.service.devices['phone']['plugins'] = []
        self.service.command({'op':'sms_send','device':'phone','recipient':'5550100','text':'unavailable','files':[],'request_id':'u'})
        self.assertEqual(self.events[-1]['error'], 'This KDE Connect capability is unavailable')
        self.assertFalse(self.transport.calls)

    def test_live_other_thread_does_not_complete_page(self):
        page = self.store.begin_page('a', 'phone', '9')
        self.service.signal(device_path('phone'), CONVERSATIONS, 'conversationUpdated', (wire(thread=10),))
        self.assertFalse(page.seen); self.assertIn(('phone', '10'), self.store.threads)

    def test_attachment_completion_reuses_kde_cache(self):
        self.store.ingest('phone', wire(attachments=[(7, 'image/jpeg', '', 'photo')]))
        self.service.request_attachment('a', 'phone', '9', '1', '7', 'photo')
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary) / 'kdeconnect.daemon' / 'Phone'
            cache.mkdir(parents=True)
            file = cache / 'photo'; file.write_bytes(b'available attachment')
            with patch.dict('os.environ', {'XDG_CACHE_HOME': temporary}):
                self.service.attachment_received('phone', str(file), 'photo')
        self.assertEqual(self.events[-1]['event'], 'attachment_ready')
        self.assertEqual(self.events[-1]['request_id'], 'a')
        self.assertFalse(self.service.attachments)

    def test_attachment_rejects_unrelated_local_path(self):
        self.store.ingest('phone', wire(attachments=[(7, 'image/jpeg', '', 'photo')]))
        self.service.request_attachment('a', 'phone', '9', '1', '7', 'photo')
        self.service.attachment_received('phone', '/etc/passwd', 'photo')
        self.assertEqual(self.events[-1]['event'], 'error')

    def test_history_dbus_error_clears_pending(self):
        page = self.store.begin_page('a', 'phone', '9'); self.service.request_page(page)
        self.transport.respond(error='Unavailable')
        self.assertFalse(self.store.pages)
        self.assertEqual(self.events[-1]['event'], 'error')

    def test_delayed_notification_read_after_offline_ignored(self):
        self.service.read_notification('phone', '1'); self.service.disconnect('phone')
        self.transport.respond(value=({'text': 'stale'},))
        self.assertFalse(self.service.notifications)

    def test_remove_all_invalidates_inflight_notification_read(self):
        self.service.read_notification('phone', '1')
        self.service.signal(device_path('phone') + '/notifications', NOTIFICATIONS,
                            'allNotificationsRemoved', ())
        self.transport.respond(value=({'text': 'stale'},))
        self.assertFalse(self.service.notifications)

    def test_contact_vcards_keep_multiple_numbers(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / 'kpeoplevcard' / 'kdeconnect-phone'; folder.mkdir(parents=True)
            (folder / 'one.vcf').write_bytes(b'BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Ana Example\r\nTEL;TYPE=CELL:+1 (555) 0100\r\nTEL;TYPE=WORK:555-0198\r\nEND:VCARD\r\n')
            result = contacts.read_contacts('phone', temp)
        self.assertTrue(result['available']); self.assertEqual(len(result['contacts'][0]['numbers']), 2)

    def test_missing_contacts_do_not_block_manual_number(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertFalse(contacts.read_contacts('phone', temp)['available'])
        self.assertEqual(sms.recipient('+1 (555) 0100'), '+15550100')

    def test_attachment_validation_and_picker_cancel(self):
        with tempfile.NamedTemporaryFile() as file:
            result = sms.files([file.name, file.name])
            self.assertEqual(len(result), 1)
        self.assertTrue(sms.picker_result(1, '')['cancelled'])
        with self.assertRaises(ValueError): sms.files(['/definitely/missing'])

    def test_same_proof_conflicting_historical_replays_fail_closed(self):
        for replay_timestamp in (100, 50):
            for timing in ('direct', 'file', 'online'):
                with self.subTest(timestamp=replay_timestamp, timing=timing):
                    self.setUp()
                    original = list(wire(uid=1, addresses=[('5550100',)]))
                    self.store.ingest('phone', original)
                    replacement = list(wire(uid=1, addresses=[('5550199',)])); replacement[3] = 200
                    self.store.ingest('phone', replacement)
                    replay = list(original); replay[3] = replay_timestamp
                    pending = []
                    command = {'op': 'sms_reply', 'device': 'phone', 'thread': '9',
                               'conversation_token': self.store.token('phone', '9'),
                               'recipient_scope': ['5550199'], 'text': 'reply', 'files': [],
                               'request_id': 'historical-replay'}
                    if timing == 'file':
                        self.service.local_job = lambda work, complete: pending.append((work, complete))
                    elif timing == 'online':
                        self.service.local_job = lambda work, complete: complete(work(), None)
                    if timing != 'direct':
                        self.service.send_sms(command)
                    self.store.ingest('phone', replay, history_signal=True)
                    self.assertEqual(self.store.reply_status('phone', '9'), 'incomplete')
                    self.assertNotIn(('phone', '9'), self.store.reply_scopes)
                    self.assertEqual(self.store.reply_ordering_watermarks[('phone', '9')], (200, 1, '1'))
                    self.assertTrue(any(e.get('event') in ('reply_scope', 'message') and
                                        e.get('reply_status') == 'incomplete' for e in self.events))
                    if timing == 'direct':
                        with self.assertRaises(ValueError):
                            self.service.send_sms(command)
                    elif timing == 'file':
                        work, complete = pending.pop(); complete(work(), None)
                    if timing != 'direct':
                        self.transport.respond(value=({'isReachable': True, 'isPaired': True},))
                    self.assertFalse(any(call[2] == 'replyToConversation' for call in self.transport.calls))

    def test_same_recipient_proof_rollback_preserves_freshness_watermark(self):
        self.store.ingest('phone', wire(uid=1, addresses=[('5550100',)]))
        replacement = list(wire(uid=1, addresses=[('5550199',)])); replacement[3] = 200
        self.store.ingest('phone', replacement)
        token = self.store.token('phone', '9')
        rollback = list(wire(uid=1, addresses=[('5550199',)], body='rollback')); rollback[3] = 50
        self.store.ingest('phone', rollback)
        self.assertEqual(self.store.reply_status('phone', '9'), 'individual')
        self.assertEqual(self.store.reply_scopes[('phone', '9')], (('5550199',), 200, '1'))
        self.assertEqual(self.store.token('phone', '9'), token)

    def test_rejected_same_recipient_evidence_advances_but_never_lowers_watermark(self):
        self.store.ingest('phone', wire(uid=1, addresses=[('5550100',)]))
        same = list(oversized_record([('5550100',)])); same[3] = 200; same[7] = 1
        with self.assertRaisesRegex(ValueError, 'serialized size limit'):
            self.store.ingest('phone', same)
        self.assertEqual(self.store.reply_status('phone', '9'), 'individual')
        self.assertEqual(self.store.reply_scopes[('phone', '9')], (('5550100',), 200, '1'))
        conflicting = list(wire(uid=1, addresses=[('5550199',)])); conflicting[3] = 150
        self.store.ingest('phone', conflicting)
        self.assertEqual(self.store.reply_status('phone', '9'), 'incomplete')
        self.assertEqual(self.store.reply_ordering_watermarks[('phone', '9')], (200, 1, '1'))

    def test_duplicate_historical_payload_after_same_proof_rollback_is_noop(self):
        self.store.ingest('phone', wire(uid=1, addresses=[('5550100',)]))
        self.store.ingest('phone', wire(uid=2, addresses=[('5550199',)]))
        self.store.ingest('phone', wire(uid=2, addresses=[('5550199',)], body='timestamp rollback'))
        key = ('phone', '9'); token = self.store.token(*key); scope = self.store.reply_scopes[key]
        count = len(self.events)
        self.store.ingest('phone', wire(uid=1, addresses=[('5550100',)]), history_signal=True)
        self.assertEqual(self.store.reply_scopes[key], scope)
        self.assertEqual(self.store.token(*key), token)
        self.assertEqual(self.store.reply_status(*key), 'individual')
        self.assertEqual(len(self.events), count, 'unchanged authorization emits no redundant safety event')

    def test_strictly_newer_singleton_recovers_ordering_risk_and_aba(self):
        self.store.ingest('phone', wire(uid=1, addresses=[('5550100',)]))
        self.store.ingest('phone', wire(uid=1, addresses=[('5550199',)]))
        stale = self.store.token('phone', '9')
        original = list(wire(uid=1, addresses=[('5550100',)]))
        self.store.ingest('phone', original, history_signal=True)
        self.assertEqual(self.store.reply_status('phone', '9'), 'incomplete')
        for timestamp, address in ((300, '5550100'), (400, '5550199'), (500, '5550100')):
            fresh = list(wire(uid=1, addresses=[(address,)])); fresh[3] = timestamp
            self.store.ingest('phone', fresh)
            self.assertEqual(self.store.reply_status('phone', '9'), 'individual')
            self.assertEqual(self.store.reply_scopes[('phone', '9')][0], (address,))
        self.assertNotEqual(self.store.token('phone', '9'), stale)

    def test_rejected_same_proof_conflict_keeps_marker_until_newer_acceptance(self):
        for rejected_kind in ('record', 'event'):
            with self.subTest(kind=rejected_kind):
                self.setUp()
                self.store.ingest('phone', wire(uid=1, addresses=[('5550100',)]))
                replacement = list(wire(uid=1, addresses=[('5550199',)])); replacement[3] = 200
                self.store.ingest('phone', replacement)
                if rejected_kind == 'record':
                    value = list(oversized_record([('5550100',)])); value[3] = 50; value[7] = 1
                else:
                    value = oversized_singleton_event_replacement(self.store, '5550100')
                with self.assertRaisesRegex(ValueError, 'serialized size limit'):
                    self.store.ingest('phone', value)
                self.assertEqual(self.store.reply_status('phone', '9'), 'incomplete')
                self.assertEqual(self.store.reply_ordering_watermarks[('phone', '9')], (200, 1, '1'))
                self.store.ingest('phone', wire(uid=1, addresses=[('5550100',)]))
                self.assertEqual(self.store.reply_status('phone', '9'), 'incomplete')
                newer = list(wire(uid=1, addresses=[('5550100',)])); newer[3] = 300
                self.store.ingest('phone', newer)
                self.assertEqual(self.store.reply_status('phone', '9'), 'individual')

    def test_actual_retention_ceiling_allows_valid_reply_after_self_eviction(self):
        for timing in ('direct', 'file', 'online'):
            with self.subTest(timing=timing):
                self.setUp()
                self.store.ingest('phone', wire(uid=1, addresses=[('5550100',)]))
                pending = []
                command = {'op': 'sms_reply', 'device': 'phone', 'thread': '9',
                           'conversation_token': self.store.token('phone', '9'),
                           'recipient_scope': ['5550100'], 'text': 'preserved individual reply',
                           'files': [], 'request_id': 'self-eviction-reply'}
                if timing == 'file':
                    self.service.local_job = lambda work, complete: pending.append((work, complete))
                else:
                    self.service.local_job = lambda work, complete: complete(work(), None)
                if timing != 'direct':
                    self.service.send_sms(command)

                uid = 1000
                while self.store.MAX_RETAINED_BYTES - self.store.retained_bytes > 150000:
                    self.store.ingest('phone', wire(uid=uid, thread=10, body='',
                        attachments=[(1, 'x', 'A' * 131072, 'x')]))
                    uid += 1
                remaining = self.store.MAX_RETAINED_BYTES - self.store.retained_bytes
                base = list(wire(uid=uid, thread=10, body='', attachments=[(1, 'x', '', 'x')]))
                delta = remaining - 100 - Message.decode('phone', base).serialized_size()
                self.assertGreaterEqual(delta, 0)
                self.assertLess(delta, 196608)
                base[1] = 'x' * (delta % 4)
                base[9] = [(1, 'x', 'A' * (delta // 4 * 4), 'x')]
                self.store.ingest('phone', base)
                self.assertEqual(self.store.MAX_RETAINED_BYTES - self.store.retained_bytes, 100)
                replacement = wire(uid=1, thread=9, body='',
                                   attachments=[(1, 'x', 'A' * 131072, 'x')])
                self.store.ingest('phone', replacement)
                self.assertEqual(self.store.retained_bytes <= self.store.MAX_RETAINED_BYTES, True)
                self.assertEqual(self.store.threads[('phone', '9')].messages, {})
                self.assertEqual(self.store.reply_scopes[('phone', '9')][0], ('5550100',))

                if timing == 'direct':
                    self.service.send_sms(command)
                elif timing == 'file':
                    work, complete = pending.pop(); complete(work(), None)
                self.transport.respond(value=({'isReachable': True, 'isPaired': True},))
                self.assertEqual(self.transport.calls[-1][2], 'replyToConversation')

    def _r1_observation(self, path, hazard, timestamp=300):
        addresses = [('5550100',), ('5550199',)] if hazard == 'group' else []
        raw = list(oversized_record(addresses) if path == 'record' else wire(uid=2, addresses=addresses))
        raw[3] = timestamp
        if path == 'event':
            raw = list(oversized_record(addresses)); raw[1] = ''; raw[3] = timestamp
            def frame():
                return {'event': 'message', 'message': Message.decode('phone', raw).json(),
                        'conversation_token': self.store.session + ':' + str(self.store.sequence + 1),
                        'source': 'summary', 'reply_status': hazard,
                        'delivery_confirmed': None, 'read_receipt': None}
            delta = Message.MAX_SERIALIZED_BYTES + 1 - json_line_size(frame())
            raw[1] = '\x01' * (delta // 6) + 'x' * (delta % 6)
            self.assertEqual(json_line_size(frame()), 614401)
            self.assertLessEqual(Message.decode('phone', raw).serialized_size(), 614400)
        return raw

    def _r1_singleton(self, timestamp, address='5550100', uid=1):
        raw = list(wire(uid=uid, addresses=[(address,)])); raw[3] = timestamp
        self.store.ingest('phone', raw, history_signal=True)

    def _r1_command(self):
        return {'op': 'sms_reply', 'device': 'phone', 'thread': '9',
                'conversation_token': self.store.token('phone', '9'),
                'recipient_scope': list(self.service.recipient_scope('phone', '9') or ('5550100',)),
                'text': 'Synthetic regression', 'files': [], 'request_id': 'r1'}

    def test_ordering_hazards_block_old_pending_and_current_authorizations(self):
        # 18 original R1 variants plus 18 hazards after a legitimate recovery.
        for recovered_first in (False, True):
            for hazard in ('group', 'incomplete'):
                for path in ('accepted', 'record', 'event'):
                    for timing in ('direct', 'file', 'online'):
                        with self.subTest(recovered_first=recovered_first, hazard=hazard, path=path, timing=timing):
                            self.setUp(); self._r1_singleton(100); self._r1_singleton(200, '5550199')
                            if recovered_first:
                                self._r1_singleton(100); self._r1_singleton(250)
                                self.assertEqual(self.store.reply_status('phone', '9'), 'individual')
                            old = self._r1_command(); pending = []
                            self.service.local_job = (lambda w,c: pending.append((w,c))) if timing == 'file' else (lambda w,c: c(w(),None))
                            if timing != 'direct': self.service.send_sms(old)
                            if not recovered_first: self._r1_singleton(100)
                            token = self.store.token('phone', '9')
                            raw = self._r1_observation(path, hazard)
                            if path == 'accepted': self.store.ingest('phone', raw)
                            else:
                                with self.assertRaisesRegex(ValueError, 'serialized size limit'):
                                    self.store.ingest('phone', raw)
                            self.assertEqual(self.store.reply_risks[('phone', '9')], hazard)
                            self.assertNotEqual(token, self.store.token('phone', '9'))
                            for timestamp in (400, 400, 50, 500, 600):
                                self._r1_singleton(timestamp)
                                self.assertEqual(self.store.reply_status('phone', '9'), hazard)
                                self.assertIsNone(self.service.recipient_scope('phone', '9'))
                            if timing == 'direct':
                                with self.assertRaises(ValueError): self.service.send_sms(old)
                            else:
                                for work,done in pending: done(work(),None)
                                self.transport.respond(value=({'isReachable': True, 'isPaired': True},))
                            with self.assertRaises(ValueError): self.service.send_sms(self._r1_command())
                            self.assertFalse(any(c[2] == 'replyToConversation' for c in self.transport.calls))

    def test_ordering_only_recovery_then_replay_never_reuses_old_authorization(self):
        for timing in ('direct', 'file', 'online'):
            with self.subTest(timing=timing):
                self.setUp(); self._r1_singleton(100); first = self._r1_command()
                self._r1_singleton(200, '5550199'); self._r1_singleton(100)
                self.assertEqual(self.store.reply_risks[('phone', '9')], 'ordering')
                self._r1_singleton(400); current = self._r1_command()
                self.assertTrue(self.events[-1]['reply_scope_recovered'])
                with self.assertRaises(ValueError): self.service.send_sms(first)
                pending = []
                self.service.local_job = (lambda w,c: pending.append((w,c))) if timing == 'file' else (lambda w,c: c(w(),None))
                if timing != 'direct': self.service.send_sms(current)
                # Superseded B proof, including equal and regressive conflicts.
                self._r1_singleton(200, '5550199'); self._r1_singleton(400, '5550199')
                self.assertEqual(self.store.reply_ordering_watermarks[('phone', '9')], (400, 1, '1'))
                self.assertEqual(self.store.reply_risks[('phone', '9')], 'ordering')
                if timing == 'direct':
                    with self.assertRaises(ValueError): self.service.send_sms(current)
                else:
                    for work,done in pending: done(work(),None)
                    self.transport.respond(value=({'isReachable': True, 'isPaired': True},))
                with self.assertRaises(ValueError): self.service.send_sms(self._r1_command())
                self.assertFalse(any(c[2] == 'replyToConversation' for c in self.transport.calls))
                self._r1_singleton(500, '5550199')
                self.service.local_job = lambda w,c: c(w(),None)
                self.service.send_sms(self._r1_command())
                self.transport.respond(value=({'isReachable': True, 'isPaired': True},))
                self.assertEqual(self.transport.calls[-1][2], 'replyToConversation')

    def test_sticky_risk_survives_payload_and_conversation_lifecycle(self):
        for hazard in ('group', 'incomplete'):
            for lifecycle in ('messages', 'threads', 'remove', 'reset'):
                with self.subTest(hazard=hazard, lifecycle=lifecycle):
                    self.setUp(); self._r1_singleton(100); self._r1_singleton(200, '5550199'); self._r1_singleton(100)
                    self.store.ingest('phone', self._r1_observation('accepted', hazard))
                    if lifecycle == 'messages':
                        for uid in range(10, 311): self._r1_singleton(50, uid=uid)
                        self.assertNotIn('2', self.store.threads[('phone', '9')].messages)
                    elif lifecycle == 'threads':
                        for thread in range(10, 211): self.store.ingest('phone', wire(thread=thread))
                        self.assertNotIn(('phone', '9'), self.store.threads)
                    elif lifecycle == 'remove': self.store.remove_conversation('phone', '9')
                    else: self.store.reset_device('phone')
                    self._r1_singleton(400)
                    self.assertEqual(self.store.reply_status('phone', '9'), hazard)
                    with self.assertRaises(ValueError): self.service.send_sms(self._r1_command())

    def test_ordering_to_sticky_without_payload_publishes_changed_risk_and_token(self):
        self._r1_singleton(100); self._r1_singleton(200, '5550199'); self._r1_singleton(100)
        before = self.store.token('phone', '9'); self.events.clear()
        with self.assertRaises(ValueError): self.store.ingest('phone', self._r1_observation('record', 'incomplete'))
        self.assertEqual(self.events[-1]['event'], 'reply_scope')
        self.assertEqual(self.events[-1]['reply_status'], 'incomplete')
        self.assertNotIn('reply_risk', self.events[-1])
        self.assertNotEqual(self.events[-1]['conversation_token'], before)
        self._r1_singleton(400)
        self.assertEqual(self.store.reply_risks[('phone', '9')], 'incomplete')

    def test_rejected_singleton_during_ordering_preserves_only_ordering_risk(self):
        self._r1_singleton(100); self._r1_singleton(200, '5550199'); self._r1_singleton(100)
        raw = list(oversized_record([('5550100',)])); raw[3] = 300
        with self.assertRaises(ValueError): self.store.ingest('phone', raw)
        self.assertEqual(self.store.reply_risks[('phone', '9')], 'ordering')
        self._r1_singleton(250)
        self.assertEqual(self.store.reply_status('phone', '9'), 'incomplete')
        self._r1_singleton(400)
        self.assertEqual(self.store.reply_status('phone', '9'), 'individual')

    def test_ordering_ledger_capacity_and_sticky_upgrade_share_one_entry(self):
        store = Store(lambda event: None)
        for thread in range(4096):
            store.ingest('phone', wire(thread=thread))
            store.ingest('phone', wire(thread=thread, addresses=[('5550199',)]))
        self.assertEqual(len(store.reply_risks), 4096)
        self.assertEqual(len(store.reply_ordering_watermarks), 4096)
        self.assertFalse(store.reply_scopes)
        store.ingest('phone', wire(thread=0, addresses=[]))
        store.ingest('phone', wire(thread=1, addresses=[('a',), ('b',)]))
        self.assertEqual(store.reply_risks[('phone', '0')], 'incomplete')
        self.assertEqual(store.reply_risks[('phone', '1')], 'group')
        self.assertFalse(store._device_uncertain('phone'))
        store.ingest('phone', wire(thread=5000))
        self.assertTrue(store._device_uncertain('phone'))
        self.assertEqual(store._evidence_count(), 4096)
        self.assertLessEqual(set(store.reply_ordering_watermarks), set(store.reply_risks))


if __name__ == '__main__': unittest.main()
