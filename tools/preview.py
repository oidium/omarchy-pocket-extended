#!/usr/bin/env python3
"""Launch the actual Panel with synthetic data; this is not a host-isolated sandbox."""
from pathlib import Path
import argparse
import json
import os
import shutil
import subprocess
import tempfile

parser=argparse.ArgumentParser()
parser.add_argument("--screen",default="",help="select a Wayland output by name")
parser.add_argument("--bottom",action="store_true",help="place the synthetic preview bar at the bottom")
args=parser.parse_args()
root=Path(__file__).resolve().parents[1]
preview=Path(tempfile.mkdtemp(prefix="pocket-extended-preview-"))
try:
    for name in ("Commons","Ui"):
        (preview/name).symlink_to(Path("/usr/share/omarchy/shell")/name)
    (preview/"Pocket").mkdir()
    for pattern in ("*.qml","*.js","*.py"):
        for source in root.glob(pattern):shutil.copy2(source,preview/"Pocket"/source.name)
    fixture=(root/"tools/Preview.qml").read_text().replace("@PROJECT@",str(root))
    if args.screen:
        fixture=fixture.replace('  PanelWindow {','  PanelWindow {\n    screen: Quickshell.screens.find(function(s){return s.name==='+json.dumps(args.screen)+'})',1)
    if args.bottom:
        fixture=fixture.replace('position: "top"','position: "bottom"').replace('anchors { top: true; left: true; right: true }','anchors { bottom: true; left: true; right: true }')
    (preview/"shell.qml").write_text(fixture)
    env=os.environ.copy()
    env.update(XDG_CONFIG_HOME=str(preview/"config"),XDG_STATE_HOME=str(preview/"state"),XDG_CACHE_HOME=str(preview/"cache"),PYTHONDONTWRITEBYTECODE="1")
    print("Synthetic preview uses temporary XDG paths but reads shared Omarchy modules and the current compositor/session.",flush=True)
    subprocess.run(["quickshell","-p",str(preview)],check=True,env=env)
finally:
    shutil.rmtree(preview,ignore_errors=True)
