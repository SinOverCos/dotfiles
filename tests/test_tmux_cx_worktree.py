import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import time
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/tmux_cx_worktree.py"


@unittest.skipUnless(shutil.which("tmux") and shutil.which("zsh"), "needs tmux and zsh")
class TmuxWorktreeIntegrationTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="tmux-cx-test-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
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
        }
        self.env.pop("TMUX", None)
        self.env.pop("TMUX_PANE", None)
        self.run_command("git", "-C", str(self.repo), "init", "--initial-branch=main")
        self.run_command(
            "git", "-C", str(self.repo),
            "-c", "user.name=Test", "-c", "user.email=test@example.com",
            "commit", "--allow-empty", "-m", "seed",
        )
        self.socket = self.root / "tmux.sock"
        self.pane = self.tmux(
            "-f", "/dev/null", "new-session", "-d", "-s", "test",
            "-x", "120", "-y", "40", "-c", str(self.repo),
            "-P", "-F", "#{pane_id}", "exec sleep 60",
        )
        self.addCleanup(self.tmux, "kill-server")
        self.tmux("set-option", "-g", "default-shell", shutil.which("zsh"))

    def run_command(self, *args):
        return subprocess.run(
            args, env=self.env, capture_output=True, text=True, check=True, timeout=30,
        ).stdout.strip()

    def tmux(self, *args):
        return self.run_command("tmux", "-S", str(self.socket), *args)

    def launch(self, agent_command, timeout=15):
        return subprocess.run(
            [
                "python3", str(SCRIPT), "--repo", str(self.repo),
                "--managed-root", str(self.managed_root),
                "--socket", str(self.socket), "--pane", self.pane,
                "--timeout", str(timeout), "--agent-command", agent_command,
            ],
            env=self.env, capture_output=True, text=True, timeout=30,
        )

    def agent_command(self):
        return (
            f"git -C {shlex.quote(str(self.repo))} worktree add --detach "
            f"{shlex.quote(str(self.worktree))} HEAD >/dev/null 2>&1; exec sleep 60"
        )

    def assert_layout(self, directory):
        panes = self.tmux(
            "list-panes", "-F", "#{pane_id}\t#{pane_current_path}\t#{pane_left}\t#{pane_active}",
        ).splitlines()
        self.assertEqual(len(panes), 2)
        left, right = [pane.split("\t") for pane in panes]
        self.assertEqual(Path(left[1]), directory)
        self.assertEqual(Path(right[1]), self.repo)
        self.assertLess(int(left[2]), int(right[2]))
        self.assertEqual(right[3], "1")

    def test_opens_shell_in_worktree(self):
        result = self.launch(self.agent_command())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_layout(self.worktree)

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

    def test_timeout_opens_shell_in_base_checkout(self):
        result = self.launch("exec sleep 60", timeout=1)
        self.assertEqual(result.returncode, 1)
        self.assertIn("No Codex worktree appeared after 1s", result.stderr)
        self.assert_layout(self.repo)

    def test_agent_exit_opens_shell_in_base_checkout(self):
        result = self.launch("tmux set-option -p @cx_worktree_exited 1; exec sleep 60")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Codex exited before creating a worktree", result.stderr)
        self.assert_layout(self.repo)


if __name__ == "__main__":
    unittest.main()
