from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import World, make_context

from heroflow.engine import Outcome, Review, TaskContext, TaskState, TaskStatus, TaskStore, run_flow
from heroflow.flows.story_sdd import FLOW
from heroflow.integrations.git import Git
from heroflow.nodes.agent import StructuredAnswerError, ask_structured, extract_json
from heroflow.nodes.review import CodeReviewFix, Ralplan


def verdict(v: str, *findings: tuple[str, str]) -> str:
    body = {"verdict": v, "summary": v, "findings": [{"severity": s, "title": t} for s, t in findings]}
    return f"Готово.\n```json\n{json.dumps(body, ensure_ascii=False)}\n```"


def answers(*replies: str):  # type: ignore[no-untyped-def]
    queue = list(replies)

    def script(prompt: str, cwd: Path) -> str:
        return queue.pop(0)

    return script


@pytest.fixture
def ctx(origin: Path, tmp_path: Path) -> TaskContext:
    ctx = make_context(tmp_path / "task")
    ctx.delta_spec_dir = "openspec/changes/pay-1"
    ctx.explore_file = "openspec/changes/explore-PAY-1.md"
    repo = Git(ctx.repo_path)
    repo.clone(str(origin))
    repo.fetch()
    repo.checkout_work_branch(ctx.branch_name, ctx.base_branch)
    return ctx


class TestStructured:
    def test_extract_json(self) -> None:
        assert extract_json('text ```json\n{"a": 1}\n``` more ```json\n{"a": 2}\n```') == '{"a": 2}'
        assert extract_json('вот {"a": {"b": 1}} всё') == '{"a": {"b": 1}}'
        with pytest.raises(ValueError):
            extract_json("нет json")

    def test_retry_with_error_then_success(self, ctx: TaskContext, world: World) -> None:
        world.agent.scripts["r"] = answers("не json", verdict("APPROVE"))
        review = ask_structured("r", ctx, world.env, "проверь", Review)
        assert review.verdict == "APPROVE"
        assert "Прошлый ответ не прошёл проверку" in world.agent.calls[1][1]

    def test_gives_up_after_retries(self, ctx: TaskContext, world: World) -> None:
        world.agent.scripts["r"] = answers('{"verdict": "MAYBE"}', '{"verdict": "MAYBE"}')
        with pytest.raises(StructuredAnswerError):
            ask_structured("r", ctx, world.env, "проверь", Review)

    def test_reviewer_edits_are_reverted(self, ctx: TaskContext, world: World) -> None:
        def sneaky(prompt: str, cwd: Path) -> str:
            (cwd / "README.md").write_text("испорчено", encoding="utf-8")
            (cwd / "new.txt").write_text("x", encoding="utf-8")
            return verdict("APPROVE")

        world.agent.scripts["r"] = sneaky
        ask_structured("r", ctx, world.env, "проверь", Review)
        assert (ctx.repo_path / "README.md").read_text(encoding="utf-8") == "service\n"
        assert not (ctx.repo_path / "new.txt").exists()


class TestCodeReviewFix:
    def test_fixes_major_then_approves(self, ctx: TaskContext, world: World) -> None:
        world.agent.scripts["code_review_review"] = answers(
            verdict("ITERATE", ("major", "нет проверки лимита"), ("minor", "имя переменной")),
            verdict("APPROVE"),
        )

        def fix(prompt: str, cwd: Path) -> None:
            assert "нет проверки лимита" in prompt
            assert "имя переменной" not in prompt, "minor не отдаём фиксеру"
            (cwd / "Limits.py").write_text("fixed", encoding="utf-8")

        world.agent.scripts["code_review_fix"] = fix

        assert CodeReviewFix().run(ctx, world.env) is Outcome.APPROVE
        assert len(ctx.reviews["code_review"]) == 2
        assert not Git(ctx.repo_path).has_changes()
        diff_prompt = next(p for n, p in world.agent.calls if n == "code_review_review")
        assert ".heroflow-context/review/diff.patch" in diff_prompt

    def test_only_minor_is_approve_without_fix(self, ctx: TaskContext, world: World) -> None:
        world.agent.scripts["code_review_review"] = answers(verdict("ITERATE", ("minor", "вкус")))
        assert CodeReviewFix().run(ctx, world.env) is Outcome.APPROVE
        assert [n for n, _ in world.agent.calls] == ["code_review_review"]

    def test_stuck_after_max_rounds(self, ctx: TaskContext, world: World) -> None:
        world.agent.scripts["code_review_review"] = lambda p, c: verdict("ITERATE", ("blocker", "всё плохо"))
        assert CodeReviewFix(max_rounds=2).run(ctx, world.env) is Outcome.STUCK
        names = [n for n, _ in world.agent.calls]
        assert names == ["code_review_review", "code_review_fix", "code_review_review"]


class TestRalplan:
    def test_planner_revises_until_critic_approves(self, ctx: TaskContext, world: World) -> None:
        world.agent.scripts["ralplan_architect"] = answers(
            verdict("ITERATE", ("major", "не как в референсе")), verdict("APPROVE")
        )
        world.agent.scripts["ralplan_critic"] = answers(
            verdict("ITERATE", ("major", "нет сценария")), verdict("APPROVE")
        )

        def planner(prompt: str, cwd: Path) -> None:
            assert "не как в референсе" in prompt and "нет сценария" in prompt
            (cwd / "design.md").write_text("ADR", encoding="utf-8")

        world.agent.scripts["ralplan_planner"] = planner

        assert Ralplan().run(ctx, world.env) is Outcome.APPROVE
        assert len(ctx.ralplan) == 2
        critic_round2 = [p for n, p in world.agent.calls if n == "ralplan_critic"][1]
        assert "нет сценария" in critic_round2, "критик видит свои прошлые находки"
        assert "не как в референсе" not in critic_round2, "но не видит ответ архитектора"

    def test_architect_blocker_prevents_approval(self, ctx: TaskContext, world: World) -> None:
        world.agent.scripts["ralplan_architect"] = lambda p, c: verdict("ITERATE", ("blocker", "не тот модуль"))
        assert Ralplan(max_rounds=2).run(ctx, world.env) is Outcome.STUCK
        assert [n for n, _ in world.agent.calls].count("ralplan_planner") == 1


def test_ralplan_stuck_pauses_for_human_and_resume_continues(ctx: TaskContext, tmp_path: Path, world: World) -> None:
    store = TaskStore(tmp_path / "tasks")
    tasks = ctx.repo_path / "openspec/changes/pay-1/tasks.md"
    tasks.parent.mkdir(parents=True)
    tasks.write_text("- [ ] 1. Модель\n", encoding="utf-8")
    Git(ctx.repo_path).commit_all("spec")
    world.agent.scripts["ralplan_critic"] = lambda p, c: verdict("ITERATE", ("major", "нет сценария"))
    world.human.answers = [False]

    state = run_flow(FLOW, TaskState(context=ctx, current_node="ralplan"), world.env, store)

    assert state.status is TaskStatus.WAITING_HUMAN
    assert state.current_node == "ralplan_gate"
    assert len(state.context.ralplan) == 5

    # Человек поправил спеку руками и решил продолжить
    world.human.answers = [True, False, False]
    state = run_flow(FLOW, store.load(ctx.issue_key), world.env, store)

    assert state.status is TaskStatus.DONE, state.error
    assert [t.node for t in state.history].count("ralplan_gate") == 2
