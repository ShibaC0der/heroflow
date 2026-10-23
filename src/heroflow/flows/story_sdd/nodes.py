"""Узлы флоу story_sdd: тот же процесс, что был, на новом контракте."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from heroflow.engine import Env, Outcome, TaskContext
from heroflow.flows.story_sdd import prompts
from heroflow.integrations.git import Git
from heroflow.nodes.agent import Role, call_agent

log = logging.getLogger(__name__)

CHANGES_DIR = Path("openspec") / "changes"


def change_name(ctx: TaskContext) -> str:
    return ctx.issue_key.lower()


class InitSandbox:
    name = "init_sandbox"

    def run(self, ctx: TaskContext, env: Env) -> Outcome:
        git = Git(ctx.repo_path)
        git.clone(env.config.bitbucket.repo_clone_url)
        git.fetch()
        git.checkout_work_branch(ctx.branch_name, ctx.base_branch)
        return Outcome.OK


class Explore:
    name = "explore"

    def run(self, ctx: TaskContext, env: Env) -> Outcome:
        explore_file = str(CHANGES_DIR / f"explore-{ctx.issue_key}.md")
        ctx.explore_file = explore_file
        call_agent(self.name, ctx, env, prompts.explore(ctx, explore_file))
        if not (ctx.repo_path / explore_file).exists():
            raise RuntimeError(f"Агент не создал файл {explore_file}")
        Git(ctx.repo_path).commit_all(f"explore done. {ctx.issue_key} [skip ci]")
        return Outcome.OK


class Propose:
    name = "opsx_propose"

    def run(self, ctx: TaskContext, env: Env) -> Outcome:
        call_agent(self.name, ctx, env, prompts.propose(ctx, change_name(ctx)), role=Role.PLANNER)
        Git(ctx.repo_path).commit_all(f"propose done. {ctx.issue_key} [skip ci]")
        return Outcome.OK


def find_delta_spec_dir(repo_path: Path, changed_files: list[str], expected: str) -> str | None:
    """Папка change: сначала та, что мы попросили создать, иначе первая папка
    в openspec/changes из последнего коммита. explore-файл и прочие файлы — не папки change."""
    expected_dir = CHANGES_DIR / expected
    if (repo_path / expected_dir).is_dir():
        return expected_dir.as_posix()
    for file_path in changed_files:
        parts = Path(file_path).parts
        if len(parts) >= 4 and parts[:2] == CHANGES_DIR.parts and parts[2] != "archive":
            candidate = Path(*parts[:3])
            if (repo_path / candidate).is_dir():
                return candidate.as_posix()
    return None


class ResolveDeltaSpecDir:
    name = "resolve_delta_spec_dir"

    def run(self, ctx: TaskContext, env: Env) -> Outcome:
        files = Git(ctx.repo_path).files_in_commit("HEAD")
        found = find_delta_spec_dir(ctx.repo_path, files, change_name(ctx))
        if not found:
            raise RuntimeError("Не удалось определить папку delta-спецификации в openspec/changes")
        log.info("Папка спецификации -> %s", found)
        ctx.delta_spec_dir = found
        return Outcome.OK


class AddSddLabel:
    name = "add_sdd_label"

    def run(self, ctx: TaskContext, env: Env) -> Outcome:
        env.jira.add_label(ctx.issue_key, "SDD")
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
    ) -> None:
        self.name = name
        self.question = question
        self.prompt = prompt
        self.commit_message = commit_message

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
        if git.commit_all(self.commit_message.format(key=ctx.issue_key)):
            git.push(ctx.branch_name)
        ctx.processed_comment_ids.extend(c.id for c in comments)
        return Outcome.ITERATE


def spec_files(ctx: TaskContext) -> list[Path]:
    if not ctx.delta_spec_dir:
        return []
    return sorted((ctx.repo_path / ctx.delta_spec_dir).rglob("spec.md"))


class AttachSpecToJira:
    name = "attach_spec_file_to_jira_task"

    def run(self, ctx: TaskContext, env: Env) -> Outcome:
        files = spec_files(ctx)
        if not files:
            log.info("spec.md не найден, прикладывать нечего")
            return Outcome.OK
        for spec in files:
            # specs/<capability>/spec.md -> <capability>-spec.md, чтобы файлы в Jira не затирали друг друга
            name = "spec.md" if len(files) == 1 else f"{spec.parent.name}-spec.md"
            env.jira.attach_file(ctx.issue_key, spec, name)
        return Outcome.OK


class CleanupSpecChanges:
    """Оставляет в PR только spec.md текущего change. Чужие changes в openspec/changes не трогает."""

    name = "remove_unnecessary_spec_changes"

    def run(self, ctx: TaskContext, env: Env) -> Outcome:
        if ctx.explore_file:
            (ctx.repo_path / ctx.explore_file).unlink(missing_ok=True)
        if ctx.delta_spec_dir:
            for file in (ctx.repo_path / ctx.delta_spec_dir).rglob("*"):
                if file.is_file() and file.name != "spec.md":
                    file.unlink()
        git = Git(ctx.repo_path)
        if git.commit_all(f"remove unnecessary spec files. {ctx.issue_key} [skip ci]"):
            git.push(ctx.branch_name)
        return Outcome.OK
