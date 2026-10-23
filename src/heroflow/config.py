"""Настройки: переменные окружения > .env > ~/.heroflow/config.yaml.

Секции yaml совпадают с префиксами переменных: `bitbucket:` <-> `BB_*`, `jira:` <-> `JIRA_*` и т.д.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, ClassVar

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import (
    BaseSettings,
    InitSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from heroflow.paths import heroflow_home


def _load_home_config() -> dict[str, Any]:
    path = heroflow_home() / "config.yaml"
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


class ConfigBase(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    section: ClassVar[str] = ""

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        yaml_settings = InitSettingsSource(settings_cls, init_kwargs=_load_home_config().get(cls.section, {}))
        return init_settings, env_settings, dotenv_settings, yaml_settings, file_secret_settings


class HttpConfig(ConfigBase):
    model_config = SettingsConfigDict(env_prefix="http_")
    section = "http"

    # Путь к корпоративному CA. Лучше, чем выключать проверку сертификатов.
    ca_bundle: str | None = None
    # Явный opt-in на старое поведение (verify=False). По умолчанию сертификаты проверяются.
    insecure: bool = False
    timeout_s: float = 30.0

    @property
    def verify(self) -> bool | str:
        if self.insecure:
            return False
        return self.ca_bundle or True


class BitbucketConfig(ConfigBase):
    model_config = SettingsConfigDict(env_prefix="bb_")
    section = "bitbucket"

    token: str
    repo_slug: str
    project: str
    url: str
    # Чьи /hf-комментарии брать в работу. Пусто = всех (небезопасно: любой комментатор управляет агентом).
    allowed_comment_authors: list[str] = Field(default_factory=list)

    @property
    def repo_clone_url(self) -> str:
        return f"{self.url}/scm/{self.project}/{self.repo_slug}.git".lower()


class JiraConfig(ConfigBase):
    model_config = SettingsConfigDict(env_prefix="jira_")
    section = "jira"

    token: str
    url: str
    epic_field: str = "customfield_11400"


class GigaCodeConfig(ConfigBase):
    model_config = SettingsConfigDict(env_prefix="gg_")
    section = "gigacode"

    executable: str = "gigacode"
    fast_model: str | None = None
    reasoning_model: str | None = None
    permission_mode: str = "auto-edit"
    # Чем ограничить ревьюверов: имена инструментов Qwen Code / GigaCode, которые пишут файлы или запускают команды
    # Что разрешить без подтверждения агентам, которые пишут код (worker, fixer).
    # Например ["run_shell_command(make)"], чтобы агент сам гонял сборку. Пусто = по permission_mode
    allowed_tools: list[str] = Field(default_factory=list)
    readonly_exclude_tools: list[str] = Field(
        default_factory=lambda: ["write_file", "edit", "run_shell_command", "monitor", "agent"]
    )

    @property
    def model(self) -> str | None:
        return self.reasoning_model or self.fast_model


class ChecksConfig(ConfigBase):
    """Проверки, которые heroflow запускает сам: по ним Ralph loop решает, готова ли задача.

    Репозиторий может переопределить команды файлом .heroflow.yaml в корне: `checks: [...]`.
    """

    model_config = SettingsConfigDict(env_prefix="hf_checks_")
    section = "checks"

    # Команды сборки, линтера и тестов целевого проекта. Обязательны: по ним решается, готова ли задача
    commands: list[str] = Field(default_factory=list)
    timeout_s: int = 1800
    # Сколько последних строк вывода упавшей проверки отдавать агенту
    output_tail_lines: int = 150


class ContextRepoConfig(BaseModel):
    url: str
    default_branch: str = "master"
    # Какие папки и файлы брать, если в задаче не указано иное. Пусто = весь репозиторий
    paths: list[str] = Field(default_factory=list)


class ContextConfig(ConfigBase):
    """Внешний контекст для планирования: вложения из Jira и дополнительные репозитории."""

    model_config = SettingsConfigDict(env_prefix="hf_context_")
    section = "context"

    attachment_extensions: list[str] = Field(
        default_factory=lambda: [
            *("md", "txt", "yaml", "yml", "json", "xml", "sql", "csv"),
            *("png", "jpg", "jpeg", "pdf", "docx"),
        ]
    )
    attachment_max_mb: float = 20
    # Имя -> репозиторий. Имя используется в блоке heroflow в задаче: `analytics: <ветка>`
    repos: dict[str, ContextRepoConfig] = Field(default_factory=dict)


class SkillsConfig(ConfigBase):
    """Скиллы Qwen Code / GigaCode, которые узлы флоу подключают к своему вызову агента.

    Скилл ищется по имени: встроенные скиллы heroflow, папки из `dirs`, ~/.qwen/skills,
    расширения (~/.qwen/extensions/*/skills) и .qwen/skills самого репозитория.
    Репозиторий может дополнить привязку файлом .heroflow.yaml: `skills: {узел: [скилл, ...]}`.
    """

    model_config = SettingsConfigDict(env_prefix="hf_skills_")
    section = "skills"

    # Где CLI держит пользовательские скиллы и расширения
    qwen_home: str = "~/.qwen"
    # Дополнительные папки со скиллами: <папка>/<скилл>/SKILL.md
    dirs: list[str] = Field(default_factory=list)
    # Узел -> скиллы. ponytail ставится отдельно: qwen extensions install DietrichGebert/ponytail:ponytail
    nodes: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "ralph": ["ponytail"],
            "code_review_fix": ["ponytail"],
            "code_review_review": ["review-checklist", "ponytail-review"],
        }
    )


class Config(BaseSettings):
    bitbucket: BitbucketConfig = Field(default_factory=lambda: BitbucketConfig())  # type: ignore[call-arg]
    jira: JiraConfig = Field(default_factory=lambda: JiraConfig())  # type: ignore[call-arg]
    gigacode: GigaCodeConfig = Field(default_factory=GigaCodeConfig)
    http: HttpConfig = Field(default_factory=HttpConfig)
    context: ContextConfig = Field(default_factory=ContextConfig)
    checks: ChecksConfig = Field(default_factory=ChecksConfig)
    skills: SkillsConfig = Field(default_factory=SkillsConfig)


@lru_cache
def get_config() -> Config:
    return Config()
