from pathlib import Path
from textwrap import dedent

import gigacode
import git


def opsx_verify(data):
    repo_path = Path(data["sandbox_path"]) / "repo"

    prompt = dedent(f"""
        Проверь реализацию по спецификации `{data["delta_spec_dir"]}` с помощью /opsx:verify

        # Если в ходе проверки найдены проблемы:
        1. Проанализируй каждую проблему.
        2. Определи причину: ошибка в коде, тестах, спецификации, дизайне или незавершённая задача.
        3. Исправь проблему в соответствующем месте.

        # Важно:
        - Не изменяй спецификацию только для того, чтобы устранить замечание проверки.
        - Если ошибка в реализации - исправляй код.
        - Если ошибка действительно в спецификации - исправляй спецификацию.
        - Не ограничивайся исправлением текста или результата проверки - устраняй фактическую причину проблемы.
        - Если проблем нет, ничего не изменяй.

        Git-коммит НЕ делай
        """).strip()

    gigacode.run(prompt, repo_path)

    if git.has_changes(repo_path):
        git.commit_all(repo_path, f"audit spec and code done. {data['issue_key']}")
        git.push(repo_path, data['branch_name'])
