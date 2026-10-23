from __future__ import annotations

import logging
import sys
from datetime import datetime
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from heroflow.config import get_config
from heroflow.engine import Env, TaskContext, TaskState, TaskStatus, TaskStore, run_flow
from heroflow.flows import FLOWS, flow_for_issue_type, get_flow

app = typer.Typer(help="heroflow: задача из Jira -> спека -> код -> PR", no_args_is_help=True)
console = Console()
log = logging.getLogger("heroflow")

STATUS_STYLE = {
    TaskStatus.RUNNING: "cyan",
    TaskStatus.WAITING_HUMAN: "yellow",
    TaskStatus.STUCK: "magenta",
    TaskStatus.FAILED: "red",
    TaskStatus.DONE: "green",
}


def setup_logging(issue_key: str, store: TaskStore) -> None:
    fmt = logging.Formatter(f"%(asctime)s [{issue_key}] %(message)s", datefmt="%H:%M:%S")
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(fmt)
    task_dir = store.task_dir(issue_key)
    task_dir.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(task_dir / "heroflow.log", encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(console_handler)
    root.addHandler(file_handler)
    root.setLevel(logging.INFO)


def build_env() -> Env:
    from heroflow.integrations.bitbucket import BitbucketClient
    from heroflow.integrations.gigacode import GigaCodeAgent
    from heroflow.integrations.human import TerminalHuman
    from heroflow.integrations.jira import JiraClient

    config = get_config()
    return Env(
        config=config,
        jira=JiraClient(config.jira, config.http),
        bitbucket=BitbucketClient(config.bitbucket, config.http),
        agent=GigaCodeAgent(config.gigacode),
        human=TerminalHuman(),
    )


def _drive(state: TaskState, env: Env, store: TaskStore) -> None:
    flow = get_flow(state.context.flow)
    try:
        state = run_flow(flow, state, env, store)
    except KeyboardInterrupt:
        log.info("Прервано пользователем. Продолжить: heroflow resume %s", state.key)
        raise typer.Exit(130) from None
    except Exception:
        log.exception("Узел %s упал. Продолжить после исправления: heroflow resume %s", state.current_node, state.key)
        raise typer.Exit(1) from None
    console.print(f"[{STATUS_STYLE[state.status]}]{state.key}: {state.status}[/]")
    if state.error:
        console.print(state.error)


@app.command()
def run(
    issue_key: Annotated[str, typer.Argument(help="Ключ задачи в Jira")],
    base_branch: Annotated[str, typer.Option("--base", "-b", help="Ветка, от которой создаётся рабочая")] = "master",
    flow_name: Annotated[
        str | None, typer.Option("--flow", "-f", help=f"Флоу: {', '.join(FLOWS)}. По умолчанию по типу задачи")
    ] = None,
) -> None:
    """Запустить флоу по задаче. Если задача уже есть, продолжить её."""
    store = TaskStore()
    setup_logging(issue_key, store)
    env = build_env()

    if store.exists(issue_key):
        log.info("Задача уже запускалась, продолжаю")
        _drive(store.load(issue_key), env, store)
        return

    jira_task = env.jira.get_task(issue_key)
    flow = get_flow(flow_name) if flow_name else flow_for_issue_type(jira_task.issue_type)
    ctx = TaskContext(
        issue_key=issue_key,
        flow=flow.name,
        base_branch=base_branch,
        branch_name=f"feature/{issue_key}",
        task_dir=store.task_dir(issue_key),
        jira=jira_task,
    )
    log.info("Запуск флоу %s", flow.name)
    _drive(TaskState(context=ctx), env, store)


@app.command()
def resume(issue_key: Annotated[str, typer.Argument(help="Ключ задачи в Jira")]) -> None:
    """Продолжить задачу с узла, на котором она остановилась."""
    store = TaskStore()
    if not store.exists(issue_key):
        console.print(f"[red]Задача {issue_key} не найдена. Запустите: heroflow run {issue_key}[/]")
        raise typer.Exit(1)
    setup_logging(issue_key, store)
    _drive(store.load(issue_key), build_env(), store)


def _ago(dt: datetime) -> str:
    return dt.astimezone().strftime("%d.%m %H:%M")


@app.command("list")
def list_tasks() -> None:
    """Все задачи: название, флоу, текущий узел, статус, PR."""
    states = TaskStore().list()
    if not states:
        console.print("Задач нет")
        return
    table = Table("Задача", "Название", "Флоу", "Узел", "Статус", "PR", "Обновлено")
    for s in states:
        table.add_row(
            s.key,
            s.context.jira.summary,
            s.context.flow,
            s.current_node or "",
            f"[{STATUS_STYLE[s.status]}]{s.status}[/]",
            s.context.pull_request.url if s.context.pull_request else "",
            _ago(s.updated_at),
        )
    console.print(table)


@app.command()
def status(issue_key: Annotated[str, typer.Argument(help="Ключ задачи в Jira")]) -> None:
    """История узлов задачи с исходами и длительностью."""
    store = TaskStore()
    if not store.exists(issue_key):
        console.print(f"[red]Задача {issue_key} не найдена[/]")
        raise typer.Exit(1)
    s = store.load(issue_key)
    console.print(f"[bold]{s.key}[/] {s.context.jira.summary}")
    console.print(
        f"Флоу: {s.context.flow}  Статус: [{STATUS_STYLE[s.status]}]{s.status}[/]  Узел: {s.current_node or '-'}"
    )
    if s.context.pull_request:
        console.print(f"PR: {s.context.pull_request.url}")
    if s.error:
        console.print(f"[red]{s.error}[/]")
    table = Table("Начало", "Узел", "Исход", "Длительность")
    for t in s.history:
        table.add_row(_ago(t.started_at), t.node, t.outcome, f"{t.duration_s:.0f} с")
    console.print(table)
    console.print(f"Папка задачи: {s.context.task_dir}")


@app.command()
def clean(
    issue_keys: Annotated[list[str] | None, typer.Argument(help="Конкретные задачи")] = None,
    done: Annotated[bool, typer.Option("--done", help="Все завершённые")] = False,
    failed: Annotated[bool, typer.Option("--failed", help="Все упавшие")] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Без подтверждения")] = False,
) -> None:
    """Удалить папки задач (клон репозитория, логи, состояние)."""
    store = TaskStore()
    states = store.list()
    wanted = set(issue_keys or [])
    statuses = {TaskStatus.DONE} if done else set()
    if failed:
        statuses.add(TaskStatus.FAILED)
    if not wanted and not statuses:
        console.print("Укажите задачи или --done / --failed")
        raise typer.Exit(2)

    targets = [s for s in states if s.key in wanted or s.status in statuses]
    unknown = wanted - {s.key for s in states}
    for key in sorted(unknown):
        console.print(f"[yellow]{key}: не найдена[/]")
    if not targets:
        console.print("Удалять нечего")
        return

    for s in targets:
        console.print(f"  {s.key}  {s.status}  {s.context.jira.summary}")
    if not yes and not typer.confirm(f"Удалить {len(targets)} задач(и)?"):
        raise typer.Exit(1)
    for s in targets:
        store.delete(s.key)
    console.print(f"Удалено: {len(targets)}")
