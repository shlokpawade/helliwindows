"""
planner.py – Multi-step task planner.

Takes one or more Intents, optionally expands them into sub-tasks (for
routines or compound commands), and dispatches each task to the correct
action handler.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from brain import Intent
from memory import Memory
from utils import logger, speak


# ---------------------------------------------------------------------------
# Task representation
# ---------------------------------------------------------------------------

@dataclass
class Task:
    action: str
    args: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------

class Planner:
    def __init__(self, memory: Memory) -> None:
        self._memory = memory
        # Lazy import to avoid circular dependency; actions import planner
        self._actions: dict[str, Callable] = {}

    def register_actions(self, actions: dict[str, Callable]) -> None:
        """Register {action_name: handler_fn} mapping."""
        self._actions = actions

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def plan_and_run(self, intent: Intent) -> bool:
        """
        Expand a single *intent* into one or more Tasks and execute them.
        Returns True if all tasks succeeded.
        """
        tasks = self._expand(intent)
        logger.debug("Planned tasks: %s", tasks)
        return self._execute_all(tasks)

    def plan_and_run_multi(self, intents: list[Intent]) -> bool:
        """
        Process a list of intents (from a compound command) sequentially.
        Returns True if every intent's tasks succeeded.
        """
        all_ok = True
        for intent in intents:
            ok = self.plan_and_run(intent)
            if not ok:
                all_ok = False
        return all_ok

    # ------------------------------------------------------------------
    # Expansion
    # ------------------------------------------------------------------
    def _expand(self, intent: Intent) -> list[Task]:
        """Convert an Intent into a flat list of Tasks."""

        # Routines (study mode, coding mode, user-defined)
        if intent.name in ("activate_mode", "run_routine"):
            mode = intent.args.get("mode", "")
            routine = self._memory.get_routine(mode)
            if routine:
                return [Task(step["action"], step.get("args", {})) for step in routine]
            # If no routine defined, fall through to the registered handler
            return [Task(intent.name, intent.args)]

        # All other intents map 1-to-1
        return [Task(intent.name, intent.args)]

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------
    def _execute_all(self, tasks: list[Task]) -> bool:
        all_ok = True
        for task in tasks:
            ok = self._execute(task)
            all_ok = all_ok and ok
        return all_ok

    def _execute(self, task: Task) -> bool:
        handler = self._actions.get(task.action)
        if handler is None:
            logger.warning("No handler registered for action '%s'", task.action)
            speak(f"I don't know how to {task.action.replace('_', ' ')} yet.")
            return False
        try:
            handler(**task.args)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("Action '%s' raised: %s", task.action, exc, exc_info=True)
            speak(f"Something went wrong while trying to {task.action.replace('_', ' ')}.")
            return False
