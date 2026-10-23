import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Callable

import questionary
from questionary import Choice

import git
import jira
from config import get_config
from flow import FLOWS
from state import deep_merge

data = {}

log = logging.getLogger(__name__)


def init_sandbox(issue_key: str, branch_name: str, base_branch: str | None = None) -> Path:
    sandbox_path = Path.home() / ".heroflow" / "sandbox" / issue_key
    repo_path = sandbox_path / "repo"

    log.info(f"Инициализация песочницы -> {str(sandbox_path)}")

    repo_path.mkdir(parents=True, exist_ok=True)

    git.clone_repo(
        repo_url=get_config().bitbucket.repo_clone_url,
        dest_path=repo_path
    )

    git.checkout_branch(
        name=branch_name,
        repo_path=repo_path,
        base_branch=base_branch
    )

    return sandbox_path


def run_piepline(steps: list[Callable], data: dict):
    state_file = Path(data["sandbox_path"]) / "pipeline_state.json"
    state = {"completed_steps": {}, "data": data}

    if state_file.exists():
        with open(state_file, mode="r", encoding="utf-8") as file:
            state = deep_merge(json.load(file), {"data": data})

    data = state["data"]

    for step in steps:
        step_name = step.__name__
        if step_name not in state["completed_steps"]:
            logging.info(f"Запуск шага {step_name}")
            step(data)
            state["completed_steps"][step_name] = datetime.now().isoformat()
            state["data"] = data
            with open(state_file, mode="w", encoding="utf-8") as file:
                file.write(json.dumps(state, ensure_ascii=False, indent=4))
    log.info("Завершено")


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-i", "--issue",
        dest="issue_key",
        help="Номер задачи в Jira",
        required=True
    )
    parser.add_argument(
        "-b", "--base-branch",
        dest="base_branch",
        default="master",
        help="Ветка, от которой будет создана рабочая ветка. По умолчанию master"
    )
    parser.add_argument(
        "-f", "--flow",
        choices=list(FLOWS),
        help="Имя флоу. Если не указан и флоу несколько - будет предложен выбор"
    )
    return parser.parse_args()


def select_flow(flow_name: str | None) -> ModuleType:
    if flow_name:
        return FLOWS[flow_name]

    if len(FLOWS) == 1:
        name, module = next(iter(FLOWS.items()))
        return module

    answer = questionary.select(
        "Выберите флоу для запуска:",
        choices=[Choice(title=name, value=module) for name, module in FLOWS.items()]
    ).ask()

    if answer is None:
        raise Exception("Флоу не определен")

    return answer


def setup_logging(issue_key: str) -> None:
    level_name = "INFO"
    level = getattr(logging, level_name, logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(f"%(asctime)s [{issue_key}] %(message)s", datefmt="%H:%M:%S"))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)


def main():
    args = parse_args()
    issue_key = args.issue_key
    base_branch = args.base_branch

    setup_logging(issue_key)

    data["issue_key"] = issue_key
    data["branch_name"] = f"feature/{issue_key}"
    data["base_branch"] = base_branch
    data["jira_task"] = jira.get_jira_task(issue_key)

    sandbox_path = init_sandbox(issue_key, data["branch_name"], base_branch)

    data["sandbox_path"] = str(sandbox_path)

    flow = select_flow(args.flow)

    log.info(f"Запуск {flow.__name__} для задачи")

    run_piepline(flow.STEPS, data)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Процесс прерван пользователем. Выход...")
        sys.exit(130)
