"""
UTFW Core Framework
==================
Clean framework for class-based test execution

Author: DvidMakesThings
"""

import time
import threading
from typing import Any, Dict, List, Callable, Optional
from dataclasses import dataclass
from pathlib import Path
from .logger import get_active_logger


@dataclass
class TestStep:
    step_number: str
    description: str
    result: str
    duration: float
    error: Optional[str] = None


class TestAction:
    """Represents an executable test action that can be used in test steps.
    
    TestAction is the fundamental building block of the UTFW framework. It encapsulates
    a single test operation that can be executed as part of a test step. TestActions
    can be called directly, executed via the execute() method, or run via the run() method.
    
    TestActions are designed to be composable and can be combined using STE (Sub-step
    Test Executor) to create complex test scenarios with multiple sub-steps.

    The action encapsulates both the human-readable name (for reporting) and the
    executable function that performs the actual test operation.

    Args:
        name (str): Human-readable action name used in test reports and logs.
            This should be descriptive enough to understand what the action does
            without looking at the implementation.
        execute_func (Callable[..., Any]): Callable that performs the actual test
            operation. The function may accept *args and **kwargs and should return
            any relevant result data. The function should raise an exception if
            the test operation fails.
    
    Example:
        >>> def ping_device():
        ...     # Ping implementation
        ...     return True
        >>> action = TestAction("Ping device connectivity", ping_device)
        >>> result = action()  # Execute the action
        >>> # or
        >>> result = action.execute()  # Alternative execution method
    """

    def __init__(self, name: str, execute_func: Callable[..., Any]):
        self.name = name
        self.execute_func = execute_func

    def __call__(self, *args, **kwargs) -> Any:
        """Execute the action by calling the instance directly.
        
        This method allows TestAction instances to be called like functions,
        providing a convenient interface for test execution.

        Args:
            *args: Positional arguments forwarded to the underlying execute_func.
            **kwargs: Keyword arguments forwarded to the underlying execute_func.

        Returns:
            Any: The return value of the underlying execute_func.
        
        Raises:
            Exception: Any exception raised by the underlying execute_func,
                typically indicating test failure.
        """
        return self.execute_func(*args, **kwargs)

    def execute(self, *args, **kwargs) -> Any:
        """Execute the action via the execute method.
        
        This method provides an explicit way to execute the test action,
        which can be more readable in some contexts than direct calling.

        Args:
            *args: Positional arguments forwarded to the underlying execute_func.
            **kwargs: Keyword arguments forwarded to the underlying execute_func.

        Returns:
            Any: The return value of the underlying execute_func.
        
        Raises:
            Exception: Any exception raised by the underlying execute_func,
                typically indicating test failure.
        """
        return self.execute_func(*args, **kwargs)

    def run(self, *args, **kwargs) -> Any:
        """Execute the action via the run method (alias for execute).
        
        This method is an alias for execute() provided for compatibility
        and alternative naming preferences.

        Args:
            *args: Positional arguments forwarded to the underlying execute_func.
            **kwargs: Keyword arguments forwarded to the underlying execute_func.

        Returns:
            Any: The return value of the underlying execute_func.
        
        Raises:
            Exception: Any exception raised by the underlying execute_func,
                typically indicating test failure.
        """
        return self.execute_func(*args, **kwargs)


class STE:
    """Sub-step Test Executor - groups multiple TestActions into sub-steps within one main step.
    
    STE (Sub-step Test Executor) is used to group multiple TestActions together so they
    execute as sub-steps within a single main test step. This is useful for organizing
    related test operations while maintaining detailed logging and reporting for each
    individual operation.
    
    When an STE is executed, each contained action becomes a numbered sub-step
    (e.g., STEP 1.1, STEP 1.2, etc.) with individual pass/fail reporting.
    
    The STE itself can have a custom name that describes the overall purpose of
    the grouped operations.

    Args:
        *actions: TestAction instances, callables, or other action objects to be
            executed as sub-steps. Each action will be executed in the order provided.
        name (str, optional): Human-friendly name for this STE group that describes
            the overall purpose of the grouped operations. If not provided, a default
            name "Multi-action step with N sub-steps" is generated.
    
    Example:
        >>> ping_action = TestAction("Ping device", ping_device_func)
        >>> snmp_action = TestAction("Check SNMP", check_snmp_func) 
        >>> connectivity_test = STE(ping_action, snmp_action, 
        ...                        name="Verify device connectivity")
        >>> # This will execute as sub-steps 1.1 and 1.2 within step 1
    """

    def __init__(self, *actions, name: str | None = None):
        self.actions = actions
        self.name = name or f"Multi-action step with {len(actions)} sub-steps"


class PTE:
    """Parallel Test Executor - runs multiple TestActions concurrently as sub-steps within one main step.
    
    PTE (Parallel Test Executor) is analogous to STE but starts all contained actions
    concurrently. Each action is logged as an individual sub-step (e.g., STEP 1.1, STEP 1.2)
    with independent pass/fail reporting, and the group completes when all sub-steps finish.

    Start-order control:
        Actions wrapped via `startFirstWith(...)` (from `parallelstep.py`) will be
        launched first. PTE will then wait `stagger_s` seconds (if > 0) before
        launching the remaining actions. PTE does not wait for the first actions to
        finish before launching others; it only guarantees launch order.

    Args:
        *actions: TestAction instances, callables, or other action objects to be
            executed in parallel as sub-steps.
        name (str, optional): Human-friendly name for this PTE group that describes
            the overall purpose of the grouped operations. If not provided, a default
            name "Parallel step with N sub-steps" is generated.
        stagger_s (float, optional): Delay between starting the start-first set and
            the remaining actions. Defaults to 0.35 seconds.
    """

    def __init__(self, *actions, name: str | None = None, stagger_s: float = 0.35):
        self.actions = actions
        self.name = name or f"Parallel step with {len(actions)} sub-steps"
        self.stagger_s = float(stagger_s)


class TestFramework:
    """Main test framework with class-based execution and comprehensive logging.
    
    TestFramework is the core execution engine for UTFW tests. It manages the
    execution of test classes, handles step numbering, provides detailed logging
    and reporting, and manages the overall test lifecycle.
    
    The framework supports both simple test methods and complex multi-step tests
    using STE (Sub-step Test Executor) and PTE (Parallel Test Executor) for organizing
    related operations.
    
    Key features:
    - Automatic step numbering and tracking
    - Detailed logging with timestamps
    - Exception handling and error reporting  
    - Integration with TestReporter for HTML/XML report generation
    - Support for individual TestActions, STE groups, and PTE groups
    """

    def __init__(self, test_name: str, reports_dir: Optional[str] = None):
        self.test_name = test_name
        self.reports_dir = reports_dir
        self.test_steps: List[TestStep] = []
        self.overall_result = "UNKNOWN"

        from .reporting import TestReporter, set_active_reporter
        self.reporter = TestReporter(test_name, reports_dir)
        # Make reporter globally accessible so modules can log TX/RX
        set_active_reporter(self.reporter)

    def _resolve_action(self, action) -> tuple[str, Callable[[], Any]]:
        """
        Resolve any action-like object to (name, callable).
        """
        if isinstance(action, TestAction):
            return action.name, action.execute_func
        if hasattr(action, "execute_func") and callable(getattr(action, "execute_func")):
            name = getattr(action, "name", getattr(action, "__name__", "Unknown action"))
            return name, action.execute_func
        if callable(action):
            return getattr(action, "__name__", "Unknown action"), action
        def _raiser() -> Any:
            raise TypeError(f"Unsupported action type: {type(action)}")
        return "Unknown action", _raiser

    def _execute_single_action(self, action, step_number: str, sub_step_number: Optional[str] = None) -> Any:
        """Execute a single TestAction with proper logging and error handling."""
        step_id = f"{step_number}.{sub_step_number}" if sub_step_number else step_number

        action_name, execute_func = self._resolve_action(action)
        self.reporter.log_step_start(step_id, action_name)

        start_time = time.time()
        try:
            result = execute_func()
            self.reporter.log_pass(f"{step_id} completed successfully")
            return result
        except Exception as e:
            self.reporter.log_fail(f"{step_id} failed: {str(e)}")
            raise
        finally:
            duration = time.time() - start_time
            self.test_steps.append(TestStep(step_id, action_name, "PASS" if 'result' in locals() else "FAIL", duration, str(e) if 'e' in locals() else None))
            self.reporter.log_step_end(step_id)

    def _execute_ste_group(self, ste_group: "STE", step_number: str) -> List[Any]:
        """Execute an STE group as numbered sub-steps within one main step."""
        results = []
        for i, action in enumerate(ste_group.actions, 1):
            result = self._execute_single_action(action, step_number, str(i))
            results.append(result)
        return results

    def _execute_pte_group(self, pte_group: "PTE", step_number: str) -> List[Any]:
        """Execute a PTE group: launch all sub-steps in parallel and wait for completion.

        Honors `startFirstWith(action)` markers (from parallelstep.py) by launching those
        actions first, then waiting `pte_group.stagger_s`, and finally launching the
        remaining actions. It does not wait for the first group to complete before
        launching the rest.
        """
        import threading

        # Try to import the internal wrapper used by parallelstep.startFirstWith
        try:
            from .parallelstep import _startFirstWithWrapper as _PSFWrapper  # type: ignore
        except Exception:
            class _PSFWrapper:  # type: ignore
                pass

        total = len(pte_group.actions)
        results: List[Optional[Any]] = [None] * total
        exceptions: List[Optional[BaseException]] = [None] * total
        threads: List[threading.Thread] = []

        # Split into first-wave and second-wave while preserving original order
        first_wave: List[tuple[int, Any]] = []
        second_wave: List[tuple[int, Any]] = []
        for i, action in enumerate(pte_group.actions):
            if isinstance(action, _PSFWrapper):
                first_wave.append((i, action.action))
            else:
                second_wave.append((i, action))

        def runner(idx: int, act):
            try:
                results[idx] = self._execute_single_action(act, step_number, str(idx + 1))
            except BaseException as exc:
                exceptions[idx] = exc  # already logged inside _execute_single_action

        # Launch first-wave
        for idx, act in first_wave:
            t = threading.Thread(target=runner, args=(idx, act), daemon=True)
            threads.append(t)
            t.start()

        # Optional stagger before launching the rest
        if first_wave and second_wave and getattr(pte_group, "stagger_s", 0.0) > 0.0:
            time.sleep(float(pte_group.stagger_s))

        # Launch second-wave
        for idx, act in second_wave:
            t = threading.Thread(target=runner, args=(idx, act), daemon=True)
            threads.append(t)
            t.start()

        # Wait for all to finish
        for t in threads:
            t.join()

        failed_indices = [i for i, e in enumerate(exceptions) if e is not None]
        if failed_indices:
            failed_list = ", ".join(f"{step_number}.{i+1}" for i in failed_indices)
            raise Exception(f"One or more parallel sub-steps failed: {failed_list}")

        return results  # type: ignore[return-value]

    def run_test_class(self, test_class_instance) -> str:
        """Run a test class instance and return the overall result."""
        self.reporter.log_test_start(self.test_name)

        try:
            actions = test_class_instance.setup()
            for idx, action in enumerate(actions, 1):
                step_number = f"STEP {idx}"
                if isinstance(action, STE):
                    self.reporter.log_step_start(step_number, action.name)
                    self._execute_ste_group(action, step_number)
                    self.reporter.log_step_end(step_number)
                elif isinstance(action, PTE):
                    self.reporter.log_step_start(step_number, action.name)
                    self._execute_pte_group(action, step_number)
                    self.reporter.log_step_end(step_number)
                else:
                    self._execute_single_action(action, step_number)
            self.overall_result = "PASS"
        except Exception as e:
            self.overall_result = "FAIL"
            self.reporter.log_fail(f"Test failed: {str(e)}")
        finally:
            self.reporter.log_test_end(self.test_name, self.overall_result)
        return self.overall_result

    def generate_reports(self) -> Dict[str, Path]:
        """Generate HTML and JUnit XML reports from the test execution.
        
        This method uses the TestReporter to generate comprehensive HTML reports
        and JUnit XML files suitable for CI/CD integration.
        
        Returns:
            Dict[str, Path]: Dictionary mapping report types to their file paths.
        """
        return self.reporter.generate_reports()

    def cleanup(self):
        """Cleanup resources and close the reporter."""
        try:
            self.reporter.close()
        finally:
            from .reporting import set_active_reporter
            set_active_reporter(None)


def run_test_with_teardown(test_class_instance, test_name: str, reports_dir: Optional[str] = None) -> int:
    """Universal test runner with automatic teardown and report generation.
    
    This is the main entry point for running UTFW tests. It creates a TestFramework
    instance, executes the provided test class, generates reports, and ensures
    proper cleanup regardless of test outcome.
    
    Args:
        test_class_instance: Test class instance with a setup() method that returns
            a list of TestActions and/or STE groups to execute.
        test_name (str): Logical name for the test suite used in reports.
        reports_dir (Optional[str]): Base directory for reports. If None, uses
            default location based on TestCases directory structure.
    
    Returns:
        int: Exit code (0 for PASS, 1 for FAIL) suitable for use with sys.exit().
    
    Example:
        >>> exit_code = run_test_with_teardown(MyTest(), "Device Test")
        >>> sys.exit(exit_code)
    """
    framework = TestFramework(test_name, reports_dir)
    try:
        result = framework.run_test_class(test_class_instance)
        framework.generate_reports()
        return 0 if result == "PASS" else 1
    finally:
        framework.cleanup()
