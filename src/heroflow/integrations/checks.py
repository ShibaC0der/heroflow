"""Проверки проекта (сборка, линтер, тесты), которые heroflow запускает сам.

Результат проверок — факт, а не слова агента: по нему Ralph loop решает, готова ли задача.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

import yaml

from heroflow.config import ChecksConfig

log = logging.getLogger(__name__)

REPO_CONFIG = ".heroflow.yaml"


@dataclass(frozen=True)
class CheckResult:
    ok: bool
    command: str
    output: str


def commands_for(repo_path: Path, config: ChecksConfig) -> list[str]:
    """Команды из .heroflow.yaml репозитория, иначе из конфига heroflow."""
    repo_config = repo_path / REPO_CONFIG
    if repo_config.exists():
        data = yaml.safe_load(repo_config.read_text(encoding="utf-8")) or {}
        checks = data.get("checks")
        if checks:
            return [str(c) for c in checks]
    return list(config.commands)


def run_checks(repo_path: Path, config: ChecksConfig) -> CheckResult:
    """Запускает команды по очереди до первой упавшей."""
    for command in commands_for(repo_path, config):
        log.info("Проверка: %s", command)
        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=repo_path,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=config.timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired as e:
            output = e.stdout if isinstance(e.stdout, str) else ""
            return CheckResult(False, command, _tail(f"{output}\nТаймаут {config.timeout_s} с", config))
        if result.returncode != 0:
            log.info("Проверка упала: %s (код %s)", command, result.returncode)
            return CheckResult(False, command, _tail(result.stdout, config))
    return CheckResult(True, "", "")


def _tail(output: str, config: ChecksConfig) -> str:
    lines = output.splitlines()
    return "\n".join(lines[-config.output_tail_lines :])
