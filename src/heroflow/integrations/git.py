"""Тонкая обёртка над git CLI. Любая ошибка git — исключение со stderr, а не тихий успех."""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)


class GitError(RuntimeError):
    pass


class Git:
    def __init__(self, repo_path: Path) -> None:
        self.repo_path = repo_path

    def _run(self, *args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
        cmd = ["git", *args]
        result = subprocess.run(cmd, cwd=cwd or self.repo_path, text=True, capture_output=True, check=False)
        if check and result.returncode != 0:
            raise GitError(f"{' '.join(cmd)} -> {result.returncode}\n{result.stderr.strip()}")
        return result

    def clone(self, url: str) -> None:
        if (self.repo_path / ".git").exists():
            log.info("Репозиторий уже склонирован -> %s", self.repo_path)
            return
        log.info("Клонирую %s в %s", url, self.repo_path)
        self.repo_path.parent.mkdir(parents=True, exist_ok=True)
        self._run("clone", url, str(self.repo_path), cwd=self.repo_path.parent)

    def fetch(self) -> None:
        self._run("fetch", "origin")

    def current_branch(self) -> str:
        return self._run("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()

    def _has_ref(self, ref: str) -> bool:
        return self._run("rev-parse", "--verify", "--quiet", ref, check=False).returncode == 0

    def checkout_work_branch(self, name: str, base_branch: str) -> None:
        """Переключается на рабочую ветку. Если её ещё нет, создаёт от origin/<base_branch>."""
        if self.current_branch() == name:
            return
        if self._has_ref(f"refs/heads/{name}"):
            log.info("Переключаюсь на существующую ветку %s", name)
            self._run("checkout", name)
        elif self._has_ref(f"refs/remotes/origin/{name}"):
            log.info("Беру ветку %s с origin", name)
            self._run("checkout", "-b", name, f"origin/{name}")
        else:
            log.info("Создаю ветку %s от origin/%s", name, base_branch)
            self._run("checkout", "-b", name, f"origin/{base_branch}")

    def has_changes(self) -> bool:
        return bool(self._run("status", "--porcelain").stdout.strip())

    def commit_all(self, message: str) -> bool:
        """Коммитит всё. Возвращает False, если коммитить было нечего."""
        if not self.has_changes():
            log.info("Нет изменений для коммита: %s", message)
            return False
        log.info("Коммит -> %s", message)
        self._run("add", "-A")
        self._run("commit", "-m", message)
        return True

    def discard_changes(self) -> None:
        """Откатывает незакоммиченные правки и новые файлы. Исключённые (.git/info/exclude) не трогает."""
        self._run("reset", "--hard", "-q")
        self._run("clean", "-fdq")

    def diff(self, base: str) -> str:
        return self._run("diff", f"{base}...HEAD").stdout

    def push(self, branch: str) -> None:
        log.info("Push -> %s", branch)
        self._run("push", "-u", "origin", branch)

    def files_in_commit(self, commit: str = "HEAD") -> list[str]:
        out = self._run("diff-tree", "--no-commit-id", "--name-only", "-r", commit).stdout
        return [line.strip() for line in out.splitlines() if line.strip()]

    @staticmethod
    def remote_heads(url: str) -> list[str]:
        result = subprocess.run(["git", "ls-remote", "--heads", url], text=True, capture_output=True, check=False)
        if result.returncode != 0:
            raise GitError(f"git ls-remote --heads {url} -> {result.returncode}\n{result.stderr.strip()}")
        prefix = "refs/heads/"
        return [line.split("\t", 1)[1].removeprefix(prefix) for line in result.stdout.splitlines() if "\t" in line]

    def shallow_clone(self, url: str, branch: str, paths: list[str] | None = None) -> str:
        """Клон одной ветки без истории; с `paths` — только эти папки и файлы. Возвращает SHA."""
        if self.repo_path.exists():
            shutil.rmtree(self.repo_path)
        self.repo_path.parent.mkdir(parents=True, exist_ok=True)
        args = ["clone", "--depth", "1", "--branch", branch, "--single-branch"]
        if paths:
            args += ["--no-checkout"]
        self._run(*args, url, str(self.repo_path), cwd=self.repo_path.parent)
        if paths:
            self._run("sparse-checkout", "set", "--no-cone", *paths)
            self._run("checkout", branch)
        return self._run("rev-parse", "HEAD").stdout.strip()

    def exclude(self, pattern: str) -> None:
        """Добавляет путь в .git/info/exclude: как .gitignore, но без коммита."""
        exclude_file = self.repo_path / ".git" / "info" / "exclude"
        exclude_file.parent.mkdir(parents=True, exist_ok=True)
        lines = exclude_file.read_text(encoding="utf-8").splitlines() if exclude_file.exists() else []
        if pattern not in lines:
            exclude_file.write_text("\n".join([*lines, pattern]) + "\n", encoding="utf-8")
