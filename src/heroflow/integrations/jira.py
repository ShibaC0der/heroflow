from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from jira2markdown import convert

from heroflow.config import HttpConfig, JiraConfig
from heroflow.engine.state import JiraTask
from heroflow.integrations.http import HttpClient

log = logging.getLogger(__name__)


def parse_issue(issue_key: str, payload: dict[str, Any], epic_field: str) -> JiraTask:
    fields = payload["fields"]
    description = fields.get("description") or ""
    sprint = fields.get("sprint") or {}
    return JiraTask(
        key=issue_key,
        summary=fields.get("summary") or issue_key,
        issue_type=(fields.get("issuetype") or {}).get("name", ""),
        description=convert(description) if description else "",
        labels=fields.get("labels") or [],
        epic_key=fields.get(epic_field),
        sprint=sprint.get("name") if isinstance(sprint, dict) else None,
    )


class JiraClient:
    def __init__(self, config: JiraConfig, http: HttpConfig) -> None:
        self.config = config
        self.client = HttpClient(config.url, config.token, http)

    def get_task(self, issue_key: str) -> JiraTask:
        log.info("Загружаю задачу %s из Jira", issue_key)
        # agile API отдаёт поле sprint, обычный /rest/api — нет
        response = self.client.request("GET", f"/rest/agile/latest/issue/{issue_key}")
        return parse_issue(issue_key, response.json(), self.config.epic_field)

    def attach_file(self, issue_key: str, file_path: Path, file_name: str | None = None) -> None:
        if not file_path.exists():
            raise FileNotFoundError(f"Не найден файл {file_path} для задачи {issue_key}")
        log.info("Прикладываю %s к задаче %s", file_path, issue_key)
        with file_path.open("rb") as data:
            self.client.request(
                "POST",
                f"/rest/api/latest/issue/{issue_key}/attachments",
                headers={"X-Atlassian-Token": "no-check"},
                files={"file": (file_name or file_path.name, data, "application/octet-stream")},
            )

    def add_label(self, issue_key: str, label: str) -> None:
        log.info("Добавляю лейбл %s к задаче %s", label, issue_key)
        self.client.request(
            "PUT",
            f"/rest/api/latest/issue/{issue_key}",
            json={"update": {"labels": [{"add": label}]}},
        )
