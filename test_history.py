import unittest
from test_messaging import FakeTransport, wire
from messaging_service import Service, CONVERSATIONS, device_path


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.transport = FakeTransport()
        self.service = Service(self.transport, self.events.append, lambda: 0)
        self.service.devices['phone'] = {'online': True, 'generation': 1, 'plugins': ['kdeconnect_sms']}
        self.service.local_job = lambda work, done: done(work(), None)

    def test_enumeration_and_open_use_existing_api(self):
        self.service.refresh_threads('phone')
        self.transport.respond(0, ([wire(), wire(thread=10)],))
        self.assertEqual(len(self.service.store.threads), 2)
        self.service.command({'op': 'history', 'device': 'phone', 'thread': '9', 'request_id': 'page'})
        self.assertEqual(self.transport.calls[-1][2:5], ('requestConversation', '(xii)', (9, 0, 25)))

    def test_reply_targets_thread_not_manual_recipient(self):
        self.service.store.ingest('phone', wire(thread=2**60))
        self.service.command({'op': 'sms_reply', 'conversation_token': self.service.store.token('phone', str(2**60)), 'recipient_scope': ['5550100'], 'device': 'phone', 'thread': str(2**60), 'recipient': 'WRONG', 'text': 'Test 👋', 'files': [], 'request_id': 'reply'})
        self.transport.respond(value=({'isReachable': True, 'isPaired': True},))
        call = self.transport.calls[-1]
        self.assertEqual(call[2:5], ('replyToConversation', '(xsav)', (2**60, 'Test 👋', [])))
        self.transport.respond(error='failed')
        self.assertFalse(self.events[-1]['accepted'])
        self.assertNotIn('sendWithoutConversation', [c[2] for c in self.transport.calls])

    def test_removed_or_stale_conversation_cannot_fallback(self):
        self.service.command({'op': 'sms_reply', 'device': 'phone', 'thread': '9', 'text': 'test'})
        self.assertFalse(self.transport.calls)
        self.service.store.ingest('phone', wire())
        self.service.command({'op': 'sms_reply', 'conversation_token': self.service.store.token('phone', '9'), 'recipient_scope': ['5550100'], 'device': 'phone', 'thread': '9', 'text': 'test'})
        self.service.signal(device_path('phone'), CONVERSATIONS, 'conversationRemoved', (9,))
        self.transport.respond(value=({'isReachable': True, 'isPaired': True},))
        self.assertNotIn('replyToConversation', [c[2] for c in self.transport.calls])

    def test_generation_change_clears_history_and_ignores_late_heads(self):
        self.service.store.ingest('phone', wire())
        self.service.refresh_threads('phone')
        self.service.owner_changed()
        self.transport.respond(0, ([wire(uid=2)],))
        self.assertFalse(self.service.store.conversation('phone', '9').messages)

    def test_bounds_live_during_history_and_overlaps(self):
        store = self.service.store
        page = store.begin_page('p', 'phone', '9', 25)
        for uid in range(1000):
            store.ingest('phone', wire(uid=uid), True)
        self.assertLessEqual(len(page.seen), 27)
        self.assertEqual(len(store.conversation('phone', '9').messages), store.MAX_MESSAGES)
        store.finish_page(('phone', '9'), 'partial')
        self.assertEqual(store.conversation('phone', '9').next_offset, 23)
        for thread in range(300): store.ingest('phone', wire(thread=thread))
        self.assertEqual(len(store.threads), store.MAX_THREADS)

    def test_multiple_addresses_and_all_android_states(self):
        for kind in range(7):
            data = list(wire(uid=kind, kind=kind)); data[2] = [('5550100',), ('5550198',)]
            self.service.store.ingest('phone', data)
        messages = self.service.store.conversation('phone', '9').messages
        self.assertEqual(messages['6'].state, 'queued')
        self.assertEqual(messages['2'].direction, 'outgoing')
        self.assertEqual(messages['1'].direction, 'incoming')
        self.assertEqual(messages['1'].addresses, ['5550100', '5550198'])

    def test_ordinary_refresh_keeps_connection_generation(self):
        self.service.refresh()
        self.transport.respond(value=(['phone'],))
        self.transport.respond(value=({'isReachable': True, 'isPaired': True},))
        self.assertEqual(self.service.devices['phone']['generation'], 1)

    def test_concurrent_pages_are_bounded(self):
        for thread in range(4): self.service.store.begin_page(str(thread), 'phone', str(thread))
        with self.assertRaises(ValueError): self.service.store.begin_page('extra', 'phone', '5')


if __name__ == '__main__': unittest.main()
