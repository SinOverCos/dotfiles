import os
import json
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import tempfile
import time
import unittest
import uuid


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/tmux_cx_worktree.py"


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

    def launch(self, agent_command=None):
        result = subprocess.run(
            [
                "python3", str(SCRIPT), "--repo", str(self.repo),
                "--managed-root", str(self.managed_root),
                "--socket", str(self.socket), "--pane", self.pane,
                *(["--agent-command", agent_command] if agent_command else []),
            ],
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

    def test_default_command_runs_cx_and_returns_to_base_after_exit(self):
        called = self.root / "cx-called"
        (self.startup / ".zshrc").write_text(
            f"cx() {{ printf ran > {shlex.quote(str(called))}; }}\n"
            'PROMPT="ready> "\n'
        )
        result = self.launch()
        self.assertEqual(result.returncode, 0, result.stderr)
        deadline = time.monotonic() + 5
        while not called.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue(called.exists())
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
