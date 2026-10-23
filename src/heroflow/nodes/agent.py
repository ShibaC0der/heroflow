"""Вызов агента из узлов: лог траектории, роли (модель на роль) и структурированный ответ."""

from __future__ import annotations

import json
import logging
import re
from enum import StrEnum

from pydantic import BaseModel, ValidationError

from heroflow.engine import Env, TaskContext
from heroflow.integrations.git import Git
from heroflow.prompts import render
from heroflow.skills import skills_hint

log = logging.getLogger(__name__)


class Role(StrEnum):
    """Кто работает: от роли зависят модель и права на запись."""

    PLANNER = "planner"
    REVIEWER = "reviewer"
    FIXER = "fixer"
    WORKER = "worker"


def model_for(role: Role, env: Env) -> str | None:
    gg = env.config.gigacode
    if role in (Role.PLANNER, Role.REVIEWER):
        return gg.reasoning_model or gg.fast_model
    if role is Role.FIXER:
        return gg.fast_model or gg.reasoning_model
    return gg.model


def call_agent(node: str, ctx: TaskContext, env: Env, prompt: str, *, role: Role = Role.WORKER) -> str:
    """Вызов агента с логом всей траектории в tasks/<KEY>/logs/<узел>-<N>.jsonl."""
    ctx.logs_dir.mkdir(parents=True, exist_ok=True)
    n = len(list(ctx.logs_dir.glob(f"{node}-*.jsonl"))) + 1
    gg = env.config.gigacode
    readonly = role is Role.REVIEWER
    writes_code = role in (Role.WORKER, Role.FIXER)
    hint = skills_hint(node, ctx.repo_path, env.config.skills)
    return env.agent.run(
        f"{prompt}\n\n{hint}" if hint else prompt,
        ctx.repo_path,
        model=model_for(role, env),
        append_system_prompt=render("common/system.md.j2"),
        exclude_tools=gg.readonly_exclude_tools if readonly else None,
        allowed_tools=gg.allowed_tools if writes_code and gg.allowed_tools else None,
        log_file=ctx.logs_dir / f"{node}-{n}.jsonl",
    )


_FENCED = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def extract_json(text: str) -> str:
    """JSON из ответа агента: последний ```json-блок, иначе всё от первой { до последней }."""
    blocks = _FENCED.findall(text)
    if blocks:
        return str(blocks[-1])
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("в ответе нет JSON-объекта")
    return text[start : end + 1]


class StructuredAnswerError(RuntimeError):
    pass


def ask_structured[M: BaseModel](
    node: str,
    ctx: TaskContext,
    env: Env,
    prompt: str,
    model_cls: type[M],
    *,
    role: Role = Role.REVIEWER,
    retries: int = 1,
) -> M:
    """Спросить агента и разобрать ответ в pydantic-модель. Невалидный ответ — повтор с текстом ошибки.

    Ревьювер работает только на чтение: если он всё же поменял файлы, изменения откатываются.
    """
    attempt_prompt = prompt
    for attempt in range(retries + 1):
        answer = call_agent(node, ctx, env, attempt_prompt, role=role)
        if role is Role.REVIEWER:
            git = Git(ctx.repo_path)
            if git.has_changes():
                log.warning("%s: ревьювер изменил файлы, откатываю", node)
                git.discard_changes()
        try:
            return model_cls.model_validate(json.loads(extract_json(answer)))
        except (ValueError, ValidationError) as e:
            log.warning("%s: ответ не разобран (попытка %s): %s", node, attempt + 1, e)
            attempt_prompt = (
                f"{prompt}\n\n# Исправь формат ответа\n"
                f"Прошлый ответ не прошёл проверку: {e}\nВерни только JSON по схеме выше, без пояснений вокруг."
            )
    raise StructuredAnswerError(f"{node}: агент {retries + 1} раз вернул ответ не по схеме {model_cls.__name__}")
