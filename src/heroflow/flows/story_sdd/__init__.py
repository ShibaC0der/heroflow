from heroflow.engine import END, Flow, Outcome, linear
from heroflow.flows.story_sdd import prompts
from heroflow.flows.story_sdd.nodes import (
    AddSddLabel,
    Apply,
    AttachSpecToJira,
    CleanupSpecChanges,
    CreatePullRequest,
    Explore,
    HumanReview,
    InitSandbox,
    Propose,
    ResolveDeltaSpecDir,
    SelfReviewSpec,
    Verify,
)
from heroflow.nodes.context import GatherContext

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
        AddSddLabel(),
        SelfReviewSpec(),
        CreatePullRequest(),
        HumanReview(
            HUMAN_REVIEW_SPEC,
            "Есть замечания по спецификации?",
            prompts.fix_spec_comments,
            "fix spec review issues. {key}. [skip ci]",
        ),
        Apply(),
        Verify(),
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
        **linear(
            "init_sandbox",
            "gather_context",
            "explore",
            "opsx_propose",
            "resolve_delta_spec_dir",
            "add_sdd_label",
            "review_proposal",
            "create_pull_request",
            HUMAN_REVIEW_SPEC,
        ),
        (HUMAN_REVIEW_SPEC, Outcome.ITERATE): HUMAN_REVIEW_SPEC,
        (HUMAN_REVIEW_SPEC, Outcome.APPROVE): "opsx_apply",
        **linear("opsx_apply", "opsx_verify", HUMAN_REVIEW_CODE),
        (HUMAN_REVIEW_CODE, Outcome.ITERATE): HUMAN_REVIEW_CODE,
        (HUMAN_REVIEW_CODE, Outcome.APPROVE): "attach_spec_file_to_jira_task",
        **linear("attach_spec_file_to_jira_task", "remove_unnecessary_spec_changes", END),
    },
    max_visits={HUMAN_REVIEW_SPEC: 50, HUMAN_REVIEW_CODE: 50},
    default_max_visits=1,
)

__all__ = ["FLOW"]
