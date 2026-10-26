import unittest
from test_messaging import FakeTransport, wire
from messaging_service import Service, DEVICE, device_path


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.events=[];self.bus=FakeTransport();self.s=Service(self.bus,self.events.append)
        self.s.devices['phone']={'online':True,'generation':1,'plugins':['kdeconnect_sms','kdeconnect_notifications']}
        self.s.local_job=lambda work,done:done(work(),None)

    def reply(self,token):
        self.s.command({'op':'sms_reply','device':'phone','thread':'9','conversation_token':token,'recipient_scope':['5550100'],'text':'synthetic','request_id':'r'})

    def test_recreated_thread_cannot_receive_old_draft(self):
        self.s.store.ingest('phone',wire());token=self.s.store.token('phone','9')
        self.s.store.threads.pop(('phone','9'));self.s.store.ingest('phone',wire())
        self.reply(token);self.assertFalse(self.bus.calls)
        self.assertIn('Conversation changed',self.events[-1]['error'])

    def test_replacement_between_validation_and_send_is_blocked(self):
        self.s.store.ingest('phone',wire());self.reply(self.s.store.token('phone','9'))
        self.s.store.threads.pop(('phone','9'));self.s.store.ingest('phone',wire())
        self.bus.respond(value=({'isReachable':True,'isPaired':True},))
        self.assertEqual(len(self.bus.calls),1);self.assertFalse(self.events[-1]['accepted'])

    def test_worker_restart_never_reuses_thread_token(self):
        self.s.store.ingest('phone',wire());other=Service(FakeTransport(),lambda e:None)
        other.store.ingest('phone',wire())
        self.assertNotEqual(self.s.store.token('phone','9'),other.store.token('phone','9'))

    def test_notification_churn_does_not_accumulate_tombstones(self):
        for i in range(1000):
            self.s.read_notification('phone',str(i));self.bus.respond(value=({'text':'test'},))
            self.s.remove_notification('phone',str(i))
        self.assertFalse(self.s.note_versions);self.assertFalse(self.s.note_reads);self.assertFalse(self.s.calls.notes)

    def test_notification_burst_is_bounded_and_coalesced(self):
        for i in range(1000):self.s.read_notification('phone',str(i))
        self.assertEqual(len(self.bus.calls),128);self.assertEqual(len(self.s.note_reads),128)
        for i in range(1000):self.s.read_notification('phone','0')
        self.assertEqual(len(self.bus.calls),128);self.assertEqual(len(self.s.note_dirty),1)
        self.s.owner_changed();self.assertFalse(self.s.note_reads);self.assertFalse(self.s.note_dirty)

    def test_unknown_device_signals_do_not_grow_device_cache(self):
        for i in range(1000):self.s.signal(device_path(str(i)),DEVICE,'reachableChanged',(False,))
        self.assertEqual(len(self.s.devices),1)

    def test_global_history_budget_keeps_per_thread_window(self):
        for thread in range(10):
            for uid in range(300):self.s.store.ingest('phone',wire(uid=uid,thread=thread))
        self.assertEqual(sum(len(c.messages) for c in self.s.store.threads.values()),2000)
        self.assertEqual(len(self.s.store.threads[('phone','9')].messages),300)
        self.assertTrue(any(e['event']=='messages_evicted' for e in self.events))

if __name__=='__main__':unittest.main()
