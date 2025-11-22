"""
UTFW/__init__.py

UTFW (Universal Test Framework)
========================================

A comprehensive framework for hardware device testing that provides:
- Modular test components organized in core and modules packages
- Automatic test case numbering and sub-step execution
- Hardware-agnostic configuration
- Comprehensive logging and reporting system
- TestAction-based architecture for composable tests

Author: DvidMakesThings
"""

# Import core framework components
from .core import (
    # Core framework
    TestFramework, TestStep, TestAction, STE, run_test_with_teardown,
    # Sub-step execution
    SubStepExecutor,
    # Logging system
    UniversalLogger, LogConfig, LogLevel, set_active_logger, get_active_logger, create_logger,
    # Reporting
    TestReporter, set_active_reporter, get_active_reporter,
    # Validation utilities
    ValidationTestError, test_regex_match, test_regex_search, test_numeric_range,
    test_exact_match, test_contains_all, test_key_value_pairs, test_firmware_version,
    test_ip_address, test_mac_address, test_frequency_value,
    # Utilities
    UtilitiesError, load_config_file, save_config_file, create_default_config,
    format_duration, sanitize_filename, wait_for_condition, extract_numeric_value,
    parse_eeprom_data, create_example_hardware_config, hwcfg_from_cli,
    load_hardware_config, get_hwconfig
)

# Import test modules directly (lazy loader in UTFW.modules prevents circulars)
from .modules import serial, snmp, network, ethernet, fx2LA, nop, failuremem
from .tools import generate_test_report as REPORT_HELPER

# Convenient aliases exposed at top-level
Serial = serial
SNMP = snmp
Network = network
Ethernet = ethernet
FX2 = fx2LA
NOP = nop.NOP
FailureMemory = failuremem

__version__ = "2.2.12"
__all__ = [
    # Core framework
    "TestFramework",
    "TestStep", 
    "STE",
    "TestAction",
    "run_test_with_teardown",
    "SubStepExecutor",
    
    # Logging system
    "UniversalLogger",
    "LogConfig", 
    "LogLevel",
    "set_active_logger",
    "get_active_logger", 
    "create_logger",
    
    # Reporting
    "TestReporter",
    "set_active_reporter",
    "get_active_reporter",
    
    # Test modules
    "SNMP",
    "Serial",
    "Network",
    "Ethernet",
    "FX2",
    "NOP",
    "Metrics",
    "FailureMemory",

    # Module package
    "modules",
    
    # Report helper
    "REPORT_HELPER"
]