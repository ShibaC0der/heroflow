import logging
from pathlib import Path

import git

log = logging.getLogger(__name__)


def remove_unnecessary_spec_changes(data):
    log.info("Удаление лишних файлов из openspec/changes, кроме spec.md")

    branch_name = data["branch_name"]
    repo_path = Path(data["sandbox_path"]) / "repo"
    changes_dir = repo_path / "openspec" / "changes"

    if not changes_dir.exists():
        return

    for file in changes_dir.rglob("*"):
        if not file.is_file():
            continue
        if file.name == "spec.md":
            continue
        file.unlink()

    git.commit_all(repo_path, f"remove unnecessary spec files. {data['issue_key']} [skip ci]")
    git.push(repo_path, branch_name)
