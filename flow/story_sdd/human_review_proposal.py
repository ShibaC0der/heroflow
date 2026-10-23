import logging
from pathlib import Path

import bitbucket
import ask
import gigacode
import git

log = logging.getLogger(__name__)


def human_review_proposal(data: dict):
    repo_path = Path(data["sandbox_path"]) / "repo"
    branch_name = data['branch_name']

    while ask.bool_choice("Есть замечания по спецификации?"):

        pr_comments_report = bitbucket.get_pr_comments_md(
            pull_request_id=data.get("pull_request", {}).get("id")
        )

        if len(pr_comments_report) == 0:
            print("В PR нет новых комментариев")
            break

        log.info(f"Исправляю замечания: \n{pr_comments_report}")

        prompt = f"""
        Твоя единственная цель — исправить указанные замечания в файлах спецификации в режиме ПОЛНОЙ АВТОНОМНОСТИ.

        # Замечания на Code Review
        {pr_comments_report}

        # Предварительно исследование
        Файл с предварительным исследованием `{data["explore_file"]}`

        # Правила выполнения
        1. ИСПРАВЛЕНИЕ ЗАМЕЧАНИЙ: Локализуй места ошибок в файлах папки `{data["delta_spec_dir"]}` и исправь только то, что указано в комментариях.
        2. СТИЛЬ И СТРУКТУРА OpenSpec: Исправленные документы должны идеально соответствовать канонической структуре OpenSpec, быть логичными, технически точными и не содержать "TBD" заглушек.
        3. СИНХРОНИЗАЦИЯ СМЕЖНЫХ ДОКУМЕНТОВ: Если исправление замечания в одном документе (например, в `spec.md`) меняет логику или архитектуру, ты ОБЯЗАН одновременно внести соответствующие правки в остальные локальные файлы спецификации задачи (`design.md`, `tasks.md`, `spec.md`). Все документы спеки должны остаться синхронными.
        4. ЕСЛИ НЕЧЕГО ПРАВИТЬ: Если замечания не требуют изменений в документации или уже исправлены — ничего не меняй.
        5. БЕЗ КОДИНГА И ВОПРОСОВ: Действуй абсолютно автономно, не задавай уточняющих вопросов в чат. Код (production-код приложения) на этом этапе НЕ ПИШИ.
        6. БЕЗ КОММИТОВ: Git-коммит (commit) НЕ ДЕЛАЙ.

        # Валидация
        После внесения изменений обязательно убедись, что:
        - В спецификациях нет синтаксических ошибок Markdown.
        - Пошаговый чек-лист в `tasks.md` полностью соответствует обновленному дизайну и требованиям.
        """

        gigacode.run(prompt, repo_path)

        if git.has_changes(repo_path):
            git.commit_all(repo_path, f"fix spec review issues. {data['issue_key']}. [skip ci]")
            git.push(repo_path, branch_name)
