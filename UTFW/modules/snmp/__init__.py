"""
UTFW/modules/snmp/__init__.py

UTFW SNMP Module
================

High-level SNMP TestAction factories.

Capabilities:
- GET/SET operations with logging
- Outlet control & verification
- Enterprise MIB walking
- System info retrieval & validation
- Bulk outlet operations
- Error condition testing

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