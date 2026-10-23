from heroflow.engine import END, Flow, Outcome, linear
from heroflow.flows.story_sdd import prompts
from heroflow.flows.story_sdd.nodes import (
    AddSddLabel,
    AttachSpecToJira,
    CleanupSpecChanges,
    CreatePullRequest,
    Explore,
    HumanReview,
    InitSandbox,
    Propose,
    ResolveDeltaSpecDir,
)
from heroflow.nodes.context import GatherContext
from heroflow.nodes.human import HumanDecision
from heroflow.nodes.ralph import RalphImplement
from heroflow.nodes.review import CodeReviewFix, Ralplan

HUMAN_REVIEW_SPEC = "human_review_proposal"
HUMAN_REVIEW_CODE = "human_review_impl"

FLOW = Flow(
    name="story_sdd",
    start="init_sandbox",
    nodes=(
        InitSandbox(),
        GatherContext(),
        Explore(),
        Propose(),
        ResolveDeltaSpecDir(),
        Ralplan(max_rounds=5),
        HumanDecision(
            "ralplan_gate",
            "Ревьюверы спеки не сошлись за 5 раундов. Продолжить с текущей спекой? "
            "(Нет — пауза: поправьте спеку в ветке и запустите heroflow resume)",
        ),
        AddSddLabel(),
        CreatePullRequest(),
        HumanReview(
            HUMAN_REVIEW_SPEC,
            "Есть замечания по спецификации?",
            prompts.fix_spec_comments,
            "fix spec review issues. {key}. [skip ci]",
        ),
        RalphImplement(max_iterations=30, max_failures_in_row=3),
        HumanDecision(
            "ralph_gate",
            "Реализация застряла, причина в heroflow status. Продолжить цикл? "
            "(Можно сначала поправить код в ветке. Нет — пауза до heroflow resume)",
        ),
        CodeReviewFix(max_rounds=3),
        HumanDecision(
            "code_review_gate",
            "Ревью кода не сошлось за 3 раунда, находки в heroflow status. Отдать код на ревью человеку?",
        ),
        HumanReview(
            HUMAN_REVIEW_CODE,
            "Есть ли замечания на Code Review?",
            prompts.fix_code_comments,
            "fix review issues. {key}",
        ),
        AttachSpecToJira(),
        CleanupSpecChanges(),
    ),
    edges={
        **linear("init_sandbox", "gather_context", "explore", "opsx_propose", "resolve_delta_spec_dir", "ralplan"),
        ("ralplan", Outcome.APPROVE): "add_sdd_label",
        ("ralplan", Outcome.STUCK): "ralplan_gate",
        ("ralplan_gate", Outcome.OK): "add_sdd_label",
        **linear("add_sdd_label", "create_pull_request", HUMAN_REVIEW_SPEC),
        (HUMAN_REVIEW_SPEC, Outcome.ITERATE): HUMAN_REVIEW_SPEC,
        (HUMAN_REVIEW_SPEC, Outcome.APPROVE): "ralph",
        ("ralph", Outcome.OK): "code_review",
        ("ralph", Outcome.STUCK): "ralph_gate",
        ("ralph_gate", Outcome.OK): "ralph",
        ("code_review", Outcome.APPROVE): HUMAN_REVIEW_CODE,
        ("code_review", Outcome.STUCK): "code_review_gate",
        ("code_review_gate", Outcome.OK): HUMAN_REVIEW_CODE,
        (HUMAN_REVIEW_CODE, Outcome.ITERATE): HUMAN_REVIEW_CODE,
        (HUMAN_REVIEW_CODE, Outcome.APPROVE): "attach_spec_file_to_jira_task",
        **linear("attach_spec_file_to_jira_task", "remove_unnecessary_spec_changes", END),
    },
    max_visits={
        HUMAN_REVIEW_SPEC: 50,
        HUMAN_REVIEW_CODE: 50,
        "ralph": 10,
        "ralph_gate": 10,
        "ralplan_gate": 10,
        "code_review_gate": 10,
    },
    default_max_visits=1,
)

__all__ = ["FLOW"]
