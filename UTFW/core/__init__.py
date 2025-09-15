"""
UTFW Core Module
================

Core functionality for the Universal Test Framework including:
- Test framework and execution engine
- Test actions and step management  
- Sub-step execution
- Logging and reporting
- Validation utilities
- Common utilities

Author: DvidMakesThings
"""

from .logger import UniversalLogger, LogConfig, LogLevel, set_active_logger, get_active_logger, create_logger
from .core import TestFramework, TestStep, TestAction, STE, run_test_with_teardown
from .substep import SubStepExecutor
from .reporting import TestReporter, set_active_reporter, get_active_reporter
from .validation import *
from .utilities import *

__all__ = [
    # Logger
    "UniversalLogger", "LogConfig", "LogLevel", "set_active_logger", "get_active_logger", "create_logger",
    # Core framework
    "TestFramework", "TestStep", "TestAction", "STE", "run_test_with_teardown",
    # Sub-step execution
    "SubStepExecutor", 
    # Reporting
    "TestReporter", "set_active_reporter", "get_active_reporter",
    # Validation (imported via *)
    # Utilities (imported via *)
]