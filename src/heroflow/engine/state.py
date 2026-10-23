"""Состояние задачи и его хранение на диске: ~/.heroflow/tasks/<KEY>/state.json."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field

from heroflow.paths import heroflow_home

CONTEXT_DIR_NAME = ".heroflow-context"


def now() -> datetime:
    return datetime.now(UTC)


class TaskStatus(StrEnum):
    RUNNING = "running"
    WAITING_HUMAN = "waiting_human"
    STUCK = "stuck"
    FAILED = "failed"
    DONE = "done"


class JiraAttachment(BaseModel):
    id: str
    filename: str
    url: str
    size: int = 0


class JiraTask(BaseModel):
    key: str
    summary: str
    issue_type: str
    # Markdown для промптов, без служебного блока heroflow
    description: str = ""
    # Исходная wiki-разметка: из неё читаются директивы heroflow и ссылки на ветки
    description_raw: str = ""
    attachments: list[JiraAttachment] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)
    epic_key: str | None = None
    sprint: str | None = None


class PullRequest(BaseModel):
    id: int
    url: str


class ContextRepo(BaseModel):
    """Внешний репозиторий, склонированный как контекст (например, системная аналитика)."""

    path: str  # относительно repo_path
    branch: str
    sha: str
    source: str  # откуда взята ветка: directive / link / issue_key / default


class TaskContext(BaseModel):
    """Данные, которые узлы читают и пишут. Опечатка в поле ловится mypy, а не через час прогона."""

    issue_key: str
    flow: str
    base_branch: str
    branch_name: str
    task_dir: Path
    jira: JiraTask
    explore_file: str | None = None
    delta_spec_dir: str | None = None
    pull_request: PullRequest | None = None
    processed_comment_ids: list[int] = Field(default_factory=list)
    # Пути относительно repo_path, чтобы агент видел их внутри рабочей папки
    attachments: list[str] = Field(default_factory=list)
    context_repos: dict[str, ContextRepo] = Field(default_factory=dict)

    @property
    def repo_path(self) -> Path:
        return self.task_dir / "repo"

    @property
    def context_dir(self) -> Path:
        """Папка внешнего контекста внутри клона. Исключена из git через .git/info/exclude."""
        return self.repo_path / CONTEXT_DIR_NAME

    @property
    def logs_dir(self) -> Path:
        return self.task_dir / "logs"


class Transition(BaseModel):
    node: str
    outcome: str
    started_at: datetime
    finished_at: datetime

    @property
    def duration_s(self) -> float:
        return (self.finished_at - self.started_at).total_seconds()


class TaskState(BaseModel):
    context: TaskContext
    status: TaskStatus = TaskStatus.RUNNING
    current_node: str | None = None
    visits: dict[str, int] = Field(default_factory=dict)
    history: list[Transition] = Field(default_factory=list)
    error: str | None = None
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)

    @property
    def key(self) -> str:
        return self.context.issue_key


class TaskStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or heroflow_home() / "tasks"

    def task_dir(self, key: str) -> Path:
        return self.root / key

    def _file(self, key: str) -> Path:
        return self.task_dir(key) / "state.json"

    def exists(self, key: str) -> bool:
        return self._file(key).exists()

    def load(self, key: str) -> TaskState:
        return TaskState.model_validate_json(self._file(key).read_text(encoding="utf-8"))

    def save(self, state: TaskState) -> None:
        state.updated_at = now()
        path = self._file(state.key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Пишем во временный файл и переименовываем, чтобы Ctrl+C не оставил битый JSON
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(state.model_dump_json(indent=2), encoding="utf-8")
        tmp.replace(path)

    def list(self) -> list[TaskState]:
        if not self.root.exists():
            return []
        states = [self.load(p.parent.name) for p in self.root.glob("*/state.json")]
        return sorted(states, key=lambda s: s.updated_at, reverse=True)

    def delete(self, key: str) -> None:
        shutil.rmtree(self.task_dir(key))
