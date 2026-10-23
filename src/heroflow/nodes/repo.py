"""Узлы, общие для флоу, которые работают с репозиторием задачи: песочница, PR, ревью человеком в PR."""

from __future__ import annotations

import logging
from collections.abc import Callable

from heroflow.engine import Env, Outcome, TaskContext
from heroflow.integrations.checks import run_checks
from heroflow.integrations.git import Git
from heroflow.nodes.agent import Role, call_agent
from heroflow.skills import install_skills

log = logging.getLogger(__name__)


class InitSandbox:
    name = "init_sandbox"

    def run(self, ctx: TaskContext, env: Env) -> Outcome:
        git = Git(ctx.repo_path)
        git.clone(env.config.bitbucket.repo_clone_url)
        git.fetch()
        git.checkout_work_branch(ctx.branch_name, ctx.base_branch)
        installed = install_skills(ctx.repo_path, env.config.skills)
        if installed:
            log.info("Скиллы в песочнице: %s", ", ".join(installed))
        return Outcome.OK


class CreatePullRequest:
    name = "create_pull_request"

    def run(self, ctx: TaskContext, env: Env) -> Outcome:
        Git(ctx.repo_path).push(ctx.branch_name)
        if ctx.pull_request:
            log.info("PR уже создан -> %s", ctx.pull_request.url)
            return Outcome.OK
        ctx.pull_request = env.bitbucket.create_pull_request(
            title=ctx.jira.summary, from_branch=ctx.branch_name, to_branch=ctx.base_branch
        )
        log.info("PR -> %s", ctx.pull_request.url)
        return Outcome.OK


class HumanReview:
    """Ревью человеком через /hf-комментарии в PR.

    Человек говорит «есть замечания» -> берём новые /hf-комментарии -> агент правит -> push -> ITERATE (снова сюда).
    «Замечаний нет» -> APPROVE. Обработанные комментарии запоминаются и второй раз не уходят агенту.
    """

    def __init__(
        self,
        name: str,
        question: str,
        prompt: Callable[[TaskContext, str], str],
        commit_message: str,
        run_checks: bool = False,
    ) -> None:
        self.name = name
        self.question = question
        self.prompt = prompt
        self.commit_message = commit_message
        # Для правок кода: heroflow сам проверяет сборку и тесты после фиксера
        self.run_checks = run_checks

    def run(self, ctx: TaskContext, env: Env) -> Outcome:
        if not env.human.confirm(self.question):
            return Outcome.APPROVE
        if not ctx.pull_request:
            raise RuntimeError("PR ещё не создан, комментарии брать неоткуда")

        comments = [
            c for c in env.bitbucket.heroflow_comments(ctx.pull_request.id) if c.id not in ctx.processed_comment_ids
        ]
        if not comments:
            log.info("В PR нет новых /hf-комментариев")
            return Outcome.ITERATE

        comments_md = "\n".join(c.as_markdown() for c in comments)
        log.info("Исправляю замечания:\n%s", comments_md)
        call_agent(self.name, ctx, env, self.prompt(ctx, comments_md), role=Role.FIXER)

        git = Git(ctx.repo_path)
        if self.run_checks and not self._checks_green(ctx, env, comments_md):
            log.warning("Правки по замечаниям ломают проверки, откатываю. Замечания возьмём в следующий раз")
            git.discard_changes()
            return Outcome.ITERATE
        if git.commit_all(self.commit_message.format(key=ctx.issue_key)):
            git.push(ctx.branch_name)
        ctx.processed_comment_ids.extend(c.id for c in comments)
        return Outcome.ITERATE

    def _checks_green(self, ctx: TaskContext, env: Env, comments_md: str) -> bool:
        result = run_checks(ctx.repo_path, env.config.checks)
        if result.ok:
            return True
        failure = f"$ {result.command}\n{result.output}"
        retry = (
            f"{self.prompt(ctx, comments_md)}\n\n# Проверки упали\n"
            "После твоих правок проверки heroflow красные. Почини причину:\n\n"
            f"<check_output>\n{failure}\n</check_output>"
        )
        call_agent(self.name, ctx, env, retry, role=Role.FIXER)
        return run_checks(ctx.repo_path, env.config.checks).ok
