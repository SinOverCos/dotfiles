import contextlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sync_dotfiles


def git(repo, *args):
    result = subprocess.run(
        ["git", *args], cwd=repo, text=True, capture_output=True, check=True
    )
    return result.stdout.strip()


class SyncIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.origin = self.root / "origin.git"
        self.origin.mkdir()
        git(self.origin, "init", "--bare", "--initial-branch=master")

        seed = self.root / "seed"
        seed.mkdir()
        git(seed, "init", "--initial-branch=master")
        git(seed, "config", "user.name", "Dotfiles Test")
        git(seed, "config", "user.email", "dotfiles@example.com")
        (seed / "shared.txt").write_text("base\n")
        git(seed, "add", "-A")
        git(seed, "commit", "-m", "initial")
        git(seed, "remote", "add", "origin", str(self.origin))
        git(seed, "push", "origin", "master")

        self.repos = {}
        self.homes = {}
        for host in ("mac", "devapp", "data-devapp"):
            home = self.root / host
            code = home / "code"
            code.mkdir(parents=True)
            repo = code / "dotfiles"
            git(code, "clone", str(self.origin), str(repo))
            git(repo, "config", "user.name", "Dotfiles Test")
            git(repo, "config", "user.email", "dotfiles@example.com")
            self.repos[host] = repo
            self.homes[host] = home

    def fake_remote(self, host, script, *args):
        env = {**os.environ, "HOME": str(self.homes[host])}
        return sync_dotfiles.run(
            ("sh", "-s", "--", *args),
            cwd=self.homes[host],
            env=env,
            input_text=script,
        )

    def run_sync(self):
        with mock.patch.object(sync_dotfiles, "REPO", self.repos["mac"]), mock.patch.object(
            sync_dotfiles, "remote", side_effect=self.fake_remote
        ), mock.patch.object(
            sync_dotfiles, "remote_git_url",
            side_effect=lambda host: str(self.repos[host]),
        ), mock.patch.object(
            sync_dotfiles, "remote_git_env", return_value=os.environ.copy()
        ), mock.patch.object(sync_dotfiles.sys, "platform", "darwin"), mock.patch.dict(
            os.environ,
            {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"},
        ), contextlib.redirect_stdout(io.StringIO()):
            sync_dotfiles.sync()

    def test_merges_edits_from_all_three_and_updates_every_checkout(self):
        (self.repos["mac"] / "mac.txt").write_text("mac\n")
        (self.repos["devapp"] / "devapp.txt").write_text("devapp\n")
        (self.repos["devapp"] / "shared.txt").write_text("base\nunstaged devapp edit\n")
        (self.repos["data-devapp"] / "data.txt").write_text("data\n")
        (self.repos["devapp"] / "new-untracked.txt").write_text("new file\n")

        self.run_sync()

        heads = {host: git(repo, "rev-parse", "HEAD") for host, repo in self.repos.items()}
        self.assertEqual(len(set(heads.values())), 1)
        self.assertEqual(heads["mac"], git(self.origin, "rev-parse", "master"))
        for repo in self.repos.values():
            for filename in ("mac.txt", "devapp.txt", "data.txt", "new-untracked.txt"):
                self.assertTrue((repo / filename).exists())
            self.assertEqual(
                (repo / "shared.txt").read_text(), "base\nunstaged devapp edit\n"
            )
        self.run_sync()
        self.assertEqual(
            {host: git(repo, "rev-parse", "HEAD") for host, repo in self.repos.items()},
            heads,
        )

    def test_conflict_stops_before_origin_push_and_preserves_remote_edit(self):
        (self.repos["mac"] / "shared.txt").write_text("mac edit\n")
        (self.repos["devapp"] / "shared.txt").write_text("devapp edit\n")
        original_origin = git(self.origin, "rev-parse", "master")

        with self.assertRaises(sync_dotfiles.SyncError):
            self.run_sync()

        self.assertEqual(git(self.origin, "rev-parse", "master"), original_origin)
        self.assertTrue((self.repos["mac"] / ".git" / "MERGE_HEAD").exists())
        self.assertEqual(
            (self.repos["devapp"] / "shared.txt").read_text(), "devapp edit\n"
        )

    def test_untracked_add_add_conflict_stops_before_push(self):
        (self.repos["mac"] / "new.txt").write_text("mac version\n")
        (self.repos["devapp"] / "new.txt").write_text("devapp version\n")
        original_origin = git(self.origin, "rev-parse", "master")

        with self.assertRaises(sync_dotfiles.SyncError):
            self.run_sync()

        self.assertEqual(git(self.origin, "rev-parse", "master"), original_origin)
        self.assertTrue((self.repos["mac"] / ".git" / "MERGE_HEAD").exists())
        self.assertIn("new.txt", git(self.repos["mac"], "diff", "--name-only", "--diff-filter=U"))

    def test_interactive_codex_resolution_can_finish_sync(self):
        (self.repos["mac"] / "shared.txt").write_text("mac edit\n")
        (self.repos["devapp"] / "shared.txt").write_text("devapp edit\n")

        def resolve_with_codex(label):
            self.assertEqual(label, "devapp")
            (self.repos["mac"] / "shared.txt").write_text("both edits resolved\n")
            git(self.repos["mac"], "add", "shared.txt")

        with mock.patch.object(sync_dotfiles, "launch_codex", side_effect=resolve_with_codex):
            self.run_sync()

        heads = {host: git(repo, "rev-parse", "HEAD") for host, repo in self.repos.items()}
        self.assertEqual(len(set(heads.values())), 1)
        self.assertEqual(heads["mac"], git(self.origin, "rev-parse", "master"))
        self.assertEqual(
            (self.repos["data-devapp"] / "shared.txt").read_text(),
            "both edits resolved\n",
        )

    def test_already_cherry_picked_devapp_commit_can_still_sync(self):
        (self.repos["devapp"] / "shared.txt").write_text("devapp edit\n")
        git(self.repos["devapp"], "add", "shared.txt")
        git(self.repos["devapp"], "commit", "-m", "edit on devapp")
        devapp_commit = git(self.repos["devapp"], "rev-parse", "HEAD")
        git(self.repos["mac"], "fetch", str(self.repos["devapp"]), "master")
        git(self.repos["mac"], "cherry-pick", devapp_commit)
        git(self.repos["mac"], "push", "origin", "master")

        self.run_sync()

        heads = {host: git(repo, "rev-parse", "HEAD") for host, repo in self.repos.items()}
        self.assertEqual(len(set(heads.values())), 1)
        self.assertEqual(heads["mac"], git(self.origin, "rev-parse", "master"))
        self.assertEqual((self.repos["data-devapp"] / "shared.txt").read_text(), "devapp edit\n")

    def test_preexisting_divergent_commits_from_both_devapps_are_preserved(self):
        (self.repos["devapp"] / "normal.txt").write_text("normal devapp\n")
        git(self.repos["devapp"], "add", "normal.txt")
        git(self.repos["devapp"], "commit", "-m", "normal devapp change")
        normal_commit = git(self.repos["devapp"], "rev-parse", "HEAD")

        (self.repos["data-devapp"] / "data.txt").write_text("data devapp\n")
        git(self.repos["data-devapp"], "add", "data.txt")
        git(self.repos["data-devapp"], "commit", "-m", "data devapp change")
        data_commit = git(self.repos["data-devapp"], "rev-parse", "HEAD")

        self.run_sync()

        head = git(self.repos["mac"], "rev-parse", "HEAD")
        for commit in (normal_commit, data_commit):
            self.assertEqual(
                subprocess.run(
                    ["git", "merge-base", "--is-ancestor", commit, head],
                    cwd=self.repos["mac"],
                ).returncode,
                0,
            )
        self.assertEqual(head, git(self.origin, "rev-parse", "master"))
        for repo in self.repos.values():
            self.assertEqual(git(repo, "rev-parse", "HEAD"), head)


class CodexLaunchTest(unittest.TestCase):
    def test_default_command_comes_from_zshrc_alias(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            (repo / ".zshrc").write_text(
                'alias cx="ai-sandbox codex --sandbox danger-full-access '
                '--yolo --model gpt-6.1-sol -c model_reasoning_effort=xhigh"\n'
            )
            with mock.patch.object(sync_dotfiles, "REPO", repo), mock.patch.dict(
                os.environ
            ) as environment:
                environment.pop("DOTFILES_SYNC_CODEX_COMMAND", None)
                command = sync_dotfiles.codex_command()

        self.assertEqual(
            command,
            [
                "ai-sandbox", "codex", "--sandbox", "danger-full-access", "--yolo",
                "--model", "gpt-6.1-sol", "-c", "model_reasoning_effort=xhigh",
            ],
        )

    def test_conflict_opens_tui_with_terminal_attached(self):
        terminal = mock.Mock()
        terminal.isatty.return_value = True
        completed = mock.Mock(returncode=0)
        with mock.patch.object(sync_dotfiles.sys, "stdin", terminal), mock.patch.object(
            sync_dotfiles.sys, "stdout", terminal
        ), mock.patch.object(
            sync_dotfiles, "codex_command",
            return_value=("ai-sandbox", "codex", "--model", "gpt-6.1-sol"),
        ), mock.patch.object(
            sync_dotfiles.subprocess, "run", return_value=completed
        ) as run:
            sync_dotfiles.launch_codex("data-devapp")

        command = run.call_args.args[0]
        self.assertEqual(command[:4], ("ai-sandbox", "codex", "--model", "gpt-6.1-sol"))
        self.assertIn("data-devapp", command[-1])
        self.assertEqual(run.call_args.kwargs["cwd"], sync_dotfiles.REPO)
        self.assertNotIn("capture_output", run.call_args.kwargs)
        self.assertNotIn("stdin", run.call_args.kwargs)


if __name__ == "__main__":
    unittest.main()
