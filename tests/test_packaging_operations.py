"""Disposable regression fixtures for the reviewed Omarchy plugin-manager scripts.

The tests patch only PLUGINS_DIR in copied host scripts. All plugin paths, local
Git origins, and the external state sentinel live below a TemporaryDirectory.
The test never invokes the scripts against the user's installed plugin. The lifecycle stub models enabled/disabled keepLoaded ownership and asserts disable/update/validate/enable ordering; it is not Omarchy production code.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ID = "io.github.oidium.pocket-extended"
IDENTITY = {
    "GIT_AUTHOR_NAME": "oidium",
    "GIT_AUTHOR_EMAIL": "oidium45@proton.me",
    "GIT_COMMITTER_NAME": "oidium",
    "GIT_COMMITTER_EMAIL": "oidium45@proton.me",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_TERMINAL_PROMPT": "0",
}


def git(cwd: Path | None, *args: str, env: dict[str, str] | None = None) -> str:
    proc = subprocess.run(
        ["git", *( ["-C", str(cwd)] if cwd else [] ), *args],
        check=True, capture_output=True, text=True,
        env={**os.environ, **IDENTITY, **(env or {})},
    )
    return proc.stdout.strip()


class PackagingOperationsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.host_add = shutil.which("omarchy-plugin-add")
        cls.host_update = shutil.which("omarchy-plugin-update")
        cls.host_validate = shutil.which("omarchy-plugin-validate")
        cls.host_disable = shutil.which("omarchy-plugin-disable")
        cls.host_enable = shutil.which("omarchy-plugin-enable")
        if not all((cls.host_add, cls.host_update, cls.host_validate,
                    cls.host_disable, cls.host_enable)):
            raise unittest.SkipTest("Omarchy plugin-manager scripts are not installed")
        if not shutil.which("jq"):
            raise unittest.SkipTest("jq is required by the installed plugin manager")

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="pocket-operations-fixture-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.plugins = self.root / "plugins"
        self.plugins.mkdir()
        self.state_file = self.root / "xdg-state" / "omarchy-pocket-extended" / "notification-removals-v1.json"
        self.state_file.parent.mkdir(parents=True)
        self.state_file.write_text('{"fixture":"external-state-sentinel"}\n')
        self.state_hash = self.digest(self.state_file)
        self.lifecycle_file = self.root / "service-lifecycle.json"
        self.lifecycle_file.write_text(json.dumps({
            "enabled": True,
            "owner": "old-service-1",
            "owners_created": 1,
            "owners_destroyed": 0,
        }))
        self.git_config = self.root / "empty-git-config"
        self.git_config.touch()
        self._stub("omarchy-git-url-check", "exit 0\n")
        self._stub("omarchy-plugin-catalog", "printf '[]\\n'\n")
        shell_stub = self.root / "service-lifecycle-stub.py"
        lifecycle_source = "\n".join([
            "import json, pathlib, sys",
            "state_path = pathlib.Path(sys.argv[1])",
            "args = sys.argv[2:]",
            "state = json.loads(state_path.read_text())",
            "if len(args) < 2 or args[0] != 'shell': raise SystemExit('unexpected shell IPC')",
            "method = args[1]",
            "if method == 'setPluginEnabled' and args[-1] == 'false':",
            " state['enabled'] = False",
            " if state['owner'] is not None:",
            "  state['owner'] = None; state['owners_destroyed'] += 1",
            "elif method == 'rescanPlugins':",
            " pass  # keepLoaded owner survives a rescan",
            "elif method == 'enablePlugin':",
            " state['enabled'] = True",
            " if state['owner'] is None:",
            "  state['owners_created'] += 1",
            "  state['owner'] = 'service-owner-' + str(state['owners_created'])",
            "else: raise SystemExit('unexpected shell method: ' + method)",
            "state_path.write_text(json.dumps(state))",
            "print('ok')",
            "",
        ])
        shell_stub.write_text(lifecycle_source)
        self._stub("omarchy-shell", f"exec {sys.executable} {shell_stub} {self.lifecycle_file} \"$@\"\n")
        self._copy_host_script("omarchy-plugin-add", self.host_add)
        self._copy_host_script("omarchy-plugin-update", self.host_update)
        for name, source in (("omarchy-plugin-disable", self.host_disable),
                             ("omarchy-plugin-enable", self.host_enable),
                             ("omarchy-plugin-validate", self.host_validate)):
            copied = self.bin / name
            shutil.copy2(source, copied)
            copied.chmod(0o755)
        validate_copy = self.bin / "omarchy-plugin-validate"
        shutil.copy2(self.host_validate, validate_copy)
        validate_copy.chmod(0o755)

    @staticmethod
    def digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _stub(self, name: str, body: str) -> Path:
        path = self.bin / name
        path.write_text("#!/bin/sh\nset -eu\n" + body)
        path.chmod(0o755)
        return path

    def _copy_host_script(self, name: str, source: str | None) -> Path:
        assert source
        original = Path(source).read_text()
        anchor = 'PLUGINS_DIR="$HOME/.config/omarchy/plugins"'
        if original.count(anchor) != 1:
            self.fail(f"unexpected {name} host script layout; PLUGINS_DIR anchor changed")
        rewritten = original.replace(anchor, f"PLUGINS_DIR='{self.plugins}'")
        path = self.bin / name
        path.write_text(rewritten)
        path.chmod(0o755)
        return path

    def _env(self) -> dict[str, str]:
        return {
            **os.environ,
            **IDENTITY,
            "GIT_CONFIG_GLOBAL": str(self.git_config),
            "PATH": str(self.bin) + os.pathsep + os.environ["PATH"],
            "XDG_STATE_HOME": str(self.root / "xdg-state"),
        }

    def _run(self, script: str, *args: str, ok: bool = True) -> subprocess.CompletedProcess[str]:
        proc = subprocess.run(
            [str(self.bin / script), *args], cwd=self.root,
            env=self._env(), capture_output=True, text=True,
        )
        if ok and proc.returncode != 0:
            self.fail(f"{script} failed ({proc.returncode}): {proc.stdout}\n{proc.stderr}")
        if not ok and proc.returncode == 0:
            self.fail(f"{script} unexpectedly succeeded: {proc.stdout}")
        self.assertEqual(self.digest(self.state_file), self.state_hash)
        return proc

    def _make_bare_origin(self, path: Path) -> Path:
        git(None, "clone", "--bare", str(ROOT), str(path), env={"GIT_CONFIG_GLOBAL": str(self.git_config)})
        git(path, "symbolic-ref", "HEAD", "refs/heads/main")
        return path

    def test_fresh_add_only_when_plugin_id_is_absent(self) -> None:
        target = self.plugins / PLUGIN_ID
        self.assertFalse(target.exists())
        proc = self._run("omarchy-plugin-add", str(ROOT), "--yes")
        self.assertTrue((target / "manifest.json").is_file())
        self.assertIn("Added " + PLUGIN_ID, proc.stdout)
        self.assertIn("Enable it later with:", proc.stdout)

    def test_duplicate_id_refuses_add_without_replacing_existing_files(self) -> None:
        target = self.plugins / PLUGIN_ID
        target.mkdir()
        sentinel = target / "existing-install-sentinel"
        sentinel.write_text("keep existing plugin\n")
        proc = self._run("omarchy-plugin-add", str(ROOT), "--yes", ok=False)
        self.assertIn("already installed", proc.stderr)
        self.assertEqual(sentinel.read_text(), "keep existing plugin\n")
        self.assertFalse((self.plugins / ".add.tmp").exists())

    def test_non_git_manual_install_is_rejected_by_update(self) -> None:
        target = self.plugins / PLUGIN_ID
        target.mkdir()
        (target / "manual-install-sentinel").write_text("non-git V6 fixture\n")
        proc = self._run("omarchy-plugin-update", PLUGIN_ID, ok=False)
        self.assertIn("not a git checkout", proc.stderr)
        self.assertTrue((target / "manual-install-sentinel").exists())

    def test_same_public_lineage_fast_forwards_to_origin_default_head(self) -> None:
        bare = self._make_bare_origin(self.root / "public-lineage.git")
        active = self.plugins / PLUGIN_ID
        producer = self.root / "producer"
        git(None, "clone", str(ROOT), str(active), env={"GIT_CONFIG_GLOBAL": str(self.git_config)})
        git(active, "remote", "set-url", "origin", str(bare))
        git(None, "clone", str(ROOT), str(producer), env={"GIT_CONFIG_GLOBAL": str(self.git_config)})
        git(producer, "remote", "set-url", "origin", str(bare))
        (producer / "manager-fixture-update.txt").write_text("fast-forward fixture\n")
        git(producer, "add", "manager-fixture-update.txt")
        git(producer, "commit", "-m", "fixture fast-forward", env={"GIT_CONFIG_GLOBAL": str(self.git_config)})
        git(producer, "push", "origin", "HEAD:main", env={"GIT_CONFIG_GLOBAL": str(self.git_config)})

        # The previous keepLoaded Service must be gone before files change.
        self._run("omarchy-plugin-disable", PLUGIN_ID)
        disabled = json.loads(self.lifecycle_file.read_text())
        self.assertFalse(disabled["enabled"])
        self.assertIsNone(disabled["owner"])
        self.assertEqual(disabled["owners_destroyed"], 1)
        self._run("omarchy-plugin-update", PLUGIN_ID, "--yes")
        self.assertEqual((active / "manager-fixture-update.txt").read_text(), "fast-forward fixture\n")
        expected = git(bare, "rev-parse", "refs/heads/main")
        self.assertEqual(git(active, "rev-parse", "HEAD"), expected)
        after_update = json.loads(self.lifecycle_file.read_text())
        self.assertFalse(after_update["enabled"])
        self.assertIsNone(after_update["owner"])
        self._run("omarchy-plugin-validate", str(active))
        self.assertEqual(git(active, "rev-parse", "HEAD"), expected)
        self._run("omarchy-plugin-enable", PLUGIN_ID)
        enabled = json.loads(self.lifecycle_file.read_text())
        self.assertTrue(enabled["enabled"])
        self.assertEqual(enabled["owner"], "service-owner-2")
        self.assertEqual(enabled["owners_destroyed"], 1)
        self.assertEqual(enabled["owners_created"], 2)

    def test_validation_failure_after_update_leaves_service_disabled(self) -> None:
        bare = self._make_bare_origin(self.root / "invalid-update-origin.git")
        active = self.plugins / PLUGIN_ID
        producer = self.root / "invalid-update-producer"
        git(None, "clone", str(ROOT), str(active), env={"GIT_CONFIG_GLOBAL": str(self.git_config)})
        git(active, "remote", "set-url", "origin", str(bare))
        git(None, "clone", str(ROOT), str(producer), env={"GIT_CONFIG_GLOBAL": str(self.git_config)})
        git(producer, "remote", "set-url", "origin", str(bare))
        old_head = git(active, "rev-parse", "HEAD")
        (producer / "manifest.json").write_text("{ invalid manifest\n")
        git(producer, "add", "manifest.json")
        git(producer, "commit", "-m", "invalid disposable manifest", env={"GIT_CONFIG_GLOBAL": str(self.git_config)})
        git(producer, "push", "origin", "HEAD:main", env={"GIT_CONFIG_GLOBAL": str(self.git_config)})

        self._run("omarchy-plugin-disable", PLUGIN_ID)
        self._run("omarchy-plugin-update", PLUGIN_ID, "--yes", ok=False)
        self.assertEqual(git(active, "rev-parse", "HEAD"), old_head)
        lifecycle = json.loads(self.lifecycle_file.read_text())
        self.assertFalse(lifecycle["enabled"])
        self.assertIsNone(lifecycle["owner"])
        self.assertEqual(lifecycle["owners_destroyed"], 1)
        self.assertEqual(lifecycle["owners_created"], 1)
        self._run("omarchy-plugin-validate", str(active))
        # Failure handling intentionally does not re-enable the previous owner.
        self.assertIsNone(json.loads(self.lifecycle_file.read_text())["owner"])

    def test_unrelated_git_history_is_not_fast_forwarded(self) -> None:
        bare = self._make_bare_origin(self.root / "independent-public-root.git")
        active = self.plugins / PLUGIN_ID
        git(None, "init", "-q", "-b", "main", str(active), env={"GIT_CONFIG_GLOBAL": str(self.git_config)})
        (active / "unrelated.txt").write_text("unrelated root\n")
        git(active, "add", "unrelated.txt")
        git(active, "commit", "-m", "unrelated installation root", env={"GIT_CONFIG_GLOBAL": str(self.git_config)})
        old_head = git(active, "rev-parse", "HEAD")
        git(active, "remote", "add", "origin", str(bare))
        proc = self._run("omarchy-plugin-update", PLUGIN_ID, "--yes", ok=False)
        self.assertIn("cannot fast-forward", proc.stderr)
        self.assertEqual(git(active, "rev-parse", "HEAD"), old_head)

    def test_backup_restore_uses_one_active_directory_and_preserves_external_state(self) -> None:
        active = self.plugins / PLUGIN_ID
        git(None, "clone", str(ROOT), str(active), env={"GIT_CONFIG_GLOBAL": str(self.git_config)})
        (active / "old-install-marker").write_text("verified backup\n")
        backup_root = self.root / "backup-outside-plugin-root"
        backup_root.mkdir()
        shutil.copytree(active, backup_root / "plugin", symlinks=True)
        shutil.copy2(self.state_file, backup_root / "notification-removals-v1.json")

        self._run("omarchy-plugin-disable", PLUGIN_ID)
        active.rename(backup_root / "disabled-plugin")
        git(None, "clone", str(ROOT), str(active), env={"GIT_CONFIG_GLOBAL": str(self.git_config)})
        self._run("omarchy-plugin-validate", str(active))

        self._run("omarchy-plugin-disable", PLUGIN_ID)
        active.rename(backup_root / "failed-plugin")
        shutil.copytree(backup_root / "plugin", active, symlinks=True)
        self._run("omarchy-plugin-validate", str(active))
        self._run("omarchy-plugin-enable", PLUGIN_ID)
        self.assertEqual((active / "old-install-marker").read_text(), "verified backup\n")
        self.assertEqual([p.name for p in self.plugins.iterdir() if p.name == PLUGIN_ID], [PLUGIN_ID])
        self.assertEqual(self.digest(self.state_file), self.state_hash)
        self.assertEqual(self.digest(backup_root / "notification-removals-v1.json"), self.state_hash)


if __name__ == "__main__":
    unittest.main()
