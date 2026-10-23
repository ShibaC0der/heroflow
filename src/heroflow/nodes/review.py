"""Ревью с разделением ролей: ревьювер только читает и выносит вердикт, фиксер только правит."""

from __future__ import annotations

import logging

from heroflow.engine import Env, Finding, Outcome, RalplanRound, Review, Severity, TaskContext, Verdict
from heroflow.engine.state import CONTEXT_DIR_NAME
from heroflow.integrations.checks import run_checks
from heroflow.integrations.git import Git
from heroflow.nodes.agent import Role, ask_structured, call_agent
from heroflow.prompts import render

log = logging.getLogger(__name__)


class CodeReviewFix:
    """Цикл «ревью -> правка» по коду ветки.

    Ревьювер видит diff относительно базовой ветки и находки прошлого раунда.
    APPROVE или нет находок не ниже `fix_threshold` -> APPROVE. Раунды кончились -> STUCK.
    История раундов хранится в ctx.reviews[name], поэтому resume продолжает с того же раунда.
    """

    def __init__(
        self,
        name: str = "code_review",
        max_rounds: int = 3,
        fix_threshold: Severity = Severity.MAJOR,
        *,
        review_template: str = "review/code_review.md.j2",
        fix_template: str = "review/code_fix.md.j2",
    ):
        self.name = name
        self.max_rounds = max_rounds
        self.fix_threshold = fix_threshold
        self.review_template = review_template
        self.fix_template = fix_template

    def run(self, ctx: TaskContext, env: Env) -> Outcome:
        history = ctx.reviews.setdefault(self.name, [])
        git = Git(ctx.repo_path)
        diff_file = ctx.context_dir / "review" / "diff.patch"
        git.exclude(f"/{CONTEXT_DIR_NAME}/")

        while len(history) < self.max_rounds:
            diff_file.parent.mkdir(parents=True, exist_ok=True)
            diff_file.write_text(git.diff(f"origin/{ctx.base_branch}"), encoding="utf-8")
            previous = history[-1].findings if history else []
            prompt = render(
                self.review_template,
                ctx=ctx,
                diff_file=diff_file.relative_to(ctx.repo_path).as_posix(),
                previous=previous,
            )
            review = ask_structured(f"{self.name}_review", ctx, env, prompt, Review)
            history.append(review)
            to_fix = review.at_least(self.fix_threshold)
            log.info("Ревью кода, раунд %s: %s, к исправлению %s", len(history), review.verdict, len(to_fix))

            if review.verdict is Verdict.APPROVE or not to_fix:
                return Outcome.APPROVE
            if len(history) >= self.max_rounds:
                break

            if self._fix(ctx, env, to_fix) and git.commit_all(f"fix code review round {len(history)}. {ctx.issue_key}"):
                git.push(ctx.branch_name)

        log.warning("Ревью кода не сошлось за %s раунда", self.max_rounds)
        return Outcome.STUCK

    def _fix(self, ctx: TaskContext, env: Env, findings: list[Finding]) -> bool:
        """Фиксер правит, heroflow проверяет. Две попытки получить зелёные проверки, иначе правки откатываются."""
        failure = ""
        for _ in range(2):
            prompt = render(self.fix_template, ctx=ctx, findings=findings, failure=failure)
            call_agent(f"{self.name}_fix", ctx, env, prompt, role=Role.FIXER)
            result = run_checks(ctx.repo_path, env.config.checks)
            if result.ok:
                return True
            failure = f"$ {result.command}\n{result.output}"
        log.warning("Правки по ревью ломают проверки, откатываю их")
        Git(ctx.repo_path).discard_changes()
        return False


def ralplan_approved(round_: RalplanRound) -> bool:
    """Критик одобрил, а у архитектора нет блокеров и он не отверг подход."""
    architect = round_.architect
    return (
        round_.critic.verdict is Verdict.APPROVE
        and architect.verdict is not Verdict.REJECT
        and not architect.at_least(Severity.BLOCKER)
    )


class Ralplan:
    """Planner -> Architect + Critic -> Planner дорабатывает, пока Critic не скажет APPROVE.

    Architect и Critic смотрят на один и тот же снимок спеки и не видят ответы друг друга.
    Planner получает оба ревью. После каждой доработки — коммит.
    """

    name = "ralplan"

    def __init__(self, max_rounds: int = 5) -> None:
        self.max_rounds = max_rounds

    def run(self, ctx: TaskContext, env: Env) -> Outcome:
        git = Git(ctx.repo_path)
        while len(ctx.ralplan) < self.max_rounds:
            last = ctx.ralplan[-1] if ctx.ralplan else None
            architect = ask_structured(
                "ralplan_architect",
                ctx,
                env,
                render("review/spec_architect.md.j2", ctx=ctx, previous=last.architect.findings if last else []),
                Review,
            )
            critic = ask_structured(
                "ralplan_critic",
                ctx,
                env,
                render("review/spec_critic.md.j2", ctx=ctx, previous=last.critic.findings if last else []),
                Review,
            )
            round_ = RalplanRound(architect=architect, critic=critic)
            ctx.ralplan.append(round_)
            n = len(ctx.ralplan)
            log.info("ralplan, раунд %s: architect=%s critic=%s", n, architect.verdict, critic.verdict)

            if ralplan_approved(round_):
                return Outcome.APPROVE
            if n >= self.max_rounds:
                break

            call_agent(
                "ralplan_planner",
                ctx,
                env,
                render("review/spec_revise.md.j2", ctx=ctx, round=round_),
                role=Role.PLANNER,
            )
            git.commit_all(f"ralplan iteration {n}. {ctx.issue_key} [skip ci]")

        log.warning("ralplan не сошёлся за %s раундов", self.max_rounds)
        return Outcome.STUCK
