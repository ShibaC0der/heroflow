import asyncio.streams
import logging
from pathlib import Path

from qwen_code_sdk import is_sdk_result_message, query_sync

from config import get_config

log = logging.getLogger(__name__)

# Патчим класс StreamReader, чтобы ЛЮБОЙ новый объект создавался с большим лимитом (увеличиваем лимит ответа)
original_init = asyncio.streams.StreamReader.__init__


def patched_init(self, limit=65536, *args, **kwargs):
    # Игнорируем дефолтные 64КБ и ставим 50 Мегабайт
    custom_limit = 50 * 1024 * 1024
    original_init(self, limit=custom_limit, *args, **kwargs)


asyncio.streams.StreamReader.__init__ = patched_init


def run_fast(prompt: str, path: Path) -> str:
    return run(prompt, path, model=get_config().gigacode.fast_model)


def run_reasoning(prompt: str, path: Path) -> str:
    return run(prompt, path, model=get_config().gigacode.reasoning_model)


def run(
        prompt: str,
        path: Path,
        model: str | None = None,
        system_prompt: str | None = None,
        exclude_tools: list[str] | None = None,
) -> str:
    model = model or get_config().gigacode.model
    print(f"Вызов GigaCode. Модель={model or 'по умолчанию'}")

    options = {
        "cwd": str(path),
        "path_to_qwen_executable": "gigacode",
        "permission_mode": "auto-edit"
    }

    if model:
        options["model"] = model

    if system_prompt:
        options["system_prompt"] = system_prompt

    if exclude_tools:
        options["exclude_tools"] = exclude_tools

    result_msg = ""

    with query_sync(
            prompt=prompt,
            options=options,
    ) as result:
        for message in result:
            if is_sdk_result_message(message):
                if message.get("is_error"):
                    error = message.get("error") or {}
                    log.error(f"gigacode: {error.get('message', 'Unknown error')}")
                    raise Exception(error)
                else:
                    result_msg = message.get("result", "")
                    log.info(f"gigacode: {result_msg}")
                    break
    return result_msg
