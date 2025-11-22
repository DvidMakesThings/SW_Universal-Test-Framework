"""
UTFW Failure Memory Module
===========================
Universal failure memory testing for devices with event logging systems.

This module provides comprehensive failure memory testing capabilities including:
- Reading ERROR and WARNING logs
- Decoding 16-bit error codes
- Clearing failure memory regions
- Validating error presence/absence
- Generating test errors
- Comprehensive reporting

Author: DvidMakesThings
"""

from .failure_memory import (
    # Exception
    FailureMemoryError,
    
    # Core functions
    decode_error_code,
    extract_eeprom_bytes_from_dump,
    decode_event_log_region,
    read_failure_memory_uart,
    clear_failure_memory_uart,
    
    # TestAction factories
    read_failure_log,
    clear_failure_log,
    verify_error_present,
    verify_log_empty,
    
    # Constants
    EVENT_LOG_BLOCK_SIZE,
    FAILURE_MEM_TIMEOUT,
)

# Import decode tables (for direct access if needed)
from ._error_tables import MODULE_NAMES, SEVERITY_NAMES, FID_NAMES
from ._code_descriptions import EID_NAMES

__version__ = "1.0.0"
__all__ = [
    # Exception
    "FailureMemoryError",
    
    # Core functions
    "decode_error_code",
    "extract_eeprom_bytes_from_dump",
    "decode_event_log_region",
    "read_failure_memory_uart",
    "clear_failure_memory_uart",
    
    # TestAction factories
    "read_failure_log",
    "clear_failure_log",
    "verify_error_present",
    "verify_log_empty",
    
    # Constants
    "EVENT_LOG_BLOCK_SIZE",
    "FAILURE_MEM_TIMEOUT",
    
    # Decode tables
    "MODULE_NAMES",
    "SEVERITY_NAMES",
    "FID_NAMES",
    "EID_NAMES",
]