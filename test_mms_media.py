import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import mms_media
from messaging_service import Service, Gio
from test_messaging import FakeTransport, wire


class MediaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, {'XDG_CACHE_HOME': self.temp.name})
        self.env.start(); self.addCleanup(self.env.stop)
        self.cache = Path(self.temp.name) / 'kdeconnect.daemon' / 'Phone'
        self.cache.mkdir(parents=True)
        self.events = []; self.now = 0
        self.transport = FakeTransport()
        self.s = Service(self.transport, self.events.append, lambda: self.now)
        self.s.devices['phone'] = {'online': True, 'generation': 1, 'name': 'Phone', 'plugins': ['kdeconnect_sms']}
        self.add()

    def add(self, uid=1, thread=9, part=7, name='photo'):
        self.s.store.ingest('phone', wire(uid=uid, thread=thread, attachments=[(part, 'image/jpeg', '', name)]))

    def request(self, request='a', uid='1', thread='9', part='7', name='photo'):
        self.s.request_attachment(request, 'phone', thread, uid, part, name)

    def finish(self, name='photo'):
        path = self.cache / name; path.write_bytes(b'synthetic fixture')
        self.s.attachment_received('phone', str(path), name)
        return path

    def command(self):
        return {'op': 'attachment_open', 'request_id': 'open', 'device': 'phone', 'thread': '9', 'message_id': '1', 'part_id': '7', 'identifier': 'photo'}

    def test_completion_identity_and_no_automatic_open(self):
        self.request()
        with patch.object(Gio.AppInfo, 'launch_default_for_uri_async') as launch:
            self.finish(); launch.assert_not_called()
        event = self.events[-1]
        self.assertEqual((event['thread'], event['message_id'], event['part_id']), ('9', '1', '7'))
        self.assertEqual(self.transport.calls[-1][2:5], ('requestAttachmentFile', '(xs)', (7, 'photo')))
        count = len(self.events); self.finish(); self.assertEqual(len(self.events), count)

    def test_open_is_explicit_revalidated_default_application(self):
        self.request(); path = self.finish()
        with patch.object(Gio.AppInfo, 'launch_default_for_uri_async') as launch:
            self.s.open_attachment(self.command())
            self.assertEqual(launch.call_args.args[0], path.as_uri())
        path.unlink()
        with patch.object(Gio.AppInfo, 'launch_default_for_uri_async') as launch:
            self.s.command(self.command()); launch.assert_not_called()
        self.assertEqual(self.events[-1]['event'], 'error')

    def test_replaced_file_rejected_on_open(self):
        self.request(); path = self.finish(); path.write_bytes(b'changed file')
        with self.assertRaises(ValueError): self.s.open_attachment(self.command())

    def test_multiple_attachments_out_of_order(self):
        self.s.store.ingest('phone', wire(attachments=[(7, 'image/jpeg', '', 'photo'), (8, 'audio/ogg', '', 'sound')]))
        self.request(); self.request('b', part='8', name='sound')
        self.finish('sound'); self.finish('photo')
        self.assertEqual([e['request_id'] for e in self.events if e['event'] == 'attachment_ready'], ['b', 'a'])

    def test_same_filename_other_thread_or_message_rejected(self):
        for uid, thread in [(2, 9), (1, 10)]:
            self.add(uid=uid, thread=thread)
            with self.assertRaises(ValueError): self.request()
        self.assertFalse(self.transport.calls)

    def test_collision_arriving_during_download_rejected(self):
        self.request(); self.add(uid=2); self.finish()
        self.assertEqual(self.events[-1]['event'], 'error'); self.assertFalse(self.s.downloads)

    def test_filename_cannot_be_rebound_after_timeout(self):
        self.request(); self.now=31; self.s.tick(); self.now=62; self.s.tick()
        self.s.store.threads.clear(); self.add(uid=2, part=8)
        with self.assertRaises(ValueError): self.request(uid='2', part='8')

    def test_stale_removed_message_and_thread(self):
        self.request(); self.s.store.threads.clear(); self.finish()
        self.assertFalse(self.s.downloads); self.assertEqual(self.events[-1]['event'], 'error')

    def test_stale_descriptor_is_not_retried(self):
        self.request(); self.s.store.threads.clear(); self.now=31; self.s.tick()
        self.assertEqual(len(self.transport.calls), 1)
        self.assertFalse(self.s.attachments)

    def test_disconnect_and_daemon_replacement_ignore_completion(self):
        self.request(); self.s.disconnect('phone'); count=len(self.events); self.finish()
        self.assertEqual(len(self.events), count); self.assertFalse(self.s.downloads)
        self.s.devices['phone']['online']=True; self.add(); self.request('b'); self.s.owner_changed()
        count=len(self.events); self.finish(); self.assertEqual(len(self.events), count)

    def test_path_validation(self):
        outside=Path(self.temp.name)/'outside'; outside.write_text('fixture')
        link=self.cache/'photo'; link.symlink_to(outside)
        for path in [str(outside), str(link), 'photo', 'file:///etc/passwd', str(self.cache/'missing')]:
            with self.assertRaises(ValueError): mms_media.local_file(path, 'photo', 'Phone')
        link.unlink(); link.mkdir()
        with self.assertRaises(ValueError): mms_media.local_file(str(link), 'photo', 'Phone')

    def test_malformed_descriptors(self):
        for name in ['', '..', '../photo', '/photo', 'x\x00y']:
            with self.assertRaises(ValueError): self.request(name=name)
        with self.assertRaises(ValueError): self.request(part='-1')
        self.assertFalse(self.transport.calls)
        self.s.store.ingest('phone', wire(attachments=[None, (), ('bad', None, {}, '')]))
        message = self.s.store.threads[('phone', '9')].messages['1']
        self.assertEqual(message.body, 'Hi 👋')
        self.assertTrue(all(a.part_id == '' for a in message.attachments))

    def test_same_named_devices_rejected(self):
        self.s.devices['other']={'name':'Phone'}
        with self.assertRaises(ValueError): self.request()

    def test_failure_clears_pending(self):
        self.request(); self.transport.respond(error='Unavailable')
        self.assertFalse(self.s.attachments); self.assertEqual(self.events[-1]['event'], 'error')

    def test_completion_after_unrelated_thread_selected_still_correct(self):
        self.request(); self.add(uid=2, thread=10, name='other')
        self.finish()
        self.assertEqual(self.events[-1]['thread'], '9')

    def test_default_app_result_is_only_open_not_delivery(self):
        self.request(); self.finish()
        with patch.object(Gio.AppInfo, 'launch_default_for_uri_async') as launch, patch.object(Gio.AppInfo, 'launch_default_for_uri_finish', return_value=True):
            self.s.open_attachment(self.command())
            launch.call_args.args[3](None, None, None)
        self.assertEqual(self.events[-1], {'event':'attachment_opened', 'request_id':'open'})

if __name__ == '__main__': unittest.main()
