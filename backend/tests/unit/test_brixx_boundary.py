"""The BRIXX client boundary is an import-linter contract (run by `lint-imports` in G1); this pins its shape."""

import tomllib
from pathlib import Path
from typing import Any

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"
# app.dev.brixx*: developer tooling (metadata snapshot, migration codegen); production code cannot import app.dev
# (the "Dev tooling is never imported by production code" contract).
ALLOWED = {
    "app.channels.registry",
    "app.workflows.deps",
    "app.directory.brixx.**",
    "app.dev.brixx",
    "app.dev.brixx_codegen",
}
BRIXX_WORKFLOWS = "app.workflows.brixx_"


def _brixx_contract() -> dict[str, Any]:
    contracts = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["tool"]["importlinter"]["contracts"]
    found = [c for c in contracts if "app.channels.brixx" in c.get("forbidden_modules", [])]
    assert len(found) == 1, "exactly one contract guards app.channels.brixx"
    return dict(found[0])


def test_only_the_brixx_sync_package_may_import_the_client() -> None:
    contract = _brixx_contract()
    assert contract["type"] == "forbidden"
    assert {"app", "app.*"} <= set(contract["source_modules"])
    importers = {rule.split(" -> ")[0] for rule in contract["ignore_imports"]}
    workflows = {i for i in importers if i.startswith(BRIXX_WORKFLOWS)}
    assert workflows, "the BRIXX workflows import the port"
    assert importers - {"app.channels.brixx.**"} - workflows == ALLOWED
