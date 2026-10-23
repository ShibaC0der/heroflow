import logging
from pathlib import Path

import requests
import urllib3
from jira2markdown import convert

from config import JiraConfig, get_config

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

log = logging.getLogger(__name__)


def get_jira_task(issue_key: str, config: JiraConfig | None = None) -> dict:
    config = config or get_config().jira

    url = f"{config.url}/rest/agile/latest/issue/{issue_key}"

    log.info(f"Загружаем данные из Jira -> {url}")

    response = requests.get(
        url,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {config.token}"
        },
        verify=False
    )

    response.raise_for_status()
    json = response.json()
    fields = json["fields"]

    description_original = fields["description"]
    description_md = convert(description_original)

    return {
        "issue_type": fields["issuetype"]["name"],
        "description_original": description_original,
        "description": description_md,
        "epik_key": fields["customfield_11400"],
        "summary": fields["summary"],
        "labels": fields.get("labels", []),
        "sprint_version": fields["sprint"]["name"]
    }


def attach_file(issue_key: str, file_path: Path, file_name: str | None = None, config: JiraConfig | None = None):
    if not file_path.exists():
        raise RuntimeError(f"Ошибка добавления файла в задачу {issue_key}. Не найден файл по пути {file_path} ")

    log.info(f"Прикладываем файл {file_path} к задаче {issue_key}")

    config = config or get_config().jira
    url = f"{config.url}/rest/api/latest/issue/{issue_key}/attachments"
    file_name = file_name or str(file_path.name)

    with open(file_path, "rb") as file_data:
        response = requests.post(
            url,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {config.token}",
                "X-Atlassian-Token": "no-check"
            },
            verify=False,
            files={
                "file": (file_name, file_data, "application/octet-stream")
            }
        )
        response.raise_for_status()


def add_label(issue_key: str, label_name: str, config: JiraConfig | None = None) -> None:
    log.info(f"Добавление лейбла {label_name} к задаче {issue_key}")

    config = config or get_config().jira

    url = f"{config.url}/rest/api/latest/issue/{issue_key}"

    payload = {
        "update": {
            "labels": [
                {"add": label_name}
            ]
        }
    }

    response = requests.put(
        url,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {config.token}"
        },
        verify=False,
        json=payload
    )

    response.raise_for_status()
