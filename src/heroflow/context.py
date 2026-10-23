"""Контракт внешнего контекста: блок heroflow в описании задачи Jira.

    {panel:title=heroflow}
    attachments: openapi.yaml, *.png
    analytics: feature/PAY-123-limits
    analytics_paths: docs/payments, docs/glossary.md
    {panel}

Что в блоке есть, то агент и получит. Без блока не скачивается ни одно вложение,
а репозитории контекста берутся с веткой по умолчанию.
"""

from __future__ import annotations

import fnmatch
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import unquote

from heroflow.config import ContextRepoConfig
from heroflow.engine.state import JiraAttachment

_BLOCK = re.compile(
    r"\{(?P<tag>panel|code|noformat)(?::[^}]*?)?title=heroflow[^}]*\}(?P<body>.*?)\{(?P=tag)\}",
    re.IGNORECASE | re.DOTALL,
)


class ContextError(RuntimeError):
    pass


def _split(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


@dataclass(frozen=True)
class Directives:
    values: dict[str, str] = field(default_factory=dict)

    def get(self, key: str) -> str | None:
        value = self.values.get(key)
        return value or None

    def list(self, key: str) -> list[str]:
        return _split(self.values.get(key, ""))


def parse_directives(description_raw: str) -> Directives:
    match = _BLOCK.search(description_raw or "")
    if not match:
        return Directives()
    values: dict[str, str] = {}
    for line in match.group("body").splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        values[key.strip().lower()] = value.strip()
    return Directives(values)


def strip_directives(description_raw: str) -> str:
    """Описание без блока heroflow: служебный блок агенту не нужен."""
    return _BLOCK.sub("", description_raw or "").strip()


def select_attachments(
    attachments: list[JiraAttachment],
    patterns: list[str],
    extensions: list[str],
    max_bytes: int,
) -> list[JiraAttachment]:
    """Вложения, перечисленные в блоке heroflow. Шаблон без совпадений — ошибка, а не тихий пропуск."""
    allowed = {e.lower().lstrip(".") for e in extensions}
    selected: dict[str, JiraAttachment] = {}
    for pattern in patterns:
        matched = [a for a in attachments if fnmatch.fnmatch(a.filename.lower(), pattern.lower())]
        if not matched:
            names = ", ".join(a.filename for a in attachments) or "вложений нет"
            raise ContextError(f"В задаче нет вложения «{pattern}». Есть: {names}")
        for a in matched:
            ext = a.filename.rsplit(".", 1)[-1].lower() if "." in a.filename else ""
            if ext not in allowed:
                raise ContextError(
                    f"Вложение {a.filename}: расширение .{ext} не разрешено (context.attachment_extensions)"
                )
            if a.size > max_bytes:
                raise ContextError(f"Вложение {a.filename}: {a.size} байт, больше лимита {max_bytes}")
            selected[a.id] = a
    return list(selected.values())


def _repo_path_in_url(url: str) -> str:
    """https://bb/scm/prj/repo.git -> projects/prj/repos/repo (как в ссылках browse)."""
    m = re.search(r"/scm/(?P<project>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$", url, re.IGNORECASE)
    if not m:
        return ""
    return f"projects/{m['project']}/repos/{m['repo']}".lower()


def branch_from_link(description_raw: str, repo_url: str) -> str | None:
    """Ветка из ссылки Bitbucket на этот репозиторий: .../projects/P/repos/R/browse?at=refs/heads/<ветка>."""
    repo_part = _repo_path_in_url(repo_url)
    if not repo_part:
        return None
    for m in re.finditer(r"https?://\S+", description_raw or ""):
        link = unquote(m.group(0)).rstrip("|]")
        if repo_part not in link.lower():
            continue
        at = re.search(r"[?&]at=refs/heads/([^&#\s|\]]+)", link)
        if at:
            return at.group(1)
    return None


@dataclass(frozen=True)
class ResolvedBranch:
    branch: str
    source: str


def resolve_branch(
    name: str,
    repo: ContextRepoConfig,
    directives: Directives,
    description_raw: str,
    issue_key: str,
    remote_heads: Callable[[], list[str]],
) -> ResolvedBranch:
    """Порядок: блок heroflow -> ссылка на ветку в описании -> ветка с ключом задачи -> ветка по умолчанию."""
    heads = None

    explicit = directives.get(name)
    if explicit:
        heads = remote_heads()
        if explicit not in heads:
            raise ContextError(f"Ветка «{explicit}» из блока heroflow не найдена в репозитории {name}")
        return ResolvedBranch(explicit, "directive")

    linked = branch_from_link(description_raw, repo.url)
    if linked:
        return ResolvedBranch(linked, "link")

    heads = heads if heads is not None else remote_heads()
    with_key = sorted(h for h in heads if issue_key.lower() in h.lower())
    if len(with_key) == 1:
        return ResolvedBranch(with_key[0], "issue_key")
    if len(with_key) > 1:
        raise ContextError(
            f"В репозитории {name} несколько веток с {issue_key}: {', '.join(with_key)}. "
            "Укажите нужную в блоке heroflow"
        )
    return ResolvedBranch(repo.default_branch, "default")
