from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import World, git, make_context

from heroflow.engine import TaskContext, TaskState, TaskStatus, TaskStore, run_flow
from heroflow.flows import branch_name, flow_for_issue_type
from heroflow.flows.bug_fix import FLOW
from heroflow.flows.bug_fix.nodes import short_test_name
from heroflow.integrations.git import Git

TEST_FILE = "src/test/LimitsTest.kt"
# Проверки проекта в этих тестах: тест-воспроизведение падает, пока нет исправления src/main/Limits.kt
CHECK = (
    f"! test -f {TEST_FILE} || test -f src/main/Limits.kt"
    ' || { echo "LimitsTest > rejects over limit FAILED"; exit 1; }'
)


def write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def answer(**fields: object) -> str:
    return f"```json\n{json.dumps(fields, ensure_ascii=False)}\n```"


@pytest.fixture
def ctx(origin: Path, tmp_path: Path, world: World) -> TaskContext:
    world.env.config.checks.commands = [CHECK]
    store = TaskStore(tmp_path / "tasks")
    ctx = make_context(store.task_dir("PAY-1"), flow="bug_fix")
    ctx.branch_name = "bugfix/PAY-1"
    repo = Git(ctx.repo_path)
    repo.clone(str(origin))
    repo.fetch()
    repo.checkout_work_branch(ctx.branch_name, ctx.base_branch)
    return ctx


def triage(prompt: str, cwd: Path) -> str:
    write(cwd, ".heroflow-context/bug/report.md", "## Симптом\nлимит не проверяется\n")
    return answer(actionable=True, summary="лимит не проверяется", missing=[])


def root_cause(prompt: str, cwd: Path) -> None:
    assert "rejects over limit FAILED" in prompt, "агенту показывают, как падает тест"
    write(cwd, ".heroflow-context/bug/root_cause.md", "## Причина\nнет проверки\n")
    write(cwd, ".heroflow-context/bug/tasks.md", "- [ ] Добавить проверку лимита\n")


def test_full_bug_flow(ctx: TaskContext, tmp_path: Path, origin: Path, world: World) -> None:
    attempts: list[str] = []

    def reproduce(prompt: str, cwd: Path) -> str:
        attempts.append(prompt)
        if len(attempts) == 1:
            return answer(test_file="src/test/Nope.kt", test_name="x")
        write(cwd, TEST_FILE, "class LimitsTest { fun `rejects over limit`() {} }\n")
        return answer(test_file=TEST_FILE, test_name="LimitsTest#rejects over limit")

    def fix(prompt: str, cwd: Path) -> None:
        assert "«Добавить проверку лимита»" in prompt and "rejects over limit" in prompt
        write(cwd, "src/main/Limits.kt", "class Limits\n")

    world.agent.scripts = {
        "bug_triage": triage,
        "bug_reproduce": reproduce,
        "bug_root_cause": root_cause,
        "ralph": fix,
    }
    world.human.answers = [False]  # замечаний на code review нет

    store = TaskStore(tmp_path / "tasks")
    result = run_flow(FLOW, TaskState(context=ctx, current_node="bug_triage"), world.env, store)

    assert result.status is TaskStatus.DONE, result.error
    assert len(attempts) == 2 and "не найден" in attempts[1], "вторая попытка получает причину отказа"
    assert result.context.bug.reproduced
    assert "rejects over limit FAILED" in result.context.bug.repro_output
    assert world.bitbucket.created == [("bugfix/PAY-1", "master")]
    assert [name for name, _ in world.jira.attachments] == ["PAY-1-report.md", "PAY-1-root_cause.md"]

    log = git("log", "--format=%s", "bugfix/PAY-1", cwd=origin).splitlines()
    assert log[:2] == ["PAY-1: Добавить проверку лимита", "PAY-1: failing test reproducing the bug"]
    files = git("ls-tree", "-r", "--name-only", "bugfix/PAY-1", cwd=origin).split()
    assert TEST_FILE in files and "src/main/Limits.kt" in files
    assert not any(f.startswith(".heroflow-context") for f in files), "разбор бага не попадает в коммиты"


def test_green_test_is_not_a_reproduction(ctx: TaskContext, tmp_path: Path, world: World) -> None:
    def passing_test(prompt: str, cwd: Path) -> str:
        write(cwd, "src/test/OtherTest.kt", "class OtherTest\n")
        return answer(test_file="src/test/OtherTest.kt", test_name="OtherTest#works")

    world.agent.scripts = {"bug_triage": triage, "bug_reproduce": passing_test}
    world.human.answers = [False]  # продолжить без воспроизведения? нет

    store = TaskStore(tmp_path / "tasks")
    result = run_flow(FLOW, TaskState(context=ctx, current_node="bug_triage"), world.env, store)

    assert result.status is TaskStatus.WAITING_HUMAN
    assert result.current_node == "bug_reproduce_gate"
    assert not result.context.bug.reproduced
    assert "3 попытки" in result.context.bug.note
    assert not Git(ctx.repo_path).has_changes(), "неудачные тесты откатываются"


def test_red_base_branch_stops_reproduction(ctx: TaskContext, tmp_path: Path, world: World) -> None:
    world.env.config.checks.commands = ["false"]
    world.agent.scripts = {"bug_triage": triage}
    world.human.answers = [False]

    store = TaskStore(tmp_path / "tasks")
    result = run_flow(FLOW, TaskState(context=ctx, current_node="bug_triage"), world.env, store)

    assert result.current_node == "bug_reproduce_gate"
    assert "ещё до теста" in result.context.bug.note
    assert not any(n == "bug_reproduce" for n, _ in world.agent.calls)


def test_triage_without_data_asks_human(ctx: TaskContext, tmp_path: Path, world: World) -> None:
    def unclear(prompt: str, cwd: Path) -> str:
        write(cwd, ".heroflow-context/bug/report.md", "## Симптом\n?\n")
        return answer(actionable=False, summary="непонятно", missing=["какой лимит правильный"])

    world.agent.scripts = {"bug_triage": unclear}
    world.human.answers = [False]

    store = TaskStore(tmp_path / "tasks")
    result = run_flow(FLOW, TaskState(context=ctx, current_node="bug_triage"), world.env, store)

    assert result.status is TaskStatus.WAITING_HUMAN
    assert result.current_node == "bug_triage_gate"
    assert "какой лимит правильный" in result.context.bug.note


def test_routing_and_branch() -> None:
    assert flow_for_issue_type("Bug") is FLOW
    assert flow_for_issue_type("Ошибка") is FLOW
    assert flow_for_issue_type("Story").name == "story_sdd"
    assert branch_name(FLOW, "PAY-1") == "bugfix/PAY-1"
    assert branch_name(flow_for_issue_type("Story"), "PAY-1") == "feature/PAY-1"


@pytest.mark.parametrize(
    ("name", "short"),
    [
        ("com.acme.LimitsTest#rejects 1.5 over limit", "rejects 1.5 over limit"),
        ("test_limits.py::test_over", "test_over"),
        ("com.acme.LimitsTest.rejectsOverLimit", "rejectsOverLimit"),
    ],
)
def test_short_test_name(name: str, short: str) -> None:
    assert short_test_name(name) == short
