# Proposed Omarchy Marketplace listing

**Name:** Pocket Extended
**Plugin ID:** `io.github.oidium.pocket-extended`
**Proposed version:** `1.0.0-rc.1` (prerelease; release decision pending)
**Category:** Network

**Short description:** An Omarchy bar companion for KDE Connect with device controls, Android notification actions, individual SMS/MMS composition and bounded messaging history.

**Approved preview artwork:** repository-root `preview.png`, SHA-256 `998d166d7eba6477464e70eee82f5546eeee2af628a14f0bddeb5ecf63211f08`. Additional review screenshots are separate, unapproved assets and are not included in this candidate.

The listing must state that KDE Connect desktop and the Android app must be installed, paired and configured manually. Phone notification forwarding requires Android notification access; SMS/MMS requires the Android SMS permission and KDE Connect's SMS plugin. Contacts and Files integrations are optional to their respective features. Pocket Extended supports individual conversation replies; group and uncertain replies are disabled while group history remains visible. KDE Connect submission does not confirm carrier delivery. History may be incomplete and outgoing messages may not appear in desktop History. Compatibility beyond the tested environment, including iPhone compatibility, is not established.

The host versions reviewed were Omarchy `4.0.4-1`, Quickshell `0.3.1-1`, Qt base `6.11.2-3`, KDE Connect desktop `26.08.0-1`, and PyGObject `3.56.3-1`. These are tested versions, not minimum requirements. The exact Android app version is not stated in the sanitized matrix.

Installation, migration and backup/rollback procedures are in [Operations](OPERATIONS.md); pairing references are in the KDE Connect [official download page](https://kdeconnect.kde.org/download.html) and [KDE UserBase](https://userbase.kde.org/KDEConnect/en#Pairing_two_devices_together).

This document is listing copy for review only. It does not indicate Marketplace submission or publication.
