"""
UTFW Core Framework
==================
Clean framework for class-based test execution

Author: DvidMakesThings
"""

import time
import threading
import hashlib
from typing import Any, Dict, List, Callable, Optional
from dataclasses import dataclass
from pathlib import Path
from .logger import get_active_logger

# Global test session ID - unique per test execution
_current_test_session_id: Optional[str] = None


def generate_test_session_id(test_name: str) -> str:
    """Generate a unique test session ID based on test name and timestamp.

    Creates a hash-based ID that's unique for each test execution. This ID is used
    to track which files belong to the current test run and need to be cleaned up.

    Args:
        test_name: Name of the test being executed

    Returns:
        Unique session ID string (8 character hex)
    """
    timestamp = str(time.time())
    combined = f"{test_name}_{timestamp}"
    hash_obj = hashlib.md5(combined.encode())
    return hash_obj.hexdigest()[:8]


def set_test_session_id(session_id: str) -> None:
    """Set the current test session ID.

    Args:
        session_id: The session ID to set as current
    """
    global _current_test_session_id
    _current_test_session_id = session_id


def get_test_session_id() -> Optional[str]:
    """Get the current test session ID.

    Returns:
        Current session ID or None if not set
    """
    return _current_test_session_id


def clear_test_session_id() -> None:
    """Clear the current test session ID."""
    global _current_test_session_id
    _current_test_session_id = None


@dataclass
class TestStep:
    step_number: str
    description: str
    result: str
    duration: float
    error: Optional[str] = None
    negative_test: bool = False


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
        negative_test (bool): If True, this test expects to fail. A failure will be
            treated as success and reported as PASS. Defaults to False.

    Example:
        >>> def ping_device():
        ...     # Ping implementation
        ...     return True
        >>> action = TestAction("Ping device connectivity", ping_device)
        >>> result = action()  # Execute the action
        >>> # or
        >>> result = action.execute()  # Alternative execution method
    """

    def __init__(self, name: str, execute_func: Callable[..., Any], negative_test: bool = False,
                 metadata: Optional[Dict[str, Any]] = None):
        self.name = name
        self.execute_func = execute_func
        self.negative_test = negative_test
        self.metadata = metadata or {}

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

    def get_display_command(self) -> str:
        """Get formatted command string for GUI display.

        Returns the command that will be sent when this action executes.
        Modules populate this in metadata['display_command'].

        Returns:
            str: Formatted command string or empty string if not available.
        """
        return self.metadata.get('display_command', '')

    def get_display_expected(self) -> str:
        """Get formatted expected value/result for GUI display.

        Returns the expected result/value for this action.
        Modules populate this in metadata['display_expected'].

        Returns:
            str: Formatted expected value or empty string if not available.
        """
        return self.metadata.get('display_expected', '')


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
        self.metadata = {"type": "STE"}

    def get_display_command(self) -> str:
        """STE groups don't send commands themselves."""
        return ""

    def get_display_expected(self) -> str:
        """STE groups don't have expected values themselves."""
        return ""


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
        self.metadata = {"type": "PTE"}

    def get_display_command(self) -> str:
        """PTE groups don't send commands themselves."""
        return ""

    def get_display_expected(self) -> str:
        """PTE groups don't have expected values themselves."""
        return ""


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

        # Generate and set unique test session ID
        self.session_id = generate_test_session_id(test_name)
        set_test_session_id(self.session_id)

        from .reporting import TestReporter, set_active_reporter
        self.reporter = TestReporter(test_name, reports_dir, session_id=self.session_id)
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
        negative_test = getattr(action, 'negative_test', False)

        self.reporter.log_step_start(step_id, action_name, negative_test=negative_test)

        start_time = time.time()
        error_obj = None
        result_str = "UNKNOWN"

        try:
            result = execute_func()
            if negative_test:
                self.reporter.log_fail(f"{step_id} passed but expected to fail")
                result_str = "FAIL"
                raise Exception("Negative test passed when it should have failed")
            else:
                self.reporter.log_pass(f"{step_id} completed successfully")
                result_str = "PASS"
            return result
        except Exception as e:
            error_obj = e
            if negative_test:
                self.reporter.log_pass(f"{step_id} failed as expected: {str(e)}")
                result_str = "PASS"
                return None
            else:
                self.reporter.log_fail(f"{step_id} failed: {str(e)}")
                result_str = "FAIL"
                raise
        finally:
            duration = time.time() - start_time
            self.test_steps.append(TestStep(
                step_id,
                action_name,
                result_str,
                duration,
                str(error_obj) if error_obj else None,
                negative_test
            ))
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

    def _execute_steps_list(self, actions: List[Any], label_prefix: str, start_idx: int = 1) -> None:
        """Execute a list of actions with given label prefix and starting index.

        Args:
            actions: List of actions to execute
            label_prefix: Prefix for step labels (e.g., "PRE-STEP", "STEP", "POST-STEP")
            start_idx: Starting index for step numbering
        """
        for idx, action in enumerate(actions, start_idx):
            step_number = f"{label_prefix} {idx}"
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

    def run_test_class(self, test_class_instance) -> str:
        """Run a test class instance and return the overall result.

        Execution order:
        1. pre() - Optional preparation steps (labeled as PRE-STEP)
        2. setup() - Main test steps (labeled as STEP)
        3. post() - Optional cleanup steps (labeled as POST-STEP)
        4. teardown() - Always executed if test fails or after post() completes
                       (labeled as TEARDOWN with sub-step numbering 1.1, 1.2, etc.)
        """
        self.reporter.log_test_start(self.test_name)
        test_failed = False
        teardown_actions = None

        try:
            # Execute pre-steps if available
            if hasattr(test_class_instance, 'pre') and callable(test_class_instance.pre):
                pre_actions = test_class_instance.pre()
                if pre_actions:
                    self._execute_steps_list(pre_actions, "PRE-STEP")

            # Execute main test steps
            actions = test_class_instance.setup()
            self._execute_steps_list(actions, "STEP")

            # Execute post-steps if available
            if hasattr(test_class_instance, 'post') and callable(test_class_instance.post):
                post_actions = test_class_instance.post()
                if post_actions:
                    self._execute_steps_list(post_actions, "POST-STEP")

            self.overall_result = "PASS"

        except Exception as e:
            test_failed = True
            self.overall_result = "FAIL"
            self.reporter.log_fail(f"Test failed: {str(e)}")

        finally:
            # Execute teardown if it exists - always runs on failure, or after success
            if hasattr(test_class_instance, 'teardown') and callable(test_class_instance.teardown):
                try:
                    teardown_actions = test_class_instance.teardown()
                    if teardown_actions:
                        # Teardown steps are numbered as TEARDOWN 1.1, 1.2, etc.
                        for idx, action in enumerate(teardown_actions, 1):
                            step_number = f"TEARDOWN {idx}"
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
                except Exception as td_error:
                    self.reporter.log_fail(f"Teardown failed: {str(td_error)}")
                    # Don't override original test failure
                    if not test_failed:
                        self.overall_result = "FAIL"

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
            # Clear the test session ID
            clear_test_session_id()


def run_test_with_teardown(test_class_instance, test_name: str, reports_dir: Optional[str] = None) -> int:
    """Universal test runner with automatic teardown and report generation.

    This is the main entry point for running UTFW tests. It creates a TestFramework
    instance, executes the provided test class, generates reports, and ensures
    proper cleanup regardless of test outcome.

    Test Class Methods (all optional except setup):
        - pre(): Returns list of preparation steps (labeled as PRE-STEP 1, PRE-STEP 2, ...)
                 Executed before main test steps. Use for test environment setup.
        - setup(): Returns list of main test steps (labeled as STEP 1, STEP 2, ...)
                   This is the core test logic. REQUIRED.
        - post(): Returns list of cleanup steps (labeled as POST-STEP 1, POST-STEP 2, ...)
                  Executed after successful completion of setup(). Use for normal cleanup.
        - teardown(): Returns list of emergency cleanup steps (labeled as TEARDOWN 1.1, 1.2, ...)
                      ALWAYS executed on test failure. If test passes, executed after post().
                      Use for critical cleanup that must always happen (e.g., power off equipment).

    Args:
        test_class_instance: Test class instance with optional pre(), required setup(),
            optional post(), and optional teardown() methods.
        test_name (str): Logical name for the test suite used in reports.
        reports_dir (Optional[str]): Reports directory name relative to test script location.
            Can be overridden by test suite via UTFW_SUITE_REPORTS_DIR environment variable.
            If None, defaults to "report_{test_name}".

    Returns:
        int: Exit code (0 for PASS, 1 for FAIL) suitable for use with sys.exit().

    Example:
        >>> class MyTest:
        ...     def pre(self):
        ...         return [power_on_device()]
        ...     def setup(self):
        ...         return [run_main_test()]
        ...     def post(self):
        ...         return [save_logs()]
        ...     def teardown(self):
        ...         return [power_off_device()]
        >>> exit_code = run_test_with_teardown(MyTest(), "Device Test")
        >>> sys.exit(exit_code)
    """
    import os
    import inspect

    # Check if running as part of a test suite with -r argument
    suite_reports_base = os.environ.get('UTFW_SUITE_REPORTS_DIR')
    if suite_reports_base:
        # Suite runner specified a reports directory - use it as absolute path
        final_reports_dir = str(Path(suite_reports_base) / f"report_{test_name}")
    else:
        # Not in suite mode - make reports_dir relative to the test script's location
        # Get the caller's file path (the test script that called run_test_with_teardown)
        caller_frame = inspect.stack()[1]
        caller_file = caller_frame.filename
        test_script_dir = Path(caller_file).parent

        if reports_dir is None:
            # No explicit reports_dir - use default
            final_reports_dir = str(test_script_dir / f"report_{test_name}")
        else:
            # Use provided reports_dir relative to test script location
            final_reports_dir = str(test_script_dir / reports_dir)

    # Make reports directory available to test code via get_reports_dir()
    from .utilities import set_reports_dir
    set_reports_dir(final_reports_dir)

    framework = TestFramework(test_name, final_reports_dir)
    try:
        result = framework.run_test_class(test_class_instance)
        framework.generate_reports()
        return 0 if result == "PASS" else 1
    finally:
        framework.cleanup()
