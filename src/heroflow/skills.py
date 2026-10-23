"""Скиллы агента: где их искать, как подложить в песочницу и как сослаться на них в промпте.

Скилл — папка с SKILL.md (frontmatter `name`, `description`) в формате Qwen Code / GigaCode.
CLI сам видит ~/.qwen/skills, расширения и .qwen/skills репозитория. Встроенные скиллы heroflow и папки
из конфига он не видит, поэтому heroflow копирует нужные в <repo>/.qwen/skills и прячет их от git.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

import yaml

from heroflow.config import SkillsConfig
from heroflow.integrations.checks import REPO_CONFIG
from heroflow.integrations.git import Git

log = logging.getLogger(__name__)

BUILTIN_DIR = Path(__file__).parent / "skills_builtin"
REPO_SKILLS_DIR = Path(".qwen") / "skills"


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    path: Path
    # True — CLI найдёт скилл сам; False — его нужно скопировать в репозиторий
    visible_to_cli: bool


def _frontmatter(skill_md: Path) -> dict[str, str]:
    text = skill_md.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    head = text.split("---", 2)[1]
    data = yaml.safe_load(head) or {}
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}


def _scan(root: Path, *, visible_to_cli: bool) -> list[Skill]:
    if not root.is_dir():
        return []
    found = []
    for skill_md in sorted(root.glob("*/SKILL.md")):
        meta = _frontmatter(skill_md)
        name = meta.get("name") or skill_md.parent.name
        found.append(Skill(name, meta.get("description", ""), skill_md.parent, visible_to_cli))
    return found


def available_skills(repo_path: Path | None, config: SkillsConfig) -> dict[str, Skill]:
    """Все скиллы по имени. При совпадении имён побеждает более «близкий» к задаче источник."""
    qwen = Path(config.qwen_home).expanduser()
    sources: list[Skill] = []
    sources += _scan(BUILTIN_DIR, visible_to_cli=False)
    for extra in config.dirs:
        sources += _scan(Path(extra).expanduser(), visible_to_cli=False)
    for extension in sorted((qwen / "extensions").glob("*")):
        sources += _scan(extension / "skills", visible_to_cli=True)
    sources += _scan(qwen / "skills", visible_to_cli=True)
    if repo_path:
        sources += _scan(repo_path / REPO_SKILLS_DIR, visible_to_cli=True)
    return {skill.name: skill for skill in sources}


def node_skills(repo_path: Path | None, config: SkillsConfig) -> dict[str, list[str]]:
    """Привязка узел -> скиллы: конфиг heroflow, дополненный .heroflow.yaml репозитория."""
    mapping = {node: list(names) for node, names in config.nodes.items()}
    repo_config = repo_path / REPO_CONFIG if repo_path else None
    if repo_config and repo_config.exists():
        data = yaml.safe_load(repo_config.read_text(encoding="utf-8")) or {}
        for node, names in (data.get("skills") or {}).items():
            mapping[str(node)] = [str(n) for n in names]
    return mapping


def install_skills(repo_path: Path, config: SkillsConfig) -> list[str]:
    """Копирует в репозиторий скиллы, которые узлы используют, а CLI сам не найдёт. Возвращает имена."""
    wanted = {name for names in node_skills(repo_path, config).values() for name in names}
    skills = available_skills(repo_path, config)
    git = Git(repo_path)
    installed = []
    for name in sorted(wanted):
        skill = skills.get(name)
        if skill is None:
            log.warning("Скилл %s не найден, узлы будут работать без него", name)
            continue
        if skill.visible_to_cli:
            continue
        target = repo_path / REPO_SKILLS_DIR / skill.path.name
        shutil.copytree(skill.path, target, dirs_exist_ok=True)
        git.exclude(f"/{(REPO_SKILLS_DIR / skill.path.name).as_posix()}/")
        installed.append(name)
    return installed


def skills_hint(node: str, repo_path: Path, config: SkillsConfig) -> str:
    """Блок для промпта: какие скиллы применить на этом шаге. Пусто, если скиллов нет."""
    names = node_skills(repo_path, config).get(node, [])
    if not names:
        return ""
    skills = available_skills(repo_path, config)
    lines = [_hint_line(skills[name]) for name in names if name in skills]
    if not lines:
        return ""
    return "# Скиллы\nНа этом шаге загрузи и примени скиллы:\n" + "\n".join(lines)


def _hint_line(skill: Skill) -> str:
    return f"- `{skill.name}`: {skill.description}" if skill.description else f"- `{skill.name}`"
