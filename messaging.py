"""In-memory messaging model. No device transport or persistence in this module."""
import base64
from dataclasses import asdict, dataclass, field
import json
import time
import uuid

STATES = {0: 'unknown', 1: 'received', 2: 'sent', 3: 'draft', 4: 'outbox',
          5: 'failed', 6: 'queued'}


def _char_utf8_width(char):
    codepoint = ord(char)
    if codepoint <= 0x7f:
        return 1
    if codepoint <= 0x7ff:
        return 2
    if 0xd800 <= codepoint <= 0xdfff:
        return 1  # errors='replace' emits one ASCII replacement byte.
    if codepoint <= 0xffff:
        return 3
    return 4


def bounded_text(value, limit, *, reject=False):
    """Return valid UTF-8 text within a byte limit; reject non-text wire values."""
    if not isinstance(value, str):
        if reject:
            raise ValueError('Malformed KDE Connect text field')
        return ''
    if limit < 0:
        raise ValueError('Invalid text limit')
    used = 0
    end = 0
    for index, char in enumerate(value):
        # D-Bus supplies valid Unicode. Treat an isolated surrogate as the
        # replacement byte it would produce rather than copying the input.
        width = _char_utf8_width(char)
        if used + width > limit:
            if reject:
                raise ValueError('KDE Connect text field exceeds its size limit')
            return value[:end].encode('utf-8', errors='replace').decode('utf-8')
        used += width
        end = index + 1
    if end == len(value) and not any(0xd800 <= ord(char) <= 0xdfff for char in value):
        return value
    return value[:end].encode('utf-8', errors='replace').decode('utf-8')


def utf8_size(value):
    """Measure text without making a full-size encoded copy."""
    if not isinstance(value, str):
        return 0
    total = 0
    for char in value:
        total += _char_utf8_width(char)
    return total


def json_line_size(value):
    """Measure one complete UTF-8 JSON-lines frame, including its newline."""
    return len((json.dumps(value, ensure_ascii=False) + '\n').encode('utf-8'))


@dataclass(frozen=True)
class Attachment:
    part_id: str
    mime_type: str
    thumbnail_base64: str
    identifier: str

    MAX_THUMBNAIL_BYTES = 192 * 1024

    @classmethod
    def decode(cls, wire):
        if not isinstance(wire, (tuple, list)) or len(wire) != 4:
            return cls('', '', '', '')
        part, mime, thumbnail, identifier = wire
        safe_thumbnail = ''
        if isinstance(thumbnail, str) and utf8_size(thumbnail) <= cls.MAX_THUMBNAIL_BYTES:
            try:
                base64.b64decode(thumbnail, validate=True)
            except (ValueError, UnicodeEncodeError):
                pass
            else:
                safe_thumbnail = thumbnail
        safe_identifier = identifier if isinstance(identifier, str) and utf8_size(identifier) <= 512 and not any(
            0xd800 <= ord(char) <= 0xdfff for char in identifier) else ''
        return cls(str(part) if isinstance(part, int) and not isinstance(part, bool) else '',
                   bounded_text(mime, 256), safe_thumbnail, safe_identifier)


@dataclass(frozen=True)
class Message:
    device_id: str
    thread_id: str
    message_id: str
    addresses: list
    timestamp: int
    message_type: int
    direction: str
    state: str
    android_read: int
    subscription_id: str
    body: str
    attachments: list
    event: int
    addresses_complete: bool = True

    MAX_BODY_BYTES = 16 * 1024
    MAX_ADDRESSES = 16
    MAX_ADDRESS_BYTES = 256
    MAX_ATTACHMENTS = 16
    MAX_ATTACHMENT_BYTES = 512 * 1024
    MAX_RECORD_BYTES = 600 * 1024
    MAX_SERIALIZED_BYTES = 600 * 1024

    @classmethod
    def decode(cls, device, wire):
        if not isinstance(wire, (tuple, list)) or len(wire) != 10:
            raise ValueError('Unsupported KDE Connect message record')
        event, body, addresses, timestamp, kind, read, thread, uid, sub, attachments = wire
        if not isinstance(body, str) or not isinstance(addresses, (list, tuple)):
            raise ValueError('Malformed KDE Connect message record')
        if any(not isinstance(v, int) or isinstance(v, bool) for v in (event, timestamp, kind, read, thread, uid, sub)):
            raise ValueError('Malformed KDE Connect message identifiers or state')
        if not -(2**63) <= timestamp < 2**63:
            raise ValueError('Malformed KDE Connect message timestamp')
        body = bounded_text(body, cls.MAX_BODY_BYTES)
        addresses_complete = len(addresses) <= cls.MAX_ADDRESSES
        if addresses_complete:
            addresses_complete = all(
                isinstance(address, (tuple, list)) and address and
                isinstance(address[0], str) and bool(address[0])
                and utf8_size(address[0]) <= cls.MAX_ADDRESS_BYTES
                and not any(0xd800 <= ord(char) <= 0xdfff for char in address[0])
                for address in addresses
            )
        safe_addresses = []
        for address in addresses[:cls.MAX_ADDRESSES]:
            if isinstance(address, (tuple, list)) and address and isinstance(address[0], str):
                safe_addresses.append(bounded_text(address[0], cls.MAX_ADDRESS_BYTES))
        if not isinstance(attachments, (list, tuple)):
            attachments = ()
        bounded_attachments = []
        total = utf8_size(body) + sum(utf8_size(a) for a in safe_addresses)
        for raw in attachments[:cls.MAX_ATTACHMENTS]:
            item = Attachment.decode(raw)
            thumb = item.thumbnail_base64
            available = max(0, cls.MAX_ATTACHMENT_BYTES - total)
            if utf8_size(thumb) > available:
                # Base64 image bytes are atomic payloads; truncation would leave
                # a corrupt preview and still expose an attacker-sized string.
                item = Attachment(item.part_id, item.mime_type, '', item.identifier)
            total += sum(utf8_size(v) for v in (item.part_id, item.mime_type,
                                                item.thumbnail_base64, item.identifier))
            bounded_attachments.append(item)
        total += sum(utf8_size(v) for v in (str(device), str(thread), str(uid), str(sub)))
        if total > cls.MAX_RECORD_BYTES:
            raise ValueError('KDE Connect message record exceeds its size limit')
        # Keep 64-bit identities as decimal strings across JSON / JavaScript.
        message = cls(bounded_text(device, 256), bounded_text(str(thread), 256), bounded_text(str(uid), 256), safe_addresses, timestamp,
                   kind, 'incoming' if kind == 1 else 'outgoing' if kind in range(2, 7) else 'unknown',
                   STATES.get(kind, 'unknown'), read, bounded_text(str(sub), 256), body,
                   bounded_attachments, event, addresses_complete)
        if message.serialized_size() > cls.MAX_SERIALIZED_BYTES:
            raise ValueError('KDE Connect message record exceeds its serialized size limit')
        return message

    def serialized_size(self):
        return len(json.dumps(self.json(), ensure_ascii=False).encode('utf-8'))

    def json(self):
        return asdict(self)


@dataclass
class Conversation:
    device_id: str
    thread_id: str
    messages: dict = field(default_factory=dict)
    message_bytes: dict = field(default_factory=dict)
    # Never interpret this as total history or an end-of-history marker.
    daemon_cached_count: int | None = None
    next_offset: int = 0
    generation: int = 0
    # Monotonic recipient classification for this worker session. Risk evidence
    # is also kept separately by Store so record eviction cannot erase it.
    reply_status: str = 'unknown'

    def ordered(self):
        return sorted(self.messages.values(), key=lambda m: (m.timestamp, m.message_id), reverse=True)


@dataclass
class Page:
    request_id: str
    device: str
    thread: str
    start: int
    size: int
    deadline: float
    seen: set = field(default_factory=set)
    attempts: int = 1


class Store:
    MAX_THREADS = 200
    MAX_MESSAGES = 300
    MAX_TOTAL_MESSAGES = 2000
    # 32 MiB bounds the complete normalized message JSON retained by the
    # worker, while preserving the existing per-thread and count limits.
    MAX_RETAINED_BYTES = 32 * 1024 * 1024
    # Shared cap for exact singleton authorizations plus group/incomplete risk
    # records. Keep the historical name for compatibility with tests/tools.
    MAX_REPLY_RISKS = 4096
    MAX_UNCERTAIN_DEVICES = 16
    def __init__(self, emit, clock=time.monotonic):
        self.emit, self.clock = emit, clock
        self.threads = {}
        self.pages = {}
        self.session = uuid.uuid4().hex
        self.sequence = 0
        self.message_order = {}
        self.retained_bytes = 0
        # Mutually exclusive per-thread evidence: singleton scope or one risk
        # classification (ordering, incomplete, group). Only ordering is
        # recoverable; incomplete/group are sticky for this Store session.
        # Their combined entry count is independent of payloads and capped.
        self.reply_risks = {}
        # One exact, current singleton authorization per thread, independent
        # of retained messages: (recipient tuple, timestamp, message id).
        self.reply_scopes = {}
        # Ordering metadata, never recovery eligibility. Keys are a subset of
        # reply_risks (including risks strengthened to sticky hazards), so the
        # metadata shares the 4,096-entry bound. Recovery requires the explicit
        # 'ordering' classification as well as strictly newer evidence.
        self.reply_ordering_watermarks = {}
        self.reply_uncertain_devices = set()
        self.reply_uncertain_all = False

    def _device_uncertain(self, device):
        return self.reply_uncertain_all or device in self.reply_uncertain_devices

    def _mark_device_uncertain(self, device):
        if self._device_uncertain(device):
            return
        if len(self.reply_uncertain_devices) >= self.MAX_UNCERTAIN_DEVICES:
            # The global bit replaces the set: every future device is blocked,
            # so clearing per-device entries cannot reauthorize one.
            self.reply_uncertain_all = True
            self.reply_uncertain_devices.clear()
            self.emit({'event': 'reply_scope_uncertain', 'all': True})
            return
        self.reply_uncertain_devices.add(device)
        self.emit({'event': 'reply_scope_uncertain', 'device': device})

    def _publish_reply_status(self, device, thread, status, recovered=False):
        if self._device_uncertain(device):
            return
        event = {'event': 'reply_scope', 'device': device, 'thread': thread,
                 'reply_status': status}
        if self.reply_risks.get((device, str(thread))) == 'ordering':
            event['reply_risk'] = 'ordering'
        if recovered:
            event['reply_scope_recovered'] = True
        if status == 'individual':
            scope = self.reply_scopes.get((device, str(thread)))
            if scope:
                event['recipient_scope'] = list(scope[0])
        token = self.token(device, thread)
        if token:
            event['conversation_token'] = token
        self.emit(event)

    def _authorization_state(self, key):
        scope = self.reply_scopes.get(key)
        recipient_scope = scope[0] if scope else None
        return (self.reply_status(*key), recipient_scope, self.token(*key),
                self._device_uncertain(key[0]), self.reply_risks.get(key))

    def _publish_authorization_change(self, key, before):
        if before != self._authorization_state(key) and key in self.threads:
            self._publish_reply_status(*key, self.reply_status(*key),
                recovered=before[4] == 'ordering' and self.reply_status(*key) == 'individual')

    @staticmethod
    def _message_order(message):
        return message.timestamp, len(message.message_id), message.message_id

    def token(self, device, thread):
        c = self.threads.get((device, str(thread)))
        return self.session + ':' + str(c.generation) if c else ''

    def conversation(self, device, thread):
        key = (device, str(thread))
        if key not in self.threads and len(self.threads) >= self.MAX_THREADS:
            victim = next((k for k in self.threads if k not in self.pages), None)
            if victim is not None:
                self._drop_conversation(victim)
                self.emit({'event': 'thread_evicted', 'device': victim[0], 'thread': victim[1]})
        if key not in self.threads:
            self.sequence += 1
            self.threads[key] = Conversation(*key, generation=self.sequence)
            self.threads[key].reply_status = self._effective_reply_status(key)
        return self.threads[key]

    @staticmethod
    def _record_reply_status(message, raw_addresses):
        if len(raw_addresses) > 1:
            return 'group'
        if len(raw_addresses) != 1 or not message.addresses_complete or len(message.addresses) != 1:
            return 'incomplete'
        return 'individual'

    @staticmethod
    def _merge_reply_status(previous, observed):
        if previous == 'group' or observed == 'group':
            return 'group'
        if previous == 'incomplete':
            return 'incomplete'
        if previous == 'unknown':
            return observed
        return observed

    def _effective_reply_status(self, key):
        if self._device_uncertain(key[0]):
            return 'unknown'
        risk = self.reply_risks.get(key)
        return ('incomplete' if risk == 'ordering' else risk) if risk else (
            'individual' if key in self.reply_scopes else 'unknown')

    def reply_status(self, device, thread):
        key = (device, str(thread))
        if self._device_uncertain(device):
            return 'unknown'
        return self._effective_reply_status(key)

    def _evidence_count(self):
        return len(self.reply_risks) + len(self.reply_scopes)

    def _advance_generation(self, conversation):
        self.sequence += 1
        conversation.generation = self.sequence

    def _record_risk(self, conversation, status):
        key = (conversation.device_id, conversation.thread_id)
        previous = self.reply_risks.get(key)
        # Monotone hazard strength: ordering < incomplete < group. A retained
        # watermark can never downgrade a sticky hazard to ordering-only.
        if previous == 'group' or status == 'group':
            status = 'group'
        elif previous == 'incomplete' or status == 'incomplete':
            status = 'incomplete'
        if key not in self.reply_risks and key not in self.reply_scopes and self._evidence_count() >= self.MAX_REPLY_RISKS:
            self._mark_device_uncertain(conversation.device_id)
            conversation.reply_status = 'unknown'
            return 'unknown'
        self.reply_scopes.pop(key, None)
        self.reply_risks[key] = status
        if previous != status:
            self._advance_generation(conversation)
        conversation.reply_status = self._effective_reply_status(key)
        return conversation.reply_status

    def _record_ordering_risk(self, conversation, watermark):
        key = (conversation.device_id, conversation.thread_id)
        if key not in self.reply_risks and key not in self.reply_scopes and self._evidence_count() >= self.MAX_REPLY_RISKS:
            self._mark_device_uncertain(conversation.device_id)
            conversation.reply_status = 'unknown'
            return 'unknown'
        prior = self.reply_ordering_watermarks.get(key)
        if prior is None or watermark > prior:
            self.reply_ordering_watermarks[key] = watermark
        status = self._record_risk(conversation, 'ordering')
        # _record_risk removes any singleton scope while preserving the
        # bounded, nonregressing marker above.
        return status

    def _observe_reply_status(self, conversation, message, raw_addresses):
        key = (conversation.device_id, conversation.thread_id)
        if self._device_uncertain(conversation.device_id):
            conversation.reply_status = 'unknown'
            return 'unknown'
        observed = self._record_reply_status(message, raw_addresses)
        # Classify hazards before considering recovery. Accepted group or
        # incomplete evidence is sticky even during an ordering ambiguity.
        if observed in ('group', 'incomplete'):
            return self._record_risk(conversation, observed)
        if self.reply_risks.get(key) == 'ordering':
            watermark = self.reply_ordering_watermarks[key]
            if self._message_order(message) > watermark:
                # A strictly newer accepted singleton is fresh evidence. A
                # replay at/below the invalidated proof watermark stays blocked.
                self.reply_risks.pop(key, None)
                self.reply_ordering_watermarks.pop(key, None)
                self.reply_scopes[key] = (tuple(message.addresses), message.timestamp, message.message_id)
                self._advance_generation(conversation)
                conversation.reply_status = 'individual'
                return 'individual'
            conversation.reply_status = 'incomplete'
            return conversation.reply_status
        if key in self.reply_risks:
            status = self._merge_reply_status(self.reply_risks[key], observed)
            if status != self.reply_risks[key]:
                status = self._record_risk(conversation, status)
            conversation.reply_status = status
        else:
            scope = tuple(message.addresses)
            previous = self.reply_scopes.get(key)
            if previous is None and self._evidence_count() >= self.MAX_REPLY_RISKS:
                self._mark_device_uncertain(conversation.device_id)
                status = 'unknown'
            else:
                replaces_proof = previous is not None and message.message_id == previous[2]
                message_order = self._message_order(message)
                previous_order = ((previous[1], len(previous[2]), previous[2])
                                  if previous is not None else None)
                if (replaces_proof and previous[0] != scope and
                        message_order <= previous_order):
                    # A changed proof with an older/equal order is ambiguous
                    # history, not fresh authorization. Keep its high-water
                    # marker and fail closed until strictly newer evidence.
                    return self._record_ordering_risk(conversation, previous_order)
                if (previous is not None and not replaces_proof and
                        message_order < previous_order):
                    # Older history can arrive after the current head. It does
                    # not supersede recipient evidence unless it replaces the
                    # very message that established that evidence. A changed
                    # recipient on that UID must invalidate the old scope even
                    # if its timestamp moves backwards.
                    status = 'individual'
                    conversation.reply_status = status
                    return 'unknown' if self._device_uncertain(conversation.device_id) else status
                if replaces_proof and previous[0] == scope and message_order < previous_order:
                    # Same-recipient timestamp rollback cannot lower the
                    # freshness watermark used to classify later history.
                    self.reply_scopes[key] = (scope, previous[1], previous[2])
                    conversation.reply_status = 'individual'
                    return 'individual'
                if previous is not None and previous[0] != scope:
                    self._advance_generation(conversation)
                self.reply_scopes[key] = (scope, message.timestamp, message.message_id)
                status = 'individual'
                conversation.reply_status = status
        return 'unknown' if self._device_uncertain(conversation.device_id) else status

    def observe_rejected_record(self, device, wire):
        """Keep only bounded recipient evidence when a record cannot be retained."""
        if self._device_uncertain(device):
            return
        thread = None
        observed = None
        if isinstance(wire, (tuple, list)) and len(wire) == 10:
            raw_thread, raw_addresses = wire[6], wire[2]
            if (isinstance(raw_thread, int) and not isinstance(raw_thread, bool) and
                    -(2**63) <= raw_thread < 2**63):
                thread = str(raw_thread)
                if isinstance(raw_addresses, (tuple, list)):
                    if len(raw_addresses) > 1:
                        observed = 'group'
                    elif len(raw_addresses) == 1:
                        address = raw_addresses[0]
                        if (isinstance(address, (tuple, list)) and address and
                                isinstance(address[0], str) and address[0] and len(address[0]) <= Message.MAX_ADDRESS_BYTES and
                                utf8_size(address[0]) <= Message.MAX_ADDRESS_BYTES and
                                not any(0xd800 <= ord(char) <= 0xdfff for char in address[0])):
                            observed = 'individual'
                        else:
                            observed = 'incomplete'
                    else:
                        observed = 'incomplete'
        if thread is None or observed is None:
            # Without a bounded key/scope, no surviving individual reply on
            # this device can safely authorize a reply during this worker.
            self._mark_device_uncertain(device)
            return
        key = (device, thread)
        before = self._authorization_state(key)
        conversation = self.threads.get(key)
        previous_scope = self.reply_scopes.get(key)
        wire_order = None
        rejected_singleton = observed == 'individual'
        if observed == 'individual':
            address = wire[2][0][0]
            raw_id = None
            if (isinstance(wire[3], int) and not isinstance(wire[3], bool) and
                    -(2**63) <= wire[3] < 2**63 and
                    isinstance(wire[7], int) and not isinstance(wire[7], bool)):
                try:
                    raw_id = str(wire[7])
                except ValueError:
                    raw_id = ''
                if raw_id and utf8_size(raw_id) <= 256:
                    wire_order = (wire[3], len(raw_id), raw_id)
            previous_order = (previous_scope[1], len(previous_scope[2]), previous_scope[2]) if previous_scope else None
            replaces_proof = previous_scope is not None and raw_id == previous_scope[2]
            if previous_scope is not None and previous_scope[0] == (address,):
                # Rejected same-recipient evidence cannot supersede the
                # retained recipient authorization. It can still advance the
                # bounded freshness watermark, never lower it or replace the
                # accepted proof UID.
                if wire_order is not None and wire_order > previous_order:
                    self.reply_scopes[key] = (previous_scope[0], wire_order[0], previous_scope[2])
                return
            if (previous_scope is not None and previous_scope[0] != (address,) and
                    (replaces_proof or wire_order is None or wire_order >= previous_order)):
                if conversation is None:
                    conversation = self.conversation(device, thread)
                if wire_order is None:
                    # Unknown conflict order cannot support a recovery proof.
                    self._record_risk(conversation, 'incomplete')
                else:
                    self._record_ordering_risk(conversation, max(previous_order, wire_order))
                self._publish_authorization_change(key, before)
                return
            if (previous_scope is not None and not replaces_proof and
                    wire_order is not None and wire_order < previous_order):
                return
            observed = 'incomplete'  # rejected evidence never grants authorization
        if conversation is None:
            conversation = self.conversation(device, thread)
        if (rejected_singleton and wire_order is not None and
                self.reply_risks.get(key) == 'ordering'):
            self._record_ordering_risk(conversation, wire_order)
        else:
            self._record_risk(conversation, observed)
        self._publish_authorization_change(key, before)

    def _reject_unretained(self, conversation, observed_scope, previous_scope=None, message=None):
        key = (conversation.device_id, conversation.thread_id)
        current = self.reply_scopes.get(key)
        order_is_older = (observed_scope is not None and previous_scope is not None and
                          message is not None and
                          message.message_id != previous_scope[2] and
                          self._message_order(message) < (previous_scope[1], len(previous_scope[2]), previous_scope[2]))
        if (observed_scope is not None and previous_scope is not None and current is not None and
                (previous_scope[0] == observed_scope or order_is_older)):
            # A same-recipient rejected update does not supersede the prior
            # reliable proof, including its ordering metadata.
            self.reply_scopes[key] = previous_scope
            return self.reply_status(*key)
        proof = current or previous_scope
        if (message is not None and proof is not None and observed_scope is not None and
                (message.message_id == proof[2] and observed_scope != proof[0] or current is not None)):
            self._record_ordering_risk(conversation,
                max((proof[1], len(proof[2]), proof[2]), self._message_order(message)))
        elif observed_scope is not None and self.reply_risks.get(key) == 'ordering':
            # A rejected singleton cannot recover ordering risk, but is not
            # an ordinary incomplete-recipient observation either.
            self._record_ordering_risk(conversation, self._message_order(message))
        else:
            self._record_risk(conversation, 'incomplete')
        return self.reply_status(*key)

    def ingest(self, device, wire, history_signal=False):
        try:
            message = Message.decode(device, wire)
        except (ValueError, TypeError, IndexError, OverflowError):
            self.observe_rejected_record(device, wire)
            raise
        key = (device, message.thread_id)
        authorization_before = self._authorization_state(key)
        created = key not in self.threads
        conversation = self.conversation(device, message.thread_id)
        prior = conversation.messages.get(message.message_id)
        prior_scope = self.reply_scopes.get(key)
        ordering_recovery = self.reply_risks.get(key) == 'ordering'
        reply_status = self._observe_reply_status(conversation, message, wire[2])
        event = {'event': 'message', 'message': message.json(),
                 'conversation_token': self.token(device, message.thread_id),
                 'source': 'history_or_live' if history_signal else 'summary',
                 'reply_status': reply_status,
                 'delivery_confirmed': None, 'read_receipt': None}
        if self.reply_risks.get(key) == 'ordering':
            event['reply_risk'] = 'ordering'
        if ordering_recovery and reply_status == 'individual':
            # The UI treats ordinary incomplete/group classifications as
            # sticky. Explicitly mark the narrowly permitted strictly-newer
            # singleton recovery so HistoryState can mirror this transition.
            event['reply_scope_recovered'] = True
        if reply_status == 'individual':
            scope = self.reply_scopes.get(key)
            if scope:
                event['recipient_scope'] = list(scope[0])
        if json_line_size(event) > Message.MAX_SERIALIZED_BYTES:
            self._reject_unretained(conversation, tuple(message.addresses) if message.addresses_complete and len(message.addresses) == 1 else None, prior_scope, message)
            if created and not conversation.messages:
                self._drop_conversation(key)
            self._publish_authorization_change(key, authorization_before)
            raise ValueError('KDE Connect message event exceeds its serialized size limit')
        message_size = message.serialized_size()
        if message_size > self.MAX_RETAINED_BYTES:
            self._reject_unretained(conversation, tuple(message.addresses) if message.addresses_complete and len(message.addresses) == 1 else None, prior_scope, message)
            if created and not conversation.messages:
                self._drop_conversation(key)
            self._publish_authorization_change(key, authorization_before)
            raise ValueError('KDE Connect message exceeds the retained memory budget')
        if prior is not None:
            self.retained_bytes -= conversation.message_bytes.get(message.message_id, prior.serialized_size())
        conversation.messages[message.message_id] = message
        conversation.message_bytes[message.message_id] = message_size
        self.retained_bytes += message_size
        if prior is None:
            self.message_order[key + (message.message_id,)] = None
        while len(conversation.messages) > self.MAX_MESSAGES:
            oldest = next(iter(conversation.messages))
            self._remove_message(conversation, oldest, emit=False)
        while sum(len(c.messages) for c in self.threads.values()) > self.MAX_TOTAL_MESSAGES or self.retained_bytes > self.MAX_RETAINED_BYTES:
            oldest_key = next(iter(self.message_order), None)
            if oldest_key is None:
                break
            victim = self.threads.get(oldest_key[:2])
            if victim is None or oldest_key[2] not in victim.messages:
                self.message_order.pop(oldest_key, None)
                continue
            removed = oldest_key[2]
            self._remove_message(victim, removed, emit=True)
        page = self.pages.get((device, message.thread_id))
        if page and history_signal and len(page.seen) < page.size + 2:
            page.seen.add(message.message_id)
        if prior != message and message.message_id in conversation.messages:
            self.emit(event)
        elif message.message_id not in conversation.messages:
            # A discarded record cannot establish a new UI authorization.
            # An unchanged existing scope remains reliable; a changed or new
            # scope is invalidated by _reject_unretained.
            scope = self.reply_scopes.get(key)
            if scope and scope[2] == message.message_id:
                observed_scope = (tuple(message.addresses) if message.addresses_complete and
                                  len(message.addresses) == 1 else None)
                self._reject_unretained(conversation, observed_scope, prior_scope, message)
        if not (prior != message and message.message_id in conversation.messages):
            self._publish_authorization_change(key, authorization_before)
        return message

    def _remove_message(self, conversation, message_id, emit=False):
        message = conversation.messages.pop(message_id, None)
        if message is None:
            return
        self.retained_bytes -= conversation.message_bytes.pop(message_id, message.serialized_size())
        self.message_order.pop((conversation.device_id, conversation.thread_id, message_id), None)
        if emit:
            self.emit({'event': 'messages_evicted', 'device': conversation.device_id,
                       'thread': conversation.thread_id, 'ids': [message_id]})

    def _drop_conversation(self, key):
        conversation = self.threads.pop(key, None)
        if conversation is None:
            return
        for message_id in list(conversation.messages):
            self._remove_message(conversation, message_id)

    def remove_conversation(self, device, thread):
        key = (device, str(thread))
        self._drop_conversation(key)

    def begin_page(self, request, device, thread, size=25):
        key = (device, str(thread))
        if key in self.pages:
            raise ValueError('History is already loading for this conversation')
        if len(self.pages) >= 4:
            raise ValueError('History is busy. Wait for the current requests to finish.')
        if not 1 <= size <= 100:
            raise ValueError('Page size must be between 1 and 100')
        conversation = self.conversation(*key)
        page = Page(request, *key, conversation.next_offset, size, self.clock() + 15)
        self.pages[key] = page
        return page

    def finish_page(self, key, reason):
        page = self.pages.pop(key)
        conversation = self.conversation(*key)
        # Shared signals cannot prove a page is complete. Overlap pages to absorb
        # index shifts while new messages arrive; identity deduplication handles repeats.
        if page.seen:
            conversation.next_offset = max(conversation.next_offset,
                                           page.start + max(1, min(page.size, len(page.seen)) - 2))
        self.emit({'event': 'history_result', 'request_id': page.request_id,
                   'device': page.device, 'thread': page.thread, 'reason': reason,
                   'received': len(page.seen), 'next_offset': conversation.next_offset,
                   'exhaustive': False, 'complete': None})

    def reset_device(self, device):
        for key in list(self.pages):
            if key[0] == device:
                self.finish_page(key, 'disconnected')
        for key, thread in self.threads.items():
            if key[0] == device:
                for message_id in list(thread.messages):
                    self._remove_message(thread, message_id)
                thread.next_offset = 0
                thread.daemon_cached_count = None
                self.sequence += 1
                thread.generation = self.sequence
