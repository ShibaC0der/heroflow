# TODO: строки 1-6 не попали на фото — импорты восстановлены по коду
import logging
from pathlib import Path
from textwrap import dedent

import ask
import bitbucket
import gigacode
import git

log = logging.getLogger(__name__)


def human_review_impl(data):
    repo_path = Path(data["sandbox_path"]) / "repo"
    branch_name = data['branch_name']

    while ask.bool_choice("Есть ли замечания на Code Review ?"):

        pr_comments_report = bitbucket.get_pr_comments_md(
            pull_request_id=data.get("pull_request", {}).get("id")
        )

        print(f"Исправляю замечания: \n{pr_comments_report}")

        if len(pr_comments_report) == 0:
            log.info("В Pull Request нет новых комментариев")
            continue

        prompt = dedent(f"""
        Исправь замечания из Pull Request в режиме ПОЛНОЙ АВТОНОМНОСТИ.
        Твоя единственная цель - исправить указанные замечания.

        # Замечания на Review
        {pr_comments_report}

        # Спецификация
        Спецификация по задаче находится в папке `{data['delta_spec_dir']}`

        # Строгие правила выполнения (MUST)
        1. ИСПРАВЛЕНИЕ ЗАМЕЧАНИЙ: Локализуй места ошибок и исправь только то, что указано в комментариях к PR.
        3. СТИЛЬ И РЕФЕРЕНСЫ: Перед правкой кода изучи смежные файлы и текущую кодовую базу. Исправленный код должен идеально мимикрировать под существующий стиль проекта (именование, обработка ошибок, структура).
        4. СИНХРОНИЗАЦИЯ СПЕЦИФИКАЦИИ (OpenSpec): Если исправление замечания меняет логику, архитектуру или структуру данных, ты ОБЯЗАН одновременно внести соответствующие правки в локальные файлы спецификации задачи в (`spec.md`,`design.md`, `tasks.md`). Код и спека должны остаться синхронными.
        5. ЕСЛИ НЕЧЕГО ПРАВИТЬ: Если замечания не требуют изменений в коде или уже исправлены - ничего не меняй.
        6. БЕЗ ВОПРОСОВ: Действуй абсолютно автономно, не задавай уточняющих вопросов в чат.
        7. БЕЗ КОММИТОВ: Git-коммит (commit) НЕ ДЕЛАЙ.

        # Валидация
        После внесения изменений обязательно запусти цепочку проверок локально:
        - Проверь, что код успешно компилируется.
        - Выполни статический анализ (`detekt`).
        - Запусти unit-тесты и убедись, что они проходят.
        Если detekt выдает ошибки или тесты падают - автономно переписывай и исправляй свой код до тех пор, пока проверка не станет полностью "зеленой".
        """).strip()

        log.info(f"Замечания: {pr_comments_report}")

        gigacode.run(prompt, repo_path)

        if git.has_changes(repo_path):
            git.commit_all(repo_path, f"fix review issues. {data['issue_key']}")
            git.push(repo_path, branch_name)
