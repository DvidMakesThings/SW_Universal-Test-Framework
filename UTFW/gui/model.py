"""
UTFW GUI Model Layer
====================
Non-GUI logic for test discovery, metadata extraction, and execution.

This module provides all the core functionality needed by the GUI without
any GUI dependencies. It can be tested independently.
"""

import sys
import importlib.util
import inspect
import threading
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass, field


@dataclass
class TestMetadata:
    """Metadata about a discovered test module."""
    id: str
    description: str
    module_path: Path
    class_name: str
    relative_path: str


@dataclass
class StepInfo:
    """Information about a single test step or sub-step."""
    phase: str
    step_label: str
    name: str
    negative: bool
    metadata: Dict[str, Any]
    parent_label: Optional[str] = None


@dataclass
class TestStepModel:
    """Complete model of all steps in a test."""
    test_id: str
    pre_steps: List[StepInfo] = field(default_factory=list)
    main_steps: List[StepInfo] = field(default_factory=list)
    post_steps: List[StepInfo] = field(default_factory=list)
    teardown_steps: List[StepInfo] = field(default_factory=list)


def discover_tests(test_root: Path) -> List[TestMetadata]:
    """Discover all UTFW test modules under the given root directory.

    Searches for test modules using patterns:
    - Directories named tc_* containing a tc_*.py file
    - Standalone tc_*.py files

    Args:
        test_root: Root directory to search for tests

    Returns:
        List of discovered test metadata
    """
    tests = []

    if not test_root.exists() or not test_root.is_dir():
        return tests

    # Pattern 1: tc_*/tc_*.py directories
    for test_dir in test_root.glob("tc_*"):
        if not test_dir.is_dir():
            continue

        # Look for matching .py file
        test_file = test_dir / f"{test_dir.name}.py"
        if test_file.exists():
            try:
                metadata = _load_test_metadata(test_file, test_root)
                if metadata:
                    tests.append(metadata)
            except Exception:
                # Skip tests that fail to load
                pass

    # Pattern 2: Standalone tc_*.py files
    for test_file in test_root.glob("tc_*.py"):
        if test_file.is_file():
            try:
                metadata = _load_test_metadata(test_file, test_root)
                if metadata:
                    tests.append(metadata)
            except Exception:
                # Skip tests that fail to load
                pass

    return tests


def _load_test_metadata(test_file: Path, test_root: Path) -> Optional[TestMetadata]:
    """Load metadata for a single test module.

    Args:
        test_file: Path to the test .py file
        test_root: Root directory for relative path calculation

    Returns:
        TestMetadata if valid test found, None otherwise
    """
    # Load module
    spec = importlib.util.spec_from_file_location(test_file.stem, test_file)
    if not spec or not spec.loader:
        return None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # Find test class
    test_class = _find_test_class(module, test_file.stem)
    if not test_class:
        return None

    # Extract metadata
    test_id = test_file.stem
    description = getattr(test_class, "__doc__", test_id) or test_id
    if description:
        description = description.strip().split("\n")[0]

    relative_path = str(test_file.relative_to(test_root))

    return TestMetadata(
        id=test_id,
        description=description,
        module_path=test_file,
        class_name=test_class.__name__,
        relative_path=relative_path
    )


def _find_test_class(module, module_name: str):
    """Find the test class in a module.

    Prefers a class whose name matches the module name, or any class
    with a setup() method.

    Args:
        module: Loaded module object
        module_name: Name of the module (for matching)

    Returns:
        Test class if found, None otherwise
    """
    # First try: exact name match
    if hasattr(module, module_name):
        candidate = getattr(module, module_name)
        if inspect.isclass(candidate) and hasattr(candidate, "setup"):
            return candidate

    # Second try: any class with setup method
    for name, obj in inspect.getmembers(module, inspect.isclass):
        if hasattr(obj, "setup") and callable(obj.setup):
            return obj

    return None


def _setup_mock_context(hwconfig_path: Optional[Path] = None):
    """Set up mock context for step parsing in GUI.

    Args:
        hwconfig_path: Optional path to hardware_config.py file.
                      If not provided, tries to auto-discover.
    """
    from types import ModuleType

    # Determine which hardware_config to load
    real_hw_path = None

    if hwconfig_path:
        # Use user-provided path
        real_hw_path = Path(hwconfig_path)
    else:
        # Try to auto-discover
        real_hw_path = Path(__file__).resolve().parent.parent.parent / "tests" / "hardware_config.py"

    mock_hw = ModuleType("hardware_config")

    # Try to import real values
    if real_hw_path and real_hw_path.exists():
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location("_temp_hw_config", real_hw_path)
            if spec and spec.loader:
                real_hw = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(real_hw)
                # Copy all attributes from real config to mock
                for attr in dir(real_hw):
                    if not attr.startswith('_'):
                        setattr(mock_hw, attr, getattr(real_hw, attr))
        except Exception as e:
            print(f"Warning: Could not load real hardware_config from {real_hw_path}: {e}")

    # Ensure essential attributes exist (fallback values if not loaded)
    if not hasattr(mock_hw, 'SERIAL_PORT'):
        mock_hw.SERIAL_PORT = "COM1"
    if not hasattr(mock_hw, 'BAUDRATE'):
        mock_hw.BAUDRATE = 115200
    if not hasattr(mock_hw, 'BASELINE_IP'):
        mock_hw.BASELINE_IP = "192.168.1.100"
    if not hasattr(mock_hw, 'SNMP_COMMUNITY'):
        mock_hw.SNMP_COMMUNITY = "public"

    # Save original if it exists
    original_hw = sys.modules.get("hardware_config")

    # Inject mock into sys.modules
    sys.modules["hardware_config"] = mock_hw

    # Mock get_hwconfig to return the mock hardware config
    from UTFW.core import utilities
    _original_get_hwconfig = utilities.get_hwconfig
    _original_load_hardware_config = utilities.load_hardware_config

    utilities.get_hwconfig = lambda argv=None: mock_hw
    utilities.load_hardware_config = lambda hwcfg=None: mock_hw

    # Mock the test context for get_reports_dir
    _original_test_context = utilities._test_context.copy()
    utilities._test_context['reports_dir'] = "/tmp/reports"

    _original_get_reports_dir = utilities.get_reports_dir

    return (original_hw, _original_get_hwconfig, _original_load_hardware_config, _original_get_reports_dir, _original_test_context)


def _cleanup_mock_context(originals):
    """Restore original functions after step parsing."""
    if originals:
        original_hw, _original_get_hwconfig, _original_load_hardware_config, _original_get_reports_dir, _original_test_context = originals

        # Restore hardware_config module
        if original_hw is not None:
            sys.modules["hardware_config"] = original_hw
        elif "hardware_config" in sys.modules:
            del sys.modules["hardware_config"]

        # Restore functions and context
        from UTFW.core import utilities
        utilities.get_hwconfig = _original_get_hwconfig
        utilities.load_hardware_config = _original_load_hardware_config
        utilities.get_reports_dir = _original_get_reports_dir
        utilities._test_context.clear()
        utilities._test_context.update(_original_test_context)


def build_step_model(test_cls, hwconfig_path: Optional[Path] = None) -> TestStepModel:
    """Build a complete model of all steps in a test without executing them.

    This instantiates the test class and calls pre(), setup(), post(), and
    teardown() to collect action lists, then analyzes each action to build
    a step model.

    Args:
        test_cls: Test class to analyze
        hwconfig_path: Optional path to hardware_config.py file

    Returns:
        TestStepModel with all step information
    """
    # Set up mock context for step parsing
    originals = _setup_mock_context(hwconfig_path)

    try:
        # Instantiate test class
        test_instance = test_cls()

        model = TestStepModel(test_id=test_cls.__name__)

        # Collect pre-steps
        if hasattr(test_instance, "pre") and callable(test_instance.pre):
            try:
                pre_actions = test_instance.pre()
                if pre_actions:
                    model.pre_steps = _analyze_actions(pre_actions, "PRE-STEP")
            except Exception as e:
                print(f"Warning: Failed to parse pre-steps: {e}")

        # Collect main steps (check both 'setup' and 'test' methods)
        main_method = None
        if hasattr(test_instance, "setup") and callable(test_instance.setup):
            main_method = test_instance.setup
        elif hasattr(test_instance, "test") and callable(test_instance.test):
            main_method = test_instance.test

        if main_method:
            try:
                main_actions = main_method()
                if main_actions:
                    model.main_steps = _analyze_actions(main_actions, "STEP")
            except Exception as e:
                print(f"Warning: Failed to parse main steps: {e}")
                import traceback
                traceback.print_exc()

        # Collect post-steps
        if hasattr(test_instance, "post") and callable(test_instance.post):
            try:
                post_actions = test_instance.post()
                if post_actions:
                    model.post_steps = _analyze_actions(post_actions, "POST-STEP")
            except Exception as e:
                print(f"Warning: Failed to parse post-steps: {e}")

        # Collect teardown steps
        if hasattr(test_instance, "teardown") and callable(test_instance.teardown):
            try:
                teardown_actions = test_instance.teardown()
                if teardown_actions:
                    model.teardown_steps = _analyze_actions(teardown_actions, "TEARDOWN")
            except Exception as e:
                print(f"Warning: Failed to parse teardown steps: {e}")

        return model
    finally:
        # Clean up mock context
        _cleanup_mock_context(originals)


def _analyze_actions(actions: List, phase_prefix: str) -> List[StepInfo]:
    """Analyze a list of actions and extract step information.

    Args:
        actions: List of TestAction, STE, PTE, or callables
        phase_prefix: Prefix for step labels (e.g., "STEP", "PRE-STEP")

    Returns:
        List of StepInfo objects
    """
    from UTFW.core import STE, PTE

    steps = []

    for idx, action in enumerate(actions, 1):
        step_label = f"{phase_prefix} {idx}"

        # Handle STE (sub-step executor)
        if isinstance(action, STE):
            name = getattr(action, "name", f"Sub-step group {idx}")
            metadata = {"type": "STE", "sub_count": len(action.actions)}

            # Add parent step
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
                sub_info = _extract_action_info(sub_action)
                steps.append(StepInfo(
                    phase=phase_prefix,
                    step_label=sub_label,
                    name=sub_info["name"],
                    negative=sub_info["negative"],
                    metadata=sub_info["metadata"],
                    parent_label=step_label
                ))

        # Handle PTE (parallel test executor)
        elif isinstance(action, PTE):
            name = getattr(action, "name", f"Parallel step group {idx}")
            metadata = {"type": "PTE", "sub_count": len(action.actions)}

            # Add parent step
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
    """Extract name, negative_test flag, and metadata from an action.

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
    elif hasattr(action, "name"):
        name = action.name
        negative = getattr(action, "negative_test", False)
    elif callable(action):
        name = getattr(action, "__name__", "Unknown action")

    # Extract metadata from closure
    metadata = extract_action_metadata(action)
    metadata["negative_test"] = negative

    return {"name": name, "negative": negative, "metadata": metadata}


def extract_action_metadata(action) -> Dict[str, Any]:
    """Extract metadata from a TestAction by inspecting its execute_func closure.

    This attempts to extract captured variables like expected, min_val, max_val,
    ip, oid, command, etc. from the closure.

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
                    "ip", "oid", "community",
                    "timeout", "cmd", "command", "port", "baudrate", "channel",
                    "state", "value", "param", "tokens", "description", "pattern",
                    "response", "name", "outlet_base_oid", "all_on_oid", "all_off_oid"
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
                on_finished(1)
                return

            module = importlib.util.module_from_spec(spec)

            # Add module to sys.modules temporarily
            sys.modules[test_metadata.id] = module

            try:
                spec.loader.exec_module(module)

                # Get test class
                test_cls = getattr(module, test_metadata.class_name, None)
                if not test_cls:
                    on_finished(1)
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

                    # Use Reports directory in the project root
                    reports_dir = test_root / "Reports"
                    reports_dir.mkdir(exist_ok=True)

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
