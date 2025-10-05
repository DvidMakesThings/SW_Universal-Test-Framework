"""
UTFW Modules Package
====================

This package contains all the specialized test modules for different
communication protocols and testing domains.

Each module provides TestAction factories and utilities for specific
types of testing operations.

Available modules:
- serial: UART/Serial communication testing
- snmp: SNMP protocol testing and device management
- network: Network connectivity and HTTP testing
- ethernet: Advanced HTTP and web testing utilities
- fx2LA: Logic analyzer integration (experimental)
- nop: No Operation / Wait utilities

Author: DvidMakesThings
"""

# Import all modules for easy access
from . import serial
from . import snmp
from . import network
from . import ethernet
from . import fx2LA
from . import nop
from UTFW.tools import generate_test_report as REPORT_HELPER

__all__ = [
    "serial",
    "snmp",
    "network",
    "ethernet",
    "fx2LA",
    "nop"
]