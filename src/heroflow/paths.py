import os
from pathlib import Path


def heroflow_home() -> Path:
    """Корень данных heroflow. Переопределяется HEROFLOW_HOME (например, в тестах)."""
    return Path(os.environ.get("HEROFLOW_HOME", Path.home() / ".heroflow"))
