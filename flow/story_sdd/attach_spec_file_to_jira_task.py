import logging
from pathlib import Path

import jira

log = logging.getLogger(__name__)


def attach_spec_file_to_jira_task(data: dict):
    log.info("Прикладываю spec.md файл к задаче в Jira")

    issue_key = data["issue_key"]

    if not data["delta_spec_dir"]:
        log.info("Нет информации об spec.md файле")
        return

    absolute_delta_spec_dir = Path(data["sandbox_path"]) / "repo" / data["delta_spec_dir"]

    spec_file = next(absolute_delta_spec_dir.rglob("spec.md"), None)

    if not spec_file.exists():
        log.info(f"Нет spec.md по пути {spec_file}")
        return

    jira.attach_file(issue_key, file_path=spec_file, file_name="spec.md")
