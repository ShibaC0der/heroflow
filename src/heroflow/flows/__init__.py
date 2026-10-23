from heroflow.engine import Flow
from heroflow.flows import bug_fix, story_sdd

FLOWS: dict[str, Flow] = {
    story_sdd.FLOW.name: story_sdd.FLOW,
    bug_fix.FLOW.name: bug_fix.FLOW,
}

# Старое имя из heroflow 0.1, чтобы `--flow sdd_openspec` продолжал работать
ALIASES = {"sdd_openspec": story_sdd.FLOW.name}

# Типы задач Jira, которые идут во флоу bug_fix. Сравнение без учёта регистра
BUG_ISSUE_TYPES = frozenset({"bug", "defect", "баг", "ошибка", "дефект"})

BRANCH_PREFIX = {bug_fix.FLOW.name: "bugfix"}


def get_flow(name: str) -> Flow:
    return FLOWS[ALIASES.get(name, name)]


def flow_for_issue_type(issue_type: str) -> Flow:
    """Роутер по типу задачи: баги -> bug_fix, всё остальное -> story_sdd."""
    if issue_type.strip().lower() in BUG_ISSUE_TYPES:
        return bug_fix.FLOW
    return story_sdd.FLOW


def branch_name(flow: Flow, issue_key: str) -> str:
    return f"{BRANCH_PREFIX.get(flow.name, 'feature')}/{issue_key}"
