"""Узлы флоу bug_fix: разбор -> падающий тест -> причина -> исправление."""

from __future__ import annotations

import logging
from pathlib import Path

from pydantic import BaseModel, Field

from heroflow.engine import Env, Outcome, TaskContext
from heroflow.engine.state import CONTEXT_DIR_NAME
from heroflow.integrations.checks import CheckResult, run_checks
from heroflow.integrations.git import Git
from heroflow.nodes.agent import Role, ask_structured, call_agent
from heroflow.nodes.ralph import pending_steps
from heroflow.prompts import render

log = logging.getLogger(__name__)

PLAN_DIR = f"{CONTEXT_DIR_NAME}/bug"
REPORT = "report.md"
ROOT_CAUSE = "root_cause.md"
TASKS = "tasks.md"


def plan_dir(ctx: TaskContext) -> Path:
    return ctx.repo_path / (ctx.bug.plan_dir or PLAN_DIR)


def bug_tasks_file(ctx: TaskContext) -> Path:
    return plan_dir(ctx) / TASKS


def short_test_name(test_name: str) -> str:
    """`tests/test_limits.py::test_over` -> `test_over`, `LimitsTest#rejects` -> `rejects`: так тест виден в выводе."""
    for sep in ("#", "::", "."):
        if sep in test_name:
            test_name = test_name.rsplit(sep, 1)[1]
            break
    return test_name.strip().strip("`")


class TriageResult(BaseModel):
    actionable: bool
    summary: str
    missing: list[str] = Field(default_factory=list)


class Triage:
    """Разбор бага: симптом, ожидание, шаги, подозрительное место. Мало данных -> NEED_HUMAN."""

    name = "bug_triage"

    def run(self, ctx: TaskContext, env: Env) -> Outcome:
        Git(ctx.repo_path).exclude(f"/{CONTEXT_DIR_NAME}/")
        ctx.bug.plan_dir = PLAN_DIR
        plan_dir(ctx).mkdir(parents=True, exist_ok=True)
        prompt = render("bug_fix/triage.md.j2", ctx=ctx, report_file=f"{PLAN_DIR}/{REPORT}")
        result = ask_structured(self.name, ctx, env, prompt, TriageResult, role=Role.PLANNER)
        if not (plan_dir(ctx) / REPORT).exists():
            raise RuntimeError(f"Агент не создал {PLAN_DIR}/{REPORT}")
        log.info("Разбор бага: %s", result.summary)
        if not result.actionable:
            ctx.bug.note = "не хватает данных: " + "; ".join(result.missing)
            log.warning("В задаче не хватает данных: %s", ctx.bug.note)
            return Outcome.NEED_HUMAN
        return Outcome.OK


class Reproduction(BaseModel):
    test_file: str
    test_name: str


class Reproduce:
    """Агент пишет тест, который падает на текущем коде; heroflow сам проверяет, что он красный.

    Сначала проверки на чистой ветке должны быть зелёными, иначе красный тест ничего не доказывает.
    Тест считается воспроизведением, если проверки упали и в их выводе есть имя теста.
    """

    name = "bug_reproduce"

    def __init__(self, attempts: int = 3) -> None:
        self.attempts = attempts

    def run(self, ctx: TaskContext, env: Env) -> Outcome:
        if ctx.bug.reproduced:
            return Outcome.OK
        git = Git(ctx.repo_path)
        baseline = run_checks(ctx.repo_path, env.config.checks)
        if not baseline.ok:
            ctx.bug.note = f"проверки красные ещё до теста: `{baseline.command}`"
            log.warning("Базовая ветка красная, воспроизведение невозможно: %s", baseline.command)
            return Outcome.STUCK

        feedback = ""
        for attempt in range(1, self.attempts + 1):
            prompt = render("bug_fix/reproduce.md.j2", ctx=ctx, report_file=f"{PLAN_DIR}/{REPORT}", feedback=feedback)
            repro = ask_structured(self.name, ctx, env, prompt, Reproduction, role=Role.WORKER)
            result = run_checks(ctx.repo_path, env.config.checks)
            feedback = self._verdict(ctx, repro, result)
            if not feedback:
                ctx.bug.test_file, ctx.bug.test_name = repro.test_file, repro.test_name
                ctx.bug.repro_output = result.output
                ctx.bug.reproduced = True
                ctx.bug.note = ""
                git.commit_all(f"{ctx.issue_key}: failing test reproducing the bug")
                log.info("Баг воспроизведён тестом %s (попытка %s)", repro.test_name, attempt)
                return Outcome.OK
            log.warning("Воспроизведение, попытка %s: %s", attempt, feedback.splitlines()[0])

        git.discard_changes()
        ctx.bug.note = f"за {self.attempts} попытки не получилось падающего теста"
        return Outcome.STUCK

    @staticmethod
    def _verdict(ctx: TaskContext, repro: Reproduction, result: CheckResult) -> str:
        """Пусто, если тест годится; иначе что сказать агенту на следующей попытке."""
        if not (ctx.repo_path / repro.test_file).exists():
            return f"Файл `{repro.test_file}` не найден. Укажи путь к тесту относительно корня репозитория."
        if result.ok:
            return "Проверки зелёные: тест проходит на текущем коде, значит баг он не воспроизводит."
        if short_test_name(repro.test_name) not in result.output:
            return (
                f"Проверки упали, но в выводе нет теста `{repro.test_name}`: похоже, сломалась сборка "
                f"или другой тест. Тест должен компилироваться и падать сам.\n\n<check_output>\n$ "
                f"{result.command}\n{result.output}\n</check_output>"
            )
        return ""


class RootCause:
    """Причина бага и план исправления в tasks.md для Ralph loop."""

    name = "bug_root_cause"

    def run(self, ctx: TaskContext, env: Env) -> Outcome:
        prompt = render(
            "bug_fix/root_cause.md.j2",
            ctx=ctx,
            report_file=f"{PLAN_DIR}/{REPORT}",
            root_cause_file=f"{PLAN_DIR}/{ROOT_CAUSE}",
            tasks_file=f"{PLAN_DIR}/{TASKS}",
        )
        call_agent(self.name, ctx, env, prompt, role=Role.PLANNER)
        tasks = bug_tasks_file(ctx)
        if not tasks.exists() or not pending_steps(tasks.read_text(encoding="utf-8")):
            raise RuntimeError(f"Агент не составил план в {PLAN_DIR}/{TASKS}")
        # План мог потрогать рабочие файлы: в этом узле код не меняем
        if Git(ctx.repo_path).has_changes():
            log.warning("Анализ причины изменил файлы репозитория, откатываю")
            Git(ctx.repo_path).discard_changes()
        return Outcome.OK


class VerifyRegressionTest:
    """После исправления тест из воспроизведения должен остаться на месте: зелёные проверки без него не в счёт."""

    name = "verify_regression_test"

    def run(self, ctx: TaskContext, env: Env) -> Outcome:
        if not ctx.bug.reproduced:
            log.info("Тест-воспроизведение не писался, проверять нечего")
            return Outcome.OK
        test_file = ctx.repo_path / ctx.bug.test_file
        if test_file.exists() and short_test_name(ctx.bug.test_name) in test_file.read_text(encoding="utf-8"):
            return Outcome.OK
        ctx.bug.note = f"тест {ctx.bug.test_name} пропал из {ctx.bug.test_file} после исправления"
        log.warning(ctx.bug.note)
        return Outcome.STUCK


class AttachBugReport:
    name = "attach_bug_report"

    def run(self, ctx: TaskContext, env: Env) -> Outcome:
        for file_name in (REPORT, ROOT_CAUSE):
            path = plan_dir(ctx) / file_name
            if path.exists():
                env.jira.attach_file(ctx.issue_key, path, f"{ctx.issue_key}-{file_name}")
        return Outcome.OK
