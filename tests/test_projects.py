from __future__ import annotations

import json
from pathlib import Path

import pytest

from omni import cli
from omni import projects


def test_register_and_list_projects(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    registry = tmp_path / "registry" / "projects.json"
    monkeypatch.setattr(projects, "registry_path", lambda: registry)

    first = projects.register(tmp_path / "repo_a")
    second = projects.register(tmp_path / "repo_b")

    assert first["count"] == 1
    assert second["count"] == 2
    listed = projects.list_registered()
    assert listed["count"] == 2
    assert str((tmp_path / "repo_a").resolve()) in listed["projects"]


def test_status_all_is_read_only_aggregate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project_a = tmp_path / "repo_a"
    project_a.mkdir()
    (project_a / ".omni").mkdir()
    registry = tmp_path / "registry" / "projects.json"
    monkeypatch.setattr(projects, "registry_path", lambda: registry)
    projects.register(project_a)

    summary = projects.status_all()

    assert summary["count"] == 1
    project = summary["projects"][0]
    assert project["root"] == str(project_a.resolve())
    assert project["omni_dir"] is True


def test_cli_project_register_and_status_all(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project_a = tmp_path / "repo_a"
    project_a.mkdir()
    (project_a / ".omni").mkdir()
    registry = tmp_path / "registry" / "projects.json"
    monkeypatch.setattr(projects, "registry_path", lambda: registry)
    monkeypatch.chdir(project_a)

    register_code = cli.main(["project", "register"])
    register_captured = capsys.readouterr()
    assert register_code == 0
    assert json.loads(register_captured.out)["count"] == 1

    status_code = cli.main(["status", "--all"])
    status_captured = capsys.readouterr()
    status_output = json.loads(status_captured.out)

    assert status_code == 0
    assert status_output["count"] == 1
    assert status_output["projects"][0]["root"] == str(project_a.resolve())
