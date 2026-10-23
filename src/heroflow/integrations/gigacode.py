from __future__ import annotations

import asyncio.streams
import json
import logging
from pathlib import Path
from typing import Any, cast

from heroflow.config import GigaCodeConfig

log = logging.getLogger(__name__)

_STREAM_LIMIT = 50 * 1024 * 1024
_patched = False


def _raise_stream_limit() -> None:
    """SDK читает ответ CLI через asyncio.StreamReader с лимитом строки 64 КБ.
    Длинный ответ агента в него не влезает, поэтому поднимаем лимит до 50 МБ.
    Патч глобальный, но ставится только при первом вызове агента, а не при импорте."""
    global _patched
    if _patched:
        return
    original_init = asyncio.streams.StreamReader.__init__

    def patched_init(self: asyncio.StreamReader, limit: int = _STREAM_LIMIT, loop: Any = None) -> None:
        original_init(self, limit=max(limit, _STREAM_LIMIT), loop=loop)

    asyncio.streams.StreamReader.__init__ = patched_init  # type: ignore[method-assign]
    _patched = True


class AgentError(RuntimeError):
    pass


class GigaCodeAgent:
    def __init__(self, config: GigaCodeConfig) -> None:
        self.config = config

    def run(
        self,
        prompt: str,
        cwd: Path,
        *,
        model: str | None = None,
        system_prompt: str | None = None,
        exclude_tools: list[str] | None = None,
        log_file: Path | None = None,
    ) -> str:
        from qwen_code_sdk import is_sdk_result_message, query_sync

        _raise_stream_limit()
        model = model or self.config.model
        log.info("Вызов GigaCode, модель=%s", model or "по умолчанию")

        options: dict[str, Any] = {
            "cwd": str(cwd),
            "path_to_qwen_executable": self.config.executable,
            "permission_mode": self.config.permission_mode,
        }
        if model:
            options["model"] = model
        if system_prompt:
            options["system_prompt"] = system_prompt
        if exclude_tools:
            options["exclude_tools"] = exclude_tools

        transcript = None
        if log_file:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            transcript = log_file.open("a", encoding="utf-8")
            transcript.write(
                json.dumps({"type": "heroflow_prompt", "prompt": prompt, "options": options}, ensure_ascii=False) + "\n"
            )

        try:
            with query_sync(prompt=prompt, options=options) as result:
                for message in result:
                    if transcript:
                        transcript.write(json.dumps(message, ensure_ascii=False, default=str) + "\n")
                    if is_sdk_result_message(message):
                        result_msg = cast(dict[str, Any], message)
                        if result_msg.get("is_error"):
                            error = result_msg.get("error") or {}
                            raise AgentError(error.get("message", "Неизвестная ошибка gigacode"))
                        text = str(result_msg.get("result", ""))
                        log.info("gigacode: %s", text)
                        return text
        finally:
            if transcript:
                transcript.close()
        raise AgentError("gigacode завершился без итогового сообщения")
