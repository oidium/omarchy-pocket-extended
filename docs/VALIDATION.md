# Validation and test coverage

This document describes synthetic and independent verification. It does not claim universal device compatibility or message delivery.

## Candidate coverage

The public candidate is byte-compared with runtime source from commit `c56f5c1ccb8f481de8c4e8c4fa67f82938a3c8d1`. Public changes are limited to the proposed prerelease manifest version, release documentation, packaging metadata and allowlisted test files. See the accompanying packaging evidence for per-file comparison.

The implementation self-validation recorded 273 Python tests (including 38 Quickshell production-component cases), 62 JavaScript checks, 56 Qt/QML tests, synthetic runtime regression, Python compilation, plugin validation and whitespace checks. These are reported as implementation-run results. Independent verification of the R1 correction then passed 12 affected production-component tests and nine focused authorization/lifecycle probes against the exact runtime commit. The preceding independent audit ran the full suites against the byte-equivalent runtime base. These scopes are distinct; the focused rerun is not described as a new full-suite run.

The full runtime suites can be run from the repository root:

```sh
python -m unittest discover -v
node tests/test_notification_state.cjs
node tests/test_composer_state.cjs
node tests/test_history_state.cjs
node tests/test_media_state.cjs
node tests/test_integration.cjs
node tests/test_retention_cross_layer.cjs
QT_QPA_PLATFORM=offscreen QT_QPA_PLATFORMTHEME=basic QT_QUICK_CONTROLS_STYLE=Basic QT_QUICK_BACKEND=software /usr/lib/qt6/bin/qmltestrunner -input tests/qml -o -,txt
python tools/runtime_regression.py
omarchy plugin validate .
```

`tests/test_packaging_operations.py` is an additional host-script regression. When the Omarchy plugin manager is present, it runs copied `omarchy-plugin-add` and `omarchy-plugin-update` scripts only after changing their plugin root to a disposable temporary directory. Git origins in the test are local temporary repositories; shell/rescan calls are stubbed. It covers absent-ID add, duplicate refusal, non-Git rejection, same-lineage fast-forward, unrelated-history rejection, and backup/restore with an external notification-state sentinel. It does not call the manager against the installed plugin. The test skips when the host scripts or required local tools are unavailable.

The Quickshell component tests require an Omarchy Wayland session, installed Quickshell and Omarchy QML modules. `tools/runtime_regression.py` exercises the synthetic actual-Panel preview path and does not start the messaging worker or connect to a phone. The general `tools/preview.py` utility uses temporary XDG config/state/cache paths but is not fully isolated: it symlinks shared Omarchy QML modules, retains the session environment/compositor, and those modules may read host theme/font configuration. It does not instantiate Pocket's Service or worker in preview mode. Do not run it as a screenshot sandbox or rely on it to hide other desktop surfaces. No screenshot-capture helper is included in this package.

Compilation may be checked with `python -m compileall -q` over runtime and tests. Validation output is synthetic and does not constitute live phone acceptance.

## Security-relevant coverage

Tests cover recipient classification, fail-closed group/incomplete/uncertain scopes, bounded history and framing, rejected-record safety observations, notification occurrence/epoch binding, consumed and pending action tokens, panel restoration, MMS file identity/validation, media snapshot whitelisting, notification-removal persistence and cross-layer UI command behavior. The actual production Panel Send control and production worker paths are exercised by Quickshell tests with fake D-Bus transports.

The R1 independent follow-up reproduced stale draft dispatch on the parent and verified zero stale dispatches on the corrected commit for closure/reuse and worker replacement. It also verified a valid current draft dispatches exactly once. No live messages or phone notification actions were sent by those tests.

## Live validation limits

The prior controlled testing record documents specific Android SMS/MMS, notification and attachment operations. Those observations apply only to the exact tested setup; they do not establish universal compatibility or carrier delivery. The sanitized public host matrix is: Omarchy `4.0.4-1`, Quickshell `0.3.1-1`, Qt base `6.11.2-3`, KDE Connect desktop `26.08.0-1`, and PyGObject `3.56.3-1`. These are tested versions, not minimums. The Android app version is not listed in the sanitized matrix. Outgoing History synchronization remains a known limitation. This public export preparation performs no installation or live-phone operation.

The repository also contains an opt-in `tools/live_readonly_smoke.py` development utility. It launches a separate worker with a temporary `XDG_STATE_HOME`, reads up to two history pages from the currently paired device, keeps message content only in process memory, and prints aggregate counts. It is not part of automated release validation and is not run by the test suite. It deliberately uses live KDE Connect state when invoked. Review its live-data scope before choosing to run it; automated tests verify that its worker environment does not reuse the parent's production persistence path.
