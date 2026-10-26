"""Extended-only namespace. No paths are created merely by importing this module."""
import os
from pathlib import Path

PLUGIN_ID = 'io.github.oidium.pocket-extended'
IPC_TARGET = PLUGIN_ID
CONFIG_DIR = Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config'))) / 'omarchy-pocket-extended'
CACHE_DIR = Path(os.environ.get('XDG_CACHE_HOME', str(Path.home() / '.cache'))) / 'omarchy-pocket-extended'
# Reserved for UI preferences and derived previews only. Never a message/contact DB.
