"""
UTFW/modules/serial/__init__.py

UTFW Serial Module
==================

High-level serial/UART TestAction factories.

Capabilities:
- Command sending and response validation
- Reboot detection and ready state monitoring
- System information parsing and validation
- Network parameter configuration
- EEPROM dump capture and analysis
- Channel state management and verification

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