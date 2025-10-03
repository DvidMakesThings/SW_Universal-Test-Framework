#!/usr/bin/env python3
"""
tc_serial_errors.py - Serial Error Handling Test
=================================================
Tests device response to invalid commands and error handling
"""

import sys
from pathlib import Path

from UTFW.core import run_test_with_teardown
from UTFW.core import get_hwconfig
from UTFW.core import STE
from UTFW.modules import serial as UART


class tc_serial_errors_test:
    """Serial error handling test"""

    def __init__(self):
        pass

    def setup(self):
        hw = get_hwconfig()

        # Invalid command tests
        invalid_commands = [
            ("INVALID_CMD", "Unknown command"),
            ("SET_CH 99 ON", "Invalid channel"),
            ("SET_CH 1 INVALID", "Invalid state"),
            ("SET_CH", "Missing parameters"),
            ("GET_CH 0", "Channel out of range"),
            ("GET_CH 100", "Channel out of range"),
            ("SET_IP", "Missing IP address"),
            ("SET_IP invalid.ip.format", "Invalid IP format"),
            ("CONFIG_NETWORK 192.168.1.1", "Missing network parameters"),
            ("READ_HLW8032 99", "Invalid channel for power read")
        ]

        invalid_actions = []
        for cmd, desc in invalid_commands:
            invalid_actions.extend([
                UART.send_command_uart(
                    name=f"Send invalid command: {desc}",
                    port=hw.SERIAL_PORT,
                    command=cmd,
                    baudrate=hw.BAUDRATE
                ),
                UART.validate_tokens(
                    name=f"Expect error response for: {desc}",
                    response="",
                    tokens=["ERROR", "INVALID", "UNKNOWN", "FAIL"]
                )
            ])

        # Malformed parameter tests
        malformed_tests = [
            (f"SET_CH 1 ON EXTRA_PARAM", "Extra parameters"),
            (f"SET_IP 192.168.1.256", "IP out of range"),
            (f"SET_IP 999.999.999.999", "Invalid IP values"),
            (f"SET_GW abc.def.ghi.jkl", "Non-numeric IP"),
            (f"SET_DNS 8.8.8", "Incomplete IP"),
            (f"SET_SN 255.255.255", "Incomplete subnet mask")
        ]

        malformed_actions = []
        for cmd, desc in malformed_tests:
            malformed_actions.extend([
                UART.send_command_uart(
                    name=f"Test malformed: {desc}",
                    port=hw.SERIAL_PORT,
                    command=cmd,
                    baudrate=hw.BAUDRATE
                ),
                UART.validate_tokens(
                    name=f"Verify error for: {desc}",
                    response="",
                    tokens=["ERROR", "INVALID", "FAIL"]
                )
            ])

        # Boundary tests
        boundary_tests = []
        boundary_tests.extend([
            UART.send_command_uart(
                name="Test channel boundary: 0",
                port=hw.SERIAL_PORT,
                command="SET_CH 0 ON",
                baudrate=hw.BAUDRATE
            ),
            UART.send_command_uart(
                name="Test channel boundary: 9",
                port=hw.SERIAL_PORT,
                command="SET_CH 9 ON",
                baudrate=hw.BAUDRATE
            ),
            UART.send_command_uart(
                name="Test channel boundary: -1",
                port=hw.SERIAL_PORT,
                command="SET_CH -1 ON",
                baudrate=hw.BAUDRATE
            ),
            UART.send_command_uart(
                name="Test channel boundary: 255",
                port=hw.SERIAL_PORT,
                command="GET_CH 255",
                baudrate=hw.BAUDRATE
            )
        ])

        # Empty and whitespace tests
        edge_case_tests = []
        edge_case_tests.extend([
            UART.send_command_uart(
                name="Test empty command",
                port=hw.SERIAL_PORT,
                command="",
                baudrate=hw.BAUDRATE
            ),
            UART.send_command_uart(
                name="Test whitespace only",
                port=hw.SERIAL_PORT,
                command="   ",
                baudrate=hw.BAUDRATE
            ),
            UART.send_command_uart(
                name="Test special characters",
                port=hw.SERIAL_PORT,
                command="!@#$%^&*()",
                baudrate=hw.BAUDRATE
            )
        ])

        return [
            # Step 1: Baseline verification
            STE(
                UART.send_command_uart(
                    name="Verify Serial communication works",
                    port=hw.SERIAL_PORT,
                    command=hw.HELP_CMD,
                    baudrate=hw.BAUDRATE
                ),
                UART.validate_tokens(
                    name="Verify HELP response",
                    response="",
                    tokens=hw.HELP_TOKENS
                ),
                name="Baseline Serial communication test"
            ),

            # Step 2: Invalid command tests
            STE(
                *invalid_actions,
                name="Invalid command error handling test"
            ),

            # Step 3: Malformed parameter tests
            STE(
                *malformed_actions,
                name="Malformed parameter error handling test"
            ),

            # Step 4: Boundary condition tests
            STE(
                *boundary_tests,
                name="Boundary condition tests"
            ),

            # Step 5: Edge case tests
            STE(
                *edge_case_tests,
                name="Edge case and special character tests"
            ),

            # Step 6: Verify system still operational
            STE(
                UART.send_command_uart(
                    name="Verify HELP still works after error tests",
                    port=hw.SERIAL_PORT,
                    command=hw.HELP_CMD,
                    baudrate=hw.BAUDRATE
                ),
                UART.validate_tokens(
                    name="Verify HELP tokens present",
                    response="",
                    tokens=hw.HELP_TOKENS
                ),
                UART.send_command_uart(
                    name="Verify SYSINFO works",
                    port=hw.SERIAL_PORT,
                    command=hw.SYSINFO_CMD,
                    baudrate=hw.BAUDRATE
                ),
                UART.validate_tokens(
                    name="Verify SYSINFO response",
                    response="",
                    tokens=["Firmware", "Core Voltage"]
                ),
                name="System stability verification after error tests"
            ),

            # Step 7: Valid command after errors
            STE(
                UART.send_command_uart(
                    name="Test valid command: SET_CH 1 ON",
                    port=hw.SERIAL_PORT,
                    command="SET_CH 1 ON",
                    baudrate=hw.BAUDRATE
                ),
                UART.send_command_uart(
                    name="Verify channel 1 is ON",
                    port=hw.SERIAL_PORT,
                    command="GET_CH 1",
                    baudrate=hw.BAUDRATE
                ),
                UART.validate_tokens(
                    name="Verify ON state",
                    response="",
                    tokens=["ON"]
                ),
                UART.send_command_uart(
                    name="Turn channel 1 OFF",
                    port=hw.SERIAL_PORT,
                    command="SET_CH 1 OFF",
                    baudrate=hw.BAUDRATE
                ),
                name="Valid command execution after error tests"
            ),

            # Step 8: Network configuration error tests
            STE(
                UART.send_command_uart(
                    name="Test invalid CONFIG_NETWORK format",
                    port=hw.SERIAL_PORT,
                    command="CONFIG_NETWORK 192.168.1.1",
                    baudrate=hw.BAUDRATE
                ),
                UART.send_command_uart(
                    name="Verify network config unchanged",
                    port=hw.SERIAL_PORT,
                    command=hw.NETINFO_CMD,
                    baudrate=hw.BAUDRATE
                ),
                UART.validate_tokens(
                    name="Verify baseline IP still present",
                    response="",
                    tokens=[hw.BASELINE_IP]
                ),
                name="Network configuration error handling"
            )
        ]


def main():
    """Create test instance and run"""
    test_instance = tc_serial_errors_test()
    return run_test_with_teardown(
        test_class_instance=test_instance,
        test_name="tc_serial_errors",
        reports_dir="report_tc_serial_errors"
    )


if __name__ == "__main__":
    sys.exit(main())
