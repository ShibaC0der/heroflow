# heroflow

Оркестратор агентских флоу: берёт задачу из Jira, готовит OpenSpec-спецификацию, реализует её агентом GigaCode
и ведёт PR в Bitbucket, принимая замечания через комментарии `/hf` в PR.

## Установка

```bash
uv sync
cp .env.example .env   # или ~/.heroflow/config.yaml с секциями bitbucket / jira / gigacode / http
```

## Команды

```bash
uv run heroflow run PAY-123 [--base develop] [--flow story_sdd]   # запустить или продолжить задачу
uv run heroflow resume PAY-123                                    # продолжить с узла, где остановились
uv run heroflow list                                              # все задачи: название, узел, статус, PR
uv run heroflow status PAY-123                                    # история узлов с исходами и временем
uv run heroflow clean --done [--failed] [PAY-1 PAY-2] [--yes]     # удалить папки задач
```

Данные задачи лежат в `~/.heroflow/tasks/<KEY>/`: `repo/` (клон), `state.json` (состояние),
`heroflow.log` и `logs/<узел>-<N>.jsonl` (полная траектория каждого вызова агента).

## Как устроено

```
src/heroflow/
  engine/        движок: Outcome, Node, Flow, run_flow, TaskContext/TaskState, TaskStore
  flows/         флоу; story_sdd — текущий SDD-процесс
  integrations/  git, Jira, Bitbucket, GigaCode, ввод в терминале
  ports.py       интерфейсы внешних систем (в тестах — фейки)
  cli.py         команды heroflow
```

**Узел** — класс с `name` и `run(ctx, env) -> Outcome`. **Флоу** — набор узлов и таблица рёбер
`(узел, исход) -> следующий узел`. Это позволяет ветвиться и делать циклы:

```python
edges = {
    **linear("explore", "opsx_propose", "review"),
    ("review", Outcome.ITERATE): "fix",
    ("fix", Outcome.OK): "review",
    ("review", Outcome.APPROVE): "ship",
    ("ship", Outcome.OK): END,
}
```

После каждого узла состояние сохраняется, поэтому после падения или Ctrl+C `heroflow resume` продолжает
с того же узла. У каждого узла есть лимит заходов (`max_visits`), чтобы цикл не крутился вечно: при
превышении задача получает статус `stuck`.

Исходы: `ok`, `approve`, `iterate`, `stuck`, `need_human`. Если для `need_human` нет ребра, движок
сохраняет задачу со статусом `waiting_human` и выходит.

## Python для котлиниста

| Kotlin | Здесь |
|---|---|
| Gradle | `uv` (`uv sync`, `uv run`, `uv.lock`) |
| data class | pydantic `BaseModel`, `@dataclass(frozen=True)` |
| sealed class + when | `StrEnum` + таблица рёбер / `match` |
| interface | `typing.Protocol` (см. `ports.py`) |
| null-safety | `str \| None` + `mypy --strict` |
| detekt / ktlint | `ruff check`, `ruff format` |
| JUnit | `pytest` |

Проверки перед коммитом:

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q
```

## Что поменялось относительно 0.1

- Папка задач: `~/.heroflow/tasks/<KEY>` вместо `~/.heroflow/sandbox/<KEY>`. Задачи, начатые старой версией,
  не продолжатся — их нужно запустить заново.
- Флоу называется `story_sdd`, старое имя `--flow sdd_openspec` тоже работает.
- TLS проверяется по умолчанию. Для корпоративного CA задайте `HTTP_CA_BUNDLE`, вернуть старое поведение
  можно через `HTTP_INSECURE=true`.
- `/hf`-комментарии: команда должна стоять в начале комментария, читаются и ответы в тредах, обработанные
  комментарии второй раз агенту не отдаются, можно ограничить авторов (`BB_ALLOWED_COMMENT_AUTHORS`).
- Исправлены ошибки: тихие падения `git push`/`checkout`, падение `commit` без изменений, удаление чужих
  changes из `openspec/changes`, выбор explore-файла вместо папки спеки, `None.exists()` при отсутствии
  spec.md, `KeyError` при ошибке создания PR, падение на задаче без описания или спринта.
