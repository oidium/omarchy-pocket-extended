#!/usr/bin/env python3
"""Small, stateless KDE Connect adapter. JSON on stdout; no shell execution."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from time import monotonic, sleep
try:
    import gi
    gi.require_version("Gio", "2.0")
    from gi.repository import Gio, GLib
except (ImportError, ValueError):
    Gio = GLib = None

BRIDGE_ERRORS = (OSError, ValueError, subprocess.SubprocessError) + ((GLib.Error,) if GLib else ())

BUS = "org.kde.kdeconnect"
ROOT = "/modules/kdeconnect"
IFACE = BUS + ".device"
PROPS = "org.freedesktop.DBus.Properties"
FOLDERS = {"files": "", "photos": "DCIM", "downloads": "Download", "documents": "Documents"}
MOUNT_READY_TIMEOUT = 10.0
MOUNT_READY_INTERVAL = 0.2
MAX_DEVICES = 64
MAX_DEVICE_ID_BYTES = 256
MAX_PLUGIN_IDS = 128
MAX_PLUGIN_ID_BYTES = 128
MAX_PLAYER_IDS = 16
MAX_PLAYER_ID_BYTES = 256


def bounded_string(value, limit):
    if not isinstance(value, str):
        return ""
    used = 0
    end = 0
    for index, char in enumerate(value):
        code = ord(char)
        if 0xd800 <= code <= 0xdfff:
            return ""
        width = 1 if code <= 0x7f else 2 if code <= 0x7ff else 3 if code <= 0xffff else 4
        if used + width > limit:
            break
        used += width
        end = index + 1
    if end == len(value):
        return value
    return value[:end]


def exact_ids(value, count_limit, byte_limit):
    """Preserve every action ID exactly, or return no IDs to disable actions."""
    if not isinstance(value, (list, tuple)) or len(value) > count_limit:
        return []
    if not all(isinstance(item, str) and item and len(item) <= byte_limit and
               not any(0xd800 <= ord(char) <= 0xdfff for char in item) and
               len(item.encode("utf-8")) <= byte_limit for item in value):
        return []
    return list(dict.fromkeys(value))


def normalize_media(data):
    """Whitelist bounded MPRIS state for the stateless snapshot path."""
    if not isinstance(data, dict):
        return {}
    player = data.get("player")
    if (not isinstance(player, str) or not player or len(player) > MAX_PLAYER_ID_BYTES or
            any(0xd800 <= ord(char) <= 0xdfff for char in player) or
            len(player.encode("utf-8")) > MAX_PLAYER_ID_BYTES):
        player = ""
    result = {"player": player,
              "playerList": exact_ids(data.get("playerList", []), MAX_PLAYER_IDS, MAX_PLAYER_ID_BYTES),
              "title": bounded_string(data.get("title", ""), 512),
              "artist": bounded_string(data.get("artist", ""), 512),
              "album": bounded_string(data.get("album", ""), 512)}
    for key in ("volume",):
        value = data.get(key)
        if type(value) is int and 0 <= value <= 100:
            result[key] = value
    for key in ("length", "position"):
        value = data.get(key)
        if type(value) is int and 0 <= value <= 2**53:
            result[key] = value
    for key in ("isPlaying", "canSeek"):
        value = data.get(key)
        if type(value) is bool:
            result[key] = value
    return result


def dependencies():
    """Check executables, including KIO FUSE's usual non-PATH install location."""
    kio_fuse = bool(shutil.which("kio-fuse")) or any(
        os.path.isfile(path) and os.access(path, os.X_OK)
        for path in ("/usr/lib/kio-fuse", "/usr/libexec/kio-fuse"))
    return {"kdeconnect": bool(shutil.which("kdeconnect-cli")),
            "sshfs": bool(shutil.which("sshfs")), "kio-fuse": kio_fuse,
            "nautilus": bool(shutil.which("nautilus")),
            "python-gobject": Gio is not None,
            "omarchy-file-select": bool(shutil.which("omarchy-file-select"))}


def require_dependencies(*packages):
    installed = dependencies()
    missing = [name for name in packages if not installed.get(name)]
    if missing:
        raise ValueError("Missing runtime dependencies: " + ", ".join(missing)
                         + ". Install them, then refresh the panel.")


def path_for(device):
    # KDE Connect identifiers are opaque D-Bus path components. Keep the
    # panel's 256-character contract and reject rather than truncate them.
    if (not isinstance(device, str) or len(device) > MAX_DEVICE_ID_BYTES or
            not re.fullmatch(r"[A-Za-z0-9_]+", device)):
        raise ValueError("Invalid device identifier")
    return ROOT + "/devices/" + device


class Bridge:
    def __init__(self):
        require_dependencies("python-gobject", "kdeconnect")
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)

    def call(self, path, interface, method, signature=None, args=(), timeout=3000):
        value = GLib.Variant(signature, args) if signature else None
        return self.bus.call_sync(BUS, path, interface, method, value, None,
                                 Gio.DBusCallFlags.NONE, timeout, None).unpack()

    def props(self, path, interface):
        return self.call(path, PROPS, "GetAll", "(s)", (interface,))[0]

    def optional_props(self, path, interface):
        try:
            return self.props(path, interface)
        except GLib.Error:
            return {}

    def snapshot(self):
        ids = self.call(ROOT, BUS + ".daemon", "devices", "(bb)", (False, True))[0]
        devices = []
        valid_ids = [device for device in ids[:MAX_DEVICES]
                     if isinstance(device, str) and len(device) <= MAX_DEVICE_ID_BYTES
                     and re.fullmatch(r"[A-Za-z0-9_]+", device)]
        for device in valid_ids:
            path = path_for(device)
            try:
                p = self.props(path, IFACE)
            except GLib.Error:
                continue
            online = bool(p.get("isReachable") and p.get("isPaired"))
            name = bounded_string(p.get("name", "Phone"), 256) or "Phone"
            raw_links = p.get("activeProviderNames", [])
            links = [bounded_string(item, 128) for item in raw_links[:16]
                     if isinstance(item, str)] if isinstance(raw_links, (list, tuple)) else []
            d = {"id": device, "name": name, "online": online,
                 "links": links, "battery": -1,
                 "charging": False, "can": [], "media": {}, "notifications": []}
            if online:
                d["can"] = exact_ids(self.call(path, IFACE, "loadedPlugins")[0],
                                      MAX_PLUGIN_IDS, MAX_PLUGIN_ID_BYTES)
                b = self.optional_props(path + "/battery", IFACE + ".battery")
                if b.get("hasBattery") is True:
                    charge, charging = b.get("charge", -1), b.get("isCharging", False)
                    d.update(battery=charge if type(charge) is int and -1 <= charge <= 100 else -1,
                             charging=charging if type(charging) is bool else False)
                d["media"] = normalize_media(self.optional_props(path + "/mprisremote", IFACE + ".mprisremote"))
                # Notifications are owned by the persistent messaging worker.
            devices.append(d)
        devices.sort(key=lambda d: (not d["online"], d["name"].casefold()))
        return {"ok": True, "devices": devices}

    def require_online(self, device):
        path = path_for(device)
        p = self.props(path, IFACE)
        if not p.get("isPaired") or not p.get("isReachable"):
            raise ValueError("Phone is offline. Open KDE Connect on your phone and check its connection.")
        return path

    def mount(self, device, folder):
        # Both are required by this plugin's supported Omarchy/Nautilus setup.
        # SSHFS performs this mount; KIO FUSE supports KDE's separate URL handoff.
        require_dependencies("sshfs", "kio-fuse", "nautilus")
        path = self.require_online(device) + "/sftp"
        if folder not in FOLDERS:
            raise ValueError("Unknown folder")
        if not self.call(path, IFACE + ".sftp", "mountAndWait", timeout=25000)[0]:
            error = self.call(path, IFACE + ".sftp", "getMountError")[0]
            raise ValueError(error or "Could not mount phone storage")
        mount = Path(self.call(path, IFACE + ".sftp", "mountPoint")[0]).resolve()
        self.wait_for_mount(device, path, mount)
        # Use the advertised share, never a hardcoded Android storage path or KIO URL.
        shares = self.call(path, IFACE + ".sftp", "getDirectories")[0]
        if not shares:
            raise ValueError("No folders shared. Enable Filesystem expose in the phone's KDE Connect settings.")
        roots = sorted(Path(s).resolve() for s in shares)
        root = next((s for s in roots if str(s).endswith("/storage/emulated/0")), roots[0])
        if not root.is_relative_to(mount) or not mount.is_mount():
            raise ValueError("Phone storage is not mounted")
        target = (root / FOLDERS[folder]).resolve()
        if not target.is_relative_to(root) or not target.is_dir():
            raise ValueError("This folder is not shared by your phone. Try Browse files.")
        return target

    def wait_for_mount(self, device, path, mount):
        # KDE Connect 26.08 emits mounted / returns mountAndWait when QProcess
        # starts sshfs, BEFORE the kernel mount exists. isMounted has the same
        # process-start semantics. Check actual readiness only for this request;
        # never remount, warm user files, or keep polling after this action ends.
        deadline = monotonic() + MOUNT_READY_TIMEOUT

        def call_timeout():
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise ValueError("Phone storage is not mounted: timed out waiting for storage to become ready. Try again.")
            return max(1, min(1000, int(remaining * 1000)))

        while not mount.is_mount():
            status = self.call(path_for(device), PROPS, "GetAll", "(s)", (IFACE,),
                               timeout=call_timeout())[0]
            if not status.get("isPaired") or not status.get("isReachable"):
                raise ValueError("Phone disconnected while connecting to storage. Reconnect and try again.")
            if not self.call(path, IFACE + ".sftp", "isMounted", timeout=call_timeout())[0]:
                error = self.call(path, IFACE + ".sftp", "getMountError", timeout=call_timeout())[0]
                raise ValueError(error or "Phone storage mount stopped before it became ready. Try again.")
            sleep(min(MOUNT_READY_INTERVAL, max(0, deadline - monotonic())))

    def action(self, verb, device, value=""):
        path = self.require_online(device)
        if verb in FOLDERS:
            target = self.mount(device, verb)
            subprocess.Popen(["nautilus", "--new-window", str(target)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            return "Opened phone " + ("storage" if verb == "files" else verb)
        if verb == "ring":
            self.call(path + "/findmyphone", IFACE + ".findmyphone", "ring")
            return "Ring request sent"
        if verb == "clipboard":
            self.call(path + "/clipboard", IFACE + ".clipboard", "sendClipboard")
            return "Clipboard sent to phone"
        if verb == "share":
            require_dependencies("omarchy-file-select")
            picker = subprocess.run(["omarchy-file-select", "--title", "Send a file to your phone"], capture_output=True, text=True, timeout=600)
            if picker.returncode == 1:
                return "Nothing sent"
            if picker.returncode:
                raise ValueError("Could not open the file chooser")
            filename = picker.stdout.rstrip("\n")
            if not filename:
                return "Nothing sent"
            if not Path(filename).is_file():
                raise ValueError("Select a regular file")
            self.require_online(device)
            uri = Gio.File.new_for_path(filename).get_uri()
            self.call(path + "/share", IFACE + ".share", "shareUrl", "(s)", (uri,))
            return "File handed to KDE Connect for transfer"
        media_path, media_iface = path + "/mprisremote", IFACE + ".mprisremote"
        if verb == "player":
            players = self.props(media_path, media_iface).get("playerList", [])
            if value not in players:
                raise ValueError("Player is no longer available")
            self.call(media_path, PROPS, "Set", "(ssv)", (media_iface, "player", GLib.Variant("s", value)))
            return "Player selected"
        if verb == "media":
            if value not in ("PlayPause", "Next", "Previous"):
                raise ValueError("Unknown media action")
            self.call(media_path, media_iface, "sendAction", "(s)", (value,))
            return "Playback request sent"
        if verb == "volume":
            volume = max(0, min(100, int(value)))
            self.call(media_path, PROPS, "Set", "(ssv)", (media_iface, "volume", GLib.Variant("i", volume)))
            return "Phone volume updated"
        raise ValueError("Unknown action")


def main():
    installed = dependencies()
    try:
        if len(sys.argv) > 1 and sys.argv[1] == "check-dependencies":
            result = {"ok": all(installed.values())}
        else:
            bridge = Bridge()
            if len(sys.argv) == 1 or sys.argv[1] == "snapshot":
                result = bridge.snapshot()
            elif sys.argv[1] == "check-mount" and len(sys.argv) == 3:
                result = {"ok": True, "path": str(bridge.mount(sys.argv[2], "files"))}
            elif len(sys.argv) in (3, 4):
                result = {"ok": True, "message": bridge.action(*sys.argv[1:])}
            else:
                raise ValueError("Usage: bridge.py [snapshot|check-dependencies|check-mount DEVICE|ACTION DEVICE [VALUE]]")
    except BRIDGE_ERRORS as error:
        result = {"ok": False, "error": str(error), "devices": []}
    result["dependencies"] = installed
    print(json.dumps(result), flush=True)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
