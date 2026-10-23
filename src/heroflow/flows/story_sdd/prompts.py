"""Промпты флоу story_sdd. Тексты лежат в heroflow/prompts/story_sdd/*.md.j2."""

from __future__ import annotations

from heroflow.engine.state import TaskContext
from heroflow.prompts import render


def explore(ctx: TaskContext, explore_file: str) -> str:
    return render("story_sdd/explore.md.j2", ctx=ctx, explore_file=explore_file)


def propose(ctx: TaskContext, change_name: str) -> str:
    return render("story_sdd/propose.md.j2", ctx=ctx, change_name=change_name)


def fix_spec_comments(ctx: TaskContext, comments_md: str) -> str:
    return render("story_sdd/fix_spec_comments.md.j2", ctx=ctx, comments=comments_md)


def apply(ctx: TaskContext) -> str:
    return render("story_sdd/apply.md.j2", ctx=ctx)


def verify(ctx: TaskContext) -> str:
    return render("story_sdd/verify.md.j2", ctx=ctx)


def fix_code_comments(ctx: TaskContext, comments_md: str) -> str:
    return render("story_sdd/fix_code_comments.md.j2", ctx=ctx, comments=comments_md)
