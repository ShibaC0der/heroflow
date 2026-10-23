from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest
from conftest import World, make_context

from heroflow.engine import (
    END,
    Flow,
    FlowError,
    Outcome,
    TaskContext,
    TaskState,
    TaskStatus,
    TaskStore,
    linear,
    run_flow,
)
from heroflow.engine.env import Env


@dataclass
class Scripted:
    """Узел, который по очереди возвращает заданные исходы (или бросает исключение)."""

    name: str
    outcomes: list[Outcome | Exception] = field(default_factory=lambda: [Outcome.OK])
    calls: int = 0

    def run(self, ctx: TaskContext, env: Env) -> Outcome:
        self.calls += 1
        result = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(result, Exception):
            raise result
        return result


def start(tmp_path: Path) -> tuple[TaskState, TaskStore]:
    store = TaskStore(tmp_path / "tasks")
    return TaskState(context=make_context(store.task_dir("PAY-1"))), store


def test_linear_flow_runs_to_end(tmp_path: Path, world: World) -> None:
    a, b = Scripted("a"), Scripted("b")
    flow = Flow("f", "a", (a, b), linear("a", "b", END))
    state, store = start(tmp_path)

    result = run_flow(flow, state, world.env, store)

    assert result.status is TaskStatus.DONE
    assert [t.node for t in result.history] == ["a", "b"]
    assert store.load("PAY-1").status is TaskStatus.DONE


def test_outcome_selects_branch(tmp_path: Path, world: World) -> None:
    review = Scripted("review", [Outcome.ITERATE, Outcome.APPROVE])
    fix, ship = Scripted("fix"), Scripted("ship")
    flow = Flow(
        "f",
        "review",
        (review, fix, ship),
        {
            ("review", Outcome.ITERATE): "fix",
            ("fix", Outcome.OK): "review",
            ("review", Outcome.APPROVE): "ship",
            ("ship", Outcome.OK): END,
        },
        default_max_visits=3,
    )
    state, store = start(tmp_path)

    result = run_flow(flow, state, world.env, store)

    assert [t.node for t in result.history] == ["review", "fix", "review", "ship"]
    assert result.status is TaskStatus.DONE


def test_loop_stops_at_visit_limit(tmp_path: Path, world: World) -> None:
    loop = Scripted("loop", [Outcome.ITERATE])
    flow = Flow("f", "loop", (loop,), {("loop", Outcome.ITERATE): "loop"}, max_visits={"loop": 3})
    state, store = start(tmp_path)

    result = run_flow(flow, state, world.env, store)

    assert result.status is TaskStatus.STUCK
    assert loop.calls == 3


def test_failure_is_saved_and_resume_continues_from_failed_node(tmp_path: Path, world: World) -> None:
    a = Scripted("a")
    b = Scripted("b", [RuntimeError("упало"), Outcome.OK])
    flow = Flow("f", "a", (a, b), linear("a", "b", END))
    state, store = start(tmp_path)

    with pytest.raises(RuntimeError):
        run_flow(flow, state, world.env, store)
    saved = store.load("PAY-1")
    assert saved.status is TaskStatus.FAILED
    assert saved.current_node == "b"
    assert "упало" in (saved.error or "")

    result = run_flow(flow, saved, world.env, store)

    assert result.status is TaskStatus.DONE
    assert a.calls == 1
    assert b.calls == 2


def test_need_human_without_edge_pauses(tmp_path: Path, world: World) -> None:
    gate = Scripted("gate", [Outcome.NEED_HUMAN])
    flow = Flow("f", "gate", (gate,), {("gate", Outcome.OK): END})
    state, store = start(tmp_path)

    result = run_flow(flow, state, world.env, store)

    assert result.status is TaskStatus.WAITING_HUMAN
    assert result.current_node == "gate"


def test_unknown_outcome_fails_loudly(tmp_path: Path, world: World) -> None:
    flow = Flow("f", "a", (Scripted("a", [Outcome.APPROVE]),), linear("a", END))
    state, store = start(tmp_path)

    with pytest.raises(FlowError):
        run_flow(flow, state, world.env, store)
    assert store.load("PAY-1").status is TaskStatus.FAILED


def test_flow_validates_edges() -> None:
    with pytest.raises(FlowError):
        Flow("f", "a", (Scripted("a"),), {("a", Outcome.OK): "missing"})
    with pytest.raises(FlowError):
        Flow("f", "missing", (Scripted("a"),), {})
