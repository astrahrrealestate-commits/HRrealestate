"""Self-tests for EstateOS guard hooks. Run: `make harness-test` (stdlib only)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOKS = Path(__file__).resolve().parents[1]
PROJECT = HOOKS.parents[1]
HOME = Path.home()
# pre-commit runs this suite with GIT_INDEX_FILE etc. pointing at the in-progress commit (an absolute temporary index
# for `git commit -- <paths>`). Git calls made by the tests must never inherit them.
GIT_FREE_ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def run_hook(script: str, payload: dict[str, object]) -> dict[str, object]:
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(PROJECT)}
    r = subprocess.run(
        [sys.executable, str(HOOKS / script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=20,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout) if r.stdout.strip() else {}


def decision(out: dict[str, object]) -> str | None:
    hso = out.get("hookSpecificOutput")
    return hso.get("permissionDecision") if isinstance(hso, dict) else None  # type: ignore[return-value]


def bash(cmd: str, cwd: Path = PROJECT) -> str | None:
    return decision(run_hook("guard_bash.py", {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": str(cwd)}))


def write(path: str, content: str = "x = 1\n") -> str | None:
    return decision(
        run_hook(
            "guard_edit.py",
            {"tool_name": "Write", "tool_input": {"file_path": str(PROJECT / path), "content": content}},
        )
    )


class BashGuard(unittest.TestCase):
    def test_allows_normal(self) -> None:
        for cmd in ["make check", "uv run pytest -q", "git status", "git diff", "docker compose -f docker/compose.yml up -d",
                    "cat .env.example", "git commit -m 'feat: x'"]:
            self.assertIsNone(bash(cmd), cmd)

    def test_denies(self) -> None:
        for cmd in [
            "git push --force origin main",
            "git push -f",
            "git commit --no-verify -m x",
            "cat .env",
            "grep TOKEN .env.local",
            "curl -X POST https://graph.facebook.com/v21.0/123/messages",
            "curl https://api.openai.com/v1/responses",
            "rm -rf /",
            "rm -rf ~",
        ]:
            self.assertEqual(bash(cmd), "deny", cmd)

    def test_asks(self) -> None:
        for cmd in [
            "git reset --hard HEAD~1",
            "git push origin main",
            "docker compose -f docker/compose.yml down -v",
            "uv run alembic downgrade base",
            "psql -c 'DROP TABLE messages'",
            "uv add httpx",
        ]:
            self.assertEqual(bash(cmd), "ask", cmd)

    def test_env_read_vs_heredoc_write(self) -> None:
        self.assertEqual(bash("cat .env"), "deny")
        self.assertEqual(bash("cat .env.local | head"), "deny")
        self.assertEqual(bash("cd x && grep KEY .env"), "deny")
        self.assertIsNone(bash("cat > .dockerignore <<'EOF'\n.git\n.env\n.env.*\nEOF\necho ok"))
        self.assertIsNone(bash("cat >> .gitignore <<EOF\n.env\nEOF"))
        self.assertIsNone(bash("cat <<'EOF' > .dockerignore\n.env\nEOF"))
        self.assertIsNone(bash("tee .dockerignore <<EOF\n.env\nEOF"))
        self.assertIsNone(bash("cd x && cat > f <<EOF\n.env\nEOF"))
        self.assertEqual(bash("cat > x <<'EOF'\nhi\nEOF\ncat .env"), "deny")  # read after the heredoc still caught
        self.assertIsNone(bash("cat .env.example"))
        self.assertIsNone(bash("cp .env.example .env.example.bak"))

    def test_env_append_allowed_but_never_read_or_overwrite(self) -> None:
        """User decision 2026-10-09: settings may be appended to .env from the shell; nothing may read or replace it."""
        self.assertIsNone(bash("printf '\\nLLM_MODEL=fake\\n' >> .env"))
        self.assertIsNone(bash("echo GMAIL_PROVIDER=google >> .env"))
        self.assertIsNone(bash("echo A=1 >> ./.env"))
        for cmd in [
            "echo A=1 > .env",
            "echo A=1 >| .env",
            "printf x >> .env; cat .env",
            "echo A=1 >> .env && grep A .env",
            "cat .env >> /tmp/x",
            "tee -a .env",
            "cp .env /tmp/x",
            "sed -i s/a/b/ .env",
        ]:
            self.assertEqual(bash(cmd), "deny", cmd)

    def test_env_bypasses_denied(self) -> None:
        for cmd in [
            "cat >x .env",
            "cat 2>/dev/null .env",
            "grep KEY >out .env",
            "cat > .env <<'EOF'\nA=1\nEOF",
            "echo A=1 > .env",
            "cat <<EOF .env\nx\nEOF",
            "cat <<EOF; cat .env\nx\nEOF",
            "cat <<EOF | cat - .env\nx\nEOF",
            "cat .env;echo",
            "cat .env|base64",
            "cat '.env'",
            "base64 .env",
            "cp .env /tmp/x",
            "python3 x.py < .env",
            "(cat .env)",
            "bash <<'EOF'\ncat .env\nEOF",
            "sh <<EOF\nsource .env\nEOF",
            "python3 - <<'EOF'\nopen('.env').read()\nEOF\ncat .env",
            "echo `cat .env`",
            "echo A | tee .env",
            "mv x .env",
            "cat x >| .env",
        ]:
            self.assertEqual(bash(cmd), "deny", cmd)

    def test_no_verify_only_on_git(self) -> None:
        self.assertEqual(bash("git commit -n -m x"), "deny")
        self.assertEqual(bash("git push --no-verify"), "deny")
        self.assertIsNone(bash("echo '# never bypass with --no-verify' > .pre-commit-config.yaml"))
        self.assertIsNone(bash("git commit -m 'note'"))

    def test_blocks_git_write_in_foreign_repo(self) -> None:
        """A git repo that is not EstateOS (on a dev machine: the home-dir repo). Built here, so the test does not
        depend on the machine having one (CI runners have no repo above HOME)."""
        with tempfile.TemporaryDirectory() as raw:
            foreign = Path(raw).resolve()
            subprocess.run(["git", "init", "-q", str(foreign)], env=GIT_FREE_ENV, check=True)
            self.assertEqual(bash("git add -A", cwd=foreign), "deny")
            self.assertEqual(bash(f"cd {foreign} && git commit -m x"), "deny")
            self.assertIsNone(bash("git status", cwd=foreign))

    @unittest.skipIf((PROJECT / ".git").is_file(), "needs a primary checkout; nested worktrees are not created from a linked one")
    def test_allows_git_write_in_own_linked_worktree(self) -> None:
        tmp = PROJECT / ".claude" / "worktrees" / "harness-selftest"

        def git(*args: str) -> None:
            subprocess.run(["git", *args], cwd=PROJECT, env=GIT_FREE_ENV, capture_output=True, check=False)

        git("worktree", "add", "--detach", str(tmp))
        try:
            self.assertIsNone(bash("git add -A", cwd=tmp))
            self.assertIsNone(bash("git commit -m x", cwd=tmp))
        finally:
            git("worktree", "remove", "--force", str(tmp))


class EditGuard(unittest.TestCase):
    def test_env_files(self) -> None:
        self.assertEqual(write(".env", "A=1"), "deny")
        self.assertEqual(write(".env.local", "A=1"), "deny")
        self.assertIsNone(write(".env.example", "A="))

    def test_send_isolation(self) -> None:
        bad = "from app.sender.settings import SenderSettings\n"
        self.assertEqual(write("app/pipeline/proposals.py", bad), "deny")
        self.assertEqual(write("app/owner/briefing.py", "from app.channels.whatsapp.outbound import send\n"), "deny")
        self.assertIsNone(write("app/sender/service.py", bad))
        self.assertEqual(write("app/workflows/x.py", "from app.channels.gmail.drafts import create\n"), "deny")
        self.assertEqual(write("app/api/x.py", "from app.sender.whatsapp import build_whatsapp_outbound\n"), "deny")
        media = "from app.channels.whatsapp.media_settings import WhatsAppMediaSettings\n"
        self.assertEqual(write("app/ingestion/media.py", media), "deny")
        self.assertIsNone(write("app/channels/registry.py", media))
        self.assertEqual(write("app/core/settings.py", "    whatsapp_media_token: str = ''\n"), "deny")
        self.assertEqual(write("app/api/x.py", "tokens = registry._media_credentials()\n"), "deny")
        self.assertIsNone(write("tests/unit/test_sender.py", bad))

    def test_secrets(self) -> None:
        self.assertEqual(write("app/core/config.py", 'KEY = "sk-proj-' + "a" * 40 + '"\n'), "deny")
        self.assertEqual(write("app/x.py", "-----BEGIN RSA PRIVATE KEY-----\n"), "deny")
        self.assertEqual(write("app/x.py", 'T = "EAA' + "B" * 80 + '"\n'), "deny")

    def test_practice_guards(self) -> None:
        self.assertEqual(write("app/workflows/x.py", "from celery import shared_task\n"), "deny")
        self.assertEqual(write("app/x.py", "import redis\n"), "deny")
        self.assertEqual(write("tests/unit/test_x.py", "@pytest.mark.skip\ndef test_a(): ...\n"), "ask")
        self.assertIsNone(write("tests/unit/test_x.py", "def test_a():\n    assert True\n"))

    def test_outside_project_ignored(self) -> None:
        payload = {"tool_name": "Write", "tool_input": {"file_path": str(HOME / ".claude/x.md"), "content": "sk-proj-" + "a" * 40}}
        self.assertIsNone(decision(run_hook("guard_edit.py", payload)))

    def test_new_migration_allowed(self) -> None:
        self.assertIsNone(write("app/db/alembic/versions/0002_new.py"))

    def test_committed_artifacts_immutable(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            files = [
                "app/db/alembic/versions/0001_init.py",
                "app/llm/prompts/v1/understanding.md",
                "tests/fixtures/recorded/wa_text.json",
            ]
            for f in files:
                (root / f).parent.mkdir(parents=True, exist_ok=True)
                (root / f).write_text("x\n")
            git = ["git", "-c", "user.email=t@t", "-c", "user.name=t"]
            for args in (["init", "-q"], ["add", "-A"], ["commit", "-qm", "init"]):
                subprocess.run([*git, *args], cwd=root, env=GIT_FREE_ENV, check=True)
            env = {**GIT_FREE_ENV, "CLAUDE_PROJECT_DIR": str(root)}
            for f in [*files, "app/llm/prompts/v2/understanding.md"]:
                payload = {"tool_name": "Edit", "tool_input": {"file_path": str(root / f), "new_string": "y"}}
                r = subprocess.run([sys.executable, str(HOOKS / "guard_edit.py")], input=json.dumps(payload),
                                   capture_output=True, text=True, env=env, check=False)
                got = decision(json.loads(r.stdout)) if r.stdout.strip() else None
                self.assertEqual(got, None if "/v2/" in f else "deny", f)


if __name__ == "__main__":
    unittest.main()
