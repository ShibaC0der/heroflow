from __future__ import annotations

from pathlib import Path

import pytest
from conftest import World, git, make_context

from heroflow.config import ContextRepoConfig
from heroflow.context import (
    ContextError,
    Directives,
    branch_from_link,
    parse_directives,
    resolve_branch,
    select_attachments,
    strip_directives,
)
from heroflow.engine import JiraAttachment
from heroflow.integrations.git import Git
from heroflow.nodes.context import GatherContext

DESCRIPTION = """Сделать лимиты.

{panel:title=heroflow|borderStyle=solid}
attachments: openapi.yaml, *.png
analytics: feature/PAY-1-limits
analytics_paths: docs/payments, docs/glossary.md
{panel}

Подробности в аналитике."""


def att(name: str, size: int = 10) -> JiraAttachment:
    return JiraAttachment(id=name, filename=name, url=f"https://jira/{name}", size=size)


class TestDirectives:
    def test_parse_panel(self) -> None:
        d = parse_directives(DESCRIPTION)
        assert d.list("attachments") == ["openapi.yaml", "*.png"]
        assert d.get("analytics") == "feature/PAY-1-limits"
        assert d.list("analytics_paths") == ["docs/payments", "docs/glossary.md"]

    def test_code_block_and_missing_block(self) -> None:
        assert parse_directives("{code:title=heroflow}\nanalytics: x\n{code}").get("analytics") == "x"
        assert parse_directives("просто текст").values == {}

    def test_strip_removes_only_block(self) -> None:
        stripped = strip_directives(DESCRIPTION)
        assert "heroflow" not in stripped
        assert stripped.startswith("Сделать лимиты.")
        assert stripped.endswith("Подробности в аналитике.")


class TestAttachments:
    def test_selects_by_name_and_glob(self) -> None:
        chosen = select_attachments(
            [att("openapi.yaml"), att("a.png"), att("b.png"), att("secret.xlsx")],
            ["openapi.yaml", "*.png"],
            ["yaml", "png"],
            max_bytes=100,
        )
        assert [a.filename for a in chosen] == ["openapi.yaml", "a.png", "b.png"]

    def test_unmatched_pattern_is_error(self) -> None:
        with pytest.raises(ContextError, match="нет вложения"):
            select_attachments([att("a.png")], ["openapi.yaml"], ["yaml"], max_bytes=100)

    def test_extension_and_size_limits(self) -> None:
        with pytest.raises(ContextError, match="расширение"):
            select_attachments([att("run.sh")], ["run.sh"], ["yaml"], max_bytes=100)
        with pytest.raises(ContextError, match="лимита"):
            select_attachments([att("big.yaml", size=1000)], ["big.yaml"], ["yaml"], max_bytes=100)


class TestBranch:
    repo = ContextRepoConfig(url="https://bb/scm/SA/analytics.git", default_branch="master")

    def resolve(self, directives: Directives, description: str = "", heads: list[str] | None = None) -> tuple[str, str]:
        r = resolve_branch("analytics", self.repo, directives, description, "PAY-1", lambda: heads or ["master"])
        return r.branch, r.source

    def test_directive_wins_and_must_exist(self) -> None:
        d = Directives({"analytics": "feature/x"})
        assert self.resolve(d, heads=["master", "feature/x"]) == ("feature/x", "directive")
        with pytest.raises(ContextError, match="не найдена"):
            self.resolve(d, heads=["master"])

    def test_link_in_description(self) -> None:
        link = "см. [аналитику|https://bb/projects/SA/repos/analytics/browse/docs?at=refs%2Fheads%2Ffeature%2FPAY-1]"
        assert branch_from_link(link, self.repo.url) == "feature/PAY-1"
        assert self.resolve(Directives(), link) == ("feature/PAY-1", "link")
        other = "https://bb/projects/SA/repos/other/browse?at=refs/heads/x"
        assert branch_from_link(other, self.repo.url) is None

    def test_branch_with_issue_key_then_default(self) -> None:
        assert self.resolve(Directives(), heads=["master", "feature/pay-1-limits"]) == (
            "feature/pay-1-limits",
            "issue_key",
        )
        assert self.resolve(Directives(), heads=["master"]) == ("master", "default")
        with pytest.raises(ContextError, match="несколько веток"):
            self.resolve(Directives(), heads=["PAY-1-a", "PAY-1-b"])


@pytest.fixture
def analytics(tmp_path: Path) -> Path:
    bare = tmp_path / "analytics.git"
    seed = tmp_path / "analytics-seed"
    git("init", "-q", "--bare", "-b", "master", str(bare), cwd=tmp_path)
    git("clone", "-q", str(bare), str(seed), cwd=tmp_path)
    for rel, text in {
        "docs/payments/limits.md": "лимит 100",
        "docs/glossary.md": "глоссарий",
        "docs/other/big.md": "не нужно",
    }.items():
        (seed / rel).parent.mkdir(parents=True, exist_ok=True)
        (seed / rel).write_text(text, encoding="utf-8")
    git("add", "-A", cwd=seed)
    git("commit", "-qm", "docs", cwd=seed)
    git("push", "-q", "origin", "master", cwd=seed)
    git("checkout", "-qb", "feature/PAY-1-limits", cwd=seed)
    (seed / "docs/payments/limits.md").write_text("лимит 200", encoding="utf-8")
    git("commit", "-qam", "limits", cwd=seed)
    git("push", "-q", "origin", "feature/PAY-1-limits", cwd=seed)
    return bare


def test_gather_context(origin: Path, analytics: Path, tmp_path: Path, world: World) -> None:
    ctx = make_context(tmp_path / "task")
    ctx.jira.description_raw = DESCRIPTION
    ctx.jira.attachments = [att("openapi.yaml"), att("schema.png"), att("notes.txt")]
    Git(ctx.repo_path).clone(str(origin))
    world.env.config.context.repos = {"analytics": ContextRepoConfig(url=str(analytics))}

    assert GatherContext().run(ctx, world.env).value == "ok"

    assert ctx.attachments == [
        ".heroflow-context/attachments/openapi.yaml",
        ".heroflow-context/attachments/schema.png",
    ]
    repo = ctx.context_repos["analytics"]
    assert (repo.branch, repo.source) == ("feature/PAY-1-limits", "directive")
    root = ctx.repo_path / repo.path
    assert (root / "docs/payments/limits.md").read_text(encoding="utf-8") == "лимит 200"
    assert (root / "docs/glossary.md").exists()
    assert not (root / "docs/other/big.md").exists()
    assert not Git(ctx.repo_path).has_changes(), "контекст не должен попадать в коммиты"


def test_gather_context_without_block_downloads_nothing(origin: Path, tmp_path: Path, world: World) -> None:
    ctx = make_context(tmp_path / "task")
    ctx.jira.attachments = [att("openapi.yaml")]
    Git(ctx.repo_path).clone(str(origin))

    GatherContext().run(ctx, world.env)

    assert ctx.attachments == []
    assert ctx.context_repos == {}
