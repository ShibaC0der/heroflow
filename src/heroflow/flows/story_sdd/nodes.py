"""Узлы флоу story_sdd: тот же процесс, что был, на новом контракте."""

from __future__ import annotations

import logging
from pathlib import Path

from heroflow.engine import Env, Outcome, TaskContext
from heroflow.flows.story_sdd import prompts
from heroflow.integrations.git import Git
from heroflow.nodes.agent import Role, call_agent

log = logging.getLogger(__name__)

CHANGES_DIR = Path("openspec") / "changes"


def change_name(ctx: TaskContext) -> str:
    return ctx.issue_key.lower()


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
