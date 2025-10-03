"""
UTFW Core Module
================

Core functionality for the Universal Test Framework including:
- Test framework and execution engine
- Test actions and step management
- Sub-step execution (sequential and parallel)
- Logging and reporting
- Validation utilities
- Common utilities

Author: DvidMakesThings
"""

from .logger import (
    UniversalLogger,
    LogConfig,
    LogLevel,
    set_active_logger,
    get_active_logger,
    create_logger,
)
from .core import (
    TestFramework,
    TestStep,
    TestAction,
    STE,
    PTE,
    run_test_with_teardown,
    get_test_session_id,
    set_test_session_id,
    clear_test_session_id,
    generate_test_session_id,
)
from .substep import SubStepExecutor
from .parallelstep import ParallelStepExecutor, startFirstWith

# Aliases for convenience
PSE = PTE  # Parallel Step Executor alias
from .reporting import TestReporter, set_active_reporter, get_active_reporter
from .validation import *
from .utilities import *

__all__ = [
    # Logger
    "UniversalLogger",
    "LogConfig",
    "LogLevel",
    "set_active_logger",
    "get_active_logger",
    "create_logger",
    # Core framework
    "TestFramework",
    "TestStep",
    "TestAction",
    "STE",
    "PTE",
    "PSE",  # Alias for PTE
    "run_test_with_teardown",
    "get_test_session_id",
    "set_test_session_id",
    "clear_test_session_id",
    "generate_test_session_id",
    # Sub-step execution
    "SubStepExecutor",
    "ParallelStepExecutor",
    "startFirstWith",
    # Reporting
    "TestReporter",
    "set_active_reporter",
    "get_active_reporter",
    # Validation (imported via *)
    # Utilities (imported via *)
]
