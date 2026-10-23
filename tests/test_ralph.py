from __future__ import annotations

from pathlib import Path

import pytest
from conftest import World, make_context

from heroflow.config import ChecksConfig
from heroflow.engine import Outcome, TaskContext
from heroflow.integrations.checks import run_checks
from heroflow.integrations.git import Git
from heroflow.nodes.ralph import RalphImplement, mark_done, pending_steps, stuck_reason

TASKS = "## Задачи\n- [x] 0. Готово\n- [ ] 1. Модель лимита\n  - [ ] 1.1 вложенный\n* [ ] 2. API\n"


def test_pending_and_mark_done() -> None:
    assert pending_steps(TASKS) == ["1. Модель лимита", "1.1 вложенный", "2. API"]
    marked = mark_done(TASKS, "1.1 вложенный")
    assert "  - [x] 1.1 вложенный\n" in marked
    assert pending_steps(marked) == ["1. Модель лимита", "2. API"]


def test_stuck_reason() -> None:
    assert stuck_reason("сделал\nHEROFLOW_STUCK: в спеке два разных лимита") == "в спеке два разных лимита"
    assert stuck_reason("всё хорошо") is None


def test_checks_use_repo_override(tmp_path: Path) -> None:
    cfg = ChecksConfig(commands=["false"], timeout_s=5)
    assert not run_checks(tmp_path, cfg).ok
    (tmp_path / ".heroflow.yaml").write_text("checks:\n  - 'true'\n  - echo ok\n", encoding="utf-8")
    assert run_checks(tmp_path, cfg).ok


def test_checks_timeout(tmp_path: Path) -> None:
    result = run_checks(tmp_path, ChecksConfig(commands=["sleep 5"], timeout_s=1))
    assert not result.ok
    assert "Таймаут" in result.output


@pytest.fixture
def ctx(origin: Path, tmp_path: Path) -> TaskContext:
    ctx = make_context(tmp_path / "task")
    ctx.delta_spec_dir = "openspec/changes/pay-1"
    repo = Git(ctx.repo_path)
    repo.clone(str(origin))
    repo.fetch()
    repo.checkout_work_branch(ctx.branch_name, ctx.base_branch)
    tasks = ctx.repo_path / ctx.delta_spec_dir / "tasks.md"
    tasks.parent.mkdir(parents=True)
    tasks.write_text("- [ ] 1. Модель\n- [ ] 2. API\n", encoding="utf-8")
    repo.commit_all("spec")
    return ctx


def commits(ctx: TaskContext) -> list[str]:
    import subprocess

    out = subprocess.run(
        ["git", "log", "--format=%s", "origin/master..HEAD"],
        cwd=ctx.repo_path,
        text=True,
        capture_output=True,
        check=True,
    ).stdout
    return out.splitlines()


def test_one_step_per_iteration_with_fix_of_red_checks(ctx: TaskContext, world: World) -> None:
    prompts: list[str] = []

    def agent(prompt: str, cwd: Path) -> None:
        prompts.append(prompt)
        n = len(prompts)
        if n == 1:
            (cwd / "Model.kt").write_text("model", encoding="utf-8")
        elif n == 2:
            (cwd / "Api.kt").write_text("api", encoding="utf-8")
            (cwd / "BROKEN").write_text("x", encoding="utf-8")  # сломал сборку
        elif n == 3:
            (cwd / "BROKEN").unlink()  # починил

    world.agent.scripts["ralph"] = agent

    assert RalphImplement().run(ctx, world.env) is Outcome.OK

    assert "«1. Модель»" in prompts[0]
    assert "«2. API»" in prompts[1]
    assert "починить проверки" in prompts[2] and "test ! -f BROKEN" in prompts[2]
    assert commits(ctx) == ["PAY-1: 2. API", "PAY-1: 1. Модель", "spec"]
    tasks = (ctx.repo_path / "openspec/changes/pay-1/tasks.md").read_text(encoding="utf-8")
    assert pending_steps(tasks) == []
    progress = (ctx.context_dir / "ralph/progress.md").read_text(encoding="utf-8")
    assert "упала" in progress and "зелёно" in progress
    assert ctx.ralph.iterations == 3
    assert not Git(ctx.repo_path).has_changes()


def test_agent_can_declare_stuck(ctx: TaskContext, world: World) -> None:
    world.agent.scripts["ralph"] = lambda p, c: "HEROFLOW_STUCK: противоречие в спеке"
    assert RalphImplement().run(ctx, world.env) is Outcome.STUCK
    assert ctx.ralph.stuck_reason == "противоречие в спеке"


def test_stuck_after_failures_in_row_and_resume_keeps_failure(ctx: TaskContext, world: World) -> None:
    def breaks(prompt: str, cwd: Path) -> None:
        (cwd / "BROKEN").write_text("x", encoding="utf-8")

    world.agent.scripts["ralph"] = breaks
    assert RalphImplement(max_failures_in_row=2).run(ctx, world.env) is Outcome.STUCK
    assert "2 итерации подряд" in ctx.ralph.stuck_reason
    assert commits(ctx) == ["spec"]

    # Человек починил руками и продолжил: следующая итерация знает о падении, но получает новый бюджет
    (ctx.repo_path / "BROKEN").unlink()
    seen: list[str] = []

    def fixes(prompt: str, cwd: Path) -> None:
        seen.append(prompt)

    world.agent.scripts["ralph"] = fixes
    assert RalphImplement().run(ctx, world.env) is Outcome.OK
    assert "починить проверки" in seen[0]


def test_budget_exhausted(ctx: TaskContext, world: World) -> None:
    world.agent.scripts["ralph"] = lambda p, c: None  # ничего не делает, пункт не отмечается
    # Зелёные проверки, но агент не отметил пункт: heroflow отмечает сам, так что бюджета 1 не хватит на 2 пункта
    assert RalphImplement(max_iterations=1).run(ctx, world.env) is Outcome.STUCK
    assert "бюджет" in ctx.ralph.stuck_reason
