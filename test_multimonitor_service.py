"""Offline contract tests for the native shell-wide Pocket service.

These tests do not start Quickshell or a KDE Connect worker.  They exercise the
ownership contract that prevents monitor-local components from creating a
second worker or IPC dispatcher, and a small lifecycle model for the events
that can be driven by monitor hotplug/reload.
"""

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).parent


class ServiceLifecycleModel:
    """Minimal deterministic model of the service/widget ownership boundary."""

    def __init__(self):
        self.service_instances = 0
        self.worker_starts = 0
        self.worker_stops = 0
        self.worker_restarts = 0
        self.commands = []
        self.monitors = set()
        self.shutting_down = False
        self.request_sequence = 0

    def next_request_id(self, prefix):
        self.request_sequence += 1
        return f"{prefix}-{self.request_sequence}"

    def create_service(self):
        if not self.service_instances:
            self.service_instances = 1
            self.worker_starts += 1
        return self

    def add_widget(self, monitor):
        self.create_service()
        self.monitors.add(monitor)
        return self

    def remove_widget(self, monitor):
        self.monitors.discard(monitor)

    def submit(self, command):
        if self.shutting_down:
            return False
        self.commands.append(command)
        return True

    def worker_exited(self):
        if self.shutting_down:
            return
        self.worker_stops += 1
        if self.worker_restarts < 3:
            self.worker_restarts += 1
            self.worker_starts += 1

    def reload(self):
        # Shell reload recreates widgets but retains one keepLoaded service.
        self.monitors.clear()
        self.add_widget("left")
        self.add_widget("right")

    def shutdown(self):
        self.shutting_down = True
        self.monitors.clear()
        if self.service_instances:
            self.worker_stops += 1
            self.service_instances = 0


class NativeMultiMonitorContractTests(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads((ROOT / "manifest.json").read_text())
        self.service = (ROOT / "Service.qml").read_text()
        self.panel = (ROOT / "Panel.qml").read_text()

    def test_manifest_declares_one_shell_service_and_bar_widget(self):
        self.assertEqual(self.manifest["kinds"], ["service", "bar-widget"])
        self.assertTrue(self.manifest["keepLoaded"])
        self.assertEqual(self.manifest["entryPoints"]["service"], "Service.qml")
        self.assertEqual(self.manifest["entryPoints"]["barWidget"], "Panel.qml")

    def test_service_owns_single_worker_and_authoritative_ipc(self):
        self.assertEqual(self.service.count("Process {"), 2)  # worker + snapshot
        self.assertEqual(self.service.count("IpcHandler {"), 1)
        self.assertEqual(self.service.count("command: [\"python3\", service.messagingWorker]"), 1)
        self.assertIn('target: service.pluginId', self.service)
        self.assertIn("if (!service.shuttingDown && service.messagingRestarts < 3)", self.service)
        self.assertIn("function nextRequestId(prefix)", self.service)

    def test_panel_is_monitor_ui_and_uses_scoped_service(self):
        self.assertIn("manageIpc: false", self.panel)
        self.assertIn("bar.shell.serviceFor(moduleName)", self.panel)
        self.assertIn("service.messagingCommand(command)", self.panel)
        self.assertIn('newRequestId("sms")', self.panel)
        self.assertIn('requestIdFactory: root.service ? function()', self.panel)
        self.assertNotIn('"sms-"+(++smsSequence)', self.panel)
        self.assertNotIn("target: root.ipcTarget", self.panel)
        # The production path must not launch the worker from a monitor widget.
        self.assertNotIn("messaging_service.py", self.panel)
        self.assertNotIn("id: messaging", self.panel)
        self.assertNotRegex(self.panel, r"messaging\.running\s*=\s*true")
        self.assertIn("function submitNotificationAction(clientId, draftCommand)", self.service)
        self.assertIn('import "ServiceEpoch.js" as ServiceEpoch', self.service)

    def test_two_monitors_share_one_service_and_one_dispatch(self):
        model = ServiceLifecycleModel()
        left = model.add_widget("left")
        right = model.add_widget("right")
        self.assertIs(left, right)
        self.assertEqual(model.service_instances, 1)
        self.assertEqual(model.worker_starts, 1)
        self.assertEqual(model.monitors, {"left", "right"})
        self.assertTrue(left.submit({"op": "refresh", "request_id": "one"}))
        self.assertEqual(model.commands, [{"op": "refresh", "request_id": "one"}])

    def test_shared_request_ids_keep_monitor_drafts_isolated(self):
        model = ServiceLifecycleModel()
        left_id = model.next_request_id("sms")
        right_id = model.next_request_id("sms")
        self.assertNotEqual(left_id, right_id)
        drafts = {left_id: "submitted draft", right_id: "unsent draft"}
        result_id = left_id
        for request_id in list(drafts):
            if request_id == result_id:
                del drafts[request_id]
        self.assertEqual(drafts, {right_id: "unsent draft"})

    def test_monitor_hotplug_does_not_stop_shared_worker(self):
        model = ServiceLifecycleModel()
        model.add_widget("left")
        model.add_widget("right")
        model.remove_widget("right")
        self.assertEqual(model.worker_starts, 1)
        self.assertEqual(model.worker_stops, 0)
        self.assertEqual(model.monitors, {"left"})
        model.add_widget("right")
        self.assertEqual(model.worker_starts, 1)

    def test_worker_restart_and_shell_reload_are_single_owner_operations(self):
        model = ServiceLifecycleModel()
        model.add_widget("left")
        model.add_widget("right")
        model.worker_exited()
        self.assertEqual(model.worker_restarts, 1)
        self.assertEqual(model.worker_starts, 2)
        model.reload()
        self.assertEqual(model.worker_starts, 2)
        self.assertEqual(model.monitors, {"left", "right"})
        model.shutdown()
        self.assertTrue(model.shutting_down)
        self.assertEqual(model.worker_stops, 2)  # crash + clean shutdown
        before = len(model.commands)
        self.assertFalse(model.submit({"op": "refresh"}))
        self.assertEqual(len(model.commands), before)


if __name__ == "__main__":
    unittest.main()
