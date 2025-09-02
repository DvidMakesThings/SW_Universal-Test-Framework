"""
UTFW (Universal Test Framework) 
========================================

A comprehensive framework for hardware device testing that provides:
- Modular test components (SNMP, Serial, Network, Validation)
- Automatic test case numbering and sub-step execution
- Hardware-agnostic configuration
- Integrated reporting with existing helpers

Usage Example:
    from UTFW import TestFramework, SNMP, Serial
    
    def test_basic_functionality(sub_executor, hw_config):
        # Test SNMP outlet control
        sub_executor.execute(
            SNMP.test_single_outlet,
            "Test outlet 1 ON",
            1, True, hw_config['network']['baseline_ip'],
            hw_config['snmp']['outlet_base_oid']
        )
        
        # Test serial command
        response = sub_executor.execute(
            Serial.send_command,
            "Send HELP command",
            hw_config['serial']['port'], 
            hw_config['commands']['help']
        )

    framework = TestFramework("my_test")
    hw_config = utilities.load_config_file("hardware_config.json")
    framework.run_test_suite([lambda se: test_basic_functionality(se, hw_config)])

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
    "Validation",
    "utilities"
]