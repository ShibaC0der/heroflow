import logging
from pathlib import Path

import bitbucket
import git

log = logging.getLogger(__name__)


def create_pull_request(data):
    log.info("Создание PR")

    if "pull_request" in data:
        log.info(f"PR ранее создан -> {data['pull_request']['url']}")
        return

    branch_name = data["branch_name"]
    repo_path = Path(data["sandbox_path"]) / "repo"
    tak_summary = data["jira_task"]["summary"]
    base_branch = data['base_branch']

    git.push(repo_path, branch_name)

    pull_request = bitbucket.create_pull_request(
        title=tak_summary,
        from_ref=f"refs/heads/{branch_name}",
        to_ref=f"refs/heads/{base_branch}"
    )

    data["pull_request"] = pull_request
