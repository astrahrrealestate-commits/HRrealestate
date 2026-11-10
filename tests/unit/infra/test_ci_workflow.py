"""G4 CI (.github/workflows/ci.yml) stays consistent with the tools it drives: pinned uv, the test images, the image
CVE scan and the frontend build. A real GitHub Actions run is the only proof the jobs pass; these keep them honest."""

import re
import tomllib

from testcontainers.core.config import testcontainers_config

from tests.unit.infra.workflows import ROOT, all_steps, run_text, steps, workflow

CI = "ci.yml"


def _required_uv() -> str:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(pyproject["tool"]["uv"]["required-version"]).removeprefix("==")


def test_ci_uv_version_equals_the_pyproject_pin() -> None:
    assert workflow(CI)["env"]["UV_VERSION"] == _required_uv()


def test_every_setup_uv_step_passes_the_pinned_version_explicitly() -> None:
    uv_steps = [(where, s) for where, s in all_steps() if str(s.get("uses", "")).startswith("astral-sh/setup-uv@")]
    assert uv_steps
    for where, step in uv_steps:
        assert step.get("with", {}).get("version") == "${{ env.UV_VERSION }}", where
        assert workflow(where.split(":")[0])["env"]["UV_VERSION"] == _required_uv(), where


def test_docker_and_pre_commit_use_the_same_uv() -> None:
    version = re.escape(_required_uv())
    assert re.search(rf"ghcr\.io/astral-sh/uv:{version}@", (ROOT / "docker/Dockerfile").read_text(encoding="utf-8"))
    assert re.search(rf"rev: {version}\b", (ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8"))


def test_every_action_is_pinned_to_a_full_commit_sha() -> None:
    for where, step in all_steps():
        if "uses" in step:
            assert re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", step["uses"]), where


def _pre_pull() -> str:
    return next(s["run"] for s in steps(workflow(CI), "integration") if "docker pull" in str(s.get("run", "")))


def test_ci_pre_pulls_the_postgres_image_testcontainers_starts() -> None:
    conftest = (ROOT / "tests/integration/conftest.py").read_text(encoding="utf-8")
    images = re.findall(r'PostgresContainer\(\s*"([^"]+)"', conftest)
    assert images
    pulled = re.findall(r"docker pull (\S+)", _pre_pull())
    assert set(images) <= set(pulled)


def test_ci_pre_pulls_the_ryuk_image_testcontainers_starts() -> None:
    assert testcontainers_config.ryuk_image in re.findall(r"docker pull (\S+)", _pre_pull())


def test_image_job_loads_the_build_and_fails_on_fixable_high_cves() -> None:
    image = steps(workflow(CI), "image")
    build = next(s for s in image if str(s.get("uses", "")).startswith("docker/build-push-action@"))
    assert build["with"]["load"] is True
    scan = run_text(workflow(CI), "image")
    assert "trivy" in scan
    assert "--exit-code 1" in scan
    assert "--severity HIGH,CRITICAL" in scan
    assert "--ignore-unfixed" in scan
    assert build["with"]["tags"] in scan


def test_frontend_is_installed_linted_and_built() -> None:
    job = workflow(CI)["jobs"]["frontend"]
    assert job["defaults"]["run"]["working-directory"] == "frontend"
    commands = run_text(workflow(CI), "frontend").splitlines()
    assert commands.index("npm ci") < commands.index("npm run lint") < commands.index("npm run build")
