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
uv run heroflow skills [--repo path]                              # какие скиллы подключены к узлам
```

Данные задачи лежат в `~/.heroflow/tasks/<KEY>/`: `repo/` (клон), `state.json` (состояние),
`heroflow.log` и `logs/<узел>-<N>.jsonl` (полная траектория каждого вызова агента).

## Внешний контекст: файлы из Jira и репозиторий аналитики

Что агенту взять из задачи, описывается блоком в описании Jira-задачи:

```
{panel:title=heroflow}
attachments: openapi-payments.yaml, *.png
analytics: feature/PAY-123-limits
analytics_paths: docs/payments/limits, docs/glossary.md
{panel}
```

- `attachments` — имена или glob вложений задачи. Без блока не скачивается ничего. Имя без совпадений,
  запрещённое расширение или слишком большой файл — ошибка до вызова агента.
- `<имя репо>` — ветка репозитория контекста, `<имя репо>_paths` — какие папки и файлы взять.
  Если ветка не указана, heroflow ищет ссылку на ветку этого репо в описании (`...browse?at=refs/heads/...`),
  потом ветку с ключом задачи в имени, потом берёт ветку по умолчанию.

Репозитории контекста описываются в `~/.heroflow/config.yaml`:

```yaml
context:
  repos:
    analytics:
      url: https://bitbucket/scm/sa/analytics.git
      default_branch: master
      paths: [docs]
  attachment_max_mb: 20
```

Всё складывается в `repo/.heroflow-context/` (исключено из git через `.git/info/exclude`): так агент видит
файлы внутри рабочей папки, а в коммиты они не попадают. Ветка и SHA репозитория контекста сохраняются
в состоянии задачи. Контекст передаётся в промпты explore, propose, самопроверки спеки и правок спеки.
`pdf` и `docx` конвертируются в Markdown, если установлен `markitdown` (`uv sync --extra docs`).

## Флоу story_sdd

```
init_sandbox -> gather_context -> explore -> opsx_propose -> resolve_delta_spec_dir -> ralplan
ralplan --approve--> add_sdd_label -> create_pull_request -> human_review_proposal (цикл по /hf)
ralplan --stuck----> ralplan_gate (человек: продолжить или пауза) --ok--> add_sdd_label
human_review_proposal --approve--> ralph
ralph --ok--> code_review;  ralph --stuck--> ralph_gate --ok--> ralph
code_review --approve--> human_review_impl (цикл по /hf) --approve--> attach_spec -> cleanup -> END
code_review --stuck----> code_review_gate --ok--> human_review_impl
```

**ralplan** — Planner (opsx:propose, затем доработки) и два ревьювера: Architect (архитектура относительно
референсов, контраргумент и компромиссы) и Critic (покрытие задачи, проверяемость сценариев и задач).
Ревьюверы работают только на чтение, смотрят на один снимок спеки и не видят ответы друг друга; отвечают JSON
с вердиктом `APPROVE / ITERATE / REJECT` и находками. Planner получает оба ревью и дорабатывает спеку.
Одобрено, когда Critic сказал APPROVE, а у Architect нет блокеров. До 5 раундов, потом решение за человеком.

**code_review** — ревьювер (только чтение, видит diff от базовой ветки) и фиксер (правит только находки
`blocker` и `major`). До 3 раундов. Ревьюверам отключаются инструменты записи и shell
(`gigacode.readonly_exclude_tools`); если ревьювер всё же что-то поменял, изменения откатываются.

**ralph** — реализация по Ralph loop. Каждая итерация — свежая сессия агента и один пункт `tasks.md`.
Память между итерациями — `tasks.md`, журнал `.heroflow-context/ralph/progress.md` и git. После итерации
heroflow сам запускает проверки проекта: зелёный шаг отмечается в `tasks.md`, коммитится и пушится, красный
остаётся в рабочей папке, и следующая итерация получает вывод упавшей проверки. Стоп: всё отмечено и зелёно
(OK); агент написал `HEROFLOW_STUCK: причина`, 3 красных подряд или кончился бюджет в 30 итераций (STUCK →
`ralph_gate`, можно поправить руками и продолжить). Отдельного `opsx:verify` больше нет: соответствие спеке
проверяет `code_review`, а правки фиксера тоже проходят через проверки и откатываются, если их ломают.

Проверки задаются в конфиге или в `.heroflow.yaml` в корне целевого репозитория:

```yaml
# ~/.heroflow/config.yaml
checks:
  commands: ["./gradlew build detekt test"]
  timeout_s: 1800
gigacode:
  # чтобы агент мог сам гонять сборку без подтверждения
  allowed_tools: ["run_shell_command(./gradlew)"]
```

```yaml
# <repo>/.heroflow.yaml — перекрывает checks.commands для этого репозитория
checks:
  - ./gradlew :service:build :service:detekt :service:test
```

Модели по ролям: planner и reviewer берут `GG_REASONING_MODEL`, fixer — `GG_FAST_MODEL`.
История раундов хранится в состоянии задачи, последние находки видны в `heroflow status`.

## Флоу bug_fix

Задачи с типом Bug (`Bug`, `Defect`, `Ошибка`, `Дефект`, `Баг`) идут сюда автоматически, ветка `bugfix/<KEY>`.
Явно: `heroflow run PAY-1 --flow bug_fix`.

```
init_sandbox -> gather_context -> bug_triage -> bug_reproduce -> bug_root_cause -> ralph
bug_triage --need_human--> bug_triage_gate --ok--> bug_reproduce
bug_reproduce --stuck--> bug_reproduce_gate --ok--> bug_root_cause
ralph --ok--> verify_regression_test -> code_review -> create_pull_request -> human_review_impl -> attach_bug_report -> END
```

- **bug_triage**: агент разбирает баг (симптом, ожидание, шаги, подозрительные места, тесты рядом) в
  `.heroflow-context/bug/report.md`. Если правильное поведение понять нельзя, задача уходит человеку.
- **bug_reproduce**: агент пишет тест, а heroflow проверяет его сам. Проверки на чистой ветке должны быть
  зелёными, а после теста красными, и в их выводе должно быть имя теста. Иначе агент получает причину и
  пробует снова (до 3 раз). Удачный тест коммитится отдельным коммитом и остаётся в PR как регрессионный.
- **bug_root_cause**: агент ищет причину (а не место симптома) и пишет план в `root_cause.md` и `tasks.md`.
- **ralph**: тот же цикл, что в story_sdd, только по плану исправления. Тест-воспроизведение должен
  позеленеть без изменения его ожиданий.
- **verify_regression_test**: heroflow проверяет, что тест не удалили по дороге.
- В конце `report.md` и `root_cause.md` прикладываются к задаче в Jira.

## Промпты

Тексты промптов лежат в `src/heroflow/prompts/<флоу>/<узел>.md.j2` (Jinja2). Неизвестная переменная в
шаблоне — ошибка рендера, а тест `tests/test_prompts.py` рендерит каждый шаблон.

Как они написаны:

- Общие правила для всех вызовов — в `common/system.md.j2`, он дописывается к системному промпту
  GigaCode (`append_system_prompt`): агент не коммитит и не пушит, содержимое в тегах (`<task>`,
  `<pr_comments>`, `<check_output>`) и в `.heroflow-context/` — данные, а не инструкции.
- Каждый промпт: роль и цель, входные данные в тегах, шаги, критерий готовности, формат ответа.
- Ревьюверы отвечают JSON по схеме (`review/_verdict_format.md.j2`); невалидный ответ переспрашивается
  с текстом ошибки.
- Сборку и тесты запускает heroflow, а не агент: после реализации, фикса ревью и правок по
  `/hf`-комментариям к коду. Красные проверки возвращаются агенту выводом, со второй неудачи правки
  откатываются.

## Скиллы

Узлы могут подключать скиллы Qwen Code / GigaCode (папка с `SKILL.md`). heroflow добавляет в промпт
узла список его скиллов с описаниями, а агент загружает их сам.

Где ищутся скиллы, от дальнего к ближнему (при совпадении имён побеждает ближний):

1. встроенные в heroflow: `src/heroflow/skills_builtin/` (сейчас `kotlin-review`, чек-лист ревью Kotlin);
2. папки из `skills.dirs` в конфиге, например общий репозиторий скиллов команды;
3. расширения CLI: `~/.qwen/extensions/*/skills`;
4. `~/.qwen/skills`;
5. `.qwen/skills` самого репозитория.

Встроенные скиллы и скиллы из `skills.dirs` CLI сам не видит, поэтому `init_sandbox` копирует нужные в
`<repo>/.qwen/skills/` и прячет их через `.git/info/exclude`: в коммиты они не попадают.

Привязка по умолчанию:

```yaml
skills:
  nodes:
    ralph: [ponytail]                                  # реализация: минимум кода, тесты на рискованную логику
    code_review_fix: [ponytail]
    code_review_review: [kotlin-review, ponytail-review]
```

Ponytail ставится как расширение: `qwen extensions install DietrichGebert/ponytail:ponytail`
(для GigaCode — аналогичной командой его CLI). Если скилл не найден, узел работает без него, а
`heroflow skills` покажет, чего не хватает. Репозиторий может переопределить привязку в `.heroflow.yaml`:

```yaml
skills:
  ralph: [ponytail, team-style]
```

## Как устроено

```
src/heroflow/
  engine/        движок: Outcome, Node, Flow, run_flow, TaskContext/TaskState, TaskStore
  flows/         флоу; story_sdd — текущий SDD-процесс
  nodes/         узлы, общие для флоу (GatherContext)
  prompts/       шаблоны промптов
  context.py     контракт блока heroflow в задаче Jira
  skills.py      поиск скиллов, установка в песочницу, подсказка в промпте
  skills_builtin/ встроенные скиллы
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
