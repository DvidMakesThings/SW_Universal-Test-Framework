"""
UTFW/modules/__init__.py

UTFW Modules Package
====================

Specialized test modules for different communication protocols and domains.

Available modules:
- serial: UART/Serial communication testing
- snmp: SNMP protocol testing and device management
- network: Network connectivity and HTTP testing
- ethernet: Advanced HTTP and web testing utilities
- fx2LA: Logic analyzer integration (experimental)
- nop: No Operation / Wait utilities
- failuremem: Failure memory decode & validation

Author: DvidMakesThings
"""

import importlib

# Lazy loading to avoid circular imports during package initialization.
# Accessing attributes like UTFW.modules.serial will trigger import on demand.

__all__ = [
    "serial",
    "snmp",
    "network",
    "ethernet",
    "fx2LA",
    "nop",
    "failuremem",
    "metrics",
    "REPORT_HELPER",
]

def __getattr__(name):  # pragma: no cover - simple delegation
    if name == "REPORT_HELPER":
        from UTFW.tools import generate_test_report as REPORT_HELPER
        return REPORT_HELPER
    if name in __all__:
        return importlib.import_module(f"{__name__}.{name}")
    raise AttributeError(f"module {__name__} has no attribute {name}")