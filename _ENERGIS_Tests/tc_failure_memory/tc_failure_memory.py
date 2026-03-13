#!/usr/bin/env python3
"""
tc_failure_memory.py - Failure Memory Testing
==============================================
Tests failure memory functionality including reading, clearing,
and validating error/warning logs in device EEPROM.

This test verifies:
- Reading ERROR and WARNING logs
- Generating test errors via Serial module (invalid commands)
- Verifying error codes appear in memory
- Clearing failure memory
- Verifying empty state after clear

Author: DvidMakesThings
"""

import sys
from pathlib import Path

from UTFW.core import run_test_with_teardown
from UTFW.core import get_hwconfig
from UTFW.core import get_reports_dir
from UTFW.core import STE
from UTFW.modules import failuremem as FAILMEM
from UTFW.modules import serial as UART
from UTFW.modules import snmp as SNMP
from UTFW.modules import nop as NOP


class tc_failure_memory_test:
    """Failure memory functionality test"""

    def __init__(self):
        pass

    def pre(self):
        """Pre-steps: Clear both logs to start with clean state."""
        hw = get_hwconfig()

        return [
            UART.send_command_uart(
                name="Reboot device via UART",
                port=hw.SERIAL_PORT,
                command="REBOOT",
                baudrate=hw.BAUDRATE,
                reboot=True,  # Special handling for reboot
            ),
            FAILMEM.clear_failure_log(
                name="Pre-clear ERROR log",
                port=hw.SERIAL_PORT,
                log_type="ERROR",
                baudrate=hw.BAUDRATE,
            ),
            FAILMEM.clear_failure_log(
                name="Pre-clear WARNING log",
                port=hw.SERIAL_PORT,
                log_type="WARNING",
                baudrate=hw.BAUDRATE,
            ),
            NOP.NOP(name="Wait for clear operations to stabilize", duration_ms=500),
        ]

    def teardown(self):
        """Teardown: Cleanup actions that always run."""
        hw = get_hwconfig()

        return [
            # TEARDOWN 1.1: Ensure all outputs are OFF (safety measure)
            SNMP.set_all_outlets(
                name="Ensure all outputs OFF",
                ip=hw.BASELINE_IP,
                all_on_oid=hw.ALL_ON_OID,
                all_off_oid=hw.ALL_OFF_OID,
                state=False,
                community=hw.SNMP_COMMUNITY,
            ),
            # TEARDOWN 1.2: Final verification all outputs are OFF
            SNMP.verify_all_outlets(
                name="Final verify all outputs OFF",
                ip=hw.BASELINE_IP,
                outlet_base_oid=hw.OUTLET_BASE_OID,
                expected_state=False,
                community=hw.SNMP_COMMUNITY,
            ),
            FAILMEM.clear_failure_log(
                name="Post-clear ERROR log",
                port=hw.SERIAL_PORT,
                log_type="ERROR",
                baudrate=hw.BAUDRATE,
            ),
            FAILMEM.clear_failure_log(
                name="Post-clear WARNING log",
                port=hw.SERIAL_PORT,
                log_type="WARNING",
                baudrate=hw.BAUDRATE,
            ),

        ]

    def setup(self):
        hw = get_hwconfig()

        return [
            # STEP 1: Verify initial clean state
            STE(

                # 1.1: Read ERROR log 
                FAILMEM.read_failure_log(
                    name="Read initial ERROR log",
                    port=hw.SERIAL_PORT,
                    log_type="ERROR",
                    baudrate=hw.BAUDRATE,
                ),

                # 1.2: Verify ERROR log is empty
                FAILMEM.verify_log_empty(
                    name="Verify ERROR log is initially empty",
                    port=hw.SERIAL_PORT,
                    log_type="ERROR",
                    baudrate=hw.BAUDRATE,
                ),
                name="Verify initial clean state",
            ),
            # STEP 2: Generate errors using Serial module
            STE(
                # 2.1: Generate error by sending invalid channel command
                UART.send_command_uart(
                    name="Generate error: invalid channel (CH9)",
                    port=hw.SERIAL_PORT,
                    command="SET_CH 9 1",  # Invalid: channel 9 doesn't exist
                    baudrate=hw.BAUDRATE,
                ),

                # 2.2: Wait for error to be written
                NOP.NOP(
                    name="Wait for error to be written to EEPROM", 
                    duration_ms=500
                ),

                # 2.3: Read ERROR log after generating error
                FAILMEM.read_failure_log(
                    name="Read ERROR log after generating error",
                    port=hw.SERIAL_PORT,
                    log_type="ERROR",
                    baudrate=hw.BAUDRATE,
                ),
                name="Generate test error via Serial module",
            ),

            # STEP 3: Generate multiple errors
            STE(
                # 3.1 : Generate error by sending invalid state command
                UART.send_command_uart(
                    name="Generate error #2: invalid state",
                    port=hw.SERIAL_PORT,
                    command="SET_CH 1 INVALID",  # Invalid state value
                    baudrate=hw.BAUDRATE,
                ),

                # 3.2: Wait for errors to be written
                NOP.NOP(
                    name="Wait for errors to be written to EEPROM", 
                    duration_ms=300
                ),

                # 3.3: Generate another error with unknown command
                UART.send_command_uart(
                    name="Generate error #3: unknown command",
                    port=hw.SERIAL_PORT,
                    command="READ_HLW8032 INVALID",  # Unknown command
                    baudrate=hw.BAUDRATE,
                ),

                # 3.4: Wait for errors to be written
                NOP.NOP(
                    name="Wait for errors to be written to EEPROM", 
                    duration_ms=300
                ),

                # 3.5: Read ERROR log after generating multiple errors
                FAILMEM.read_failure_log(
                    name="Read ERROR log with multiple entries",
                    port=hw.SERIAL_PORT,
                    log_type="ERROR",
                    baudrate=hw.BAUDRATE,
                ),
                name="Generate multiple test errors",
            ),
    
            
            # STEP 4: Test verify_error_present with multiple codes
            STE(
                # 4.1 Error code 0x8409: Invalid channel for SET_CH
                FAILMEM.verify_error_present(
                    name="Verify specific error code present",
                    port=hw.SERIAL_PORT,
                    expected_codes=0x8409,  # CONSOLE: Invalid channel for SET_CH
                    log_type="ERROR",
                    baudrate=hw.BAUDRATE,
                ),

                # 4.2 Verify multiple codes are present
                FAILMEM.verify_error_present(
                    name="Verify multiple error codes present",
                    port=hw.SERIAL_PORT,
                    expected_codes=[0x8409, 0x8407, 0x8402],  # List of codes
                    log_type="ERROR",
                    baudrate=hw.BAUDRATE,
                ),
                name="Test verify_error_present (multiple codes)",
            ),

            # STEP 5: Clear and verify
            STE(
                # 5.1: Clear ERROR log
                FAILMEM.clear_failure_log(
                    name="Clear ERROR log",
                    port=hw.SERIAL_PORT,
                    log_type="ERROR",
                    baudrate=hw.BAUDRATE,
                ),

                # 5.2: Wait for clear to complete
                NOP.NOP(
                    name="Wait", 
                    duration_ms=500
                ),

                # 5.3: Verify ERROR log is empty
                FAILMEM.verify_log_empty(
                    name="Verify ERROR log is empty after clear",
                    port=hw.SERIAL_PORT,
                    log_type="ERROR",
                    baudrate=hw.BAUDRATE,
                ),
                name="Clear and verify ERROR log empty",
            ),

            # STEP 6: Test WARNING log
            STE(

                # 6.1: Read WARNING log 
                FAILMEM.read_failure_log(
                    name="Read WARNING log",
                    port=hw.SERIAL_PORT,
                    log_type="WARNING",
                    baudrate=hw.BAUDRATE,
                ),

                # 6.2: Verify WARNING log is empty
                FAILMEM.verify_log_empty(
                    name="Verify WARNING log empty",
                    port=hw.SERIAL_PORT,
                    log_type="WARNING",
                    baudrate=hw.BAUDRATE,
                ),
                name="Verify WARNING log functionality",
            ),
            # STEP 7: Re-generate and verify persistence
            STE(

                # 7.1 Disconnect Ethernet cable to trigger warning
                NOP.NOP(
                    name="Wait for the Ethernet cable to be removed", 
                    duration_ms=5000
                ),

                # 7.2: Reboot device to generate warning
                UART.send_command_uart(
                    name="Reboot the system with disconnected Ethernet",
                    port=hw.SERIAL_PORT,
                    command="REBOOT",  # Reboot command
                    baudrate=hw.BAUDRATE,
                    reboot=True, 
                ),

                # 7.3: Wait for boot to complete
                NOP.NOP(
                    name="Wait", 
                    duration_ms=1500
                ),

                # 7.4: Read WARNING log after reboot
                FAILMEM.read_failure_log(
                    name="Verify new warning was logged",
                    port=hw.SERIAL_PORT,
                    log_type="WARNING",
                    baudrate=hw.BAUDRATE,
                ),

                # 7.5: Verify specific warning code is present
                FAILMEM.verify_error_present(
                    name="Verify multiple warning codes present",
                    port=hw.SERIAL_PORT,
                    expected_codes=[0x22B0, 0x22F5],  # List of codes
                    log_type="WARNING",
                    baudrate=hw.BAUDRATE,
                ),
                name="Test warning logging after clear",
            ),
            # STEP 8: Final cleanup
            STE(

                # 8.1: Reconnect Ethernet cable
                NOP.NOP(
                    name="Wait for the Ethernet cable to be reconnected",
                    duration_ms=5000
                ),

                # 8.2: Clear ERROR log
                FAILMEM.clear_failure_log(
                    name="Final clear ERROR log",
                    port=hw.SERIAL_PORT,
                    log_type="ERROR",
                    baudrate=hw.BAUDRATE,
                ),

                # 8.3: Clear WARNING log
                FAILMEM.clear_failure_log(
                    name="Final clear WARNING log",
                    port=hw.SERIAL_PORT,
                    log_type="WARNING",
                    baudrate=hw.BAUDRATE,
                ),

                # 8.4: Wait for clears to complete
                NOP.NOP(
                    name="Wait", 
                    duration_ms=500
                ),
                name="Final cleanup",
            ),
            # STEP 9: Final verification
            STE(
                # 9.1: Verify ERROR log is empty
                FAILMEM.verify_log_empty(
                    name="Final verify ERROR log empty",
                    port=hw.SERIAL_PORT,
                    log_type="ERROR",
                    baudrate=hw.BAUDRATE,
                ),

                # 9.2: Verify WARNING log is empty
                FAILMEM.verify_log_empty(
                    name="Final verify WARNING log empty",
                    port=hw.SERIAL_PORT,
                    log_type="WARNING",
                    baudrate=hw.BAUDRATE,
                ),
                name="Final verification - clean state",
            ),
        ]


def main():
    """Create test instance and run"""
    test_instance = tc_failure_memory_test()
    return run_test_with_teardown(
        test_class_instance=test_instance,
        test_name="tc_failure_memory",
        reports_dir="report_tc_failure_memory",
    )


if __name__ == "__main__":
    sys.exit(main())
