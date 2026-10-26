import unittest
from test_messaging import FakeTransport
from messaging_service import Service, NOTIFICATIONS, PROPERTIES


class NotificationActionsTests(unittest.TestCase):
    def setUp(self):
        self.events = []; self.now = 0; self.transport = FakeTransport()
        self.service = Service(self.transport, self.events.append, lambda: self.now)
        self.service.devices['phone'] = {'online': True, 'generation': 1, 'plugins': ['kdeconnect_notifications']}
        self.props = {'internalId': 'android-key', 'replyId': 'token', 'dismissable': True}
        self.service.read_notification('phone', '1')
        self.transport.respond(value=(self.props,))
        self.occurrence=self.service.notifications[('phone','1')]['occurrence_id']
        self.epoch=self.service.notification_epoch
        self.transport.calls.clear(); self.events.clear()

    def methods(self, name):
        return [call for call in self.transport.calls if call[2] == name]

    def command(self, op='notification_reply', **extra):
        command = dict(op=op, request_id='test', device='phone', id='1',
                       internal_id='android-key', reply_id='token', text='Hello 👋',
                       occurrence_id=self.occurrence, notification_epoch=self.epoch)
        command.update(extra); self.service.command(command)

    def test_reply_checks_fresh_properties_then_exact_token(self):
        self.command()
        self.assertEqual(self.transport.calls[-1][1:3], (PROPERTIES, 'GetAll'))
        self.transport.respond(value=(self.props,))
        self.assertEqual(self.transport.calls[-1][1:5], (NOTIFICATIONS, 'sendReply', '(ss)', ('token', 'Hello 👋')))
        self.assertEqual(len(self.methods('sendReply')),1)
        self.transport.respond()
        self.assertTrue(self.events[-1]['accepted'])
        self.assertIsNone(self.events[-1]['delivery_confirmed'])


    def test_old_occurrence_or_worker_epoch_is_rejected_before_property_read(self):
        for fields in ({'occurrence_id':'old-occurrence'}, {'notification_epoch':'old-worker'},
                       {'occurrence_id':None}, {'notification_epoch':''}):
            self.transport.calls.clear();self.events.clear()
            self.command(**fields)
            self.assertEqual(self.transport.calls,[])
            self.assertFalse(self.events[-1].get('accepted',False))

    def test_occurrence_reuse_during_pending_validation_never_dispatches(self):
        self.command()
        self.service.notifications[('phone','1')]={**self.service.notifications[('phone','1')],
            'occurrence_id':'new-occurrence'}
        self.transport.respond(value=(self.props,))
        self.assertEqual(self.methods('sendReply'),[])
        self.assertFalse(self.events[-1]['accepted'])

    def test_worker_epoch_replacement_during_validation_never_dispatches(self):
        self.command();self.service.notification_epoch='replacement-worker'
        self.transport.respond(value=(self.props,))
        self.assertEqual(self.methods('sendReply'),[])
        self.assertFalse(self.events[-1]['accepted'])

    def test_property_read_failure_never_dispatches_and_dismiss_is_occurrence_bound(self):
        self.command();self.transport.respond(error='property unavailable')
        self.assertEqual(self.methods('sendReply'),[])
        self.transport.calls.clear();self.events.clear()
        self.command('notification_dismiss',occurrence_id='old-occurrence')
        self.assertEqual(self.transport.calls,[])
        self.command('notification_dismiss')
        self.transport.respond(value=(self.props,))
        self.assertEqual(len(self.methods('dismiss')),1)
        self.transport.respond()
        self.assertTrue(self.events[-1]['accepted'])

    def test_stale_token_never_sends(self):
        self.command(); self.transport.respond(value=({**self.props, 'replyId': 'replacement'},))
        self.assertEqual(len(self.transport.calls), 1)
        self.assertEqual(self.events[-1]['error'], 'Reply no longer available')

    def test_replaced_identity_even_same_token_never_sends(self):
        self.command(); self.transport.respond(value=({**self.props, 'internalId': 'different'},))
        self.assertEqual(len(self.transport.calls), 1)
        self.assertFalse(self.events[-1]['accepted'])

    def test_disappeared_during_validation_never_sends(self):
        self.command(); self.service.remove_notification('phone', '1')
        self.transport.respond(value=(self.props,))
        self.assertEqual(len(self.transport.calls), 1)
        self.assertEqual(self.events[-1]['error'], 'Reply no longer available')

    def test_capability_missing_from_cached_card_never_calls_bus(self):
        self.command(reply_id='old')
        self.assertFalse(self.transport.calls)
        self.assertEqual(self.events[-1]['error'], 'Reply no longer available')

    def test_ordinary_update_during_validation_conservatively_stops_send(self):
        self.command(); self.service.read_notification('phone', '1')
        self.transport.respond(0, (self.props,))
        self.assertFalse(any(c[2] == 'sendReply' for c in self.transport.calls))

    def test_dismiss_requires_fresh_dismissable(self):
        self.command('notification_dismiss')
        self.transport.respond(value=({**self.props, 'dismissable': False},))
        self.assertEqual(len(self.transport.calls), 1)
        self.assertEqual(self.events[-1]['error'], 'Dismiss no longer available')

    def test_dismiss_uses_notification_object_only(self):
        self.command('notification_dismiss'); self.transport.respond(value=(self.props,))
        self.assertTrue(self.transport.calls[-1][0].endswith('/notifications/1'))
        self.assertEqual(self.transport.calls[-1][2], 'dismiss')
        self.transport.respond(); self.assertTrue(self.events[-1]['accepted'])

    def test_bus_error_after_submit_is_uncertain_and_never_retried(self):
        self.command(); self.transport.respond(value=(self.props,))
        self.transport.respond(error='timeout')
        self.now = 100; self.service.tick()
        self.assertEqual(len(self.transport.calls), 2)
        self.assertTrue(self.events[-1]['uncertain'])
        self.assertIn('Check the phone', self.events[-1]['error'])

    def test_duplicate_click_rejected(self):
        self.command(); self.command(request_id='second')
        self.assertEqual(len(self.transport.calls), 1)
        self.assertEqual(self.events[-1]['event'], 'error')

    def test_empty_reply_offline_and_missing_capability_never_send(self):
        self.command(text='  ')
        self.service.disconnect('phone'); self.command()
        self.assertFalse(self.transport.calls)

    def test_owner_change_cancels_inflight_validation(self):
        self.command(); self.service.owner_changed(); self.transport.respond(value=(self.props,))
        self.assertEqual(len(self.transport.calls), 1)
        self.assertFalse(self.service.notification_actions)

    def test_deadline_before_send_cannot_later_send(self):
        self.command(); self.now = 13; self.service.tick(); self.transport.respond(value=(self.props,))
        self.assertEqual(len(self.transport.calls), 1)
        self.assertFalse(self.service.notification_actions)


if __name__ == '__main__': unittest.main()
