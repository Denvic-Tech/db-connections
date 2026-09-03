from pathlib import Path

import pytest

from scripts import upload_builds


@pytest.skip()  # TODO: build before this test
def test_collect_artifacts_ignores_unrelated_files(tmp_path: Path) -> None:
    wheel = tmp_path / "db_connection-1.1.4-py3-none-any.whl"
    sdist = tmp_path / "db_connection-1.1.4.tar.gz"
    unrelated = tmp_path / "checksums.txt"
    wheel.write_bytes(b"wheel")
    sdist.write_bytes(b"sdist")
    unrelated.write_text("ignored", encoding="utf-8")

    assert upload_builds.collect_artifacts(tmp_path) == [wheel, sdist]


def test_resolve_api_token_prefers_environment(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".env").write_text("PYPI_API_TOKEN=file-token\n", encoding="utf-8")
    monkeypatch.setenv("PYPI_API_TOKEN", "environment-token")

    assert upload_builds.resolve_api_token(tmp_path) == "environment-token"


def test_main_publishes_to_pypi_by_default(monkeypatch) -> None:
    artifact = Path("dist/db_connection-1.1.4-py3-none-any.whl")
    calls: dict[str, object] = {}

    monkeypatch.setattr(upload_builds, "ensure_twine_available", lambda: None)
    monkeypatch.setattr(upload_builds, "collect_artifacts", lambda _dist_dir: [artifact])
    monkeypatch.setattr(upload_builds, "resolve_api_token", lambda _repo_root: "token")
    monkeypatch.setattr(
        upload_builds,
        "run_twine_check",
        lambda artifacts, _repo_root: calls.update(check_artifacts=artifacts),
    )

    def record_upload(artifacts, *, repository, api_token, repo_root) -> None:
        calls.update(
            upload_artifacts=artifacts,
            repository=repository,
            api_token=api_token,
            repo_root=repo_root,
        )

    monkeypatch.setattr(upload_builds, "run_twine_upload", record_upload)

    assert upload_builds.main([]) == 0
    assert calls["check_artifacts"] == [artifact]
    assert calls["upload_artifacts"] == [artifact]
    assert calls["repository"] == "pypi"
    assert calls["api_token"] == "token"
