"""Промпты как Jinja2-шаблоны: prompts/<флоу>/<узел>.md.j2.

StrictUndefined: опечатка в имени переменной — ошибка при рендере, а не пустое место в промпте.
"""

from __future__ import annotations

import re
from typing import Any

from jinja2 import Environment, PackageLoader, StrictUndefined

_env = Environment(
    loader=PackageLoader("heroflow", "prompts"),
    undefined=StrictUndefined,
    keep_trailing_newline=False,
    trim_blocks=True,
    lstrip_blocks=True,
    autoescape=False,
)


def render(template: str, **values: Any) -> str:
    text = _env.get_template(template).render(**values).strip()
    # Пустые условные блоки оставляют лишние пустые строки
    return re.sub(r"\n{3,}", "\n\n", text)


def templates() -> list[str]:
    return [t for t in _env.list_templates() if t.endswith(".md.j2") and not t.rsplit("/", 1)[-1].startswith("_")]
