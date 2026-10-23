from __future__ import annotations

from dataclasses import dataclass

from heroflow.config import Config
from heroflow.ports import Agent, Bitbucket, Human, Jira


@dataclass(frozen=True)
class Env:
    """Всё внешнее, что нужно узлам. В тестах собирается из фейков."""

    config: Config
    jira: Jira
    bitbucket: Bitbucket
    agent: Agent
    human: Human
