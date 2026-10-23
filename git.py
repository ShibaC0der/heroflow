# TODO: строки 1-7 не попали на фото — импорты восстановлены по коду
import logging
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)


def clone_repo(repo_url: str, dest_path: Path):
    log.info(f"Клонирую репозиторий -> {repo_url} в {dest_path}")

    if (dest_path / ".git").exists():
        log.info("Репо уже склонирован")
        return

    result = subprocess.run(
        ["git", "clone", repo_url, dest_path],
        check=True,
        text=True,
        capture_output=True
    )


def commit_all(repo_path: Path, message: str):
    log.info(f"Делаю коммит изменений -> {message}")

    subprocess.run(["git", "add", "-A"], cwd=repo_path, check=True)
    subprocess.run(["git", "commit", "-m", message], cwd=repo_path, check=True)


def checkout_branch(name: str, repo_path: Path, base_branch: str | None = None):
    log.info(f"Создаю ветку -> {name} от {'origin/' + base_branch if base_branch else 'master'}")

    cmd = ["git", "checkout", "-b", name]
    if base_branch:
        cmd.append(f"origin/{base_branch}")

    subprocess.run(
        cmd,
        cwd=repo_path,
        text=True,
        capture_output=True
    )


def has_changes(repo_path: Path) -> bool:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_path,
        text=True,
        capture_output=True
    )

    return bool(result.stdout.strip())


def push(repo_path: Path, target_branch: str):
    log.info(f"Пуш изменений в ветку -> {target_branch}")

    subprocess.run(
        ["git", "push", "origin", target_branch],
        cwd=repo_path,
        text=True,
        capture_output=True
    )


def get_files_from_commit(commit_hash: str, repo_path: Path) -> list[str]:
    cmd = ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", commit_hash]

    result = subprocess.run(cmd, stdout=subprocess.PIPE, text=True, check=True, cwd=repo_path)

    return [line.strip() for line in result.stdout.splitlines() if line.strip()]
