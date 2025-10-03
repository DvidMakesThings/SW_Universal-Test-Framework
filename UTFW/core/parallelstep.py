# parallelstep.py
"""
UTFW Parallel Step Execution Module
===================================
Handles detailed parallel sub-step execution within main test steps

This module provides the ParallelStepExecutor class which manages the execution
of multiple actions as numbered sub-steps within a single main test step,
but runs them in parallel threads. It integrates with the logging system to
provide detailed execution tracking.

It also supports marking one or more actions to be *started first* (without
waiting for their completion) before launching the rest, using a small stagger
delay to ensure tools like packet capture are fully armed.

Author: DvidMakesThings
"""

import threading
import time
from typing import Any, Callable, List, Tuple
from .core import TestAction


class _startFirstWithWrapper:
    """Internal wrapper to mark an action that must be launched first."""
    __slots__ = ("action",)
    def __init__(self, action):
        self.action = action


def startFirstWith(action):
    """Mark an action to be launched first by ParallelStepExecutor (no wait for completion)."""
    return _startFirstWithWrapper(action)


class ParallelStepExecutor:
    """Executes TestActions and other callables as numbered sub-steps in parallel.

    ParallelStepExecutor is used internally by the TestFramework to manage the
    execution of multiple actions within a single test step, running them
    concurrently in separate threads. Each action becomes a numbered sub-step
    (e.g., STEP 1.1, STEP 1.2) with individual logging and result tracking.

    Start-order control:
        Wrap any action(s) with `startFirstWith(action)` to guarantee they
        are launched first. The executor will optionally wait `stagger_s`
        seconds after launching the first set before launching the remaining actions.
        It does not wait for the first set to finish before starting the rest.

    Args:
        parent_step (str): Identifier of the parent test step (e.g., "STEP 1").
        reporter: TestReporter instance for logging sub-step execution details.
        default_stagger_s (float): Default delay between launching start-first set
            and the remaining actions. Can be overridden per-execution.

    Example:
        >>> executor = ParallelStepExecutor("STEP 1", reporter)
        >>> result = executor.execute(
        ...     startFirstWith(start_capture),
        ...     generate_traffic,
        ...     stagger_s=0.5,
        ... )
        >>> # Executes as STEP 1.1 (capture starts first), then after 0.5s STEP 1.2 starts.
    """

    def __init__(self, parent_step: str, reporter, default_stagger_s: float = 0.35):
        self.parent_step = parent_step
        self.reporter = reporter
        self._last_response = None
        self._default_stagger_s = float(default_stagger_s)

    def _resolve_action(self, action) -> Tuple[str, Callable[[], Any]]:
        """Resolve any action-like object to (name, callable)."""
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

    def _execute_single(self, idx: int, action, results: dict, errors: dict) -> None:
        """Execute a single action as sub-step (thread worker)."""
        sub_step_id = f"{self.parent_step}.{idx}"
        step_description, actual_func = self._resolve_action(action)
        self.reporter.log_step_start(sub_step_id, step_description)

        try:
            result = actual_func()
            self.reporter.log_pass(f"Sub-step {sub_step_id} completed successfully")
            results[idx] = result
        except Exception as e:
            self.reporter.log_fail(f"Sub-step {sub_step_id} failed: {str(e)}")
            errors[idx] = e
        finally:
            self.reporter.log_step_end(sub_step_id)

    def execute(self, *actions, stagger_s: float | None = None) -> Any:
        """Execute one or more actions as parallel sub-steps.

        If any actions are wrapped with `startFirstWith`, they are launched first,
        then (optionally after `stagger_s`) the remaining actions are launched.

        Args:
            *actions: Action callables or TestAction instances (optionally wrapped by startFirstWith).
            stagger_s (Optional[float]): Override the default stagger delay for this call.

        Returns:
            Any: Result(s) from the sub-steps. If a single action was provided, returns its result.
                 Otherwise returns a list of results ordered by sub-step index.
        """
        threads: List[threading.Thread] = []
        results: dict[int, Any] = {}
        errors: dict[int, Exception] = {}
        _stagger = self._default_stagger_s if stagger_s is None else float(stagger_s)

        # Split into first-wave and second-wave while preserving original positions for numbering
        first_wave: List[tuple[int, Any]] = []
        second_wave: List[tuple[int, Any]] = []
        for i, action in enumerate(actions, 1):  # 1-based sub-step index
            if isinstance(action, _startFirstWithWrapper):
                first_wave.append((i, action.action))
            else:
                second_wave.append((i, action))

        def _launch(wave: List[tuple[int, Any]]):
            for idx, action in wave:
                t = threading.Thread(target=self._execute_single, args=(idx, action, results, errors), daemon=True)
                threads.append(t)
                t.start()

        # Launch start-first actions
        if first_wave:
            _launch(first_wave)

        # Optional stagger before launching the rest
        if first_wave and second_wave and _stagger > 0.0:
            time.sleep(_stagger)

        # Launch remaining actions
        if second_wave:
            _launch(second_wave)

        # Wait for all to finish
        for t in threads:
            t.join()

        if errors:
            # Raise the first encountered error
            raise list(errors.values())[0]

        if len(actions) == 1:
            self._last_response = results[next(iter(results))]
            return self._last_response
        else:
            ordered = [results[i] for i in sorted(results.keys())]
            self._last_response = ordered[-1] if ordered else None
            return ordered

    @property
    def last_response(self):
        """Get the last response for chaining"""
        return self._last_response
