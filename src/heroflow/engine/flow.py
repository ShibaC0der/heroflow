"""Контракт флоу: узлы возвращают исход, рёбра решают, куда идти дальше."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from itertools import pairwise
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from heroflow.engine.env import Env
    from heroflow.engine.state import TaskContext


class Outcome(StrEnum):
    OK = "ok"
    APPROVE = "approve"
    ITERATE = "iterate"
    STUCK = "stuck"
    NEED_HUMAN = "need_human"


END = "__end__"


class Node(Protocol):
    """Шаг флоу. Читает и меняет контекст, возвращает исход."""

    name: str

    def run(self, ctx: TaskContext, env: Env) -> Outcome: ...


class FlowError(Exception):
    pass


@dataclass(frozen=True)
class Flow:
    name: str
    start: str
    nodes: tuple[Node, ...]
    edges: Mapping[tuple[str, Outcome], str]
    # Сколько раз можно зайти в один узел за прогон. Защита от вечных циклов.
    max_visits: Mapping[str, int] = field(default_factory=dict)
    default_max_visits: int = 5

    def __post_init__(self) -> None:
        names = [n.name for n in self.nodes]
        if len(names) != len(set(names)):
            raise FlowError(f"{self.name}: имена узлов повторяются: {names}")
        known = set(names)
        if self.start not in known:
            raise FlowError(f"{self.name}: стартовый узел {self.start} не найден")
        for (src, _), dst in self.edges.items():
            if src not in known:
                raise FlowError(f"{self.name}: ребро из неизвестного узла {src}")
            if dst != END and dst not in known:
                raise FlowError(f"{self.name}: ребро в неизвестный узел {dst}")

    def node(self, name: str) -> Node:
        for n in self.nodes:
            if n.name == name:
                return n
        raise FlowError(f"{self.name}: узел {name} не найден")

    def next(self, current: str, outcome: Outcome) -> str | None:
        return self.edges.get((current, outcome))

    def visits_limit(self, name: str) -> int:
        return self.max_visits.get(name, self.default_max_visits)


def linear(*names: str) -> dict[tuple[str, Outcome], str]:
    """Рёбра `a -ok-> b -ok-> c` для простых участков. Последним можно передать END."""
    return {(src, Outcome.OK): dst for src, dst in pairwise(names)}
