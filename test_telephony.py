import unittest
from telephony import CallEvents, number_key
from messaging_service import Service, DEVICE, device_path
from test_messaging import FakeTransport
from telephony import MAX_CALL_EVENT_BYTES
from messaging import json_line_size


class TelephonyTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.events = []
        self.calls = CallEvents(self.events.append, lambda: self.now, lambda: 1700000000)

    def incoming(self, number='+1 555 0100', name='Casey Example'):
        self.calls.receive('phone', 'callReceived', number, name)
        return list(self.calls.records.values())[-1]

    def test_incoming_event_never_claims_current_state_or_controls(self):
        r = self.incoming()
        self.assertEqual(r['kind'], 'incoming_event')
        self.assertIsNone(r['current_call_state'])
        self.assertEqual(r['authority'], 'event_only')
        self.assertFalse(any(r['capabilities'].values()))
        self.assertEqual(r['observed_at'], 1700000000000)
        self.assertIsNone(r['avatar'])

    def test_missed_replaces_same_known_incoming_as_distinct_event(self):
        self.incoming()
        self.calls.receive('phone', 'missedCall', '+15550100', 'Casey Example')
        self.assertEqual(len(self.calls.records), 1)
        self.assertEqual(next(iter(self.calls.records.values()))['kind'], 'missed_event')

    def test_local_expiration_is_not_an_ended_event(self):
        self.incoming(); self.now = 21; self.calls.expire()
        self.assertEqual(self.events[-1], {'event': 'call_events', 'calls': []})

    def test_missed_expiration(self):
        self.calls.receive('phone', 'missedCall', '5550100', '')
        self.now = 21; self.calls.expire(); self.assertEqual(len(self.calls.records), 1)
        self.now = 301; self.calls.expire(); self.assertFalse(self.calls.records)

    def test_unknown_callers_are_not_matched_or_combined(self):
        r = self.incoming('unknown number', 'unknown number')
        self.assertEqual(r['name'], 'Unknown caller'); self.assertEqual(r['number'], '')
        self.incoming('', '')
        self.assertEqual(len(self.calls.records), 2)
        self.assertIsNone(number_key('Private'))

    def test_contact_matching_exact_unique_only(self):
        r = self.incoming('+15550100', '+15550100')
        contacts = [{'name': 'Casey Example', 'numbers': [{'number': '+1 (555) 0100'}]}]
        self.calls.resolve_contacts('phone', contacts)
        self.assertEqual(r['name'], 'Casey Example'); self.assertEqual(r['name_source'], 'contacts')
        self.calls.resolve_contacts('phone', contacts + [{'name': 'Other', 'numbers': [{'number': '+15550100'}]}])
        self.assertEqual(r['name'], '+15550100')

    def test_event_name_wins_and_suffix_match_is_rejected(self):
        r = self.incoming()
        self.calls.resolve_contacts('phone', [{'name': 'Other', 'numbers': [{'number': '+15550100'}]}])
        self.assertEqual(r['name'], 'Casey Example')
        r2 = self.incoming('5550101', '')
        self.calls.resolve_contacts('phone', [{'name': 'Wrong', 'numbers': [{'number': '+15550101'}]}])
        self.assertEqual(r2['name_source'], 'number')

    def test_repeated_events_do_not_extend_incoming_lifetime(self):
        self.incoming()
        for now in (4, 8, 12, 16): self.now = now; self.incoming()
        self.assertEqual(len(self.calls.records), 1)
        self.assertEqual(next(iter(self.calls.records.values()))['repeat_count'], 5)
        self.now = 21; self.calls.expire(); self.assertFalse(self.calls.records)

    def test_unsupported_states_ignored(self):
        for event in ('ringing', 'talking', 'ended', 'declined', '', 'sms'):
            self.assertFalse(self.calls.receive('phone', event, '5550100', 'Casey Example'))
        self.assertFalse(self.events)

    def test_ambiguous_duplicate_preserves_generic_and_defers_call_card(self):
        r = self.incoming()
        n = {'device': 'phone', 'id': 'n', 'internal_id': 'android', 'title': 'Casey Example', 'body': 'Incoming call'}
        self.calls.notification(n)
        self.assertEqual(r['presentation'], 'generic')
        self.assertEqual(r['correlation'], 'ambiguous')
        self.assertEqual(set(self.calls.notes[('phone', 'n')][0]), {'device', 'id', 'internal_id', 'title', 'body'})
        self.assertEqual(self.calls.notes[('phone', 'n')][0]['id'], 'n')
        self.calls.remove_notification('phone', 'n')
        self.assertEqual(r['presentation'], 'dedicated')
        self.assertIsNone(r['current_call_state'])

    def test_name_only_unrelated_device_or_old_notification_does_not_correlate(self):
        r = self.incoming()
        self.calls.notification({'device': 'phone', 'id': 'a', 'title': 'Casey Example', 'body': 'Lunch today?'})
        self.calls.notification({'device': 'other', 'id': 'b', 'title': 'Casey Example', 'body': 'Incoming call'})
        self.now = 40
        self.calls.notification({'device': 'phone', 'id': 'c', 'title': 'Casey Example', 'body': 'Incoming call'})
        self.assertEqual(r['presentation'], 'dedicated')

    def test_number_correlation_preserves_information_and_does_not_match_suffix(self):
        r = self.incoming()
        self.calls.notification({'device': 'phone', 'id': 'a', 'title': 'Incoming call', 'body': '5550100'})
        self.assertEqual(r['presentation'], 'dedicated')
        self.calls.notification({'device': 'phone', 'id': 'b', 'title': 'Incoming call', 'body': '+1 (555) 0100'})
        self.assertEqual(r['presentation'], 'generic')

    def pixel_note(self, **changes):
        note = {'device': 'phone', 'id': 'pixel', 'app': 'Phone',
                'internal_id': '0|com.android.dialer|1|MissedCall_content://call_log/calls/987?allow_voicemails=true|10042',
                'title': 'Missed call', 'body': 'Riley Example', 'dismissable': True}
        note.update(changes)
        return note

    def missed(self, number='+1 202-555-0149', name='Riley Example'):
        self.calls.receive('phone', 'missedCall', number, name)
        return list(self.calls.records.values())[-1]

    def test_pixel_live_shape_both_orders_and_localized_title(self):
        for first in (True, False):
            for title in ('Missed call', 'Appel manqué', '不在着信'):
                with self.subTest(first=first, title=title):
                    self.setUp()
                    note = self.pixel_note(title=title)
                    if first: self.calls.notification(note)
                    record = self.missed()
                    if not first: self.calls.notification(note)
                    self.assertEqual(record['correlation'], 'ambiguous')
                    self.assertEqual(record['presentation'], 'generic')
                    self.assertEqual(record['notification_ids'], ['pixel'])
                    self.assertEqual(self.calls.notes[('phone', 'pixel')][0]['internal_id'], note['internal_id'])
                    self.assertNotIn('dismissable', self.calls.notes[('phone', 'pixel')][0])
                    self.assertEqual(record['_expires'], 300)
                    self.assertIsNone(record['current_call_state'])
                    self.assertFalse(any(record['capabilities'].values()))

    def test_pixel_wrong_source_tag_identity_and_extra_text(self):
        original = self.pixel_note()['internal_id']
        changes = [
            {'internal_id': original.replace('com.android.dialer', 'com.example.chat')},
            {'internal_id': original.replace('MissedCall_', 'Other_')},
            {'internal_id': original + '|extra'},
            {'internal_id': original.replace('/987?', '/987/extra?')},
            {'internal_id': original.replace('call_log', 'other')},
            {'internal_id': None}, {'internal_id': 'com.android.dialer MissedCall_'},
            {'device': 'other'}, {'body': 'Other Person'},
            {'body': 'Riley Example called'}, {'body': 'Hello Riley Example'},
        ]
        for change in changes:
            with self.subTest(change=change):
                self.setUp(); record = self.missed()
                self.calls.notification(self.pixel_note(**change))
                self.assertEqual(record['correlation'], 'none')

    def test_pixel_window_and_full_name_normalization(self):
        record = self.missed()
        self.now = 30
        self.calls.notification(self.pixel_note(body='  RILEY   Example\n'))
        self.assertEqual(record['correlation'], 'ambiguous')
        self.calls.remove_notification('phone', 'pixel')
        self.now = 30.01
        self.calls.notification(self.pixel_note())
        self.assertEqual(record['correlation'], 'none')

    def test_pixel_requires_explicit_missed_known_caller(self):
        for number, name in (('', 'Riley Example'), ('withheld', 'Riley Example'),
                             ('+1 202-555-0149', ''), ('+1 202-555-0149', '+1 202-555-0149')):
            with self.subTest(number=number, name=name):
                self.setUp(); record = self.missed(number, name)
                self.calls.notification(self.pixel_note())
                self.assertEqual(record['correlation'], 'none')
        self.setUp(); record = self.incoming('+1 202-555-0149', 'Riley Example')
        self.calls.notification(self.pixel_note())
        self.assertEqual(record['correlation'], 'none')

    def test_pixel_unique_contact_fallback_and_ambiguous_contacts(self):
        record = self.missed(name='')
        self.calls.notification(self.pixel_note())
        contact = {'name': 'Riley Example', 'numbers': [{'number': '+12025550149'}]}
        self.calls.resolve_contacts('phone', [contact])
        self.assertEqual(record['name_source'], 'contacts')
        self.assertEqual(record['correlation'], 'ambiguous')
        self.calls.resolve_contacts('phone', [contact, dict(contact)])
        self.assertEqual(record['name_source'], 'number')
        self.assertEqual(record['correlation'], 'none')

    def test_pixel_multiple_candidates_removal_preserves_expiry(self):
        record = self.missed()
        self.calls.notification(self.pixel_note())
        self.calls.notification(self.pixel_note(id='second'))
        self.assertEqual(record['notification_ids'], ['pixel', 'second'])
        self.calls.remove_notification('phone', 'pixel')
        self.assertEqual(record['presentation'], 'generic')
        self.calls.remove_notification('phone', 'second')
        self.assertEqual(record['presentation'], 'dedicated')
        self.assertEqual(record['_expires'], 300)
        self.now = 301; self.calls.expire()
        self.assertFalse(self.calls.records)

    def test_pixel_worker_correlation_issues_zero_mutations(self):
        transport = FakeTransport()
        worker = Service(transport, self.events.append, lambda: self.now)
        worker.devices['phone'] = {'online': True, 'generation': 1}
        worker.local_job = lambda job, done: done({'contacts': [], 'available': False}, None)
        worker.calls.notification(self.pixel_note())
        worker.signal(device_path('phone') + '/telephony', DEVICE + '.telephony',
                      'callReceived', ('missedCall', '+1 202-555-0149', 'Riley Example'))
        self.assertEqual(next(iter(worker.calls.records.values()))['presentation'], 'generic')
        self.assertFalse(transport.calls)

    def test_worker_routes_signal_and_reconnect_clears_without_controls(self):
        transport = FakeTransport()
        worker = Service(transport, self.events.append, lambda: self.now)
        worker.devices['phone'] = {'online': True, 'generation': 1}
        worker.local_job = lambda job, done: done({'contacts': [], 'available': False}, None)
        worker.signal(device_path('phone') + '/telephony', DEVICE + '.telephony', 'callReceived', ('callReceived', '5550100', 'Casey Example'))
        self.assertEqual(len(worker.calls.records), 1)
        worker.disconnect('phone')
        self.assertFalse(worker.calls.records)
        self.assertFalse(transport.calls)  # No mute, dismiss, media or packet actions.

    def test_worker_owner_change_cleans_all_devices(self):
        worker = Service(FakeTransport(), self.events.append, lambda: self.now)
        worker.devices['phone'] = {'online': True}
        worker.calls.receive('phone', 'missedCall', '5550100', 'Casey Example')
        worker.owner_changed()
        self.assertFalse(worker.calls.records)

    def test_oversized_call_identifiers_and_display_data_are_bounded(self):
        oversized_number = '5550100' + ('9' * 1000)
        self.calls.receive('phone', 'missedCall', oversized_number, 'Caller' * 1000)
        record = next(iter(self.calls.records.values()))
        self.assertEqual(record['number_key'], None)
        self.assertEqual(record['number'], '')
        self.assertLessEqual(len(record['raw_number'].encode('utf-8')), 128)
        self.assertLessEqual(len(record['name'].encode('utf-8')), 256)
        event = self.events[-1]
        self.assertLessEqual(json_line_size(event), MAX_CALL_EVENT_BYTES)

    def test_oversized_notification_identifiers_are_not_truncated_for_correlation(self):
        self.calls.notification({'device': 'phone', 'id': 'i' * 257, 'internal_id': 'x',
                                 'title': 'Missed call', 'body': 'Riley Example'})
        self.assertFalse(self.calls.notes)

    def test_call_event_framing_boundary_is_exact(self):
        import json
        event = {'event': 'call_events', 'calls': []}
        base = json_line_size(event)
        event['calls'] = ['a' * (MAX_CALL_EVENT_BYTES - base - 2)]
        self.assertEqual(json_line_size(event), MAX_CALL_EVENT_BYTES)
        self.assertEqual(json_line_size(event), len((json.dumps(event, ensure_ascii=False) + '\n').encode('utf-8')))

    def test_call_retention_prunes_to_complete_framed_event_budget(self):
        for _ in range(64):
            self.calls.receive('phone', 'missedCall', '', '\x01' * 256)
        event = self.events[-1]
        self.assertLessEqual(json_line_size(event), MAX_CALL_EVENT_BYTES)
        self.assertLess(len(event['calls']), 64)
        self.assertEqual(len(self.calls.records), len(event['calls']))


if __name__ == '__main__': unittest.main()
