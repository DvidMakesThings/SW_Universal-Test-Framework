"""
UTFW SNMP Module
================

High-level SNMP test functions and TestAction factories for universal testing.

This module provides comprehensive SNMP testing capabilities including:
- Basic SNMP GET/SET operations with detailed logging
- Outlet control and verification for managed PDUs
- Enterprise MIB walking and validation
- System information retrieval and validation
- Bulk operations for multiple outlets
- Error condition testing

All functions return TestAction instances that integrate with the UTFW
logging system and can be used in test steps or STE groups.

Author: DvidMakesThings
"""

from .snmp import *

__all__ = [
    # Exceptions
    "SNMPTestError",

    # Core SNMP functions
    "get_value",
    "set_integer",
    "test_single_outlet",
    "test_all_outlets",

    # TestAction factories
    "set_outlet",
    "get_outlet",
    "set_all_outlets",
    "verify_all_outlets",
    "cycle_outlets_all_channels",
    "walk_enterprise",
    "expect_oid_regex",
    "expect_oid_equals",
    "expect_oid_error",
    "read_oid",
    "get_oid_value",
    "expect_oid_range",
    "wait_settle",
    "verify_hlw8032_all_channels",
]