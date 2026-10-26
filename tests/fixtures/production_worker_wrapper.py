"""Run the real worker main against synthetic D-Bus replies in QML integration tests."""
import json
import os
import sys
import time
from pathlib import Path

import messaging_service_production as production
from gi.repository import GLib


class FakeParams:
    def __init__(self, values): self.values=values
    def unpack(self): return self.values

class FakeBus:
    def __init__(self): self.subscriptions=[]
    def signal_subscribe(self, *args):
        self.subscriptions.append((args[0],args[1],args[2],args[3],args[-1]))
        return len(self.subscriptions)
    def signal_unsubscribe(self, subscription): pass
    def fire(self,path,interface,member,args):
        for sender_filter,iface_filter,member_filter,path_filter,callback in tuple(self.subscriptions):
            if sender_filter and sender_filter!="org.kde.kdeconnect":continue
            if iface_filter and iface_filter!=interface:continue
            if member_filter and member_filter!=member:continue
            if path_filter and path_filter!=path:continue
            callback(self,"synthetic",path,interface,member,FakeParams(args))


class FakeTransport:
    """Fake only the external KDE Connect transport; never fabricates events."""
    def __init__(self):
        self.bus = FakeBus()

    def call(self, path, interface, method, signature=None, args=(), callback=None):
        with open(os.environ["POCKET_FIXTURE_CALL_LOG"],"a") as f:f.write(f"{method} {path}\n")
        active = json.loads(Path(os.environ["POCKET_FIXTURE_ACTIVE_FILE"]).read_text())
        if method == "devices":
            value = (["fixture_phone"],)
        elif method == "GetAll" and path.endswith("/devices/fixture_phone"):
            value = ({"isReachable": True, "isPaired": True, "name": "Synthetic phone"},)
        elif method == "loadedPlugins":
            value = (["kdeconnect_notifications"],)
        elif method == "activeNotifications":
            value = (active,)
        elif method == "GetAll" and "/notifications/" in path:
            note = path.rsplit("/", 1)[-1]
            value = ({"internalId": "fixture-internal-" + note,
                      "replyId": "fixture-reply-" + note, "dismissable": True,
                      "text": "Production main synthetic notification",
                      "title": "Pocket audit fixture", "appName": "Synthetic fixture"},)
        else:
            value = ([],)
        callback(value, None)


class Tee:
    def __init__(self, stream, log):
        self.stream, self.log = stream, log

    def write(self, value):
        self.stream.write(value)
        self.log.write(value)
        self.flush()

    def flush(self):
        self.stream.flush()
        self.log.flush()


PRODUCTION_SERVICE = None
_REAL_INIT = production.Service.__init__
def _capture_service(self,*args,**kwargs):
    global PRODUCTION_SERVICE
    _REAL_INIT(self,*args,**kwargs)
    PRODUCTION_SERVICE=self
production.Service.__init__=_capture_service

def _process_signal_control():
    path=Path(os.environ["POCKET_FIXTURE_CONTROL_FILE"])
    if not path.exists() or PRODUCTION_SERVICE is None:return True
    try: control=json.loads(path.read_text())
    except (OSError,ValueError): return True
    path.unlink(missing_ok=True)
    if control.get("type")!="signal":
        raise AssertionError("worker control file is restricted to fake external D-Bus signals")
    PRODUCTION_SERVICE.transport.bus.fire(
        control["path"],control["interface"],control["member"],control.get("args",[]))
    return True


# Keep production.main(), GLib.MainLoop, GLib.io_add_watch, stdin parsing,
# stdout framing, and QML Process stdin intact. Only D-Bus is synthetic.
production.Transport = FakeTransport
_real_command = production.Service.command
def _record_command(service, command):
    with open(os.environ["POCKET_FIXTURE_COMMAND_LOG"],"a") as f:
        f.write(json.dumps(command)+"\n")
    return _real_command(service, command)
production.Service.command = _record_command
GLib.timeout_add(25,_process_signal_control)
Path(os.environ["POCKET_FIXTURE_PID_FILE"]).write_text(str(os.getpid()))
frame_log = open(os.environ["POCKET_FIXTURE_FRAME_LOG"], "a", buffering=1)
real_stdout = sys.stdout
sys.stdout = Tee(real_stdout, frame_log)
try:
    result=production.main()
    with open(os.environ["POCKET_FIXTURE_CALL_LOG"],"a") as f:
        f.write(f"MAIN_RETURN {result}\n")
    raise SystemExit(result)
finally:
    sys.stdout = real_stdout
    frame_log.close()
