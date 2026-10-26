"""Event-only telephony presentation. No call controls or network transport."""
import re
import time
from messaging import bounded_text, json_line_size, utf8_size

MAX_CALL_EVENT_BYTES = 32 * 1024
MAX_RAW_NUMBER_BYTES = 128
MAX_CALLER_NAME_BYTES = 256
MAX_CORRELATED_NOTES = 32


def safe_text(value, limit):
    if not isinstance(value, str) or any(0xd800 <= ord(c) <= 0xdfff for c in value):
        return ''
    return bounded_text(value, limit)


def number_key(value):
    if not isinstance(value, str) or utf8_size(value) > MAX_RAW_NUMBER_BYTES or not re.fullmatch(r'[+0-9().\s-]+', value):
        return None
    value = re.sub(r'[().\s-]', '', value)
    return value if re.fullmatch(r'\+?[0-9]{3,32}', value) else None


def pixel_missed_source(value):
    """Recognize only the observed forwarded Android dialer notification key."""
    if not isinstance(value, str) or utf8_size(value) > 1024:
        return False
    fields = value.split('|')
    return (len(fields) == 5 and fields[0].isdigit() and
            fields[1] == 'com.android.dialer' and fields[2].isdigit() and
            fields[4].isdigit() and re.fullmatch(
                r'MissedCall_content://call_log/calls/[0-9]+(?:\?allow_voicemails=(?:true|false))?',
                fields[3]) is not None)


def normalized_name(value):
    return ' '.join(safe_text(value, 512).split()).casefold()


class CallEvents:
    INCOMING_TTL = 20
    MISSED_TTL = 300
    CORRELATION_WINDOW = 30

    def __init__(self, emit, clock=time.monotonic, wall=time.time):
        self.emit, self.clock, self.wall = emit, clock, wall
        self.records = {}
        self.notes = {}
        self.sequence = 0

    def publish(self):
        calls = list(self.records.values())
        event = {'event': 'call_events', 'calls': calls}
        while calls and json_line_size(event) > MAX_CALL_EVENT_BYTES:
            oldest = calls.pop(0)
            self.records.pop(oldest['id'], None)
            event = {'event': 'call_events', 'calls': calls}
        self.emit(event)

    def receive(self, device, event, number, name):
        if event not in ('callReceived', 'missedCall') or not all(isinstance(x, str) for x in (number, name)):
            return False
        number_is_bounded = utf8_size(number) <= MAX_RAW_NUMBER_BYTES and not any(0xd800 <= ord(c) <= 0xdfff for c in number)
        raw_number = safe_text(number, MAX_RAW_NUMBER_BYTES)
        number = number if number_is_bounded else ''
        name = safe_text(name, MAX_CALLER_NAME_BYTES)
        device = safe_text(device, 256)
        now = self.clock()
        normalized = number_key(number) if number_is_bounded else None
        # Without a usable number, do not combine possibly different callers.
        for record in self.records.values():
            if normalized and record['device'] == device and record['number_key'] == normalized and record['raw_event'] == event and now - record['_last_seen'] <= 5:
                record['_last_seen'] = now
                record['repeat_count'] += 1
                self.publish()
                return True
        if event == 'missedCall' and normalized:
            for key, record in list(self.records.items()):
                if record['device'] == device and record['number_key'] == normalized and record['raw_event'] == 'callReceived':
                    del self.records[key]
        self.sequence += 1
        meaningful_name = name.strip() if name.strip() and name != number and number_key(name) is None and normalized else ''
        # Names without numbers are still useful (e.g. withheld caller), but
        # localized "unknown number" repeated in both fields is not a name.
        if not normalized and name.strip() and name != number:
            meaningful_name = name.strip()
        record = {'id': str(self.sequence), 'device': device, 'raw_event': event,
                  'kind': 'incoming_event' if event == 'callReceived' else 'missed_event',
                  'number': number if normalized else '', 'raw_number': raw_number,
                  'number_key': normalized, 'event_name': name,
                  'name': meaningful_name or (number if normalized else 'Unknown caller'),
                  'name_source': 'event' if meaningful_name else 'number' if normalized else 'unknown',
                  'avatar': None, 'observed_at': int(self.wall() * 1000),
                  'authority': 'event_only', 'current_call_state': None,
                  'capabilities': {k: False for k in ('current_state', 'snapshot', 'mute', 'answer', 'decline', 'hang_up', 'caller_image')},
                  'repeat_count': 1, 'notification_ids': [], 'correlation': 'none',
                  'presentation': 'dedicated', '_last_seen': now,
                  '_observed': now, '_expires': now + (self.INCOMING_TTL if event == 'callReceived' else self.MISSED_TTL)}
        self.records[record['id']] = record
        while len(self.records) > 64:
            del self.records[next(iter(self.records))]
        self.correlate()
        self.publish()
        return True

    def resolve_contacts(self, device, contacts):
        changed = False
        for record in self.records.values():
            if record['device'] != device or not record['number_key'] or record['name_source'] == 'event':
                continue
            matches = [c for c in contacts if any(number_key(n['number']) == record['number_key'] for n in c['numbers'])]
            name = safe_text(matches[0]['name'], MAX_CALLER_NAME_BYTES) if len(matches) == 1 and matches[0]['name'].strip() else record['number']
            source = 'contacts' if len(matches) == 1 and name != record['number'] else 'number'
            if (record['name'], record['name_source']) != (name, source):
                record.update(name=name, name_source=source)
                changed = True
        if changed:
            self.correlate()
            self.publish()

    def notification(self, note):
        # Correlation only needs bounded display fields and an exact bounded
        # source token. Notification action identifiers are not routed here.
        raw_id = note.get('id')
        if not isinstance(raw_id, str) or not raw_id or utf8_size(raw_id) > 256 or any(0xd800 <= ord(c) <= 0xdfff for c in raw_id):
            return
        raw_internal_id = note.get('internal_id')
        if not isinstance(raw_internal_id, str) or utf8_size(raw_internal_id) > 256 or any(0xd800 <= ord(c) <= 0xdfff for c in raw_internal_id):
            raw_internal_id = ''
        note = {
            'device': safe_text(note.get('device'), 256),
            'id': raw_id,
            'internal_id': raw_internal_id,
            'title': safe_text(note.get('title'), 512),
            'body': safe_text(note.get('body'), 512),
        }
        if not note['device'] or not note['id']:
            return
        key = (note['device'], note['id'])
        old = self.notes.get(key)
        observed = old[1] if old and old[0].get('internal_id') == note.get('internal_id') else self.clock()
        self.notes[key] = (dict(note), observed)
        while len(self.notes)>128: self.notes.pop(next(iter(self.notes)))
        if self.correlate(): self.publish()

    def remove_notification(self, device, nid):
        self.notes.pop((device, nid), None)
        if self.correlate(): self.publish()

    def correlate(self):
        changed = False
        for record in self.records.values():
            candidates = []
            for (device, nid), (note, observed) in self.notes.items():
                if device != record['device'] or abs(observed - record['_observed']) > self.CORRELATION_WINDOW:
                    continue
                text = note.get('title', '') + '\n' + note.get('body', '')
                text = safe_text(text, 2048)
                # No exported call category or shared call ID: textual matches
                # are candidates, never verified duplicates. Never hide a note.
                phrase = 'incoming call' if record['kind'] == 'incoming_event' else 'missed call'
                # Source structure is a locale-independent hint, not a shared
                # call identity. Preserve the generic card even on this match.
                pixel_candidate = (
                    record['raw_event'] == 'missedCall' and record['number_key'] and
                    record['name_source'] in ('event', 'contacts') and
                    bool(normalized_name(record['name'])) and
                    pixel_missed_source(note.get('internal_id')) and
                    normalized_name(note.get('body')) == normalized_name(record['name']))
                if pixel_candidate:
                    candidates.append(nid)
                    if len(candidates) > MAX_CORRELATED_NOTES:
                        candidates = []
                        break
                    continue
                if phrase not in text.casefold(): continue
                numbers = [number_key(n) for n in re.findall(r'\+?[0-9][0-9 ().-]{1,}[0-9]', text)]
                exact_number = record['number_key'] and record['number_key'] in numbers
                exact_title = record['name_source'] in ('event', 'contacts') and note.get('title', '').casefold() == record['name'].casefold()
                if exact_number or exact_title: candidates.append(nid)
                if len(candidates) > MAX_CORRELATED_NOTES:
                    candidates = []
                    break
            presentation = 'generic' if candidates else 'dedicated'
            if record['notification_ids'] != candidates or record['presentation'] != presentation:
                record.update(notification_ids=candidates, correlation='ambiguous' if candidates else 'none', presentation=presentation)
                changed = True
        return changed

    def clear_device(self, device):
        self.records = {k: r for k, r in self.records.items() if r['device'] != device}
        self.notes = {k: n for k, n in self.notes.items() if k[0] != device}
        self.publish()

    def expire(self):
        expired = [k for k, r in self.records.items() if self.clock() >= r['_expires']]
        for key in expired: del self.records[key]
        if expired: self.publish()
