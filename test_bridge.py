import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import bridge


class FakeBridge(bridge.Bridge):
    def __init__(self, root=None, online=True, mount_ok=True):
        self.root = root
        self.online = online
        self.mount_ok = mount_ok
        self.calls = []

    def props(self, path, interface):
        if interface == bridge.IFACE:
            return {"isPaired": True, "isReachable": self.online}
        return {"playerList": ["Music"]}

    def call(self, path, interface, method, signature=None, args=(), timeout=3000):
        self.calls.append((method, args))
        if method == "GetAll":
            return (self.props(path, args[0]),)
        return {"mountAndWait": (self.mount_ok,), "getMountError": ("Phone denied access",),
                "isMounted": (self.mount_ok,),
                "getDirectories": ({str(self.root): "Shared files"},),
                "mountPoint": (str(self.root),)}.get(method, ())


class SnapshotBridge(bridge.Bridge):
    def __init__(self, device_ids=None):
        self.device_ids = device_ids if device_ids is not None else ["phone"]
        self.paths = []
        self.raw_media = {"player": "x" * 257, "playerList": ["x" * 257], "title": "T" * 2000,
                          "artist": "Artist", "volume": 45, "unknownNested": {"secret": "S" * 1_000_000}}
    def call(self, path, interface, method, signature=None, args=(), timeout=3000):
        self.paths.append((path, method))
        if method == "devices": return (self.device_ids,)
        if method == "loadedPlugins": return (["kdeconnect_sms", "kdeconnect_mprisremote"],)
        return ()
    def props(self, path, interface):
        if interface == bridge.IFACE:
            return {"isPaired": True, "isReachable": True, "name": "N" * 1000,
                    "activeProviderNames": ["P" * 1000], "privateMetadata": {"secret": "X" * 1_000_000}}
        if interface.endswith(".battery"):
            return {"hasBattery": True, "charge": 55, "isCharging": True,
                    "unknown": "B" * 1_000_000}
        return self.raw_media


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.dependencies = patch("bridge.dependencies", return_value={name: True for name in (
            "kdeconnect", "sshfs", "kio-fuse", "nautilus", "python-gobject", "omarchy-file-select")})
        self.dependencies.start()
        self.addCleanup(self.dependencies.stop)
        self.now = 0.0
        self.clock = patch("bridge.monotonic", side_effect=lambda: self.now)
        self.sleeper = patch("bridge.sleep", side_effect=self.advance)
        self.clock.start()
        self.sleep = self.sleeper.start()
        self.addCleanup(self.clock.stop)
        self.addCleanup(self.sleeper.stop)

    def advance(self, seconds):
        self.now += seconds

    def test_missing_sshfs_blocks_mount_before_dbus(self):
        with patch("bridge.dependencies", return_value={"sshfs": False, "kio-fuse": True, "nautilus": True}):
            b = FakeBridge()
            with self.assertRaisesRegex(ValueError, "sshfs"):
                b.mount("phone", "files")
            self.assertEqual(b.calls, [])

    def test_missing_kio_fuse_identified_separately(self):
        with patch("bridge.dependencies", return_value={"sshfs": True, "kio-fuse": False, "nautilus": True}):
            with self.assertRaisesRegex(ValueError, "kio-fuse"):
                FakeBridge().mount("phone", "files")

    def test_device_path_rejects_traversal(self):
        for device in ("../phone", "a/b", "", "$(echo bad)", "x" * 257, None):
            with self.assertRaises(ValueError): bridge.path_for(device)

    def test_device_identifier_boundaries_preserve_valid_ids_exactly(self):
        valid = "D" * bridge.MAX_DEVICE_ID_BYTES
        self.assertEqual(bridge.path_for(valid), bridge.ROOT + "/devices/" + valid)
        result = SnapshotBridge([valid, "D" * (bridge.MAX_DEVICE_ID_BYTES + 1),
                                 "../phone", "ümlaut", 17]).snapshot()
        self.assertEqual([item["id"] for item in result["devices"]], [valid])

    def test_megabyte_device_identifier_never_reaches_path_or_snapshot(self):
        bridge_fixture = SnapshotBridge(["D" * 1048576])
        result = bridge_fixture.snapshot()
        self.assertEqual(result["devices"], [])
        self.assertLess(len(__import__("json").dumps(result).encode()), 1000)
        self.assertEqual(bridge_fixture.paths, [(bridge.ROOT, "devices")])

    def test_mpris_snapshot_is_whitelisted_bounded_and_action_safe(self):
        result = SnapshotBridge().snapshot()
        device = result["devices"][0]
        self.assertEqual(device["media"]["player"], "")
        self.assertEqual(device["media"]["playerList"], [])
        self.assertEqual(device["media"]["volume"], 45)
        self.assertNotIn("unknownNested", device["media"])
        self.assertNotIn("privateMetadata", device)
        self.assertLessEqual(len(device["name"].encode()), 256)
        self.assertLessEqual(len(device["links"][0].encode()), 128)
        import json
        self.assertLess(len(json.dumps(result).encode()), 10_000)

    def test_snapshot_plugin_action_identifiers_are_exact_or_disabled(self):
        result = bridge.exact_ids(["kdeconnect_sms", "ring"], 128, 128)
        self.assertEqual(result, ["kdeconnect_sms", "ring"])
        self.assertEqual(bridge.exact_ids(["kdeconnect_sms", "x" * 129], 128, 128), [])

    def test_offline_blocks_actions(self):
        b = FakeBridge(online=False)
        with self.assertRaisesRegex(ValueError, "offline"): b.action("ring", "phone")
        self.assertEqual(b.calls, [])

    def test_mount_uses_advertised_share(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(Path, "is_mount", return_value=True):
            (Path(tmp) / "DCIM").mkdir()
            self.assertEqual(FakeBridge(tmp).mount("phone", "photos"), Path(tmp) / "DCIM")
            self.sleep.assert_not_called()

    def test_all_file_actions_wait_for_kernel_mount_then_open_once(self):
        # Reproduce KDE's process-start acknowledgement before SSHFS has mounted.
        for verb, child in bridge.FOLDERS.items():
            with self.subTest(verb=verb), tempfile.TemporaryDirectory() as tmp:
                self.now = 0
                target = Path(tmp) / child
                target.mkdir(exist_ok=True)
                b = FakeBridge(tmp)
                with patch.object(Path, "is_mount", side_effect=lambda: self.now >= .6), \
                     patch("bridge.subprocess.Popen") as launch:
                    b.action(verb, "phone")
                    launch.assert_called_once()
                    self.assertEqual(launch.call_args.args[0], ["nautilus", "--new-window", str(target)])
                self.assertGreaterEqual(self.now, .6)
                self.assertLess(self.now, .9)
                self.assertEqual(sum(m == "mountAndWait" for m, _ in b.calls), 1)
                self.assertGreater(sum(m == "isMounted" for m, _ in b.calls), 0)

    def test_started_sshfs_failure_stops_wait_without_open_or_remount(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(Path, "is_mount", return_value=False), \
             patch("bridge.subprocess.Popen") as launch:
            b = FakeBridge(tmp)
            original = b.call
            def call(*args, **kwargs):
                if args[2] == "isMounted": b.mount_ok = False
                return original(*args, **kwargs)
            b.call = call
            with self.assertRaisesRegex(ValueError, "Phone denied access"):
                b.action("files", "phone")
            self.sleep.assert_not_called()
            launch.assert_not_called()
            self.assertEqual(sum(m == "mountAndWait" for m, _ in b.calls), 1)

    def test_disconnect_during_mount_wait_stops_without_open(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(Path, "is_mount", return_value=False), \
             patch("bridge.subprocess.Popen") as launch:
            b = FakeBridge(tmp)
            original = b.call
            def call(*args, **kwargs):
                result = original(*args, **kwargs)
                if args[2] == "isMounted": b.online = False
                return result
            b.call = call
            with self.assertRaisesRegex(ValueError, "disconnected"):
                b.action("documents", "phone")
            launch.assert_not_called()
            self.assertEqual(self.now, bridge.MOUNT_READY_INTERVAL)

    def test_mount_wait_dbus_failure_propagates_without_retry(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(Path, "is_mount", return_value=False), \
             patch("bridge.subprocess.Popen") as launch:
            b = FakeBridge(tmp)
            original = b.call
            def call(*args, **kwargs):
                if args[2] == "isMounted": raise OSError("SFTP interface disappeared")
                return original(*args, **kwargs)
            b.call = call
            with self.assertRaisesRegex(OSError, "disappeared"):
                b.action("downloads", "phone")
            launch.assert_not_called()
            self.sleep.assert_not_called()

    def test_failed_mount_does_not_open_files(self):
        b = FakeBridge(mount_ok=False)
        with patch("bridge.subprocess.Popen") as launch:
            with self.assertRaisesRegex(ValueError, "denied"): b.action("files", "phone")
            launch.assert_not_called()

    def test_missing_folder_is_actionable(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(Path, "is_mount", return_value=True):
            with self.assertRaisesRegex(ValueError, "Try Browse files"):
                FakeBridge(tmp).mount("phone", "documents")

    def test_symlink_outside_share_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(Path, "is_mount", return_value=True):
            (Path(tmp) / "DCIM").symlink_to("/tmp", target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "not shared"):
                FakeBridge(tmp).mount("phone", "photos")

    def test_unmounted_path_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = FakeBridge(tmp)
            with patch("bridge.subprocess.Popen") as launch:
                with self.assertRaisesRegex(ValueError, "not mounted: timed out"):
                    b.action("files", "phone")
                launch.assert_not_called()
            self.assertEqual(self.now, bridge.MOUNT_READY_TIMEOUT)
            self.assertLessEqual(self.sleep.call_count, 51)
            self.assertEqual(sum(m == "mountAndWait" for m, _ in b.calls), 1)

    def test_advertised_share_outside_mount_rejected_after_readiness(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(Path, "is_mount", return_value=True):
            b = FakeBridge(tmp)
            original = b.call
            def call(*args, **kwargs):
                if args[2] == "getDirectories": return ({"/tmp": "Outside mount"},)
                return original(*args, **kwargs)
            b.call = call
            with self.assertRaisesRegex(ValueError, "not mounted"):
                b.mount("phone", "files")

    def test_volume_clamped(self):
        b = FakeBridge()
        b.action("volume", "phone", "200")
        self.assertEqual(b.calls[-1][1][2].unpack(), 100)
        b.action("volume", "phone", "-15")
        self.assertEqual(b.calls[-1][1][2].unpack(), 0)

    def test_player_must_be_available(self):
        b = FakeBridge()
        with self.assertRaisesRegex(ValueError, "no longer available"):
            b.action("player", "phone", "Gone")
        self.assertEqual(b.calls, [])

    def test_invalid_media_action_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unknown media"):
            FakeBridge().action("media", "phone", "Anything")

    def test_playback_action_uses_dbus_argument(self):
        b = FakeBridge()
        b.action("media", "phone", "PlayPause")
        self.assertEqual(b.calls, [("sendAction", ("PlayPause",))])

    def test_cancelled_picker_sends_nothing(self):
        b = FakeBridge()
        with patch("bridge.subprocess.run") as picker:
            picker.return_value.returncode = 1
            self.assertEqual(b.action("share", "phone"), "Nothing sent")
        self.assertEqual(b.calls, [])


class DependencyTests(unittest.TestCase):
    def test_kio_fuse_detected_outside_path(self):
        with patch("bridge.shutil.which", return_value=None), \
             patch("bridge.os.path.isfile", side_effect=lambda p: p == "/usr/lib/kio-fuse"), \
             patch("bridge.os.access", return_value=True):
            result = bridge.dependencies()
            self.assertTrue(result["kio-fuse"])
            self.assertFalse(result["sshfs"])

    def test_non_executable_kio_fuse_not_accepted(self):
        with patch("bridge.shutil.which", return_value=None), \
             patch("bridge.os.path.isfile", return_value=True), \
             patch("bridge.os.access", return_value=False):
            self.assertFalse(bridge.dependencies()["kio-fuse"])


if __name__ == "__main__":
    unittest.main()
