import logging
from pathlib import Path
from textwrap import dedent

import gigacode
import git

log = logging.getLogger(__name__)


def review_proposal(data: dict):
    repo_path = Path(data["sandbox_path"]) / "repo"
    max_iters = 3

    for i in range(max_iters):
        log.info(f"Ревью спеки. Итерация -> {i + 1}")

        prompt = dedent(f"""
        Проверь спецификацию в `{data["delta_spec_dir"]}` на соответствие задаче и предварительному исследованию {data["explore_file"]}

        # Описание задачи:
        ```
        {data['jira_task']['description']}
        ```

        # Что от тебя ТРЕБУЕТСЯ:
        - Спецификация ОБЯЗАНА соответствовать описанию задачи.
        - Если найдешь проблемы: нечёткие формулировки, пропущенные сценарии, дублирование сценариев по смыслу, противоречия - исправь их прямо в соответствующем файле.
        - Если всё корректно - не трогай файлы
        - Домен для спеки ОБЯЗАТЕЛЬНО ДОЛЖЕН соответствовать названию сервиса
        - Git-коммит (commit) НЕ ДЕЛАЙ

        """).strip()

        gigacode.run(prompt, repo_path)

        if not git.has_changes(repo_path):
            log.info("Ревью ресерча пройдено")
            git.push(repo_path, data["branch_name"])
            return

        git.commit_all(repo_path, f"research. self-review iteration {i + 1}. {data['issue_key']} [skip ci]")
