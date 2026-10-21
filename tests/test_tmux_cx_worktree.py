import os
import json
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import termios
import time
import unittest
import uuid


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/tmux_cx_worktree.py"
sys.path.insert(0, str(SCRIPT.parent))
from tmux_cx_cleanup import check_pintools_resources, cleanup_pintools_resources


class PintoolsCleanupOwnershipTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="tmux-resource-test-")
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.worktree = self.directory / "checkout"
        self.worktree.mkdir()

    def resources(self, status="running", database="ready", foreign=False):
        checkout = str(self.directory / "another-checkout" if foreign else self.worktree)
        (self.directory / "registry.json").write_text(json.dumps({
            "instances": [{"id": "owned-test", "uid": os.getuid(), "checkout": checkout, "status": status}],
        }))
        (self.directory / "databases.json").write_text(json.dumps([
            {"instance": "owned-test", "uid": os.getuid(), "checkout": checkout, "state": database},
        ]))

    def fake_local_launcher(self):
        command = self.directory / "pintools-local"
        command.write_text(
            "#!/usr/bin/env python3\n"
            "from pathlib import Path\nimport json,os,sys\n"
            f"root=Path({str(self.directory)!r})\n"
            "action=sys.argv[1]; instance=sys.argv[2].removeprefix('--instance:')\n"
            "with (root/'commands.jsonl').open('a') as log:\n"
            " log.write(json.dumps({'action':action,'instance':instance,'cwd':os.getcwd()})+'\\n')\n"
            "if (root/('fail-'+action)).exists(): raise SystemExit(3)\n"
            "if action=='stop':\n"
            " p=root/'registry.json'; data=json.loads(p.read_text())\n"
            " for row in data['instances']:\n"
            "  if row['id']==instance: row['status']='stopped'\n"
            "else:\n"
            " p=root/'databases.json'; data=json.loads(p.read_text())\n"
            " for row in data:\n"
            "  if row['instance']==instance: row['state']='released'\n"
            "p.write_text(json.dumps(data))\n"
        )
        command.chmod(0o700)
        return str(command)

    def test_async_teardown_stops_and_releases_owned_resources(self):
        self.resources()
        result = cleanup_pintools_resources(self.worktree, self.directory, self.fake_local_launcher())
        calls = [json.loads(line) for line in (self.directory / "commands.jsonl").read_text().splitlines()]
        self.assertEqual([row["action"] for row in calls], ["stop", "release"])
        self.assertTrue(all(row["instance"] == "owned-test" and row["cwd"] == str(self.worktree) for row in calls))
        self.assertIn("released 1 PinTools database", result)
        check_pintools_resources(self.worktree, self.directory)

    def test_teardown_never_targets_foreign_checkout(self):
        self.resources(foreign=True)
        self.assertEqual(cleanup_pintools_resources(self.worktree, self.directory, self.fake_local_launcher()), "")
        self.assertFalse((self.directory / "commands.jsonl").exists())

    def test_teardown_refuses_mismatched_uid(self):
        self.resources()
        path = self.directory / "registry.json"
        data = json.loads(path.read_text())
        data["instances"][0]["uid"] = os.getuid() + 1
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(RuntimeError, "owner does not match"):
            cleanup_pintools_resources(self.worktree, self.directory, self.fake_local_launcher())
        self.assertFalse((self.directory / "commands.jsonl").exists())

    def test_teardown_refuses_invalid_instance_id(self):
        self.resources()
        path = self.directory / "registry.json"
        data = json.loads(path.read_text())
        data["instances"][0]["id"] = "../foreign"
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(RuntimeError, "identity is invalid"):
            cleanup_pintools_resources(self.worktree, self.directory, self.fake_local_launcher())
        self.assertFalse((self.directory / "commands.jsonl").exists())

    def test_failed_stop_does_not_release_database(self):
        self.resources()
        (self.directory / "fail-stop").touch()
        with self.assertRaisesRegex(RuntimeError, "PinTools stop failed"):
            cleanup_pintools_resources(self.worktree, self.directory, self.fake_local_launcher())
        calls = [json.loads(line) for line in (self.directory / "commands.jsonl").read_text().splitlines()]
        self.assertEqual([row["action"] for row in calls], ["stop"])
        self.assertEqual(json.loads((self.directory / "databases.json").read_text())[0]["state"], "ready")

    def test_failed_release_retains_database_lease(self):
        self.resources()
        (self.directory / "fail-release").touch()
        with self.assertRaisesRegex(RuntimeError, "PinTools release failed"):
            cleanup_pintools_resources(self.worktree, self.directory, self.fake_local_launcher())
        self.assertEqual(json.loads((self.directory / "databases.json").read_text())[0]["state"], "ready")

    def test_already_stopped_instance_still_releases_its_database(self):
        self.resources(status="stopped")
        cleanup_pintools_resources(self.worktree, self.directory, self.fake_local_launcher())
        check_pintools_resources(self.worktree, self.directory)

    def test_running_instance_prevents_cleanup(self):
        self.resources()
        with self.assertRaisesRegex(RuntimeError, "PinTools runtime or database"):
            check_pintools_resources(self.worktree, self.directory)

    def test_stopped_instance_with_retained_database_prevents_cleanup(self):
        self.resources(status="stopped")
        with self.assertRaisesRegex(RuntimeError, "PinTools runtime or database"):
            check_pintools_resources(self.worktree, self.directory)

    def test_stopped_and_released_resources_allow_cleanup(self):
        self.resources(status="stopped", database="released")
        check_pintools_resources(self.worktree, self.directory)

    def test_foreign_checkout_resources_do_not_block_cleanup(self):
        self.resources(foreign=True)
        check_pintools_resources(self.worktree, self.directory)

    def test_invalid_registry_preserves_checkout(self):
        (self.directory / "registry.json").write_text("{")
        with self.assertRaisesRegex(RuntimeError, "could not verify PinTools"):
            check_pintools_resources(self.worktree, self.directory)


@unittest.skipUnless(shutil.which("tmux") and shutil.which("zsh"), "needs tmux and zsh")
class TmuxWorktreeIntegrationTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="tmux-cx-test-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.repo = self.root / "repo with spaces"
        self.repo.mkdir()
        self.managed_root = self.root / "managed"
        self.worktree = self.managed_root / "test" / self.repo.name
        self.worktree.parent.mkdir(parents=True)
        self.startup = self.root / "zsh"
        self.startup.mkdir()
        (self.startup / ".zshrc").write_text('PROMPT="ready> "\n')
        self.env = {
            **os.environ,
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
            "ZDOTDIR": str(self.startup),
            "XDG_STATE_HOME": str(self.root / "state"),
            "TMPDIR": str(self.root),
        }
        self.env.pop("TMUX", None)
        self.env.pop("TMUX_PANE", None)
        self.run_command("git", "-C", str(self.repo), "init", "--initial-branch=main")
        self.run_command(
            "git", "-C", str(self.repo),
            "-c", "user.name=Test", "-c", "user.email=test@example.com",
            "commit", "--allow-empty", "-m", "seed",
        )
        self.socket_name = "cx-test-" + uuid.uuid4().hex[:12]
        self.pane = self.tmux(
            "-f", "/dev/null", "new-session", "-d", "-s", "test",
            "-x", "120", "-y", "40", "-c", str(self.repo),
            "-P", "-F", "#{pane_id}", "exec sleep 60",
        )
        self.socket = Path(self.tmux("display-message", "-p", "#{socket_path}"))
        self.addCleanup(self.remove_test_socket)
        self.addCleanup(self.wait_for_watchers)
        self.addCleanup(self.stop_tmux)
        self.tmux("set-option", "-g", "default-shell", shutil.which("zsh"))

    def run_command(self, *args):
        return subprocess.run(
            args, env=self.env, capture_output=True, text=True, check=True, timeout=30,
        ).stdout.strip()

    def tmux(self, *args):
        return self.run_command("tmux", "-L", self.socket_name, *args)

    def stop_tmux(self):
        subprocess.run(
            ["tmux", "-L", self.socket_name, "kill-server"],
            env=self.env, capture_output=True, timeout=10,
        )

    def remove_test_socket(self):
        self.socket.unlink(missing_ok=True)

    def launcher_command(self, agent_command=None, agent="codex"):
        return [
            "python3", str(SCRIPT), "--repo", str(self.repo),
            "--managed-root", str(self.managed_root),
            "--socket", str(self.socket), "--pane", self.pane,
            "--agent", agent,
            *(["--agent-command", agent_command] if agent_command else []),
        ]

    def launch(self, agent_command=None, agent="codex"):
        result = subprocess.run(
            self.launcher_command(agent_command, agent),
            env=self.env, capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            self.worktree = Path(self.tmux("show-options", "-w", "-v", "@cx_worktree"))
        return result

    def agent_command(self):
        return "exec sleep 60"

    def states(self):
        return [json.loads(path.read_text()) for path in
                (self.root / "state/tmux-cx-worktree").glob("*.json")]

    def wait_for_watchers(self):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if all(state.get("status") in {"removed", "retained"} for state in self.states()):
                return
            time.sleep(0.05)
        self.fail("cleanup watcher did not finish after its tmux server stopped")

    def close_window(self):
        self.tmux("kill-window")
        self.wait_for_watchers()
        states = self.states()
        self.assertEqual(len(states), 1)
        return states[0]

    def commit(self, subject):
        self.run_command("git", "-C", str(self.worktree), "add", "--", "saved.md")
        self.run_command(
            "git", "-C", str(self.worktree),
            "-c", "user.name=Test", "-c", "user.email=test@example.com",
            "commit", "-m", subject,
        )

    def assert_layout(self, directory):
        panes = self.tmux(
            "list-panes", "-F", "#{pane_id}\t#{pane_current_path}\t#{pane_left}\t#{pane_active}",
        ).splitlines()
        self.assertEqual(len(panes), 2)
        left, right = [pane.split("\t") for pane in panes]
        self.assertEqual(Path(left[1]), directory)
        self.assertEqual(Path(right[1]), directory)
        self.assertLess(int(left[2]), int(right[2]))
        self.assertEqual(right[3], "1")

    def test_opens_shell_in_worktree(self):
        result = self.launch(self.agent_command())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_layout(self.worktree)

    def test_neither_pane_runs_automatic_dependency_installation(self):
        bootstrapped = self.root / "unwanted-install"
        ready = self.root / "ready"
        ready.mkdir()
        (self.startup / ".zshrc").write_text(
            'if [[ ${PINTOOLS_READ_ONLY:-0} != 1 ]]; then\n'
            f"  printf install >> {shlex.quote(str(bootstrapped))}\n"
            "fi\n"
            f"touch {shlex.quote(str(ready))}/\"$TMUX_PANE\"\n"
            "cx() { sleep 60; }\n"
            'PROMPT="ready> "\n'
        )
        result = self.launch()
        self.assertEqual(result.returncode, 0, result.stderr)
        deadline = time.monotonic() + 5
        while len(list(ready.iterdir())) < 2 and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertEqual(len(list(ready.iterdir())), 2, "both shells must initialize")
        self.assertFalse(bootstrapped.exists(), "opening panes must not install dependencies")
        self.assert_layout(self.worktree)

    def block_git(self, operation="pull", default_agent=False, agent="codex", fail=False):
        remote = self.root / "origin.git"
        self.run_command("git", "init", "--bare", str(remote))
        self.run_command("git", "-C", str(self.repo), "remote", "add", "origin", str(remote))
        self.run_command("git", "-C", str(self.repo), "push", "origin", "main")
        gate = self.root / "release-git"
        reached = self.root / "git-started"
        binaries = self.root / "bin"
        binaries.mkdir()
        wrapper = binaries / "git"
        condition = {
            "pull": '[ "$3" = pull ]',
            "add": '[ "$3" = worktree ] && [ "$4" = add ]',
            "watch": '[ "$3" = rev-parse ] && [ "$4" = --absolute-git-dir ]',
            "populate": '[ "$3" = sparse-checkout ] && [ "$4" = disable ]',
        }[operation]
        wrapper.write_text(
            "#!/bin/sh\n"
            f"if {condition}; then\n"
            f"  touch {shlex.quote(str(reached))}\n"
            f"  while [ ! -f {shlex.quote(str(gate))} ]; do sleep 0.05; done\n"
            + ("  echo 'simulated repository loading failure' >&2\n  exit 1\n" if fail else "") +
            "fi\n"
            f"exec {shlex.quote(shutil.which('git'))} \"$@\"\n"
        )
        wrapper.chmod(0o700)
        self.env["PATH"] = str(binaries) + os.pathsep + self.env["PATH"]
        process = subprocess.Popen(
            self.launcher_command(None if default_agent else self.agent_command(), agent), env=self.env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )

        def finish():
            gate.touch()
            process.communicate(timeout=15)

        self.addCleanup(finish)
        deadline = time.monotonic() + 5
        while not reached.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue(reached.exists(), "Git should be waiting at the refresh gate")
        return gate, process

    def seed_loading_files(self):
        for name, value in (
            ("AGENTS.md", "repo instructions\n"),
            ("CLAUDE.md", "claude instructions\n"),
            ("README.md", "original readme\n"),
            (".agents/demo/SKILL.md", "demo instructions\n"),
            ("apps/demo/source.txt", "original source\n"),
            ("common/shared.txt", "shared source\n"),
        ):
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(value)
        self.run_command("git", "-C", str(self.repo), "add", ".")
        self.run_command(
            "git", "-C", str(self.repo), "-c", "user.name=Test", "-c",
            "user.email=test@example.com", "commit", "-m", "source fixtures",
        )

    def interactive_agent(self):
        arguments = self.root / "agent-arguments"
        received = self.root / "agent-received"
        (self.startup / ".zshrc").write_text(
            "probe_agent() {\n"
            f"  printf '%s\\0' \"$@\" > {shlex.quote(str(arguments))}\n"
            "  printf 'AGENT_INPUT_READY\\n'\n"
            "  local message\n"
            "  IFS= read -r message\n"
            f"  printf '%s' \"$message\" > {shlex.quote(str(received))}\n"
            "  sleep 60\n"
            "}\n"
            'cx() { probe_agent "$@"; }\n'
            'cc() { probe_agent "$@"; }\n'
            'PROMPT="ready> "\n'
        )
        return arguments, received

    def assert_typing_during_loading(self, agent):
        self.seed_loading_files()
        arguments, received = self.interactive_agent()
        gate, process = self.block_git("populate", default_agent=True, agent=agent)
        self.worktree = Path(self.tmux("show-options", "-w", "-v", "@cx_worktree"))
        right = self.tmux("display-message", "-p", "#{pane_id}")
        deadline = time.monotonic() + 5
        while not arguments.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue(arguments.exists(), "agent must open before bulk checkout finishes")
        instructions = arguments.read_bytes().decode()
        self.assertIn("readiness check", instructions)
        self.assertIn("developer_instructions=" if agent == "codex" else "--append-system-prompt", instructions)
        self.assertTrue((self.worktree / "AGENTS.md").exists())
        self.assertTrue((self.worktree / "CLAUDE.md").exists())
        self.assertTrue((self.worktree / ".agents/demo/SKILL.md").exists())
        self.assertFalse((self.worktree / "apps/demo/source.txt").exists())
        self.assertIsNone(process.poll())
        pid = self.tmux("display-message", "-p", "-t", right, "#{pane_pid}")
        self.tmux("send-keys", "-t", right, "-l", "keep this unfinished draft")
        self.assertFalse(received.exists())
        gate.touch()
        _, errors = process.communicate(timeout=15)
        self.assertEqual(process.returncode, 0, errors)
        self.assertEqual(self.tmux("display-message", "-p", "-t", right, "#{pane_pid}"), pid)
        self.assertIn("keep this unfinished draft", self.tmux("capture-pane", "-p", "-t", right))
        self.tmux("send-keys", "-t", right, "Enter")
        deadline = time.monotonic() + 3
        while not received.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertEqual(received.read_text(), "keep this unfinished draft")
        self.assertTrue((self.worktree / "apps/demo/source.txt").exists())
        self.assert_layout(self.worktree)

    def test_codex_accepts_typing_before_checkout_and_keeps_draft(self):
        self.assert_typing_during_loading("codex")

    def test_starting_panes_do_not_echo_text_as_an_accepted_draft(self):
        gate, process = self.block_git("add")
        right = self.tmux("display-message", "-p", "#{pane_id}")
        terminal_path = self.tmux("display-message", "-p", "-t", right, "#{pane_tty}")
        descriptor = os.open(terminal_path, os.O_RDONLY | os.O_NOCTTY)
        self.addCleanup(os.close, descriptor)
        deadline = time.monotonic() + 3
        while termios.tcgetattr(descriptor)[3] & termios.ECHO and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertFalse(termios.tcgetattr(descriptor)[3] & termios.ECHO)
        self.tmux("send-keys", "-t", right, "-l", "not an accepted draft")
        capture = self.tmux("capture-pane", "-p", "-t", right)
        self.assertIn("Wait for its input prompt", capture)
        self.assertIn("discarded", capture)
        self.assertNotIn("not an accepted draft", capture)
        gate.touch()
        _, errors = process.communicate(timeout=15)
        self.assertEqual(process.returncode, 0, errors)

    def test_second_window_can_open_while_first_repository_loads(self):
        gate, first = self.block_git("populate")
        first_worktree = self.tmux("show-options", "-w", "-v", "@cx_worktree")
        second = subprocess.Popen(
            self.launcher_command(self.agent_command()), env=self.env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )

        def finish_second():
            gate.touch()
            second.communicate(timeout=15)

        self.addCleanup(finish_second)
        deadline = time.monotonic() + 5
        initialized = []
        while time.monotonic() < deadline:
            initialized = [row for row in self.tmux("list-windows", "-F", "#{@cx_agent_seconds}").splitlines() if row]
            if len(initialized) == 2 or second.poll() is not None:
                break
            time.sleep(0.05)
        self.assertEqual(len(initialized), 2, "both agents should open while bulk checkout is gated")
        self.assertIsNone(first.poll())
        self.assertIsNone(second.poll())
        self.assertNotEqual(self.tmux("show-options", "-w", "-v", "@cx_worktree"), first_worktree)
        gate.touch()
        for process in (first, second):
            _, errors = process.communicate(timeout=15)
            self.assertEqual(process.returncode, 0, errors)

    def test_claude_accepts_typing_before_checkout_and_keeps_draft(self):
        self.assert_typing_during_loading("claude")

    def test_loading_preserves_early_root_and_app_edits(self):
        self.seed_loading_files()
        gate, process = self.block_git("populate")
        self.worktree = Path(self.tmux("show-options", "-w", "-v", "@cx_worktree"))
        (self.worktree / "README.md").write_text("early root edit\n")
        source = self.worktree / "apps/demo/source.txt"
        source.parent.mkdir(parents=True)
        source.write_text("early app edit\n")
        gate.touch()
        _, errors = process.communicate(timeout=15)
        self.assertEqual(process.returncode, 0, errors)
        self.assertEqual((self.worktree / "README.md").read_text(), "early root edit\n")
        self.assertEqual(source.read_text(), "early app edit\n")
        self.assertTrue((self.worktree / "common/shared.txt").exists())
        self.assertEqual(self.close_window()["status"], "retained")

    def test_loading_failure_keeps_live_agent_and_user_files(self):
        self.seed_loading_files()
        gate, process = self.block_git("populate", fail=True)
        self.worktree = Path(self.tmux("show-options", "-w", "-v", "@cx_worktree"))
        right = self.tmux("display-message", "-p", "#{pane_id}")
        pid = self.tmux("display-message", "-p", "-t", right, "#{pane_pid}")
        saved = self.worktree / "saved.md"
        saved.write_text("user work while loading\n")
        gate.touch()
        process.communicate(timeout=15)
        self.assertNotEqual(process.returncode, 0)
        self.assertEqual(self.tmux("display-message", "-p", "-t", right, "#{pane_pid}"), pid)
        state = self.run_command("git", "-C", str(self.worktree), "rev-parse", "--git-path", "tmux-setup.json")
        self.assertEqual(json.loads(Path(state).read_text())["status"], "failed")
        check = subprocess.run(["python3", str(SCRIPT), "--wait-setup", state], env=self.env, text=True, capture_output=True, timeout=5)
        self.assertNotEqual(check.returncode, 0)
        self.assertIn("simulated repository loading failure", check.stderr)
        self.assertEqual(self.close_window()["status"], "retained")
        self.assertEqual(saved.read_text(), "user work while loading\n")

    def test_close_while_loading_waits_for_checkout_before_cleanup(self):
        self.seed_loading_files()
        gate, process = self.block_git("populate")
        self.worktree = Path(self.tmux("show-options", "-w", "-v", "@cx_worktree"))
        self.tmux("kill-window")
        time.sleep(0.7)
        self.assertTrue(self.worktree.exists(), "cleanup must not race the active loader")
        self.assertEqual(self.states()[0]["status"], "watching")
        gate.touch()
        process.communicate(timeout=15)
        self.wait_for_watchers()
        self.assertEqual(self.states()[0]["status"], "removed")
        self.assertFalse(self.worktree.exists())

    def test_both_panes_are_visible_while_base_refresh_is_blocked(self):
        gate, process = self.block_git()
        self.assert_layout(self.repo)
        deadline = time.monotonic() + 3
        content = ""
        while "Updating base branch" not in content and time.monotonic() < deadline:
            content = self.tmux("capture-pane", "-p")
            time.sleep(0.05)
        self.assertIn("Updating base branch", content)
        deadline = time.monotonic() + 4
        while "3s elapsed" not in content and time.monotonic() < deadline:
            content = self.tmux("capture-pane", "-p")
            time.sleep(0.05)
        self.assertIn("3s elapsed", content, "slow steps should show that setup is still running")
        self.assertIsNone(process.poll(), "setup should still be waiting for Git")
        gate.touch()
        _, errors = process.communicate(timeout=15)
        self.assertEqual(process.returncode, 0, errors)
        self.worktree = Path(self.tmux("show-options", "-w", "-v", "@cx_worktree"))
        self.assert_layout(self.worktree)

    def test_closing_loading_window_does_not_leave_a_worktree(self):
        gate, process = self.block_git()
        self.assert_layout(self.repo)
        log = Path(self.tmux("show-options", "-w", "-v", "@cx_setup_log"))
        self.tmux("kill-window")
        gate.touch()
        process.communicate(timeout=15)
        self.assertNotEqual(process.returncode, 0)
        self.assertEqual(list(self.managed_root.iterdir()), [self.worktree.parent])
        self.assertFalse(log.exists())

    def test_closing_left_loading_pane_cancels_before_checkout(self):
        gate, process = self.block_git()
        left, right = self.tmux("list-panes", "-F", "#{pane_id}").splitlines()
        self.tmux("kill-pane", "-t", left)
        gate.touch()
        _, errors = process.communicate(timeout=15)
        self.assertNotEqual(process.returncode, 0)
        self.assertIn("The left setup pane was closed", errors)
        self.assertEqual(list(self.managed_root.iterdir()), [self.worktree.parent])
        deadline = time.monotonic() + 3
        content = ""
        while "left setup pane" not in content and time.monotonic() < deadline:
            content = self.tmux("capture-pane", "-p", "-t", right)
            time.sleep(0.05)
        self.assertIn("The left setup pane was closed", content.replace("\n", ""))
        self.assertIn("Press Ctrl-a Ctrl-q", content.replace("\n", ""))

    def test_closing_right_loading_pane_during_checkout_removes_unused_checkout(self):
        gate, process = self.block_git("add")
        _, right = self.tmux("list-panes", "-F", "#{pane_id}").splitlines()
        self.tmux("kill-pane", "-t", right)
        gate.touch()
        _, errors = process.communicate(timeout=15)
        self.assertNotEqual(process.returncode, 0)
        self.assertIn("The right setup pane was closed", errors)
        self.assertEqual(list(self.managed_root.iterdir()), [self.worktree.parent])

    def test_closing_left_loading_pane_during_watcher_start_has_clear_error(self):
        gate, process = self.block_git("watch")
        left, _ = self.tmux("list-panes", "-F", "#{pane_id}").splitlines()
        self.tmux("kill-pane", "-t", left)
        gate.touch()
        _, errors = process.communicate(timeout=15)
        self.assertNotEqual(process.returncode, 0)
        self.assertIn("The left setup pane was closed", errors)
        self.worktree = Path(self.tmux("show-options", "-w", "-v", "@cx_worktree"))
        self.assertEqual(self.close_window()["status"], "removed")
        self.assertFalse(self.worktree.exists())

    def test_refresh_failure_is_visible_in_both_panes(self):
        missing = self.root / "missing.git"
        self.run_command("git", "-C", str(self.repo), "remote", "add", "origin", str(missing))
        result = self.launch(self.agent_command())
        self.assertNotEqual(result.returncode, 0)
        self.assert_layout(self.repo)
        for pane in self.tmux("list-panes", "-F", "#{pane_id}").splitlines():
            deadline = time.monotonic() + 3
            content = ""
            while "Setup failed" not in content and time.monotonic() < deadline:
                content = self.tmux("capture-pane", "-p", "-t", pane)
                time.sleep(0.05)
            self.assertIn("Setup failed", content)
            self.assertIn("Press Ctrl-a Ctrl-q", content.replace("\n", ""))
            self.assertIn("Then Ctrl-a Ctrl-w to retry", content.replace("\n", ""))
        self.assertEqual(list(self.managed_root.iterdir()), [self.worktree.parent])
        log = Path(self.tmux("show-options", "-w", "-v", "@cx_setup_log"))
        self.assertTrue(log.exists(), "failed setup details stay available while the window is open")
        self.tmux("kill-window")
        deadline = time.monotonic() + 3
        while log.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertFalse(log.exists(), "closing a failed setup must remove its log")

    def test_failed_add_does_not_claim_to_retain_a_nonexistent_worktree(self):
        binaries = self.root / "bin"
        binaries.mkdir()
        wrapper = binaries / "git"
        wrapper.write_text(
            "#!/bin/sh\n"
            'if [ "$3" = worktree ] && [ "$4" = add ]; then\n'
            "  echo 'simulated checkout failure' >&2\n"
            "  exit 1\n"
            "fi\n"
            f"exec {shlex.quote(shutil.which('git'))} \"$@\"\n"
        )
        wrapper.chmod(0o700)
        self.env["PATH"] = str(binaries) + os.pathsep + self.env["PATH"]
        result = self.launch(self.agent_command())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("simulated checkout failure", result.stderr)
        self.assertNotIn("Retained unused worktree", result.stderr)
        self.assertEqual(list(self.managed_root.iterdir()), [self.worktree.parent])

    def test_default_command_runs_cx_and_returns_to_base_after_exit(self):
        called = self.root / "cx-called"
        base_guard = self.root / "base-guard"
        (self.startup / ".zshrc").write_text(
            f"cx() {{ printf ran > {shlex.quote(str(called))}; }}\n"
            f"if [[ $PWD == {shlex.quote(str(self.repo))} ]]; then\n"
            f"  printf '%s' \"${{PINTOOLS_READ_ONLY-unset}}\" > {shlex.quote(str(base_guard))}\n"
            "fi\n"
            'PROMPT="ready> "\n'
        )
        result = self.launch()
        self.assertEqual(result.returncode, 0, result.stderr)
        deadline = time.monotonic() + 5
        while not base_guard.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue(called.exists())
        self.assertEqual(base_guard.read_text(), "unset", "the base shell must use its normal install hooks")
        rows = self.tmux("list-panes", "-F", "#{pane_current_path}\t#{@cx_worktree_exited}").splitlines()
        self.assertEqual(Path(rows[0].split("\t")[0]), self.worktree)
        self.assertEqual(rows[1], f"{self.repo}\t1")

    def test_window_close_removes_clean_worktree(self):
        result = self.launch(self.agent_command())
        self.assertEqual(result.returncode, 0, result.stderr)
        state = self.close_window()
        self.assertEqual(state["status"], "removed", state)
        self.assertFalse(self.worktree.exists())
        self.assertNotIn(str(self.worktree), self.run_command(
            "git", "-C", str(self.repo), "worktree", "list", "--porcelain"))

    def test_final_window_close_removes_clean_worktree(self):
        self.assertEqual(self.launch(self.agent_command()).returncode, 0)
        base = self.tmux("display-message", "-p", "-t", self.pane, "#{window_id}")
        self.tmux("kill-window", "-t", base)
        state = self.close_window()
        self.assertEqual(state["status"], "removed", state)
        self.assertFalse(self.worktree.exists())

    def test_window_close_preserves_untracked_files(self):
        self.assertEqual(self.launch(self.agent_command()).returncode, 0)
        saved = self.worktree / "saved.md"
        saved.write_text("unsaved work\n")
        state = self.close_window()
        self.assertEqual(state["status"], "retained", state)
        self.assertIn("uncommitted or untracked", state["detail"])
        self.assertEqual(saved.read_text(), "unsaved work\n")

    def test_window_close_preserves_staged_files(self):
        self.assertEqual(self.launch(self.agent_command()).returncode, 0)
        saved = self.worktree / "saved.md"
        saved.write_text("staged user work\n")
        self.run_command("git", "-C", str(self.worktree), "add", "--", "saved.md")
        state = self.close_window()
        self.assertEqual(state["status"], "retained", state)
        self.assertEqual(saved.read_text(), "staged user work\n")

    def test_window_close_preserves_ignored_local_files(self):
        (self.repo / ".git/info/exclude").write_text("private-notes.txt\n")
        self.assertEqual(self.launch(self.agent_command()).returncode, 0)
        notes = self.worktree / "private-notes.txt"
        notes.write_text("local work that Git ignores\n")
        state = self.close_window()
        self.assertEqual(state["status"], "retained", state)
        self.assertIn("ignored local files", state["detail"])
        self.assertTrue(notes.exists())

    def test_window_close_removes_ignored_dependencies(self):
        (self.repo / ".git/info/exclude").write_text("node_modules/\n")
        self.assertEqual(self.launch(self.agent_command()).returncode, 0)
        dependencies = self.worktree / "node_modules/example"
        dependencies.mkdir(parents=True)
        (dependencies / "index.js").write_text("// disposable dependency\n")
        state = self.close_window()
        self.assertEqual(state["status"], "removed", state)

    def test_window_close_preserves_bisect(self):
        self.run_command(
            "git", "-C", str(self.repo),
            "-c", "user.name=Test", "-c", "user.email=test@example.com",
            "commit", "--allow-empty", "-m", "second baseline",
        )
        self.assertEqual(self.launch(self.agent_command()).returncode, 0)
        self.run_command("git", "-C", str(self.worktree), "bisect", "start", "HEAD", "HEAD~1")
        state = self.close_window()
        self.assertEqual(state["status"], "retained", state)
        self.assertIn("Git operation", state["detail"])

    def test_missing_socket_does_not_delete_a_live_worktree(self):
        self.assertEqual(self.launch(self.agent_command()).returncode, 0)
        server_pid = int(self.tmux("display-message", "-p", "#{pid}"))
        try:
            self.socket.unlink()
            self.wait_for_watchers()
            state = self.states()[0]
            self.assertEqual(state["status"], "retained", state)
            self.assertIn("tmux", state["detail"])
            self.assertTrue(self.worktree.exists())
        finally:
            os.kill(server_pid, signal.SIGTERM)

    def test_window_close_preserves_unpushed_detached_commit(self):
        self.assertEqual(self.launch(self.agent_command()).returncode, 0)
        (self.worktree / "saved.md").write_text("committed but not pushed\n")
        self.commit("task change")
        state = self.close_window()
        self.assertEqual(state["status"], "retained", state)
        self.assertIn("remote-tracking", state["detail"])
        self.assertTrue(self.worktree.exists())

    def test_window_close_removes_pushed_commit_and_preserves_branch(self):
        remote = self.root / "origin.git"
        self.run_command("git", "init", "--bare", str(remote))
        self.run_command("git", "-C", str(self.repo), "remote", "add", "origin", str(remote))
        self.run_command("git", "-C", str(self.repo), "push", "origin", "main")
        self.assertEqual(self.launch(self.agent_command()).returncode, 0)
        self.run_command("git", "-C", str(self.worktree), "switch", "-c", "task")
        (self.worktree / "saved.md").write_text("pushed work\n")
        self.commit("task change")
        self.run_command("git", "-C", str(self.worktree), "push", "origin", "task")
        state = self.close_window()
        self.assertEqual(state["status"], "removed", state)
        self.assertFalse(self.worktree.exists())
        self.run_command("git", "-C", str(self.repo), "rev-parse", "refs/heads/task")

    def test_window_close_preserves_locked_worktree(self):
        self.assertEqual(self.launch(self.agent_command()).returncode, 0)
        self.run_command("git", "-C", str(self.repo), "worktree", "lock", str(self.worktree))
        state = self.close_window()
        self.assertEqual(state["status"], "retained", state)
        self.assertIn("locked", state["detail"])

    def test_normal_exit_waits_for_the_shell_to_leave(self):
        self.assertEqual(self.launch(self.agent_command()).returncode, 0)
        left, right = self.tmux("list-panes", "-F", "#{pane_id}").splitlines()
        self.tmux("respawn-pane", "-k", "-t", right, "-c", str(self.repo), "exec sleep 60")
        self.tmux("set-option", "-p", "-t", right, "@cx_worktree_exited", "1")
        time.sleep(1.5)
        self.assertTrue(self.worktree.exists(), "left shell is still in the worktree")
        self.tmux("respawn-pane", "-k", "-t", left, "-c", str(self.repo), "exec sleep 60")
        self.wait_for_watchers()
        self.assertEqual(self.states()[0]["status"], "removed")

    def test_other_window_using_worktree_delays_cleanup(self):
        self.assertEqual(self.launch(self.agent_command()).returncode, 0)
        window = self.tmux("display-message", "-p", "#{window_id}")
        other = self.tmux(
            "new-window", "-d", "-c", str(self.worktree), "-P", "-F", "#{window_id}",
            "exec sleep 60",
        )
        self.tmux("kill-window", "-t", window)
        time.sleep(1.5)
        self.assertTrue(self.worktree.exists())
        self.tmux("kill-window", "-t", other)
        self.wait_for_watchers()
        self.assertEqual(self.states()[0]["status"], "removed")

    def test_slow_shell_startup_does_not_fail(self):
        started = self.root / "shell-started"
        ready = self.root / "shell-ready"
        (self.startup / ".zshrc").write_text(
            f"printf started > {shlex.quote(str(started))}\n"
            "zmodload zsh/zselect\nzselect -t 800\n"
            f"printf ready > {shlex.quote(str(ready))}\n"
            'PROMPT="ready> "\n'
        )
        result = self.launch(self.agent_command())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_layout(self.worktree)
        deadline = time.monotonic() + 3
        while not started.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue(started.exists())
        self.assertFalse(ready.exists(), "shell should still be initializing")

    def test_launch_does_not_adopt_an_existing_worktree(self):
        other = self.managed_root / "unrelated" / self.repo.name
        other.parent.mkdir(parents=True)
        self.run_command("git", "-C", str(self.repo), "worktree", "add", "--detach", str(other))
        self.assertEqual(self.launch(self.agent_command()).returncode, 0)
        self.assertNotEqual(self.worktree, other)
        self.assertEqual(self.close_window()["status"], "removed")
        self.assertTrue(other.exists())

    def test_bound_launcher_does_not_capture_keystrokes(self):
        command = shlex.join([
            "python3", str(SCRIPT), "--repo", str(self.repo),
            "--managed-root", str(self.managed_root),
            "--socket", str(self.socket), "--pane", self.pane,
            "--agent-command", self.agent_command(),
        ])
        self.tmux("run-shell", "-b", command)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            rows = self.tmux("list-panes", "-a", "-F", "#{pane_id}\t#{pane_in_mode}").splitlines()
            if len(rows) == 3:
                break
            time.sleep(0.05)
        self.assertEqual(len(rows), 3)
        time.sleep(0.3)
        modes = self.tmux("list-panes", "-a", "-F", "#{pane_in_mode}").splitlines()
        self.assertEqual(modes, ["0", "0", "0"])

    def test_refreshes_local_base_before_creating_worktree(self):
        remote = self.root / "origin.git"
        writer = self.root / "writer"
        self.run_command("git", "init", "--bare", str(remote))
        self.run_command("git", "-C", str(self.repo), "remote", "add", "origin", str(remote))
        self.run_command("git", "-C", str(self.repo), "push", "origin", "main")
        self.run_command("git", "clone", "--branch", "main", str(remote), str(writer))
        self.run_command(
            "git", "-C", str(writer), "-c", "user.name=Test", "-c", "user.email=test@example.com",
            "commit", "--allow-empty", "-m", "new upstream baseline",
        )
        expected = self.run_command("git", "-C", str(writer), "rev-parse", "HEAD")
        self.run_command("git", "-C", str(writer), "push", "origin", "main")
        self.assertEqual(self.launch(self.agent_command()).returncode, 0)
        self.assertEqual(self.run_command("git", "-C", str(self.repo), "rev-parse", "HEAD"), expected)
        self.assertEqual(self.run_command("git", "-C", str(self.worktree), "rev-parse", "HEAD"), expected)

    def test_detached_commit_is_kept_after_checkout_back_to_base(self):
        self.assertEqual(self.launch(self.agent_command()).returncode, 0)
        base = self.run_command("git", "-C", str(self.worktree), "rev-parse", "HEAD")
        (self.worktree / "saved.md").write_text("detached history\n")
        self.commit("detached work")
        self.run_command("git", "-C", str(self.worktree), "checkout", base)
        state = self.close_window()
        self.assertEqual(state["status"], "retained", state)
        self.assertIn("HEAD history", state["detail"])


if __name__ == "__main__":
    unittest.main()
