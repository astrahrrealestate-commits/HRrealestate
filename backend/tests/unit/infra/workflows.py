"""Read the repo's GitHub Actions workflows and compose files as data (PyYAML ships with pydantic-evals)."""

from pathlib import Path
from typing import Any

import yaml

# .github/workflows/ lives at the true repo root; pyproject.toml, docker/, tests/ live under backend/ (this file's
# own project). Call sites pick whichever root a given path is actually under.
BACKEND_ROOT = Path(__file__).resolve().parents[3]
REPO_ROOT = BACKEND_ROOT.parent
WORKFLOWS = REPO_ROOT / ".github" / "workflows"


def load_yaml(relative: str) -> dict[str, Any]:
    data = yaml.safe_load((REPO_ROOT / relative).read_text(encoding="utf-8"))
    assert isinstance(data, dict), relative
    return data


def workflow(name: str) -> dict[str, Any]:
    return load_yaml(f".github/workflows/{name}")


def triggers(wf: dict[str, Any]) -> dict[str, Any]:
    """YAML 1.1 reads the bare key `on` as boolean True."""
    value = wf.get("on", wf.get(True))
    assert isinstance(value, dict)
    return value


def steps(wf: dict[str, Any], job: str) -> list[dict[str, Any]]:
    result = wf["jobs"][job]["steps"]
    assert isinstance(result, list)
    return result


def all_steps() -> list[tuple[str, dict[str, Any]]]:
    found: list[tuple[str, dict[str, Any]]] = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        wf = workflow(path.name)
        for job_name in wf["jobs"]:
            found.extend((f"{path.name}:{job_name}", step) for step in steps(wf, job_name))
    return found


def run_text(wf: dict[str, Any], job: str) -> str:
    return "\n".join(str(s.get("run", "")) for s in steps(wf, job))
