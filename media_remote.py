"""Signal-driven MPRIS remote state on the existing worker's D-Bus connection."""
import uuid
from gi.repository import GLib
from messaging import bounded_text, json_line_size, utf8_size

IFACE = 'org.kde.kdeconnect.device.mprisremote'
PROPS = 'org.freedesktop.DBus.Properties'
MAX_MEDIA_EVENT_BYTES = 32 * 1024
MAX_PLAYER_ID_BYTES = 256
MAX_PLAYERS = 16
MAX_DISPLAY_BYTES = 512


def _safe_string(value, limit):
    if not isinstance(value, str) or any(0xd800 <= ord(c) <= 0xdfff for c in value):
        return ''
    return bounded_text(value, limit)


def normalize_media(data):
    """Whitelist the small, typed MPRIS surface that the panel actually uses."""
    if not isinstance(data, dict):
        return {}
    player = data.get('player')
    player = player if isinstance(player, str) and not any(0xd800 <= ord(c) <= 0xdfff for c in player) and 0 < utf8_size(player) <= MAX_PLAYER_ID_BYTES else ''
    raw_players = data.get('playerList')
    players = []
    if isinstance(raw_players, (list, tuple)) and len(raw_players) <= MAX_PLAYERS:
        if all(isinstance(value, str) and 0 < utf8_size(value) <= MAX_PLAYER_ID_BYTES and
               not any(0xd800 <= ord(c) <= 0xdfff for c in value) for value in raw_players):
            players = list(dict.fromkeys(raw_players))
    result = {
        'player': player,
        # Opaque player IDs are kept exact. An invalid/oversized list disables
        # player switching instead of truncating an action target.
        'playerList': players,
        'title': _safe_string(data.get('title'), MAX_DISPLAY_BYTES),
        'artist': _safe_string(data.get('artist'), MAX_DISPLAY_BYTES),
        'album': _safe_string(data.get('album'), MAX_DISPLAY_BYTES),
    }
    for name in ('volume',):
        value = data.get(name)
        if type(value) is int and 0 <= value <= 100:
            result[name] = value
    for name in ('length', 'position'):
        value = data.get(name)
        if type(value) is int and 0 <= value <= 2**53:
            result[name] = value
    for name in ('isPlaying', 'canSeek'):
        value = data.get(name)
        if type(value) is bool:
            result[name] = value
    return result


class RemoteMedia:
    def __init__(self, service):
        self.service = service
        self.states = {}
        self.reads = {}
        self.writes = {}

    @staticmethod
    def path(device):
        return '/modules/kdeconnect/devices/' + device + '/mprisremote'

    def clear(self, device):
        self.states.pop(device, None)
        self.reads.pop(device, None)
        op = self.writes.pop(device, None)
        if op:
            self.result(device, op, False, 'Media connection changed')

    def result(self, device, op, accepted, error=''):
        self.service.emit(dict(event='volume_result', device=device, request_id=op['request'],
                               accepted=accepted, error=error))

    def refresh(self, device):
        if device in self.reads:
            self.reads[device]['dirty'] = True
            return
        generation = self.service.devices[device]['generation']
        op = {'dirty': False}
        self.reads[device] = op
        def received(value, error):
            if self.reads.get(device) is not op:
                return
            self.reads.pop(device)
            if not self.service.current(device, generation):
                return
            if op['dirty']:
                self.refresh(device)
                return
            old = self.states.get(device, {})
            data = normalize_media(value[0] if not error else {})
            token = old.get('token') if old.get('media', {}).get('player') == data.get('player') else None
            state = dict(media=data, token=token or uuid.uuid4().hex,
                         revision=old.get('revision', 0) + 1)
            event = dict(event='media_state', device=bounded_text(device, 256), **state)
            if json_line_size(event) > MAX_MEDIA_EVENT_BYTES:
                # The fixed whitelist and field limits make this a final guard;
                # if upstream changes the shape, keep exact controls but drop
                # optional display text and player switching.
                data.update(title='', artist='', album='', playerList=[])
                event = dict(event='media_state', device=bounded_text(device, 256),
                             media=data, token=state['token'], revision=state['revision'])
            if json_line_size(event) > MAX_MEDIA_EVENT_BYTES:
                data = {'player': data.get('player', ''), 'playerList': []}
                state['media'] = data
                event = dict(event='media_state', device=bounded_text(device, 256), **state)
            self.states[device] = state
            self.service.emit(event)
        self.service.call(self.path(device), PROPS, 'GetAll', '(s)', (IFACE,), received)

    def set_volume(self, command):
        device = command['device']
        self.service.require_online(device, 'kdeconnect_mprisremote')
        state = self.states.get(device, {})
        media = state.get('media', {})
        if not media.get('player') or command.get('token') != state.get('token'):
            raise ValueError('Media player changed')
        volume = command.get('value')
        if type(volume) is not int or not 0 <= volume <= 100:
            raise ValueError('Invalid media volume')
        if device in self.writes:
            raise ValueError('Volume update is already pending')
        generation = self.service.devices[device]['generation']
        op = dict(request=command.get('request_id'), token=state['token'])
        self.writes[device] = op
        def finish(error):
            if self.writes.get(device) is not op:
                return
            self.writes.pop(device)
            self.result(device, op, not error, error or '')
            self.refresh(device)
        def checked(value, error):
            if self.writes.get(device) is not op:
                return
            if not self.service.current(device, generation):
                finish('Media connection changed'); return
            current = value[0] if not error else {}
            if error or current.get('player') != media['player'] or self.states.get(device, {}).get('token') != op['token']:
                finish('Media player changed'); return
            self.service.call(self.path(device), PROPS, 'Set', '(ssv)',
                              (IFACE, 'volume', GLib.Variant('i', volume)),
                              lambda value, error: finish(error))
        self.service.call(self.path(device), PROPS, 'GetAll', '(s)', (IFACE,), checked)
