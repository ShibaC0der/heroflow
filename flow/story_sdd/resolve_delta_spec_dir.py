from pathlib import Path

import git


def resolve_delta_spec_dir(data: dict):
    delta_spec_dir = None
    repo_path = Path(data["sandbox_path"]) / "repo"

    for file_path in git.get_files_from_commit(commit_hash="HEAD", repo_path=repo_path):
        path = Path(file_path)

        if len(path.parts) >= 3 and path.parts[0:2] == ("openspec", "changes"):
            delta_spec_dir = "/".join(path.parts[:3])
            break

    if not delta_spec_dir:
        raise Exception("Не удалось определить директорию delta спецификации")

    data["delta_spec_dir"] = delta_spec_dir
