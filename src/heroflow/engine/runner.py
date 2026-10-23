"""Исполнение флоу: шаг за шагом, с checkpoint после каждого узла."""

from __future__ import annotations

import logging

from heroflow.engine.env import Env
from heroflow.engine.flow import END, Flow, FlowError, Outcome
from heroflow.engine.state import TaskState, TaskStatus, TaskStore, Transition, now

log = logging.getLogger(__name__)


def run_flow(flow: Flow, state: TaskState, env: Env, store: TaskStore) -> TaskState:
    """Крутит граф с `state.current_node` до END, ожидания человека или STUCK.

    Состояние сохраняется после каждого узла, поэтому прерванный прогон
    продолжается с того же узла, а не с начала.
    """
    if state.status is TaskStatus.DONE:
        log.info("Задача уже завершена")
        return state

    current = state.current_node or flow.start
    if state.status in (TaskStatus.STUCK, TaskStatus.WAITING_HUMAN):
        # Человек вмешался и запустил resume: даём узлу новые попытки
        state.visits[current] = 0
    state.status = TaskStatus.RUNNING
    state.error = None
    state.current_node = current
    store.save(state)

    while current != END:
        visits = state.visits.get(current, 0) + 1
        if visits > flow.visits_limit(current):
            log.warning("Узел %s превысил лимит заходов (%s)", current, flow.visits_limit(current))
            state.status = TaskStatus.STUCK
            state.error = f"Узел {current} выполнен больше {flow.visits_limit(current)} раз"
            store.save(state)
            return state

        node = flow.node(current)
        log.info("Запуск узла %s", current)
        started = now()
        try:
            outcome = node.run(state.context, env)
        except BaseException as e:
            state.status = TaskStatus.FAILED
            state.error = f"{type(e).__name__}: {e}"
            store.save(state)
            raise

        state.visits[current] = visits
        state.history.append(Transition(node=current, outcome=outcome, started_at=started, finished_at=now()))
        log.info("Узел %s -> %s", current, outcome)

        nxt = flow.next(current, outcome)
        if nxt is None:
            if outcome is Outcome.NEED_HUMAN:
                state.status = TaskStatus.WAITING_HUMAN
                store.save(state)
                return state
            if outcome is Outcome.STUCK:
                state.status = TaskStatus.STUCK
                store.save(state)
                return state
            state.status = TaskStatus.FAILED
            state.error = f"Нет ребра из {current} по исходу {outcome}"
            store.save(state)
            raise FlowError(state.error)

        current = nxt
        state.current_node = current
        store.save(state)

    state.status = TaskStatus.DONE
    state.current_node = None
    store.save(state)
    log.info("Флоу %s завершён", flow.name)
    return state
