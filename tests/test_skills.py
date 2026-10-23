from __future__ import annotations

from pathlib import Path

import pytest
from conftest import git
from typer.testing import CliRunner

from heroflow.cli import app
from heroflow.config import SkillsConfig
from heroflow.skills import available_skills, install_skills, node_skills, skills_hint


def make_skill(root: Path, name: str, description: str = "") -> None:
    path = root / name / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n", encoding="utf-8")


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git("init", "-q", cwd=repo)
    return repo


def test_sources_and_priority(tmp_path: Path) -> None:
    qwen = tmp_path / "qwen"
    make_skill(qwen / "extensions/ponytail/skills", "ponytail-review", "из расширения")
    make_skill(qwen / "skills", "mine")
    repo = make_repo(tmp_path)
    make_skill(repo / ".qwen/skills", "mine", "из репозитория")
    config = SkillsConfig(qwen_home=str(qwen), nodes={})

    found = available_skills(repo, config)

    assert found["review-checklist"].visible_to_cli is False, "встроенный скилл heroflow"
    assert found["ponytail-review"].visible_to_cli is True
    assert found["mine"].description == "из репозитория"


def test_install_copies_only_hidden_skills(tmp_path: Path) -> None:
    qwen, extra = tmp_path / "qwen", tmp_path / "extra"
    make_skill(qwen / "skills", "ponytail")
    make_skill(extra, "team-style")
    repo = make_repo(tmp_path)
    nodes = {"ralph": ["ponytail", "team-style"], "code_review_review": ["review-checklist", "missing"]}
    config = SkillsConfig(qwen_home=str(qwen), dirs=[str(extra)], nodes=nodes)

    installed = install_skills(repo, config)

    assert installed == ["review-checklist", "team-style"]
    assert (repo / ".qwen/skills/team-style/SKILL.md").exists()
    assert not (repo / ".qwen/skills/ponytail").exists(), "CLI найдёт его сам"
    assert git("status", "--porcelain", cwd=repo) == "", "скопированные скиллы не попадают в коммиты"


def test_repo_config_overrides_node_skills_and_hint(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    (repo / ".heroflow.yaml").write_text("skills:\n  ralph: [review-checklist]\n", encoding="utf-8")
    config = SkillsConfig(qwen_home=str(tmp_path / "none"), nodes={"ralph": ["ponytail"], "explore": []})

    assert node_skills(repo, config) == {"ralph": ["review-checklist"], "explore": []}
    hint = skills_hint("ralph", repo, config)
    assert "`review-checklist`" in hint and "Чек-лист" in hint
    assert skills_hint("explore", repo, config) == ""


def test_skills_command_reports_missing(tmp_path: Path, heroflow_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HF_SKILLS_QWEN_HOME", str(tmp_path / "none"))
    result = CliRunner().invoke(app, ["skills"])

    assert result.exit_code == 0, result.output
    assert "review-checklist" in result.output
    assert "не найден" in result.output
    assert "DietrichGebert/ponytail" in result.output
