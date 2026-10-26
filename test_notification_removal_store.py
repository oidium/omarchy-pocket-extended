import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from notification_removal_store import NotificationRemovalStore, notification_fingerprint
from messaging_service import Service
from test_messaging import FakeTransport


class NotificationRemovalStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'plugin-private' / 'notification-removals-v1.json'

    def tearDown(self):
        self.temp.cleanup()

    def occurrence(self, store, note='1', internal='internal', reply='reply', body='hello'):
        record = {'internal_id': internal, 'reply_id': reply, 'app': 'Messaging', 'title': 'Phone', 'body': body}
        return store.occurrence('device', note, notification_fingerprint(record))

    def test_versioned_private_atomic_state_survives_a_fresh_store(self):
        first = NotificationRemovalStore(self.path)
        occurrence = self.occurrence(first)
        self.assertTrue(occurrence)
        result = first.mark_removed([{'device': 'device', 'id': '1', 'occurrence_id': occurrence}])
        self.assertEqual(result['removed'][0]['occurrence_id'], occurrence)
        second = NotificationRemovalStore(self.path)
        self.assertTrue(second.is_removed('device', '1', occurrence))
        data = json.loads(self.path.read_text())
        self.assertEqual(data['schema'], 1)
        self.assertEqual(len(data['entries']), 1)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.path.parent.stat().st_mode), 0o700)

    def test_active_capacity_is_reclaimed_only_by_authoritative_retirement(self):
        store = NotificationRemovalStore(self.path)
        ids = []
        for i in range(128):
            occ = self.occurrence(store, str(i), body='body '+str(i))
            self.assertTrue(occ)
            ids.append((str(i), occ))
            self.assertEqual(store.mark_removed([{'device':'device','id':str(i),'occurrence_id':occ}])['pending'], 0)
        self.assertEqual(len(store.entries), 128)
        self.assertEqual(self.occurrence(store, 'overflow', body='overflow'), '')
        self.assertTrue(store.retire('device', *ids[0]))
        replacement = self.occurrence(store, 'overflow', body='overflow')
        self.assertTrue(replacement)
        self.assertEqual(len(store.entries), 128)

    def test_bulk_cleanup_over_capacity_fails_atomically_with_capacity_feedback(self):
        store = NotificationRemovalStore(self.path)
        entries = []
        for i in range(128):
            occurrence = self.occurrence(store, str(i), body="body "+str(i))
            entries.append({"device":"device","id":str(i),"occurrence_id":occurrence})
        result = store.mark_removed(entries + [{"device":"device","id":"overflow","occurrence_id":"0"*32}])
        self.assertTrue(result["capacity"])
        self.assertEqual(result["removed"], [])
        self.assertFalse(any(row["removed"] for row in store.entries.values()))

    def test_stale_item_makes_multi_item_cleanup_atomic(self):
        store = NotificationRemovalStore(self.path)
        current = self.occurrence(store, "current")
        result = store.mark_removed([
            {"device":"device","id":"current","occurrence_id":current},
            {"device":"device","id":"stale","occurrence_id":"0"*32},
        ])
        self.assertFalse(result["removed"])
        self.assertIn("changed", result["error"])
        self.assertFalse(store.is_removed("device","current",current))

    def test_reused_id_gets_new_occurrence_after_closure_or_capability_change(self):
        store = NotificationRemovalStore(self.path)
        old = self.occurrence(store)
        store.mark_removed([{'device':'device','id':'1','occurrence_id':old}])
        changed = self.occurrence(store, reply='new-reply')
        self.assertNotEqual(changed, old)
        self.assertFalse(store.is_removed('device', '1', changed))
        store.mark_removed([{'device':'device','id':'1','occurrence_id':changed}])
        self.assertTrue(store.retire('device','1',changed))
        exact_reuse = self.occurrence(store)
        self.assertNotEqual(exact_reuse, changed)
        self.assertFalse(store.is_removed('device','1',exact_reuse))

    def test_empty_action_identity_still_has_stable_nonempty_occurrence(self):
        store = NotificationRemovalStore(self.path)
        first = self.occurrence(store, internal='', reply='')
        second = self.occurrence(store, internal='', reply='')
        self.assertTrue(first)
        self.assertEqual(first, second)
        self.assertTrue(store.mark_removed([{'device':'device','id':'1','occurrence_id':first}])['removed'])
        self.assertTrue(store.is_removed('device','1',second))

    def test_empty_token_updates_do_not_create_a_new_occurrence_from_changed_text(self):
        store = NotificationRemovalStore(self.path)
        first = self.occurrence(store, internal="", reply="", body="old text")
        second = self.occurrence(store, internal="", reply="", body="updated text")
        self.assertEqual(first, second)
        self.assertTrue(store.mark_removed([{"device":"device","id":"1","occurrence_id":first}])["removed"])
        self.assertTrue(store.is_removed("device","1",second))

    def test_fifo_and_malformed_state_fail_closed_without_blocking(self):
        self.path.parent.mkdir(mode=0o700)
        os.mkfifo(self.path)
        started=__import__('time').monotonic()
        fifo=NotificationRemovalStore(self.path)
        elapsed=__import__('time').monotonic()-started
        self.assertLess(elapsed,1.0,"opening a FIFO must not block service startup")
        self.assertTrue(fifo.write_disabled)
        self.assertTrue(fifo.error)
        self.path.unlink()
        self.path.write_text('{ malformed')
        malformed=NotificationRemovalStore(self.path)
        self.assertTrue(malformed.write_disabled)
        self.assertIn('could not be read safely',malformed.error)

    def test_corrupt_or_symlink_state_fails_closed_and_is_not_overwritten(self):
        self.path.parent.mkdir(mode=0o700)
        victim = Path(self.temp.name) / 'victim'
        victim.write_text('do not replace')
        self.path.symlink_to(victim)
        store = NotificationRemovalStore(self.path)
        occurrence = self.occurrence(store)
        result = store.mark_removed([{'device':'device','id':'1','occurrence_id':occurrence}])
        self.assertFalse(result['removed'])
        self.assertTrue(result['error'])
        self.assertEqual(victim.read_text(), 'do not replace')

    def test_local_removal_command_only_persists_and_emits_local_event(self):
        store = NotificationRemovalStore(self.path)
        events=[];transport=FakeTransport();service=Service(transport,events.append,notification_state=store)
        occurrence=self.occurrence(store)
        service.command({'op':'notification_local_remove','request_id':'local-1','entries':[
            {'device':'device','id':'1','occurrence_id':occurrence}]})
        self.assertEqual(transport.calls, [])
        self.assertEqual(events[-1]['event'],'notification_local_remove')
        self.assertTrue(NotificationRemovalStore(self.path).is_removed('device','1',occurrence))
        self.assertFalse(any(e.get('event')=='notification_dismiss' for e in events))


if __name__ == '__main__':
    unittest.main()
