# Pocket Extended architecture

Pocket Extended is a Quickshell bar widget that presents KDE Connect desktop state. It does not implement a phone protocol or maintain a persistent copy of phone messages or contacts.

## Ownership and process lifecycle

Omarchy loads one plugin `Service.qml` and may create a `Panel.qml` instance for each monitor. The Service owns one `messaging_service.py` process, D-Bus subscriptions, worker restart/shutdown behavior, and shared notification, contact, media and history state. Closing a popup does not stop the worker. Unloading the plugin or restarting the shell stops it.

Panel UI state, selection and active editing remain local to each output. Draft text is copied to a bounded, short-lived-in-memory Service snapshot keyed by output identity so a recreated panel on that output can recover its own draft. Snapshots are not written to disk; a full Service unload loses them. Pending operations and file-picker requests are cleared on recreation and are never automatically replayed.

`NotificationState.js`, `HistoryState.js`, `ComposerState.js` and `MediaState.js` reduce events for QML. The Python worker owns asynchronous KDE Connect operations and bounded in-memory records. `bridge.py` supports the original device controls; messaging uses the single Service worker path.

## Action boundaries

- Notification Reply and Dismiss require current capability, occurrence and worker-epoch evidence. Pocket rechecks authorization before dispatch. Removing a notification locally from Pocket is a separate action and does not send phone Dismiss.
- A new SMS/MMS has an explicit individual recipient. Existing conversation replies are enabled only when the recipient scope is reliably individual. Group, incomplete and uncertain scopes remain visible in history but cannot reply.
- MMS retrieval is tied to a message/attachment identity, validated and opened only after an explicit user action.
- Call events are presented when KDE Connect reports them; Pocket does not create unsupported call controls.

Conversation replies use KDE Connect's `replyToConversation`, whose recipient and SIM selection comes from KDE Connect's cached thread. The API exposes no atomic recipient snapshot. Pocket enforces its observed scope but cannot make that upstream cache selection atomic.

## Retention and persistence

History and contacts are bounded, transient views of KDE Connect data. The worker retains up to 200 threads, 300 messages per thread, 2,000 total messages and 32 MiB of normalized message records. Complete message events are limited to 600 KiB. Notification events and occurrence tracking have separate bounds. Eviction can make history incomplete; it must not authorize a reply whose recipient safety evidence is uncertain.

The only application-owned disk state is the bounded local notification-removal/occurrence record at `${XDG_STATE_HOME:-~/.local/state}/omarchy-pocket-extended/notification-removals-v1.json`. It tracks local suppression and safe occurrence continuity; it is not a phone notification-dismiss command. The worker validates the file's type, owner and size and reports a hydration warning if it cannot trust the saved state. A fresh worker epoch provides a recovery boundary; corrupt state is not silently treated as trustworthy.

KDE Connect separately owns paired-device state, synchronized contacts and its MMS attachment cache. Plugin uninstall does not remove that state. Retrieved MMS files stay in the KDE Connect cache.

## Failure behavior and limits

Device/worker generations and request identities reject stale asynchronous results. Unknown, incomplete, oversized or ambiguous recipient state fails closed. A worker restart can interrupt a submitted action; delivery may then be uncertain and Pocket does not automatically retry it. Draft text may survive panel recreation while the Service lives, but not a complete shell/plugin restart.

The history display is not a complete phone database. KDE Connect does not guarantee a complete-history marker, and outgoing messages may not appear in desktop History. A successful KDE Connect request is submission, not delivery confirmation. The runtime does not upload telemetry or collect background diagnostics; normal operation uses session D-Bus and private process IPC.

## Tested host environment

The reviewed host was Omarchy `4.0.4-1`, Quickshell `0.3.1-1`, Qt base `6.11.2-3`, KDE Connect desktop `26.08.0-1`, and PyGObject `3.56.3-1`. These are tested versions, not minimum requirements. The Android app's exact version was not included in the sanitized public test matrix. No compatibility guarantee is made for other versions, devices or iPhone.

The original Pocket plugin has a separate identity and is not replaced.
