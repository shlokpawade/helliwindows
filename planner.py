"""
planner.py – Multi-step task planner.

Takes an Intent, optionally expands it into sub-tasks (for routines or
compound commands), and dispatches each task to the correct action handler.
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
        Expand *intent* into one or more Tasks and execute them in order.
        Returns True if all tasks succeeded.
        """
        tasks = self._expand(intent)
        logger.debug("Planned tasks: %s", tasks)
        return self._execute_all(tasks)

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
            # If no routine defined, just speak a note
            speak(f"No routine defined for {mode} mode yet.")
            return []

        # All other intents map 1-to-1
        return [Task(intent.name, intent.args)]

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------
    def _execute_all(self, tasks: list[Task]) -> bool:
        success = True
        for task in tasks:
            ok = self._execute(task)
            if not ok:
                success = False
        return success

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
