# Installation, pairing, update, migration and rollback

This guide describes the reviewed Omarchy plugin manager. The public repository is not published yet. Do not use the example repository URL until the release has been approved and that URL/default branch has been verified.

## KDE Connect and Android setup

Install KDE Connect desktop on Omarchy and the KDE Connect app on Android using the project's [official download page](https://kdeconnect.kde.org/download.html). Open both apps on devices that can reach one another on the same local network, request pairing from either side, and accept the request on the other device. If discovery fails, check local network/firewall reachability; the [KDE UserBase pairing guide](https://userbase.kde.org/KDEConnect/en#Pairing_two_devices_together) has troubleshooting steps.

Enable only the KDE Connect plugins you need. SMS/MMS features require the Android app's SMS permission and SMS plugin; contact names require Contacts permission and contact synchronization. Notification forwarding requires enabling Notification Sync and granting KDE Connect Android's notification access in Android Settings. Android labels and permission prompts vary by version. KDE's [Android permission explanation](https://community.kde.org/KDEConnect/PrivacyPolicy#Android_permissions) describes why the app requests each permission. Pocket Extended does not grant these permissions itself.

File integration is optional. Sending files and selecting SMS/MMS attachments requires Omarchy's `omarchy-file-select`; plain SMS and notifications do not. Browsing files on the phone additionally requires host `sshfs`, `kio-fuse`, Nautilus and the corresponding KDE Connect file-browsing setup on the phone. Python 3, PyGObject/Gio, GLib, KDE Connect desktop, Quickshell, Qt 6 and Omarchy's `qs.Commons`/`qs.Ui` modules are runtime requirements for the tested setup.

## Before changing an installation

Do not begin an update or migration with an unresolved send/reply or file picker. Wait for an authoritative result where possible. If a worker disconnect or timeout leaves the outcome uncertain, do not retry automatically; check the conversation/phone before deciding whether a new action is needed. Pocket does not replay pending actions.

Copy unsent text out of each open composer before a full Service/plugin unload or shell restart. Drafts are in memory and may be lost when the Service unloads. A panel-only recreation while the Service remains alive has a separate bounded draft recovery path, but that is not a disk backup.

The plugin directory is normally:

```sh
PLUGIN_ID=io.github.oidium.pocket-extended
PLUGIN_DIR="$HOME/.config/omarchy/plugins/$PLUGIN_ID"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/omarchy-pocket-extended"
STATE_FILE="$STATE_DIR/notification-removals-v1.json"
```

`STATE_FILE` is outside the plugin directory. It contains Pocket's bounded local notification suppression/occurrence state. Removing a notification in Pocket is local-only and does not dismiss it on the phone. The plugin manager does not clear this file, but keep a backup across replacement so a failed migration cannot force a fresh suppression history.

For any manual migration or rollback, make a complete backup outside the active plugin directory before disabling or moving it:

```sh
BACKUP_ROOT="$HOME/.local/state/pocket-extended-backups/$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -m 700 -p "$BACKUP_ROOT"
cp -a "$PLUGIN_DIR" "$BACKUP_ROOT/plugin"
if test -f "$STATE_FILE"; then
  cp -a "$STATE_FILE" "$BACKUP_ROOT/notification-removals-v1.json"
fi
```

Verify the copy before continuing, and keep it outside `~/.config/omarchy/plugins` so the scanner sees only one active directory for this ID:

```sh
diff -qr -- "$PLUGIN_DIR" "$BACKUP_ROOT/plugin"
if test -f "$STATE_FILE"; then
  cmp -- "$STATE_FILE" "$BACKUP_ROOT/notification-removals-v1.json"
fi
```

Stop if either comparison fails. Keep the verified backup until the replacement has been validated and the user state is confirmed.

## 1. Fresh installation: plugin ID absent

Use this only when `PLUGIN_DIR` does not exist and the plugin ID is not already registered:

```sh
test ! -e "$PLUGIN_DIR"
omarchy plugin add https://github.com/oidium/omarchy-pocket-extended.git
```

The manager clones the repository's current default `HEAD`, validates its manifest, and refuses a duplicate ID or target directory. It does not select a release version or commit. In an interactive run, approve cloning only after reviewing the repository, then answer **No** to the later prompt to enable it until you have checked the installed commit. For noninteractive use, `--yes` also skips the trust prompt, so use it only after independently reviewing the exact repository. Before enabling, compare `git -C "$PLUGIN_DIR" rev-parse HEAD` with the exact reviewed public commit for the release, then run:

```sh
git -C "$PLUGIN_DIR" rev-parse HEAD
omarchy plugin validate "$PLUGIN_DIR"
omarchy plugin enable "$PLUGIN_ID"
```

If the commit is not the reviewed commit, leave it disabled and remove/restore it only using the backup procedure below. The URL above is an example for a future approved publication; it is not usable for this unpublished candidate.

## 2. Update: existing Git install from the same public lineage

This procedure is for an installation whose `.git` checkout uses the same public repository as `origin` and whose current commit can fast-forward to that remote's default `HEAD`. Save unsent drafts, resolve pending sends/file pickers, and do not replay an action with an uncertain outcome. Make and verify the complete plugin and external-state backup above. Pocket's manifest sets `keepLoaded: true`: a plugin rescan alone retains the existing Service and worker. Successfully disable Pocket first so Omarchy destroys that Service before changing its files. If disable fails, stop and do not update.

```sh
omarchy plugin disable "$PLUGIN_ID"
omarchy plugin update "$PLUGIN_ID"
git -C "$PLUGIN_DIR" rev-parse HEAD
omarchy plugin validate "$PLUGIN_DIR"
```

Compare the printed commit to the exact reviewed commit before enabling. Only after the update succeeds, the expected commit matches and validation succeeds, enable Pocket:

```sh
omarchy plugin enable "$PLUGIN_ID"
```

If the update or validation fails, leave Pocket disabled. The manager rolls back a merged commit if its validation fails, but fetch/merge failures can also leave the old files in place; neither outcome should be enabled without review. Diagnose or follow the verified backup/restore procedure in section 5. Do not retry an uncertain send.

The reviewed manager runs `git fetch origin HEAD` and `git merge --ff-only FETCH_HEAD`. It follows the remote's default `HEAD`, does not accept a ref/version selector, and may therefore advance beyond a particular release if that default branch has moved. It refuses non-Git directories and unrelated/non-fast-forward history. Do not use this command to migrate the currently installed manual/private V6 or an unrelated Git checkout. Updating while disabled and enabling after validation gives the new code a fresh Service/worker owner; a rescan alone does not restart a `keepLoaded` Service.

## 3. Migration: manual/non-Git installation, including private V6

A manual installation has no `.git`; `omarchy plugin update` rejects it. Save/copy drafts and resolve pending actions as described above. Back up the complete plugin directory and external state. Then disable the old plugin and move its active directory out of the plugin scan path:

```sh
omarchy plugin disable "$PLUGIN_ID"
mv -- "$PLUGIN_DIR" "$BACKUP_ROOT/disabled-plugin"
```

After public release approval, add the reviewed public repository. In an interactive run, explicitly answer **No** to the prompt asking whether to enable the plugin; omitting `--enable` does not suppress that prompt. Inspect the commit before enabling:

```sh
omarchy plugin add https://github.com/oidium/omarchy-pocket-extended.git
git -C "$PLUGIN_DIR" rev-parse HEAD
omarchy plugin validate "$PLUGIN_DIR"
```

Compare the printed commit with the exact commit approved for that release and validate it. Only then enable it:

```sh
omarchy plugin enable "$PLUGIN_ID"
```

The manager's `add` refuses an existing plugin ID or active target directory. Moving the disabled old directory outside the plugin scan root avoids that duplicate-ID refusal and prevents two active Service/IPC owners. Do not delete the backup or external state during this process.

## 4. Migration: installation with unrelated Git history

An unrelated Git checkout cannot fast-forward to the independent public root. Do not rewrite it with `reset`, change its remote and force-pull, or attempt `plugin update`. Use the same disable, full backup, move-out, public `plugin add`, exact-commit check, validation and enable sequence in section 3. Keep the old `.git` history in the backup for recovery; it is not part of the public candidate.

## 5. Rollback from a verified backup

The plugin manager has no exact-version rollback option. Roll back from the verified full directory backup while the plugin is disabled. If the new directory exists, move it outside the active scan path; then restore the saved plugin directory, validate it, and enable it:

```sh
omarchy plugin disable "$PLUGIN_ID"
# If a replacement directory exists, preserve it outside the scan path first:
mv -- "$PLUGIN_DIR" "$BACKUP_ROOT/failed-plugin"
cp -a "$BACKUP_ROOT/plugin" "$PLUGIN_DIR"
omarchy plugin validate "$PLUGIN_DIR"
omarchy plugin enable "$PLUGIN_ID"
```

If migration used `disabled-plugin`, that directory is the complete old plugin and can be copied back instead of `plugin`. Do not overwrite a newer `STATE_FILE` automatically. Restore the saved state file only if the current copy is missing or unusable and you have verified that the backup belongs to this Pocket installation. External state and KDE Connect caches are not reverted by restoring plugin files.

If validation or enable fails, leave the plugin disabled and retain both backup and failed replacement for diagnosis. Do not repeatedly add/enable versions; resolve one active plugin directory and one Service owner before retrying.

## Disable and uninstall

```sh
omarchy plugin disable "$PLUGIN_ID"
omarchy plugin remove "$PLUGIN_ID"
```

The manager removes plugin files but does not remove `STATE_FILE` or KDE Connect's paired-device data/caches. Decide separately whether to retain or delete the external state after backing it up. No phone notification is dismissed by uninstall.
