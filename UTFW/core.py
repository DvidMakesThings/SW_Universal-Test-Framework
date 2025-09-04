# core.py
# core.py
"""
UTSW Core Framework
==================
Clean framework for class-based test execution

Author: DvidMakesThings
"""

import time
from typing import Any, Dict, List, Callable, Optional
from dataclasses import dataclass
from pathlib import Path


@dataclass
class TestStep:
    """Represents a single test step"""
    name: str
    description: str = ""
    step_number: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    status: str = "UNKNOWN"


from typing import Any, Callable

class TestAction:
    """Represents an executable test action.

    Instances are callable and also expose `execute()` and `run()` which both
    invoke the underlying function.

    Args:
        name: Human-readable action name.
        execute_func: Callable that performs the action. It may accept *args/**kwargs.
    """

    def __init__(self, name: str, execute_func: Callable[..., Any]):
        self.name = name
        self.execute_func = execute_func

    def __call__(self, *args, **kwargs) -> Any:
        """Execute the action by calling the instance.

        Args:
            *args: Positional arguments forwarded to the underlying function.
            **kwargs: Keyword arguments forwarded to the underlying function.

        Returns:
            The return value of the underlying function.
        """
        return self.execute_func(*args, **kwargs)

    def execute(self, *args, **kwargs) -> Any:
        """Execute the action.

        Args:
            *args: Positional arguments forwarded to the underlying function.
            **kwargs: Keyword arguments forwarded to the underlying function.

        Returns:
            The return value of the underlying function.
        """
        return self.execute_func(*args, **kwargs)

    def run(self, *args, **kwargs) -> Any:
        """Alias for `execute()`.

        Args:
            *args: Positional arguments forwarded to the underlying function.
            **kwargs: Keyword arguments forwarded to the underlying function.

        Returns:
            The return value of the underlying function.
        """
        return self.execute_func(*args, **kwargs)

    def __repr__(self) -> str:
        return f"TestAction(name={self.name!r})"


class STE:
    """Sub-step Test Executor - groups multiple actions into sub-steps within one main step.

    Args:
        *actions: Callables or action objects to be executed as sub-steps.
        name (str, optional): Human-friendly name for this STE group. If not provided,
                              a default "Multi-action step with N sub-steps" is used.
    """

    def __init__(self, *actions, name: str | None = None):
        self.actions = actions
        self.name = name or f"Multi-action step with {len(actions)} sub-steps"



class SubStepExecutor:
    """Executes functions as sub-steps within a main test step"""

    def __init__(self, parent_step: str, reporter):
        self.parent_step = parent_step
        self.reporter = reporter
        self.sub_step_counter = 0

    def execute(self, *actions) -> Any:
        """Execute one or more actions as sub-steps"""
        if len(actions) == 1:
            return self._execute_single(actions[0])
        else:
            results = []
            for action in actions:
                result = self._execute_single(action)
                results.append(result)
            return results

    def _resolve_action(self, action) -> tuple[str, Callable[[], Any]]:
        """
        Resolve any action-like object to (name, callable).
        Accepts:
          - core.TestAction
          - Any object with 'execute_func' attribute (duck-typed TestAction from modules)
          - A plain callable
        """
        # core.TestAction
        if isinstance(action, TestAction):
            return action.name, action.execute_func
        # Duck-typed TestAction from modules (Serial/SNMP/Network)
        if hasattr(action, "execute_func") and callable(getattr(action, "execute_func")):
            name = getattr(action, "name", getattr(action, "__name__", "Unknown action"))
            return name, action.execute_func  # type: ignore[return-value]
        # Plain callable
        if callable(action):
            return getattr(action, "__name__", "Unknown action"), action  # type: ignore[return-value]
        # Unknown type
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


class TestFramework:
    """Main test framework with class-based execution"""

    def __init__(self, test_name: str, reports_dir: Optional[str] = None):
        self.test_name = test_name
        self.current_step = 0
        self.test_steps: List[TestStep] = []
        self.overall_result = "UNKNOWN"

        from .reporting import TestReporter, set_active_reporter  # (updated)
        self.reporter = TestReporter(test_name, reports_dir)
        # Make reporter globally accessible so modules can log TX/RX
        set_active_reporter(self.reporter)

    def _resolve_action(self, action) -> tuple[str, Callable[[], Any]]:
        """
        Resolve any action-like object to (name, callable).
        Mirrors SubStepExecutor logic so module-local TestAction objects work.
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

    def _execute_single_action(self, action, step_number: str, sub_step_number: Optional[str] = None) -> Any:
        """Execute a single TestAction-like"""
        step_id = f"{step_number}.{sub_step_number}" if sub_step_number else step_number

        action_name, execute_func = self._resolve_action(action)
        self.reporter.log_step_start(step_id, action_name)

        try:
            result = execute_func()
            self.reporter.log_pass(f"{step_id} completed successfully")
            return result
        except Exception as e:
            self.reporter.log_fail(f"{step_id} failed: {str(e)}")
            raise
        finally:
            self.reporter.log_step_end(step_id)

    def _execute_ste_group(self, ste_group: STE, step_number: str) -> List[Any]:
        """Execute STE group as sub-steps within one main step"""
        results = []
        for i, action in enumerate(ste_group.actions, 1):
            result = self._execute_single_action(action, step_number, str(i))
            results.append(result)
        return results

    def run_test_class(self, test_class_instance) -> str:
        """Run test class that returns action list from setup()"""
        self.reporter.log_test_start(self.test_name)

        try:
            # Call setup() to get the action list
            if hasattr(test_class_instance, 'setup') and callable(test_class_instance.setup):
                test_actions = test_class_instance.setup()
            else:
                raise Exception("Test class must have setup() method that returns action list")

            # Execute each action in the list
            for action in test_actions:
                self.current_step += 1
                step_number = f"STEP {self.current_step}"

                # Determine step name (STE can carry a custom name)
                if isinstance(action, STE):
                    step_name = getattr(action, "name", None) or "Multi-action step"
                elif hasattr(action, "name"):
                    step_name = getattr(action, "name") or "Unknown action"
                else:
                    step_name = getattr(action, "__name__", f"Step {self.current_step}")

                step = TestStep(
                    name=step_name,
                    step_number=step_number,
                    start_time=time.strftime("%Y-%m-%d %H:%M:%S")
                )
                self.test_steps.append(step)

                try:
                    if isinstance(action, STE):
                        # Multi sub-step execution
                        self.reporter.log_step_start(step_number, step_name)
                        self._execute_ste_group(action, step_number)
                        step.status = "PASS"
                        self.reporter.log_pass(f"{step_number} all sub-steps completed")
                    else:
                        # Single step execution
                        self._execute_single_action(action, step_number)
                        step.status = "PASS"

                except Exception as e:
                    step.status = "FAIL"
                    self.reporter.log_error(f"Step {step_number} failed: {str(e)}")
                finally:
                    step.end_time = time.strftime("%Y-%m-%d %H:%M:%S")

            # Determine overall result
            failed_steps = [s for s in self.test_steps if s.status == "FAIL"]
            self.overall_result = "FAIL" if failed_steps else "PASS"

        except Exception as e:
            self.overall_result = "FAIL"
            self.reporter.log_error(f"Test suite failed: {str(e)}")
        finally:
            self.reporter.log_test_end(self.overall_result)

        return self.overall_result


    def generate_reports(self) -> Dict[str, Path]:
        """Generate HTML and JUnit reports using existing helpers"""
        return self.reporter.generate_reports()

    def cleanup(self):
        """Clean up resources"""
        try:
            self.reporter.close()
        finally:
            # Clear global reporter
            from .reporting import set_active_reporter
            set_active_reporter(None)


def run_test_with_teardown(test_class_instance, test_name: str, reports_dir: Optional[str] = None) -> int:
    """Universal test runner with automatic teardown"""
    framework = TestFramework(test_name, reports_dir)
    try:
        result = framework.run_test_class(test_class_instance)
        framework.generate_reports()
        return 0 if result == "PASS" else 1
    finally:
        framework.cleanup()
