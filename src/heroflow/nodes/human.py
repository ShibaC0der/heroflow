from __future__ import annotations

from heroflow.engine import Env, Outcome, TaskContext


class HumanDecision:
    """Развилка на человека: «да» — идём дальше (OK), «нет» — пауза (NEED_HUMAN).

    На паузе задача получает статус waiting_human; `heroflow resume` снова задаёт вопрос.
    """

    def __init__(self, name: str, question: str) -> None:
        self.name = name
        self.question = question

    def run(self, ctx: TaskContext, env: Env) -> Outcome:
        return Outcome.OK if env.human.confirm(self.question) else Outcome.NEED_HUMAN
