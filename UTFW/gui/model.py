"""
UTFW GUI Model
==============
Data structures and functions for building test step models.
"""

from pathlib import Path
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass
import sys
import threading
import importlib.util


@dataclass
class TestMetadata:
    """Metadata about a discovered test."""
    id: str
    class_name: str
    description: str
    module_path: Path
    relative_path: str


@dataclass
class StepInfo:
    """Information about a test step."""
    phase: str
    step_label: str
    name: str
    negative: bool
    metadata: Dict[str, Any]
    parent_label: Optional[str] = None


@dataclass
class TestStepModel:
    """Model containing all test steps."""
    pre_steps: List[StepInfo]
    main_steps: List[StepInfo]
    post_steps: List[StepInfo]
    teardown_steps: List[StepInfo]


def discover_tests(root_dir: Path) -> List[TestMetadata]:
    """Discover all test cases in the given root directory.

    Args:
        root_dir: Root directory to search for tests

    Returns:
        List of discovered test metadata
    """
    tests = []

    # Look for tc_* directories
    for test_dir in root_dir.iterdir():
        if not test_dir.is_dir():
            continue
        if not test_dir.name.startswith('tc_'):
            continue

        # Look for test file with same name
        test_file = test_dir / f"{test_dir.name}.py"
        if not test_file.exists():
            continue

        # Try to extract test class name and description
        try:
            with open(test_file, 'r') as f:
                content = f.read()

            # Look for class definition
            import re
            class_match = re.search(r'class\s+(\w+)[\s\(:]', content)
            if not class_match:
                continue

            class_name = class_match.group(1)

            # Try to extract description from docstring
            desc_match = re.search(r'class\s+\w+.*?"""(.+?)"""', content, re.DOTALL)
            description = desc_match.group(1).strip().split('\n')[0] if desc_match else test_dir.name

            tests.append(TestMetadata(
                id=test_dir.name,
                class_name=class_name,
                description=description,
                module_path=test_file,
                relative_path=str(test_file.relative_to(root_dir))
            ))
        except Exception:
            continue

    return sorted(tests, key=lambda t: t.id)


def build_step_model(test_class, hwconfig_path: Optional[Path] = None) -> TestStepModel:
    """Build a step model from a test class.

    Args:
        test_class: Test class to analyze
        hwconfig_path: Optional hardware config path

    Returns:
        TestStepModel with all steps
    """
    import os

    # Set hardware config env variable if provided
    original_hwconfig = os.environ.get('UTFW_HWCONFIG_PATH')
    if hwconfig_path:
        os.environ['UTFW_HWCONFIG_PATH'] = str(hwconfig_path)

    try:
        test_instance = test_class()

        pre_steps = []
        main_steps = []
        post_steps = []
        teardown_steps = []

        # Extract steps from each phase
        if hasattr(test_instance, 'pre') and callable(test_instance.pre):
            actions = test_instance.pre()
            if actions:
                pre_steps = _build_step_list(actions, "PRE-STEP")

        if hasattr(test_instance, 'setup') and callable(test_instance.setup):
            actions = test_instance.setup()
            if actions:
                main_steps = _build_step_list(actions, "STEP")

        if hasattr(test_instance, 'post') and callable(test_instance.post):
            actions = test_instance.post()
            if actions:
                post_steps = _build_step_list(actions, "POST-STEP")

        if hasattr(test_instance, 'teardown') and callable(test_instance.teardown):
            actions = test_instance.teardown()
            if actions:
                teardown_steps = _build_step_list(actions, "TEARDOWN")

        return TestStepModel(
            pre_steps=pre_steps,
            main_steps=main_steps,
            post_steps=post_steps,
            teardown_steps=teardown_steps
        )
    finally:
        # Restore original hwconfig
        if original_hwconfig is not None:
            os.environ['UTFW_HWCONFIG_PATH'] = original_hwconfig
        elif 'UTFW_HWCONFIG_PATH' in os.environ:
            del os.environ['UTFW_HWCONFIG_PATH']


def _build_step_list(actions: List, phase_prefix: str) -> List[StepInfo]:
    """Build a list of StepInfo from actions.

    Args:
        actions: List of TestAction objects
        phase_prefix: Phase prefix (PRE-STEP, STEP, etc.)

    Returns:
        List of StepInfo objects
    """
    from UTFW.core import STE, PTE

    steps = []

    for idx, action in enumerate(actions, 1):
        step_label = f"{phase_prefix} {idx}"

        # Handle STE (Sub-step Test Executor)
        if isinstance(action, STE):
            name = action.name if hasattr(action, 'name') else f"Multi-action step with {len(action.actions)} sub-steps"
            metadata = getattr(action, 'metadata', {"type": "STE"})

            steps.append(StepInfo(
                phase=phase_prefix,
                step_label=step_label,
                name=name,
                negative=False,
                metadata=metadata
            ))

            # Add sub-steps
            for sub_idx, sub_action in enumerate(action.actions, 1):
                sub_label = f"{step_label}.{sub_idx}"
                # Unwrap startFirstWith wrapper if present
                from UTFW.core.parallelstep import _startFirstWithWrapper
                if isinstance(sub_action, _startFirstWithWrapper):
                    sub_action = sub_action.action

                sub_info = _extract_action_info(sub_action)
                steps.append(StepInfo(
                    phase=phase_prefix,
                    step_label=sub_label,
                    name=sub_info["name"],
                    negative=sub_info["negative"],
                    metadata=sub_info["metadata"],
                    parent_label=step_label
                ))

        # Handle PTE (Parallel Test Executor)
        elif isinstance(action, PTE):
            name = action.name if hasattr(action, 'name') else f"Parallel step with {len(action.actions)} sub-steps"
            metadata = getattr(action, 'metadata', {"type": "PTE"})

            steps.append(StepInfo(
                phase=phase_prefix,
                step_label=step_label,
                name=name,
                negative=False,
                metadata=metadata
            ))

            # Add sub-steps
            for sub_idx, sub_action in enumerate(action.actions, 1):
                sub_label = f"{step_label}.{sub_idx}"
                # Unwrap startFirstWith wrapper if present
                from UTFW.core.parallelstep import _startFirstWithWrapper
                if isinstance(sub_action, _startFirstWithWrapper):
                    sub_action = sub_action.action

                sub_info = _extract_action_info(sub_action)
                steps.append(StepInfo(
                    phase=phase_prefix,
                    step_label=sub_label,
                    name=sub_info["name"],
                    negative=sub_info["negative"],
                    metadata=sub_info["metadata"],
                    parent_label=step_label
                ))

        # Handle regular action
        else:
            info = _extract_action_info(action)
            steps.append(StepInfo(
                phase=phase_prefix,
                step_label=step_label,
                name=info["name"],
                negative=info["negative"],
                metadata=info["metadata"]
            ))

    return steps


def _extract_action_info(action) -> Dict[str, Any]:
    """Extract name, negative_test flag, and metadata from an action (UNIVERSAL).

    Args:
        action: TestAction, callable, or action-like object

    Returns:
        Dictionary with name, negative, and metadata
    """
    from UTFW.core import TestAction

    name = "Unknown action"
    negative = False
    metadata = {}

    # Get name
    if isinstance(action, TestAction):
        name = action.name
        negative = getattr(action, "negative_test", False)
        # UNIVERSAL: Prefer action.metadata if available (NEW WAY)
        if hasattr(action, 'metadata') and action.metadata:
            metadata = action.metadata.copy()
        else:
            # Fall back to closure introspection (OLD WAY)
            metadata = extract_action_metadata(action)
    elif hasattr(action, "name"):
        name = action.name
        negative = getattr(action, "negative_test", False)
        if hasattr(action, 'metadata') and getattr(action, 'metadata'):
            metadata = getattr(action, 'metadata').copy()
        else:
            metadata = extract_action_metadata(action)
    elif callable(action):
        name = getattr(action, "__name__", "Unknown action")
        metadata = extract_action_metadata(action)

    metadata["negative_test"] = negative

    return {"name": name, "negative": negative, "metadata": metadata}


def extract_action_metadata(action) -> Dict[str, Any]:
    """Extract metadata from a TestAction by inspecting its execute_func closure.

    This is the FALLBACK method for backwards compatibility.
    New modules should populate action.metadata directly.

    Args:
        action: TestAction or action-like object

    Returns:
        Dictionary of extracted metadata
    """
    from UTFW.core import TestAction

    metadata = {}

    # Get execute_func
    execute_func = None
    if isinstance(action, TestAction):
        execute_func = action.execute_func
    elif hasattr(action, "execute_func"):
        execute_func = action.execute_func
    elif callable(action):
        execute_func = action

    if not execute_func or not callable(execute_func):
        return metadata

    # Try to extract from closure
    try:
        if hasattr(execute_func, "__closure__") and execute_func.__closure__:
            if hasattr(execute_func, "__code__"):
                var_names = execute_func.__code__.co_freevars
                var_values = execute_func.__closure__

                # Whitelist of interesting variable names
                interesting_vars = {
                    "expected", "expected_state", "expected_value", "min_val", "max_val",
                    "ip", "oid", "community", "root_oid",
                    "timeout", "cmd", "command", "port", "baudrate", "channel",
                    "state", "value", "param", "tokens", "description", "pattern", "regex",
                    "response", "name", "outlet_base_oid", "all_on_oid", "all_off_oid",
                    "reboot", "settle_s", "duration_ms"
                }

                for var_name, cell in zip(var_names, var_values):
                    if var_name in interesting_vars:
                        try:
                            metadata[var_name] = cell.cell_contents
                        except (ValueError, AttributeError):
                            pass
    except Exception:
        # If introspection fails, return empty metadata
        pass

    return metadata


def run_test_in_thread(
    test_metadata: TestMetadata,
    on_event: Callable[[Dict[str, Any]], None],
    on_log_line: Callable[[str], None],
    on_finished: Callable[[int, str], None],
    hardware_config_path: Optional[Path] = None
) -> threading.Thread:
    """Run a test in a background thread with event and log callbacks.

    This function creates and starts a background thread that:
    1. Imports the test module
    2. Instantiates the test class
    3. Registers event listener and log subscriber
    4. Runs the test
    5. Calls on_finished with exit code and report path

    Args:
        test_metadata: Metadata about the test to run
        on_event: Callback for reporter events
        on_log_line: Callback for log lines
        on_finished: Callback for completion (receives exit code and report path)
        hardware_config_path: Optional path to hardware config file

    Returns:
        Started thread object
    """
    def _runner():
        exit_code = 1
        report_path = ""
        original_cwd = None
        try:
            # Change working directory to test root (grandparent of test file)
            # This allows get_hwconfig() to find hardware_config.py correctly
            # Structure: tests/hardware_config.py and tests/tc_name/tc_name.py
            original_cwd = Path.cwd()
            test_file_dir = test_metadata.module_path.parent
            test_root = test_file_dir.parent  # Go up one more level to tests/
            import os

            # Set environment variable if hardware config is specified
            original_hwconfig_env = os.environ.get('UTFW_HWCONFIG_PATH')
            if hardware_config_path:
                os.environ['UTFW_HWCONFIG_PATH'] = str(hardware_config_path)

            os.chdir(test_root)

            # Import module
            spec = importlib.util.spec_from_file_location(
                test_metadata.id,
                test_metadata.module_path
            )
            if not spec or not spec.loader:
                on_finished(1, "")
                return

            module = importlib.util.module_from_spec(spec)

            # Add module to sys.modules temporarily
            sys.modules[test_metadata.id] = module

            try:
                spec.loader.exec_module(module)

                # Get test class
                test_cls = getattr(module, test_metadata.class_name, None)
                if not test_cls:
                    on_finished(1, "")
                    return

                # Instantiate test
                test_instance = test_cls()

                # Check if test has main() method
                if hasattr(test_instance, "main") and callable(test_instance.main):
                    # Register listeners before running
                    from UTFW.core import get_active_reporter, get_active_logger

                    # Run main which should set up reporter
                    # We need to register listeners after reporter is created
                    # So we'll use a wrapper approach

                    # Call main directly and let it handle everything
                    exit_code = test_instance.main()
                else:
                    # Use run_test_with_teardown
                    from UTFW.core import run_test_with_teardown, get_active_reporter, get_active_logger

                    # Use test's own folder for reports
                    reports_dir = test_metadata.module_path.parent
                    reports_dir.mkdir(parents=True, exist_ok=True)

                    # Register listeners via monkey-patching approach
                    original_init = None
                    try:
                        from UTFW.core.reporting import TestReporter

                        original_init = TestReporter.__init__

                        def patched_init(self, *args, **kwargs):
                            original_init(self, *args, **kwargs)
                            self.add_listener(on_event)
                            self._ulog.add_subscriber(on_log_line)

                        TestReporter.__init__ = patched_init

                        # Run test
                        exit_code = run_test_with_teardown(
                            test_instance,
                            test_metadata.id,
                            reports_dir=str(reports_dir)
                        )

                        # Find the generated HTML report
                        html_files = list(reports_dir.glob(f"{test_metadata.id}*.html"))
                        if html_files:
                            # Get the most recent HTML report
                            report_path = str(max(html_files, key=lambda p: p.stat().st_mtime))

                    finally:
                        # Restore original __init__
                        if original_init:
                            TestReporter.__init__ = original_init

            finally:
                # Remove from sys.modules
                if test_metadata.id in sys.modules:
                    del sys.modules[test_metadata.id]

        except Exception as e:
            # Test failed to run
            exit_code = 1
        finally:
            # Restore original working directory and environment
            if original_cwd:
                import os
                os.chdir(original_cwd)
                if original_hwconfig_env is not None:
                    os.environ['UTFW_HWCONFIG_PATH'] = original_hwconfig_env
                elif 'UTFW_HWCONFIG_PATH' in os.environ:
                    del os.environ['UTFW_HWCONFIG_PATH']
            on_finished(exit_code, report_path)

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    return thread
