import importlib.util
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from messaging_service import (MAX_DEVICE_EVENT_BYTES, MAX_DEVICE_NAME_BYTES,
                               MAX_DEVICE_PLUGINS, MAX_DEVICE_PLUGIN_ID_BYTES,
                               PROPERTIES, Service, device_path, json_line_size,
                               normalize_device_plugins)
from notification_removal_store import NotificationRemovalStore


class HeldTransport:
    def __init__(self):
        self.calls = []

    def call(self, *args):
        self.calls.append(args)

    def respond(self, index=-1, value=(), error=None):
        self.calls[index][-1](value, error)

    def methods(self, method):
        return [call for call in self.calls if call[2] == method]


class RuntimeRemediationTests(unittest.TestCase):
    def test_device_identifier_contract_is_exact_and_bounded_before_paths(self):
        self.assertEqual(len(device_path('A' * 256)), len('/modules/kdeconnect/devices/') + 256)
        for value in ('A' * 257, 'bad/id', 'name with spaces', 'x\ud800'):
            with self.assertRaises(ValueError):
                device_path(value)

    def test_oversized_device_discovery_list_is_rejected_before_path_construction(self):
        transport=HeldTransport();events=[]
        service=Service(transport,events.append,lambda:0,notification_state=NotificationRemovalStore(persistent=False))
        service.refresh();transport.respond(0,(['phone']*65,))
        self.assertEqual(len(transport.calls),1)
        self.assertEqual(service.devices,{})
        self.assertEqual(events[-1]['event'],'error')
        self.assertIn('too many devices',events[-1]['error'])

    def test_worker_device_discovery_bounds_names_plugins_and_event_frames(self):
        transport = HeldTransport()
        events = []
        service = Service(transport, events.append, lambda: 0,
                          notification_state=NotificationRemovalStore(persistent=False))
        service.refresh()
        transport.respond(0, (['phone'],))
        transport.respond(1, ({'isReachable': True, 'isPaired': True, 'name': 'P' * MAX_DEVICE_NAME_BYTES},))
        initial = events[-1]['device']
        self.assertTrue(initial['name_valid'])
        self.assertEqual(initial['name'], 'P' * MAX_DEVICE_NAME_BYTES)
        plugin_ids=['x'+str(i)+'_'*(120-len(str(i))) for i in range(MAX_DEVICE_PLUGINS-1)]
        transport.respond(2, (['kdeconnect_sms'] + plugin_ids,))
        plugin_event = events[-1]
        self.assertEqual(len(plugin_event['device']['plugins']), MAX_DEVICE_PLUGINS)
        self.assertLessEqual(json_line_size(plugin_event), MAX_DEVICE_EVENT_BYTES)
        self.assertEqual(plugin_event['device']['plugins'][0], 'kdeconnect_sms')
        self.assertEqual(plugin_event['device']['plugins'][1], plugin_ids[0])

    def test_complete_device_event_guard_falls_back_without_serializing_raw_fields(self):
        service=Service(HeldTransport(),lambda event:self.fail("event should be recorded below"),lambda:0,
                        notification_state=NotificationRemovalStore(persistent=False))
        events=[];service.emit=lambda event:events.append(event)
        service.devices['phone']={'id':'phone'}
        service.emit_device({'id':'phone','name':'N'*1048576,'online':True,'plugins':['x'*1048576],
                             'capabilities':'available','generation':1})
        self.assertLessEqual(json_line_size(events[-1]),MAX_DEVICE_EVENT_BYTES)
        self.assertEqual(events[-1]['device']['name'],'Phone')
        self.assertFalse(events[-1]['device']['name_valid'])
        self.assertEqual(events[-1]['device']['plugins'],[])
        self.assertNotIn('N'*1000,json.dumps(events[-1]))

    def test_oversized_or_malformed_discovery_metadata_fails_closed_without_truncating(self):
        for name in ('N' * (MAX_DEVICE_NAME_BYTES + 1), 'N' * (1024 * 1024), 'bad\ud800name'):
            transport = HeldTransport(); events = []
            service = Service(transport, events.append, lambda: 0,
                              notification_state=NotificationRemovalStore(persistent=False))
            service.refresh(); transport.respond(0, (['phone'],))
            transport.respond(1, ({'isReachable': True, 'isPaired': True, 'name': name},))
            self.assertEqual(events[-1]['device']['name'], 'Phone')
            self.assertFalse(events[-1]['device']['name_valid'])
            self.assertLessEqual(json_line_size(events[-1]), MAX_DEVICE_EVENT_BYTES)
            transport.respond(2, (['kdeconnect_sms', 'z' * (MAX_DEVICE_PLUGIN_ID_BYTES + 1)],))
            event = events[-1]
            self.assertEqual(event['device']['plugins'], [])
            self.assertEqual(event['device']['capabilities'], 'unavailable')
            self.assertLessEqual(json_line_size(event), MAX_DEVICE_EVENT_BYTES)

    def test_unrepresentable_device_name_disables_mms_cache_resolution(self):
        transport=HeldTransport();events=[]
        service=Service(transport,events.append,lambda:0,notification_state=NotificationRemovalStore(persistent=False))
        service.devices['phone']={'online':True,'generation':1,'plugins':['kdeconnect_sms'],'name':'Phone','name_valid':False}
        with self.assertRaisesRegex(ValueError,'Phone name is unavailable'):
            service.request_attachment('request','phone','1','1','0','image.jpg')
        self.assertEqual(transport.calls,[])

    def test_plugin_list_size_and_typed_data_fail_closed(self):
        self.assertEqual(normalize_device_plugins(['kdeconnect_sms'], False), (['kdeconnect_sms'], True))
        for value in (['kdeconnect_sms'] * (MAX_DEVICE_PLUGINS + 1), 'kdeconnect_sms',
                      ['kdeconnect_sms', {'nested': 'value'}], ['bad/name']):
            self.assertEqual(normalize_device_plugins(value), ([], False))


class SmokeToolIsolationTests(unittest.TestCase):
    def test_worker_environment_redirects_state_without_mutating_parent(self):
        path = Path(__file__).parent / 'tools' / 'live_readonly_smoke.py'
        spec = importlib.util.spec_from_file_location('live_readonly_smoke_test', path)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        inherited = {'HOME': '/synthetic/home', 'XDG_STATE_HOME': '/synthetic/production-state'}
        isolated = module.isolated_worker_environment('/tmp/pocket-smoke-fixture', inherited)
        self.assertEqual(inherited['XDG_STATE_HOME'], '/synthetic/production-state')
        self.assertEqual(isolated['XDG_STATE_HOME'], '/tmp/pocket-smoke-fixture')
        self.assertEqual(isolated['HOME'], '/synthetic/home')
