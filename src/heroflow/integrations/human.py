from __future__ import annotations

import questionary


class TerminalHuman:
    def confirm(self, question: str) -> bool:
        answer: bool = questionary.select(
            question,
            choices=[questionary.Choice(title="Да", value=True), questionary.Choice(title="Нет", value=False)],
        ).unsafe_ask()
        return answer
