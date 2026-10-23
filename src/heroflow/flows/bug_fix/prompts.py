"""Промпты флоу bug_fix, которые узлы вызывают как функции. Тексты лежат в heroflow/prompts/bug_fix/*.md.j2."""

from __future__ import annotations

from heroflow.engine.state import TaskContext
from heroflow.prompts import render


def fix_code_comments(ctx: TaskContext, comments_md: str) -> str:
    return render("bug_fix/fix_code_comments.md.j2", ctx=ctx, comments=comments_md)
