from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict, PydanticBaseSettingsSource

HEROFLOW_CONFIG_PATH = Path().home() / ".heroflow" / "config.yaml"


def _load_home_config() -> dict:
    if not HEROFLOW_CONFIG_PATH.exists():
        return {}
    return yaml.safe_load(HEROFLOW_CONFIG_PATH.read_text(encoding="utf-8"))


class ConfigBase(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @classmethod
    def settings_customise_sources(
            cls,
            settings_cls: type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
    ):
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            lambda: _load_home_config().get(cls._section_name(), {}),
            file_secret_settings
        )

    @classmethod
    def _section_name(cls) -> str:
        return ""


class BitbucketConfig(ConfigBase):
    model_config = SettingsConfigDict(env_prefix="bb_")

    token: str
    repo_slug: str
    project: str
    url: str

    @classmethod
    def _section_name(cls) -> str:
        return "bitbucket"

    @property
    def repo_clone_url(self) -> str:
        return f"{self.url}/scm/{self.project}/{self.repo_slug}.git".lower()


class JiraConfig(ConfigBase):
    model_config = SettingsConfigDict(env_prefix="jira_")
    token: str
    url: str

    @classmethod
    def _section_name(cls) -> str:
        return "jira"


class GigaCodeConfig(ConfigBase):
    model_config = SettingsConfigDict(env_prefix="gg_")
    fast_model: str | None = None
    reasoning_model: str | None = None

    @property
    def model(self) -> str:
        return self.reasoning_model or self.fast_model

    @classmethod
    def _section_name(cls) -> str:
        return "gigacode"


class Config(BaseSettings):
    bitbucket: BitbucketConfig = Field(default_factory=BitbucketConfig)
    jira: JiraConfig = Field(default_factory=JiraConfig)
    gigacode: GigaCodeConfig = Field(default_factory=GigaCodeConfig)


@lru_cache
def get_config() -> Config:
    return Config()
