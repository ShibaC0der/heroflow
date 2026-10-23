from __future__ import annotations

from pathlib import Path

from conftest import make_context
from typer.testing import CliRunner

from heroflow.cli import app
from heroflow.engine import Finding, Review, Severity, TaskState, TaskStatus, TaskStore, Verdict

runner = CliRunner()


def add_task(key: str, status: TaskStatus) -> None:
    store = TaskStore()
    state = TaskState(context=make_context(store.task_dir(key), issue_key=key), status=status)
    store.save(state)


def test_list_shows_tasks(heroflow_home: Path) -> None:
    add_task("PAY-1", TaskStatus.DONE)
    add_task("PAY-2", TaskStatus.WAITING_HUMAN)

    result = runner.invoke(app, ["list"])

    assert result.exit_code == 0, result.output
    assert "PAY-1" in result.output
    assert "PAY-2" in result.output
    assert "waiting_human" in result.output


def test_clean_done_removes_only_finished(heroflow_home: Path) -> None:
    add_task("PAY-1", TaskStatus.DONE)
    add_task("PAY-2", TaskStatus.FAILED)

    result = runner.invoke(app, ["clean", "--done", "--yes"])

    assert result.exit_code == 0, result.output
    assert not TaskStore().exists("PAY-1")
    assert TaskStore().exists("PAY-2")


def test_clean_requires_target(heroflow_home: Path) -> None:
    assert runner.invoke(app, ["clean"]).exit_code == 2


def test_status_prints_history_and_last_review(heroflow_home: Path) -> None:
    add_task("PAY-1", TaskStatus.STUCK)
    store = TaskStore()
    state = store.load("PAY-1")
    finding = Finding(severity=Severity.MAJOR, title="нет теста на лимит")
    state.context.reviews["code_review"] = [Review(verdict=Verdict.ITERATE, summary="почти", findings=[finding])]
    store.save(state)

    result = runner.invoke(app, ["status", "PAY-1"])

    assert result.exit_code == 0, result.output
    assert "stuck" in result.output
    assert "нет теста на лимит" in result.output
