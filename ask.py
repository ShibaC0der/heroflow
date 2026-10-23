import questionary
from questionary import Choice

def bool_choice(text: str) -> bool:
    return questionary.select(
        text,
        choices=[
            Choice(title="Да", value=True),
            Choice(title="Нет", value=False)
        ]
    ).unsafe_ask()
