"""Интерфейсы внешних систем. Узлы зависят от них, а не от requests/subprocess,
поэтому флоу тестируются на фейках без Jira, Bitbucket и gigacode."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from heroflow.engine.state import JiraAttachment, JiraTask, PullRequest


@dataclass(frozen=True)
class PrComment:
    id: int
    author: str
    text: str
    file: str | None = None
    line: int | None = None

    def as_markdown(self) -> str:
        where = f" Файл: {self.file}:{self.line or ''}" if self.file else ""
        return f"- {self.text}.{where}"


class Jira(Protocol):
    def get_task(self, issue_key: str) -> JiraTask: ...

    def attach_file(self, issue_key: str, file_path: Path, file_name: str | None = None) -> None: ...

    def add_label(self, issue_key: str, label: str) -> None: ...

    def download_attachment(self, attachment: JiraAttachment, dest: Path) -> None: ...


class Bitbucket(Protocol):
    def create_pull_request(self, title: str, from_branch: str, to_branch: str, draft: bool = True) -> PullRequest: ...

    def heroflow_comments(self, pull_request_id: int) -> list[PrComment]: ...


class Agent(Protocol):
    def run(
        self,
        prompt: str,
        cwd: Path,
        *,
        model: str | None = None,
        system_prompt: str | None = None,
        exclude_tools: list[str] | None = None,
        allowed_tools: list[str] | None = None,
        log_file: Path | None = None,
    ) -> str: ...


class Human(Protocol):
    def confirm(self, question: str) -> bool: ...
