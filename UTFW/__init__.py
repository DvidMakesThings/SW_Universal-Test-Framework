"""
UTFW (Universal Test Framework) 
========================================

A comprehensive framework for hardware device testing that provides:
- Modular test components (SNMP, Serial, Network, Validation)
- Automatic test case numbering and sub-step execution
- Hardware-agnostic configuration
- Integrated reporting with existing helpers

Author: DvidMakesThings
"""

# Import main framework components
from .core import TestFramework, TestStep, TestAction, STE, run_test_with_teardown
from .substep import SubStepExecutor
from .tools import generate_test_report as REPORT_HELPER


# Import test modules - using module imports for clean namespace
from . import snmp as SNMP
from . import serial as Serial  
from . import network as Network
from . import fx2LA as FX2
from . import validation as Validation
from . import utilities

__version__ = "2.0.0"
__all__ = [
    "TestFramework",
    "TestStep", 
    "STE",
    "TestAction",
    "run_test_with_teardown",
    "SNMP",
    "Serial",
    "Network", 
    "FX2",
    "Validation",
    "utilities"
]
