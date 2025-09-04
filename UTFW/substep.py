# substep.py
"""
UTSW Sub-Step Execution Module
==============================
Handles detailed sub-step execution when needed

Author: DvidMakesThings
"""

from typing import Any, Callable
from .core import TestAction


class SubStepExecutor:
    """Executes functions as sub-steps within a main test step"""

    def __init__(self, parent_step: str, reporter):
        self.parent_step = parent_step
        self.reporter = reporter
        self.sub_step_counter = 0
        self._last_response = None  # Store response for chaining

    def execute(self, *actions) -> Any:
        """
        Execute one or more actions as sub-steps

        Usage:
            # Single action (returns result)
            response = sub_executor.execute(Serial.send_command_simple(...))

            # Multiple actions (executes in sequence, returns list of results)
            sub_executor.execute(
                SNMP.set_outlet_state_simple(...),
                SNMP.verify_outlet_state_simple(...),
                SNMP.set_outlet_state_simple(...),
                SNMP.verify_outlet_state_simple(...)
            )

        Args:
            *actions: TestAction-like objects or regular callables

        Returns:
            Result of last action (if single action) or list of results (if multiple)
        """
        if len(actions) == 1:
            # Single action
            result = self._execute_single(actions[0])
            self._last_response = result
            return result
        else:
            # Multiple actions - execute in sequence
            results = []
            for action in actions:
                result = self._execute_single(action)
                results.append(result)
                self._last_response = result  # Store for potential chaining
            return results

    def _resolve_action(self, action) -> tuple[str, Callable[[], Any]]:
        """
        Resolve any action-like object to (name, callable).
        Accepts:
          - core.TestAction
          - Any object with 'execute_func' attribute (duck-typed TestAction from modules)
          - A plain callable
        """
        if isinstance(action, TestAction):
            return action.name, action.execute_func
        if hasattr(action, "execute_func") and callable(getattr(action, "execute_func")):
            name = getattr(action, "name", getattr(action, "__name__", "Unknown action"))
            return name, action.execute_func  # type: ignore[return-value]
        if callable(action):
            return getattr(action, "__name__", "Unknown action"), action  # type: ignore[return-value]
        def _raiser() -> Any:
            raise TypeError(f"Unsupported action type: {type(action)}")
        return "Unknown action", _raiser

    def _execute_single(self, action) -> Any:
        """Execute a single action as sub-step"""
        self.sub_step_counter += 1
        sub_step_id = f"{self.parent_step}.{self.sub_step_counter}"

        step_description, actual_func = self._resolve_action(action)
        self.reporter.log_step_start(sub_step_id, step_description)

        try:
            result = actual_func()
            self.reporter.log_pass(f"Sub-step {sub_step_id} completed successfully")
            return result
        except Exception as e:
            self.reporter.log_fail(f"Sub-step {sub_step_id} failed: {str(e)}")
            raise
        finally:
            self.reporter.log_step_end(sub_step_id)

    @property
    def last_response(self):
        """Get the last response for chaining"""
        return self._last_response
