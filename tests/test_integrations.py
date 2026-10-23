from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from conftest import git

from heroflow.integrations.bitbucket import parse_comments
from heroflow.integrations.git import Git, GitError
from heroflow.integrations.jira import parse_issue


def comment(cid: int, text: str, author: str = "alex", **extra: Any) -> dict[str, Any]:
    return {"id": cid, "text": text, "author": {"name": author}, **extra}


def activity(c: dict[str, Any], anchor: dict[str, Any] | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {"action": "COMMENTED", "commentAction": "ADDED", "comment": c}
    if anchor:
        item["commentAnchor"] = anchor
    return item


class TestBitbucketComments:
    def test_takes_only_hf_commands_and_strips_prefix(self) -> None:
        result = parse_comments(
            [
                activity(comment(1, "/hf переименуй метод"), {"path": "src/A.kt", "line": 10}),
                activity(comment(2, "просто комментарий")),
                activity(comment(3, "см. /hfoo/bar")),
                activity(comment(4, "/heroflow: добавь тест на путь /hf/x")),
            ],
            allowed_authors=[],
        )
        assert [(c.id, c.text, c.file, c.line) for c in result] == [
            (1, "переименуй метод", "src/A.kt", 10),
            (4, "добавь тест на путь /hf/x", None, None),
        ]

    def test_reads_replies_and_skips_resolved_and_orphaned(self) -> None:
        reply = comment(11, "/hf и здесь тоже")
        result = parse_comments(
            [
                activity(comment(10, "обсуждение", comments=[reply]), {"path": "B.kt", "line": 5}),
                activity(comment(20, "/hf уже решено", threadResolved=True)),
                activity(comment(30, "/hf к удалённой строке"), {"path": "C.kt", "orphaned": True}),
            ],
            allowed_authors=[],
        )
        assert [(c.id, c.file, c.line) for c in result] == [(11, "B.kt", 5)]

    def test_author_allowlist(self) -> None:
        result = parse_comments(
            [activity(comment(1, "/hf a", author="alex")), activity(comment(2, "/hf b", author="stranger"))],
            allowed_authors=["alex"],
        )
        assert [c.id for c in result] == [1]


def test_jira_issue_without_description_and_sprint() -> None:
    task = parse_issue(
        "PAY-1",
        {"fields": {"summary": "S", "issuetype": {"name": "Bug"}, "description": None, "sprint": None}},
        epic_field="customfield_11400",
    )
    assert task.description == ""
    assert task.sprint is None
    assert task.issue_type == "Bug"


class TestGit:
    def test_commit_all_without_changes_returns_false(self, origin: Path, tmp_path: Path) -> None:
        repo = Git(tmp_path / "repo")
        repo.clone(str(origin))
        assert repo.commit_all("nothing") is False
        (repo.repo_path / "x.txt").write_text("x", encoding="utf-8")
        assert repo.commit_all("x") is True

    def test_push_failure_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "lonely"
        path.mkdir()
        git("init", "-q", cwd=path)
        with pytest.raises(GitError):
            Git(path).push("master")

    def test_work_branch_is_created_once_and_reused(self, origin: Path, tmp_path: Path) -> None:
        repo = Git(tmp_path / "repo")
        repo.clone(str(origin))
        repo.fetch()
        repo.checkout_work_branch("feature/PAY-1", "master")
        assert repo.current_branch() == "feature/PAY-1"
        git("checkout", "-q", "master", cwd=repo.repo_path)
        repo.checkout_work_branch("feature/PAY-1", "master")
        assert repo.current_branch() == "feature/PAY-1"

    def test_missing_base_branch_raises(self, origin: Path, tmp_path: Path) -> None:
        repo = Git(tmp_path / "repo")
        repo.clone(str(origin))
        with pytest.raises(GitError):
            repo.checkout_work_branch("feature/PAY-1", "no-such-branch")
