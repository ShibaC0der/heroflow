from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from heroflow.config import BitbucketConfig, Config, GigaCodeConfig, HttpConfig, JiraConfig
from heroflow.engine import Env, JiraTask, PullRequest, TaskContext
from heroflow.ports import PrComment


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, text=True, capture_output=True).stdout


@pytest.fixture(autouse=True)
def heroflow_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    monkeypatch.setenv("HEROFLOW_HOME", str(home))
    monkeypatch.setenv("GIT_AUTHOR_NAME", "test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@example.com")
    return home


@pytest.fixture
def origin(tmp_path: Path) -> Path:
    """Голый репозиторий-«Bitbucket» с одним коммитом в master и чужим change в openspec."""
    bare = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    git("init", "-q", "--bare", "-b", "master", str(bare), cwd=tmp_path)
    git("clone", "-q", str(bare), str(seed), cwd=tmp_path)
    other_change = seed / "openspec" / "changes" / "other-team-change"
    other_change.mkdir(parents=True)
    (other_change / "proposal.md").write_text("чужой change\n", encoding="utf-8")
    (seed / "README.md").write_text("service\n", encoding="utf-8")
    git("add", "-A", cwd=seed)
    git("commit", "-qm", "init", cwd=seed)
    git("push", "-q", "origin", "master", cwd=seed)
    return bare


@dataclass
class FakeJira:
    labels: list[str] = field(default_factory=list)
    attachments: list[tuple[str, str]] = field(default_factory=list)

    def get_task(self, issue_key: str) -> JiraTask:
        return JiraTask(key=issue_key, summary="Лимиты платежей", issue_type="Story", description="Сделать лимиты")

    def attach_file(self, issue_key: str, file_path: Path, file_name: str | None = None) -> None:
        self.attachments.append((file_name or file_path.name, file_path.read_text(encoding="utf-8")))

    def add_label(self, issue_key: str, label: str) -> None:
        self.labels.append(label)


@dataclass
class FakeBitbucket:
    comments: list[PrComment] = field(default_factory=list)
    created: list[tuple[str, str]] = field(default_factory=list)

    def create_pull_request(self, title: str, from_branch: str, to_branch: str, draft: bool = True) -> PullRequest:
        self.created.append((from_branch, to_branch))
        return PullRequest(id=42, url="https://bitbucket/pr/42")

    def heroflow_comments(self, pull_request_id: int) -> list[PrComment]:
        return list(self.comments)


AgentScript = Callable[[str, Path], None]


@dataclass
class FakeAgent:
    """Агент по сценарию: для каждого узла функция, которая «редактирует» репозиторий."""

    scripts: dict[str, AgentScript] = field(default_factory=dict)
    calls: list[tuple[str, str]] = field(default_factory=list)

    def run(
        self,
        prompt: str,
        cwd: Path,
        *,
        model: str | None = None,
        system_prompt: str | None = None,
        exclude_tools: list[str] | None = None,
        log_file: Path | None = None,
    ) -> str:
        node = log_file.stem.rsplit("-", 1)[0] if log_file else "?"
        self.calls.append((node, prompt))
        script = self.scripts.get(node)
        if script:
            script(prompt, cwd)
        return "ok"


@dataclass
class FakeHuman:
    answers: list[bool] = field(default_factory=list)

    def confirm(self, question: str) -> bool:
        return self.answers.pop(0)


def make_config() -> Config:
    return Config(
        bitbucket=BitbucketConfig(token="t", repo_slug="svc", project="PRJ", url="https://bitbucket"),
        jira=JiraConfig(token="t", url="https://jira"),
        gigacode=GigaCodeConfig(),
        http=HttpConfig(),
    )


@dataclass
class World:
    env: Env
    jira: FakeJira
    bitbucket: FakeBitbucket
    agent: FakeAgent
    human: FakeHuman


@pytest.fixture
def world() -> World:
    jira, bitbucket, agent, human = FakeJira(), FakeBitbucket(), FakeAgent(), FakeHuman()
    env = Env(config=make_config(), jira=jira, bitbucket=bitbucket, agent=agent, human=human)
    return World(env=env, jira=jira, bitbucket=bitbucket, agent=agent, human=human)


def make_context(task_dir: Path, issue_key: str = "PAY-1", flow: str = "story_sdd") -> TaskContext:
    return TaskContext(
        issue_key=issue_key,
        flow=flow,
        base_branch="master",
        branch_name=f"feature/{issue_key}",
        task_dir=task_dir,
        jira=JiraTask(key=issue_key, summary="Лимиты платежей", issue_type="Story", description="Сделать лимиты"),
    )
