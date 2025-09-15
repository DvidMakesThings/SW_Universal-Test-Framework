"""
UTFW Serial Module
==================

High-level serial/UART test functions and TestAction factories for universal testing.

This module provides comprehensive serial communication testing capabilities including:
- Command sending and response validation
- Device reboot detection and ready state monitoring
- System information parsing and validation
- Network parameter configuration via serial
- EEPROM dump capture and analysis
- Channel state management and verification

All functions return TestAction instances that can be used directly in test steps
or combined using STE (Sub-step Test Executor) for complex test scenarios.

Author: DvidMakesThings
"""

from .serial import *

__all__ = [
    # Exceptions
    "SerialTestError",
    
    # Core communication functions
    "send_command",
    "wait_for_reboot_and_ready",
    
    # Parsing utilities
    "parse_sysinfo_response",
    "validate_sysinfo_data", 
    "parse_get_ch_all",
    
    # TestAction factories
    "wait_for_reboot",
    "validate_all_channels_state",
    "get_all_channels",
    "send_command_uart",
    "test_sysinfo_complete",
    "validate_single_token",
    "validate_tokens",
    "set_network_parameter",
    "set_network_parameter_simple",
    "verify_network_change",
    "factory_reset_complete",
    "send_eeprom_dump_command",
    "validate_eeprom_markers",
    "analyze_eeprom_dump",
    "load_eeprom_checks_from_json",
]