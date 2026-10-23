"""GatherContext: вложения из Jira и репозитории контекста по блоку heroflow в задаче."""

from __future__ import annotations

import logging
from functools import partial
from pathlib import Path

from heroflow.context import ContextError, parse_directives, resolve_branch, select_attachments
from heroflow.engine import ContextRepo, Env, Outcome, TaskContext
from heroflow.engine.state import CONTEXT_DIR_NAME
from heroflow.integrations.git import Git

log = logging.getLogger(__name__)

CONVERTIBLE = {"pdf", "docx"}


def convert_to_markdown(path: Path) -> Path | None:
    """pdf/docx -> .md рядом, если установлен markitdown (`uv sync --extra docs`)."""
    try:
        from markitdown import MarkItDown
    except ImportError:
        log.warning("markitdown не установлен, %s останется как есть (uv sync --extra docs)", path.name)
        return None
    target = path.with_suffix(path.suffix + ".md")
    target.write_text(MarkItDown().convert(str(path)).text_content, encoding="utf-8")
    return target


class GatherContext:
    name = "gather_context"

    def run(self, ctx: TaskContext, env: Env) -> Outcome:
        cfg = env.config.context
        directives = parse_directives(ctx.jira.description_raw)
        Git(ctx.repo_path).exclude(f"/{CONTEXT_DIR_NAME}/")

        known = {"attachments"} | set(cfg.repos) | {f"{name}_paths" for name in cfg.repos}
        for key in sorted(set(directives.values) - known):
            log.warning("Неизвестный ключ «%s» в блоке heroflow, игнорирую", key)

        ctx.attachments = self._attachments(ctx, env, directives.list("attachments"))
        ctx.context_repos = {}
        for name, repo in cfg.repos.items():
            resolved = resolve_branch(
                name,
                repo,
                directives,
                ctx.jira.description_raw,
                ctx.issue_key,
                remote_heads=partial(Git.remote_heads, repo.url),
            )
            paths = directives.list(f"{name}_paths") or repo.paths
            dest = ctx.context_dir / name
            log.info("Контекст %s: ветка %s (%s)", name, resolved.branch, resolved.source)
            sha = Git(dest).shallow_clone(repo.url, resolved.branch, paths)
            ctx.context_repos[name] = ContextRepo(
                path=dest.relative_to(ctx.repo_path).as_posix(),
                branch=resolved.branch,
                sha=sha,
                source=resolved.source,
            )
        return Outcome.OK

    def _attachments(self, ctx: TaskContext, env: Env, patterns: list[str]) -> list[str]:
        if not patterns:
            return []
        cfg = env.config.context
        chosen = select_attachments(
            ctx.jira.attachments, patterns, cfg.attachment_extensions, int(cfg.attachment_max_mb * 1024 * 1024)
        )
        result: list[str] = []
        for attachment in chosen:
            dest = ctx.context_dir / "attachments" / attachment.filename
            if dest.resolve().parent != (ctx.context_dir / "attachments").resolve():
                raise ContextError(f"Подозрительное имя вложения: {attachment.filename}")
            env.jira.download_attachment(attachment, dest)
            result.append(dest.relative_to(ctx.repo_path).as_posix())
            if dest.suffix.lstrip(".").lower() in CONVERTIBLE:
                converted = convert_to_markdown(dest)
                if converted:
                    result.append(converted.relative_to(ctx.repo_path).as_posix())
        return result
