from __future__ import annotations

from pathlib import Path

from conftest import World, git, make_context

from heroflow.engine import TaskState, TaskStatus, TaskStore, run_flow
from heroflow.flows.story_sdd import FLOW
from heroflow.flows.story_sdd.nodes import find_delta_spec_dir
from heroflow.integrations.git import Git
from heroflow.ports import PrComment

CHANGE = Path("openspec/changes/pay-1")


def write(root: Path, rel: str | Path, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_find_delta_spec_dir_ignores_explore_file(tmp_path: Path) -> None:
    (tmp_path / "openspec/changes/limits/specs/payments").mkdir(parents=True)
    files = ["openspec/changes/explore-PAY-1.md", "openspec/changes/limits/specs/payments/spec.md"]
    assert find_delta_spec_dir(tmp_path, files, expected="pay-1") == "openspec/changes/limits"
    (tmp_path / "openspec/changes/pay-1").mkdir()
    assert find_delta_spec_dir(tmp_path, files, expected="pay-1") == "openspec/changes/pay-1"
    assert find_delta_spec_dir(tmp_path, ["openspec/changes/explore-PAY-1.md"], expected="x") is None


def test_full_story_flow(origin: Path, tmp_path: Path, world: World) -> None:
    store = TaskStore(tmp_path / "tasks")
    ctx = make_context(store.task_dir("PAY-1"))
    repo = Git(ctx.repo_path)
    repo.clone(str(origin))
    repo.fetch()
    repo.checkout_work_branch(ctx.branch_name, ctx.base_branch)

    def explore(prompt: str, cwd: Path) -> None:
        write(cwd, "openspec/changes/explore-PAY-1.md", "## Задача\n")

    def propose(prompt: str, cwd: Path) -> None:
        assert "openspec/changes/pay-1/" in prompt
        write(cwd, CHANGE / "proposal.md", "proposal")
        write(cwd, CHANGE / "tasks.md", "- [ ] 1")
        write(cwd, CHANGE / "specs/payments/spec.md", "## Requirements\n")

    def fix_spec(prompt: str, cwd: Path) -> None:
        assert "уточни лимит" in prompt
        write(cwd, CHANGE / "specs/payments/spec.md", "## Requirements\nлимит 100\n")

    def apply(prompt: str, cwd: Path) -> None:
        write(cwd, "src/Limits.py", "class Limits: ...\n")

    world.agent.scripts = {
        "explore": explore,
        "opsx_propose": propose,
        "human_review_proposal": fix_spec,
        "opsx_apply": apply,
    }
    world.bitbucket.comments = [PrComment(id=7, author="alex", text="уточни лимит", file=str(CHANGE / "spec.md"))]
    # spec: «есть замечания» -> правка; «есть замечания» -> новых нет; «нет»; code review: «нет»
    world.human.answers = [True, True, False, False]

    state = TaskState(context=ctx, current_node="explore")
    result = run_flow(FLOW, state, world.env, store)

    assert result.status is TaskStatus.DONE, result.error
    assert result.context.delta_spec_dir == CHANGE.as_posix()
    assert result.context.processed_comment_ids == [7]
    fix_calls = [n for n, _ in world.agent.calls if n == "human_review_proposal"]
    assert len(fix_calls) == 1, "уже обработанный комментарий не должен уходить агенту второй раз"
    assert world.jira.labels == ["SDD"]
    assert world.jira.attachments == [("spec.md", "## Requirements\nлимит 100\n")]
    assert world.bitbucket.created == [("feature/PAY-1", "master")]

    # В origin: от change остался только spec.md, explore-файла нет, чужой change цел
    files = git("ls-tree", "-r", "--name-only", "feature/PAY-1", cwd=origin).split()
    assert str(CHANGE / "specs/payments/spec.md") in files
    assert str(CHANGE / "proposal.md") not in files
    assert "openspec/changes/explore-PAY-1.md" not in files
    assert "openspec/changes/other-team-change/proposal.md" in files
    assert "src/Limits.py" in files


def test_spec_without_changes_on_verify_does_not_crash(origin: Path, tmp_path: Path, world: World) -> None:
    """Агент ничего не поменял на шагах verify и self-review: раньше commit_all падал."""
    store = TaskStore(tmp_path / "tasks")
    ctx = make_context(store.task_dir("PAY-1"))
    ctx.delta_spec_dir = CHANGE.as_posix()
    repo = Git(ctx.repo_path)
    repo.clone(str(origin))
    repo.fetch()
    repo.checkout_work_branch(ctx.branch_name, ctx.base_branch)

    state = TaskState(context=ctx, current_node="opsx_verify")
    world.human.answers = [False]
    result = run_flow(FLOW, state, world.env, store)

    assert result.status is TaskStatus.DONE, result.error
    assert world.jira.attachments == []
