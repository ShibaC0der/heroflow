from heroflow.engine import Flow
from heroflow.flows import story_sdd

FLOWS: dict[str, Flow] = {
    story_sdd.FLOW.name: story_sdd.FLOW,
}

# Старое имя из heroflow 0.1, чтобы `--flow sdd_openspec` продолжал работать
ALIASES = {"sdd_openspec": story_sdd.FLOW.name}


def get_flow(name: str) -> Flow:
    return FLOWS[ALIASES.get(name, name)]


def flow_for_issue_type(issue_type: str) -> Flow:
    """Роутер по типу задачи. Пока флоу один; флоу для багов добавит ветку `Bug`."""
    return story_sdd.FLOW
