"""Self-tests for EstateOS guard hooks. Run: `make harness-test` (stdlib only)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

HOOKS = Path(__file__).resolve().parents[1]
PROJECT = HOOKS.parents[1]
HOME = Path.home()


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

    def test_no_verify_only_on_git(self) -> None:
        self.assertEqual(bash("git commit -n -m x"), "deny")
        self.assertEqual(bash("git push --no-verify"), "deny")
        self.assertIsNone(bash("echo '# never bypass with --no-verify' > .pre-commit-config.yaml"))
        self.assertIsNone(bash("git commit -m 'note'"))

    def test_blocks_git_write_in_home_repo(self) -> None:
        self.assertEqual(bash("git add -A", cwd=HOME), "deny")
        self.assertEqual(bash(f"cd {HOME} && git commit -m x"), "deny")
        self.assertIsNone(bash("git status", cwd=HOME))


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
            subprocess.run([*git, "init", "-q"], cwd=root, check=True)
            subprocess.run([*git, "add", "-A"], cwd=root, check=True)
            subprocess.run([*git, "commit", "-qm", "init"], cwd=root, check=True)
            env = {**os.environ, "CLAUDE_PROJECT_DIR": str(root)}
            for f in [*files, "app/llm/prompts/v2/understanding.md"]:
                payload = {"tool_name": "Edit", "tool_input": {"file_path": str(root / f), "new_string": "y"}}
                r = subprocess.run([sys.executable, str(HOOKS / "guard_edit.py")], input=json.dumps(payload),
                                   capture_output=True, text=True, env=env, check=False)
                got = decision(json.loads(r.stdout)) if r.stdout.strip() else None
                self.assertEqual(got, None if "/v2/" in f else "deny", f)


if __name__ == "__main__":
    unittest.main()
