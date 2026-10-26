import unittest
from messaging_service import Service, device_path, PROPERTIES
from media_remote import IFACE
from media_remote import normalize_media, MAX_MEDIA_EVENT_BYTES
from messaging import json_line_size
from test_messaging import FakeTransport


class RemoteMediaTests(unittest.TestCase):
    def setUp(self):
        self.events=[];self.transport=FakeTransport()
        self.worker=Service(self.transport,self.events.append)
        self.worker.devices['phone']=dict(online=True,generation=1,plugins=['kdeconnect_mprisremote'])

    def update(self, volume=25, player='Music'):
        self.worker.signal(device_path('phone')+'/mprisremote',IFACE,'propertiesChanged',())
        self.transport.respond(value=({'player':player,'volume':volume},))
        return self.events[-1]

    def command(self, value=70):
        self.worker.command(dict(op='media_volume',device='phone',request_id='v',
                                 token=self.worker.media.states['phone']['token'],value=value))

    def test_phone_signals_refresh_and_coalesce_without_writes(self):
        first=self.update();second=self.update(80)
        self.assertEqual(second['media']['volume'],80)
        self.assertEqual(first['token'],second['token'])
        self.assertGreater(second['revision'],first['revision'])
        self.worker.signal(device_path('phone')+'/mprisremote',PROPERTIES,'PropertiesChanged',(IFACE,{},[]))
        index=len(self.transport.calls)-1
        for _ in range(10):self.worker.media.refresh('phone')
        self.assertEqual(len(self.transport.calls),index+1)
        self.transport.respond(index,({'player':'Music','volume':35},))
        self.transport.respond(value=({'player':'Music','volume':45},))
        self.assertEqual(self.events[-1]['media']['volume'],45)
        self.assertTrue(all(c[2]=='GetAll' for c in self.transport.calls))

    def test_write_api_binding_and_acceptance_do_not_fabricate_volume(self):
        self.update();self.command()
        self.transport.respond(value=({'player':'Music','volume':25},))
        call=self.transport.calls[-1]
        self.assertEqual(call[1:4],(PROPERTIES,'Set','(ssv)'))
        self.assertEqual(call[4][:2],(IFACE,'volume'));self.assertEqual(call[4][2].unpack(),70)
        self.transport.respond()
        self.assertEqual(self.events[-1]['event'],'volume_result');self.assertTrue(self.events[-1]['accepted'])
        self.assertEqual(self.worker.media.states['phone']['media']['volume'],25)
        self.transport.respond(value=({'player':'Music','volume':66},))
        self.assertEqual(self.events[-1]['media']['volume'],66)

    def test_player_change_disconnect_and_old_completions_never_retarget(self):
        old=self.update();self.command();self.transport.respond(value=({'player':'Replacement'},))
        self.assertFalse(any(c[2]=='Set' for c in self.transport.calls))
        self.transport.respond(value=({'player':'Replacement','volume':10},))
        self.assertNotEqual(self.events[-1]['token'],old['token'])
        self.worker.media.refresh('phone');index=len(self.transport.calls)-1
        self.worker.disconnect('phone');self.transport.respond(index,({'player':'old','volume':100},))
        self.assertNotIn('phone',self.worker.media.states)

    def test_failure_no_retry_and_daemon_replacement(self):
        self.update();self.command();self.transport.respond(error='read failed')
        self.assertFalse(next(e for e in self.events if e['event']=='volume_result')['accepted'])
        self.assertFalse(any(c[2]=='Set' for c in self.transport.calls))
        self.worker.owner_changed();self.assertFalse(self.worker.media.states)
        self.transport.respond(value=({'player':'Music','volume':99},))
        self.assertFalse(self.worker.media.states)

    def test_media_whitelist_bounds_text_and_preserves_only_exact_action_ids(self):
        data = normalize_media({'player': 'p' * 257, 'playerList': ['ok', 'x' * 257],
                                'title': '🎵' * 10000, 'artist': 'A' * 10000,
                                'album': 'B' * 10000, 'unexpected': 'private' * 10000,
                                'volume': True, 'position': -1, 'isPlaying': 'yes'})
        self.assertEqual(data['player'], '')
        self.assertEqual(data['playerList'], [])
        self.assertLessEqual(len(data['title'].encode('utf-8')), 512)
        self.assertLessEqual(len(data['artist'].encode('utf-8')), 512)
        self.assertNotIn('unexpected', data)
        self.assertNotIn('volume', data)
        self.assertNotIn('position', data)
        self.assertNotIn('isPlaying', data)

    def test_media_serialized_event_and_framing_are_bounded(self):
        event = self.update()
        self.assertLessEqual(json_line_size(event), MAX_MEDIA_EVENT_BYTES)
        self.assertEqual(json_line_size({'event':'x', 'value':'a' * (MAX_MEDIA_EVENT_BYTES - json_line_size({'event':'x','value':''}))}), MAX_MEDIA_EVENT_BYTES)

    def test_oversized_player_action_is_disabled_without_identifier_truncation(self):
        event = self.update(player='P' * 257)
        self.assertEqual(event['media']['player'], '')
        self.worker.command(dict(op='media_volume', device='phone', request_id='v', token=event['token'], value=50))
        self.assertFalse(any(call[2] == 'Set' for call in self.transport.calls))
