from __future__ import annotations

from pathlib import Path

import pytest
from conftest import make_context

from heroflow.engine import ContextRepo, Finding, RalplanRound, Review, Severity, TaskContext, Verdict
from heroflow.prompts import render, templates


def full_context(tmp_path: Path) -> TaskContext:
    ctx = make_context(tmp_path)
    ctx.explore_file = "openspec/changes/explore-PAY-1.md"
    ctx.delta_spec_dir = "openspec/changes/pay-1"
    ctx.jira.description = "Строка 1\nСтрока 2 без отступа"
    ctx.jira.sprint = "Sprint 42"
    return ctx


@pytest.mark.parametrize("template", templates())
def test_every_template_renders(template: str, tmp_path: Path) -> None:
    finding = Finding(severity=Severity.MAJOR, title="нет сценария", file="spec.md", line=3)
    review = Review(verdict=Verdict.ITERATE, summary="s", findings=[finding])
    text = render(
        template,
        ctx=full_context(tmp_path),
        explore_file="e.md",
        change_name="pay-1",
        comments="- поправь",
        previous=[finding],
        findings=[finding],
        round=RalplanRound(architect=review, critic=review),
        diff_file=".heroflow-context/review/diff.patch",
    )
    assert text
    assert "{{" not in text
    assert "\n\n\n" not in text


def test_multiline_description_does_not_break_indent(tmp_path: Path) -> None:
    text = render("review/spec_critic.md.j2", ctx=full_context(tmp_path), previous=[])
    assert "\n# Что проверить" in text
    assert "\nСтрока 2 без отступа" in text


def test_context_section_only_when_present(tmp_path: Path) -> None:
    ctx = full_context(tmp_path)
    assert "Дополнительный контекст" not in render("review/spec_critic.md.j2", ctx=ctx, previous=[])
    ctx.attachments = [".heroflow-context/attachments/openapi.yaml"]
    ctx.context_repos = {
        "analytics": ContextRepo(path=".heroflow-context/analytics", branch="feature/x", sha="a" * 40, source="link")
    }
    text = render("review/spec_critic.md.j2", ctx=ctx, previous=[])
    assert "`.heroflow-context/attachments/openapi.yaml`" in text
    assert "Репозиторий `analytics` (ветка `feature/x`" in text
