"""Ralph loop: по одному пункту tasks.md за итерацию, в свежей сессии агента, с проверками от heroflow.

- Память между итерациями — tasks.md, progress.md и git, а не контекст агента.
- «Готово» решают проверки (сборка, линтер, тесты), которые запускает heroflow, а не слова агента.
- Зелёный шаг сразу коммитится и пушится; красный остаётся в рабочей папке, и следующая итерация его чинит.
- Стоп-условия: всё отмечено и зелёно -> OK; агент написал HEROFLOW_STUCK, N красных подряд или кончился
  бюджет итераций -> STUCK.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

from heroflow.engine import Env, Outcome, TaskContext
from heroflow.engine.state import CONTEXT_DIR_NAME
from heroflow.integrations.checks import run_checks
from heroflow.integrations.git import Git
from heroflow.nodes.agent import Role, call_agent
from heroflow.prompts import render

log = logging.getLogger(__name__)

_TASK = re.compile(r"^(?P<prefix>\s*[-*]\s+\[)(?P<mark>[ xX])(?P<sep>\]\s+)(?P<text>.+?)\s*$")
STUCK_MARKER = "HEROFLOW_STUCK"


def pending_steps(tasks_md: str) -> list[str]:
    return [m["text"] for line in tasks_md.splitlines() if (m := _TASK.match(line)) and m["mark"] == " "]


def mark_done(tasks_md: str, step: str) -> str:
    lines = tasks_md.splitlines(keepends=True)
    for i, line in enumerate(lines):
        m = _TASK.match(line.rstrip("\n"))
        if m and m["mark"] == " " and m["text"] == step:
            lines[i] = f"{m['prefix']}x{m['sep']}{m['text']}" + ("\n" if line.endswith("\n") else "")
            break
    return "".join(lines)


def stuck_reason(answer: str) -> str | None:
    for line in answer.splitlines():
        if STUCK_MARKER in line:
            return line.split(STUCK_MARKER, 1)[1].lstrip(": ").strip() or "агент не смог продвинуться"
    return None


class RalphImplement:
    name = "ralph"

    def __init__(self, max_iterations: int = 30, max_failures_in_row: int = 3) -> None:
        self.max_iterations = max_iterations
        self.max_failures_in_row = max_failures_in_row

    def run(self, ctx: TaskContext, env: Env) -> Outcome:
        if not ctx.delta_spec_dir:
            raise RuntimeError("Не задана папка спецификации")
        tasks_file = ctx.repo_path / ctx.delta_spec_dir / "tasks.md"
        if not tasks_file.exists():
            raise RuntimeError(f"Нет {tasks_file}")
        progress = ctx.context_dir / "ralph" / "progress.md"
        progress.parent.mkdir(parents=True, exist_ok=True)
        git = Git(ctx.repo_path)
        git.exclude(f"/{CONTEXT_DIR_NAME}/")

        st = ctx.ralph
        # Каждый заход (в том числе после человека) — новый бюджет попыток
        st.failures_in_row = 0
        st.stuck_reason = ""

        for _ in range(self.max_iterations):
            pending = pending_steps(tasks_file.read_text(encoding="utf-8"))
            step = pending[0] if pending else None

            if step is None and not st.last_failure:
                result = run_checks(ctx.repo_path, env.config.checks)
                if result.ok:
                    git.commit_all(f"{ctx.issue_key}: implementation done")
                    git.push(ctx.branch_name)
                    log.info("Ralph: все пункты tasks.md выполнены, проверки зелёные")
                    return Outcome.OK
                st.last_failure = f"$ {result.command}\n{result.output}"

            st.iterations += 1
            st.current_task = step
            log.info("Ralph, итерация %s: %s", st.iterations, step or "починка проверок")
            prompt = render(
                "ralph/iteration.md.j2",
                ctx=ctx,
                step=step,
                pending_count=len(pending),
                failure=st.last_failure,
                progress_file=progress.relative_to(ctx.repo_path).as_posix(),
            )
            answer = call_agent(self.name, ctx, env, prompt, role=Role.WORKER)

            if reason := stuck_reason(answer):
                st.stuck_reason = reason
                self._log(progress, st.iterations, f"агент остановился: {reason}")
                return Outcome.STUCK

            result = run_checks(ctx.repo_path, env.config.checks)
            if result.ok:
                text = tasks_file.read_text(encoding="utf-8")
                if step and step in pending_steps(text):
                    tasks_file.write_text(mark_done(text, step), encoding="utf-8")
                if git.commit_all(f"{ctx.issue_key}: {step or 'fix checks'}"):
                    git.push(ctx.branch_name)
                st.failures_in_row = 0
                st.last_failure = ""
                self._log(progress, st.iterations, f"зелёно, закоммичено: {step or 'починка проверок'}")
                continue

            st.failures_in_row += 1
            st.last_failure = f"$ {result.command}\n{result.output}"
            self._log(progress, st.iterations, f"проверка `{result.command}` упала ({st.failures_in_row} подряд)")
            if st.failures_in_row >= self.max_failures_in_row:
                st.stuck_reason = f"{st.failures_in_row} итерации подряд падает `{result.command}`"
                return Outcome.STUCK

        st.stuck_reason = f"закончился бюджет в {self.max_iterations} итераций"
        return Outcome.STUCK

    @staticmethod
    def _log(progress: Path, iteration: int, text: str) -> None:
        stamp = datetime.now().strftime("%d.%m %H:%M")
        with progress.open("a", encoding="utf-8") as f:
            f.write(f"- [heroflow {stamp}] итерация {iteration}: {text}\n")
