from heroflow.engine import END, Flow, Outcome, linear
from heroflow.flows.bug_fix import prompts
from heroflow.flows.bug_fix.nodes import (
    AttachBugReport,
    Reproduce,
    RootCause,
    Triage,
    VerifyRegressionTest,
    bug_tasks_file,
)
from heroflow.nodes.context import GatherContext
from heroflow.nodes.human import HumanDecision
from heroflow.nodes.ralph import RalphImplement
from heroflow.nodes.repo import CreatePullRequest, HumanReview, InitSandbox
from heroflow.nodes.review import CodeReviewFix

HUMAN_REVIEW_CODE = "human_review_impl"

FLOW = Flow(
    name="bug_fix",
    start="init_sandbox",
    nodes=(
        InitSandbox(),
        GatherContext(),
        Triage(),
        HumanDecision(
            "bug_triage_gate",
            "В задаче не хватает данных, чтобы понять правильное поведение (подробности в heroflow status). "
            "Продолжить как есть? (Нет — пауза: дополните задачу и запустите heroflow resume)",
        ),
        Reproduce(attempts=3),
        HumanDecision(
            "bug_reproduce_gate",
            "Не получилось падающего теста (причина в heroflow status). Продолжить без воспроизведения? "
            "(Можно сначала добавить тест в ветку сами. Нет — пауза до heroflow resume)",
        ),
        RootCause(),
        RalphImplement(
            max_iterations=15,
            max_failures_in_row=3,
            tasks_file=bug_tasks_file,
            template="bug_fix/ralph.md.j2",
        ),
        HumanDecision(
            "ralph_gate",
            "Исправление застряло, причина в heroflow status. Продолжить цикл? "
            "(Можно сначала поправить код в ветке. Нет — пауза до heroflow resume)",
        ),
        VerifyRegressionTest(),
        HumanDecision(
            "regression_test_gate",
            "Тест-воспроизведение пропал после исправления. Всё равно продолжить? (Нет — пауза до heroflow resume)",
        ),
        CodeReviewFix(
            max_rounds=3,
            review_template="bug_fix/code_review.md.j2",
            fix_template="bug_fix/code_fix.md.j2",
        ),
        HumanDecision(
            "code_review_gate",
            "Ревью кода не сошлось за 3 раунда, находки в heroflow status. Отдать код на ревью человеку?",
        ),
        CreatePullRequest(),
        HumanReview(
            HUMAN_REVIEW_CODE,
            "Есть ли замечания на Code Review?",
            prompts.fix_code_comments,
            "fix review issues. {key}",
            run_checks=True,
        ),
        AttachBugReport(),
    ),
    edges={
        **linear("init_sandbox", "gather_context", "bug_triage"),
        ("bug_triage", Outcome.OK): "bug_reproduce",
        ("bug_triage", Outcome.NEED_HUMAN): "bug_triage_gate",
        ("bug_triage_gate", Outcome.OK): "bug_reproduce",
        ("bug_reproduce", Outcome.OK): "bug_root_cause",
        ("bug_reproduce", Outcome.STUCK): "bug_reproduce_gate",
        ("bug_reproduce_gate", Outcome.OK): "bug_root_cause",
        ("bug_root_cause", Outcome.OK): "ralph",
        ("ralph", Outcome.OK): "verify_regression_test",
        ("ralph", Outcome.STUCK): "ralph_gate",
        ("ralph_gate", Outcome.OK): "ralph",
        ("verify_regression_test", Outcome.OK): "code_review",
        ("verify_regression_test", Outcome.STUCK): "regression_test_gate",
        ("regression_test_gate", Outcome.OK): "code_review",
        ("code_review", Outcome.APPROVE): "create_pull_request",
        ("code_review", Outcome.STUCK): "code_review_gate",
        ("code_review_gate", Outcome.OK): "create_pull_request",
        ("create_pull_request", Outcome.OK): HUMAN_REVIEW_CODE,
        (HUMAN_REVIEW_CODE, Outcome.ITERATE): HUMAN_REVIEW_CODE,
        (HUMAN_REVIEW_CODE, Outcome.APPROVE): "attach_bug_report",
        ("attach_bug_report", Outcome.OK): END,
    },
    max_visits={
        HUMAN_REVIEW_CODE: 50,
        "ralph": 10,
        "ralph_gate": 10,
        "bug_triage_gate": 10,
        "bug_reproduce_gate": 10,
        "regression_test_gate": 10,
        "code_review_gate": 10,
        # После ralph_gate цикл может вернуться к проверке теста
        "verify_regression_test": 10,
    },
    default_max_visits=1,
)

__all__ = ["FLOW"]
